#!/usr/bin/env python3
"""
Power-budget model for the ESP32-H2 Matter-over-Thread water-leak sensor (ICD / SED).

Usage:
    python3 tools/power_budget.py                 # full Markdown report (phase-1 doc tables)
    python3 tools/power_budget.py --sai 10 --tx 0 # one custom scenario
    python3 tools/power_budget.py --floor 31.5    # plug in a measured sleep floor (phase 6)

Conventions
-----------
* Every chip current is at the 3.3 V rail (output of the buck-boost).
* Charges are in micro-coulombs (uC) = uA*s; mA * s = mC.
* Sources:
    ESP32-H2 Series Datasheet v1.3  - Table 5-7 (802.15.4 TX/RX), 5-8 (modem-sleep), 5-9 (low-power).
    TPS63900 datasheet SLVSET3D     - Fig. 8-7 efficiency vs. load at VO = 3.3 V.
    IEEE 802.15.4 2.4 GHz O-QPSK    - 250 kbit/s -> 32 us per byte, 320 us unit backoff,
                                      aTurnaroundTime 192 us, SHR+PHR = 6 bytes.
* Everything that is an engineering estimate (wake-up overhead, CPU time, frame sizes...) is a
  named parameter so that bench measurements from phase 6 can replace it.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace

# --------------------------------------------------------------------------------------------
# Silicon numbers (ESP32-H2 datasheet v1.3, 3.3 V, 25 degC)
# --------------------------------------------------------------------------------------------
I_TX_MA = {20: 140.0, 9: 60.0, 0: 36.0, -24: 24.0}  # Table 5-7, 802.15.4 TX peak
I_RX_MA = 25.0                                      # Table 5-7, 802.15.4 RX
I_CPU_IDLE_MA = 6.0      # Table 5-8: 96 MHz, CPU idle, peripheral clocks gated
I_CPU_RUN_MA = 15.0      # Table 5-8: 96 MHz, CPU running, 10..17 mA depending on peripherals
I_LSLEEP_PD_UA = 25.0    # Table 5-9: light-sleep, CPU + radio + peripherals powered down
I_LSLEEP_NOPD_UA = 85.0  # Table 5-9: light-sleep, peripherals only clock-gated (TOP not powered down)
I_DSLEEP_UA = 7.0        # Table 5-9: deep-sleep, RTC timer + LP memory

BYTE_S = 32e-6           # 250 kbit/s
T_BACKOFF_S = 3.5 * 320e-6  # mean random backoff, BE = 3 -> (2^3 - 1) / 2 unit backoffs
T_CCA_S = 128e-6
T_TURN_S = 192e-6
T_GUARD_S = 200e-6       # extra RX-on time around the ACK (driver margin, estimate)
PHY_OVERHEAD_B = 6       # SHR (5) + PHR (1)
ACK_PSDU_B = 5           # Imm-Ack

# Wake-up / go-to-sleep overhead of one light-sleep cycle with TOP power-down:
# PMU power-up, 32 MHz XTAL start, REG_DMA context restore, then the reverse. Estimate.
T_WAKE_S = 1.5e-3
T_SLEEP_S = 1.0e-3

# RC_SLOW calibration that ESP-IDF runs before light sleep when no 32.768 kHz crystal is fitted
# (CONFIG_RTC_CLK_CAL_CYCLES = 1024 cycles of the ~130 kHz RC, CPU awake).
T_RC_CAL_S = 1024 / 130e3


def frame_tx_uc(psdu_bytes: float, i_tx: float) -> float:
    """CSMA-CA + CCA + TX of one unicast frame + wait for Imm-Ack (no retries)."""
    t_tx = (psdu_bytes + PHY_OVERHEAD_B) * BYTE_S
    t_ack = (ACK_PSDU_B + PHY_OVERHEAD_B) * BYTE_S
    q_ma_s = (T_BACKOFF_S * I_CPU_IDLE_MA
              + (T_CCA_S + T_TURN_S) * I_RX_MA
              + t_tx * i_tx
              + (T_TURN_S + t_ack + T_GUARD_S) * I_RX_MA)
    return q_ma_s * 1e3


def frame_rx_uc(psdu_bytes: float, i_tx: float, rx_wait_s: float = 0.5e-3) -> float:
    """Receive one frame announced by 'frame pending' + send its Imm-Ack."""
    t_rx = (psdu_bytes + PHY_OVERHEAD_B) * BYTE_S + rx_wait_s
    t_ack_tx = T_TURN_S + (ACK_PSDU_B + PHY_OVERHEAD_B) * BYTE_S
    return (t_rx * I_RX_MA + t_ack_tx * i_tx) * 1e3


def wake_uc(xtal32k: bool) -> float:
    q = (T_WAKE_S + T_SLEEP_S) * I_CPU_IDLE_MA * 1e3
    if not xtal32k:
        q += T_RC_CAL_S * I_CPU_IDLE_MA * 1e3
    return q


# --------------------------------------------------------------------------------------------
# Scenario
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    name: str = "typical"
    floor_ua: float = I_LSLEEP_PD_UA   # chip light-sleep floor
    board_ua: float = 0.5              # MOSFET/TVS/MLCC leakage, XTAL32K drive, LDO-less rail (estimate)
    sai_s: float = 15.0                # ICD slow-poll interval (SIT max = 15 s)
    tx_dbm: int = 9
    xtal32k: bool = True
    poll_scale: float = 1.0            # >1 to model MAC retries / longer wake-ups
    data_req_psdu: int = 22            # MAC cmd, security level 5, key-id mode 1, FCS
    supervision_s: float = 129.0       # OpenThread child-supervision interval (parent side)
    n_subs: int = 2                    # e.g. Apple Home hub + Home Assistant (multi-admin)
    imd_s: float = 3600.0              # ICD IdleModeDuration -> subscription MaxInterval
    fast_poll_s: float = 0.2           # ICD fast-poll interval in Active Mode
    active_s: float = 1.0              # ActiveModeDuration / Threshold actually spent fast-polling
    report_frames: float = 1.5         # ReportData frames per keep-alive (6LoWPAN fragments)
    report_psdu: int = 110
    report_cpu_ms: float = 20.0        # IM + AES-CCM + scheduling at 96 MHz
    srp_period_s: float = 7200.0       # SRP lease refresh
    srp_frames: float = 3.0
    srp_cpu_ms: float = 60.0           # ECDSA P-256 SIG(0) signature
    batt_meas_period_s: float = 6 * 3600.0
    # yearly events, expressed at the 3.3 V rail
    leak_events_per_year: float = 2.0
    buzzer: bool = False              # decision Q3: no buzzer fitted
    ota_per_year: float = 1.0
    ota_mah: float = 2.3               # ~1.5 MB image over Thread BDX + flash programming (estimate)
    commissioning_mah: float = 3.0     # BLE advertising + PASE/CASE + Thread join, once

    # ---- derived charges -------------------------------------------------------------------
    @property
    def i_tx(self) -> float:
        return I_TX_MA[self.tx_dbm]

    def q_poll_uc(self) -> float:
        q = wake_uc(self.xtal32k) + frame_tx_uc(self.data_req_psdu, self.i_tx)
        return q * self.poll_scale

    def q_exchange_uc(self, frames: float, psdu: int, cpu_ms: float) -> float:
        """Device-initiated exchange: wake, send N frames, CPU work, fast-poll in Active Mode,
        receive the response (1 frame), send the MRP standalone ACK."""
        q = wake_uc(self.xtal32k)
        q += frames * frame_tx_uc(psdu, self.i_tx)
        q += cpu_ms * 1e-3 * I_CPU_RUN_MA * 1e3
        q += (self.active_s / self.fast_poll_s) * self.q_poll_uc()
        q += frame_rx_uc(60, self.i_tx)
        q += frame_tx_uc(60, self.i_tx)
        return q

    def q_report_uc(self) -> float:
        return self.q_exchange_uc(self.report_frames, self.report_psdu, self.report_cpu_ms)

    def q_srp_uc(self) -> float:
        return self.q_exchange_uc(self.srp_frames, 100, self.srp_cpu_ms)

    def q_leak_event_mc(self) -> float:
        reports = 2 * self.n_subs * self.q_report_uc() / 1e3       # alarm + clear
        wet_poll = 360 * (wake_uc(self.xtal32k) + 2e-3 * I_CPU_IDLE_MA * 1e3) / 1e3  # 1 h, 10 s
        led = 1200 * 20e-3 * 3.0                                     # 20 ms @ 3 mA every 3 s, 1 h
        buz = (60 * 0.5 * 35.0 + 120 * 0.2 * 35.0) if self.buzzer else 0.0  # 1 min 50 % + chirps
        return reports + wet_poll + led + buz

    # ---- average currents at the 3.3 V rail (uA) -------------------------------------------
    def breakdown_ua(self) -> dict[str, float]:
        return {
            "Ngủ nhẹ (sàn chip)": self.floor_ua,
            "Rò rỉ trên board": self.board_ua,
            "Thread data poll": self.q_poll_uc() / self.sai_s,
            "Child supervision": frame_rx_uc(20, self.i_tx) / self.supervision_s,
            "Báo cáo keep-alive (subscriptions)": self.n_subs * self.q_report_uc() / self.imd_s,
            "Làm mới SRP": self.q_srp_uc() / self.srp_period_s,
            "Đo pin": (wake_uc(self.xtal32k) + 40.0) / self.batt_meas_period_s,
        }

    def avg_ua(self) -> float:
        return sum(self.breakdown_ua().values())

    def yearly_events_mah(self) -> float:
        leak_mah = self.leak_events_per_year * self.q_leak_event_mc() / 3600.0  # 1 mAh = 3600 mC
        return leak_mah + self.ota_per_year * self.ota_mah


@dataclass(frozen=True)
class Battery:
    name: str
    cap_mah: float
    v_avg: float          # mean terminal voltage over the discharge at this drain
    usable: float         # fraction usable before brown-out under TX pulses
    sd_per_year: float    # self-discharge, fraction of nominal per year
    eta_floor: float      # TPS63900 efficiency at ~30 uA (Fig. 8-7)
    eta_burst: float      # TPS63900 efficiency at 10..140 mA

    @property
    def e_usable_wh(self) -> float:
        return self.cap_mah / 1000 * self.v_avg * self.usable


BATTERIES = [
    Battery("CR123A (Li-MnO2, 1 cell)", 1450, 2.85, 0.92, 0.010, 0.91, 0.92),
    Battery("2×AAA lithium (Li-FeS2)", 1200, 3.00, 0.95, 0.010, 0.91, 0.93),
    Battery("2×AAA alkaline", 1150, 2.45, 0.90, 0.025, 0.88, 0.90),
    Battery("2×AA alkaline (tham khảo)", 2600, 2.45, 0.90, 0.025, 0.88, 0.90),
]

V_RAIL = 3.3
H_PER_YEAR = 8766.0


def life_years(s: Scenario, b: Battery) -> float:
    floor_part = (s.floor_ua + s.board_ua) / b.eta_floor
    active_part = (s.avg_ua() - s.floor_ua - s.board_ua) / b.eta_burst
    p_w = V_RAIL * (floor_part + active_part) * 1e-6
    e_year_wh = p_w * H_PER_YEAR
    e_year_wh += s.yearly_events_mah() / 1000 * V_RAIL / b.eta_burst
    e_year_wh += b.sd_per_year * b.cap_mah / 1000 * b.v_avg
    e_once_wh = s.commissioning_mah / 1000 * V_RAIL / b.eta_burst
    return (b.e_usable_wh - e_once_wh) / e_year_wh


def battery_side_ua(s: Scenario, b: Battery) -> float:
    floor_part = (s.floor_ua + s.board_ua) / b.eta_floor
    active_part = (s.avg_ua() - s.floor_ua - s.board_ua) / b.eta_burst
    return V_RAIL * (floor_part + active_part) / b.v_avg


# --------------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------------
TYPICAL = Scenario()
PESSIMISTIC = replace(TYPICAL, name="pessimistic", floor_ua=40.0, board_ua=1.0, poll_scale=1.3,
                      n_subs=3, leak_events_per_year=6, ota_per_year=2, report_cpu_ms=40)
OPTIMISTIC = replace(TYPICAL, name="optimistic", floor_ua=20.0, tx_dbm=0, n_subs=1,
                     leak_events_per_year=1)


def fmt(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}"


def print_report() -> None:
    s = TYPICAL
    print("### Điện tích mỗi sự kiện (kịch bản điển hình, +9 dBm, có XTAL 32 kHz)\n")
    print("| Sự kiện | Điện tích |")
    print("|---|---|")
    print(f"| Wake + ngủ lại (1 chu kỳ light-sleep) | {fmt(wake_uc(True))} µC |")
    print(f"| Wake + ngủ lại khi KHÔNG có XTAL 32 kHz (thêm hiệu chuẩn RC) | {fmt(wake_uc(False))} µC |")
    for dbm in (0, 9, 20):
        q = replace(s, tx_dbm=dbm).q_poll_uc()
        print(f"| 1 Thread data poll @ {dbm:+d} dBm | {fmt(q)} µC |")
    print(f"| 1 báo cáo Matter (ReportData + Active Mode + ACK) | {fmt(s.q_report_uc() / 1e3, 2)} mC |")
    print(f"| 1 lần làm mới SRP | {fmt(s.q_srp_uc() / 1e3, 2)} mC |")
    print(f"| 1 sự kiện rò rỉ 1 h (LED + đo xung + 4 báo cáo) | "
          f"{fmt(replace(s, buzzer=False).q_leak_event_mc() / 3600, 3)} mAh |")
    print(f"| *(tham khảo) như trên nếu có buzzer* | "
          f"{fmt(replace(s, buzzer=True).q_leak_event_mc() / 3600, 2)} mAh |")
    print()

    for sc in (OPTIMISTIC, TYPICAL, PESSIMISTIC):
        print(f"### Phân rã dòng trung bình @3.3 V — kịch bản `{sc.name}` "
              f"(SAI {sc.sai_s:g} s, {sc.tx_dbm:+d} dBm, sàn {sc.floor_ua:g} µA, {sc.n_subs} subscription)\n")
        print("| Thành phần | µA @3.3 V | % |")
        print("|---|---:|---:|")
        tot = sc.avg_ua()
        for k, v in sc.breakdown_ua().items():
            print(f"| {k} | {fmt(v, 2)} | {fmt(100 * v / tot)} |")
        print(f"| **Tổng** | **{fmt(tot, 1)}** | 100 |")
        print(f"\nSự kiện theo năm (rò rỉ, OTA) ≈ {fmt(sc.yearly_events_mah(), 1)} mAh/năm @3.3 V.\n")

    print("### Tuổi thọ pin ước tính (năm)\n")
    print("| Pin | Năng lượng dùng được | Dòng từ pin (điển hình) | Lạc quan | **Điển hình** | Bi quan |")
    print("|---|---:|---:|---:|---:|---:|")
    for b in BATTERIES:
        print(f"| {b.name} | {fmt(b.e_usable_wh, 2)} Wh | {fmt(battery_side_ua(TYPICAL, b))} µA | "
              f"{fmt(life_years(OPTIMISTIC, b))} | **{fmt(life_years(TYPICAL, b))}** | "
              f"{fmt(life_years(PESSIMISTIC, b))} |")
    print()

    print("### Đánh đổi chu kỳ poll ICD (kịch bản điển hình)\n")
    print("| Chế độ | Slow poll | Độ trễ lệnh controller→thiết bị (tối đa) | Dòng TB @3.3 V | CR123A | 2×AAA alkaline |")
    print("|---|---:|---:|---:|---:|---:|")
    for mode, sai in (("SIT", 5), ("SIT", 10), ("SIT", 15), ("LIT", 30), ("LIT", 60)):
        sc = replace(TYPICAL, sai_s=sai)
        print(f"| {mode} | {sai} s | {sai} s | {fmt(sc.avg_ua())} µA | "
              f"{fmt(life_years(sc, BATTERIES[0]))} năm | {fmt(life_years(sc, BATTERIES[2]))} năm |")
    print()

    print("### Độ nhạy (kịch bản điển hình, CR123A)\n")
    print("| Thay đổi | Dòng TB @3.3 V | Tuổi thọ CR123A |")
    print("|---|---:|---:|")
    cases = [
        ("Cơ sở (SAI 15 s, +9 dBm, XTAL 32 kHz, IdleModeDuration 1 h)", TYPICAL),
        ("TX 0 dBm", replace(TYPICAL, tx_dbm=0)),
        ("TX +20 dBm", replace(TYPICAL, tx_dbm=20)),
        ("Không lắp XTAL 32 kHz (hiệu chuẩn RC mỗi chu kỳ ngủ)", replace(TYPICAL, xtal32k=False)),
        ("IdleModeDuration 15 phút thay vì 1 h", replace(TYPICAL, imd_s=900)),
        ("Fast poll 500 ms thay vì 200 ms", replace(TYPICAL, fast_poll_s=0.5)),
        ("Lỗi FW: peripheral không power-down khi ngủ (sàn 85 µA)",
         replace(TYPICAL, floor_ua=I_LSLEEP_NOPD_UA)),
    ]
    for label, sc in cases:
        print(f"| {label} | {fmt(sc.avg_ua())} µA | {fmt(life_years(sc, BATTERIES[0]))} năm |")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sai", type=float, help="slow-poll interval, s")
    ap.add_argument("--tx", type=int, choices=sorted(I_TX_MA), help="TX power, dBm")
    ap.add_argument("--floor", type=float, help="measured light-sleep floor, uA @3.3 V")
    ap.add_argument("--subs", type=int, help="number of subscriptions")
    ap.add_argument("--imd", type=float, help="IdleModeDuration, s")
    ap.add_argument("--no-xtal32k", action="store_true")
    a = ap.parse_args()
    overrides = {k: v for k, v in dict(sai_s=a.sai, tx_dbm=a.tx, floor_ua=a.floor,
                                       n_subs=a.subs, imd_s=a.imd).items() if v is not None}
    if a.no_xtal32k:
        overrides["xtal32k"] = False
    if not overrides:
        print_report()
        return
    sc = replace(TYPICAL, name="custom", **overrides)
    for k, v in sc.breakdown_ua().items():
        print(f"{k:40s} {v:8.2f} uA")
    print(f"{'TOTAL @3.3 V':40s} {sc.avg_ua():8.2f} uA")
    for b in BATTERIES:
        print(f"{b.name:32s} {life_years(sc, b):5.2f} years")


if __name__ == "__main__":
    main()

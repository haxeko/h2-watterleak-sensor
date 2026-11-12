#!/usr/bin/env python3
"""
Analyse a Nordic PPK2 capture of the h2-watterleak-sensor (phase 6) and compare it with the
phase 1 power budget (tools/power_budget.py) and the acceptance criteria in docs/06.

    python3 tools/ppk2_analyze.py sleep_10min.csv --vsrc 3.0
    python3 tools/ppk2_analyze.py leak_trigger.csv --vsrc 3.0 --trigger D0 --exc D1
    python3 tools/ppk2_analyze.py long_2h.csv --vsrc 3.0 --json long_2h.json

Input: CSV exported by nRF Connect for Desktop -> Power Profiler (PPK2). Needed columns:
  * a time column whose header contains "time", unit in brackets: "Timestamp(ms)", "(us)" or "(s)";
  * a current column whose header contains "current": "Current(uA)", "(nA)", "(mA)" or "(A)";
  * optional logic port: one "D0-D7" column of '0'/'1' characters (D0 first, see --digital-order)
    or separate D0 ... D7 columns.
The file is streamed, so captures of millions of rows are fine (~1-2 million rows per second).

Measurement setup (docs/06 section 1): PPK2 in source-meter mode on JP1 pad 2 (BAT_RAW, JP1 opened),
so the current includes the TPS63900 losses, exactly what the CR123A would see.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import power_budget as pb  # phase 1 model: battery data, typical scenario
except ImportError:            # keep working if the script is copied elsewhere
    pb = None

TIME_UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6}
CURRENT_UNITS = {"a": 1e6, "ma": 1e3, "ua": 1.0, "µa": 1.0, "na": 1e-3}     # -> uA

# log-spaced histogram for streaming percentiles: 0.01 uA .. 1 A, 200 bins per decade
H_LO, H_HI, H_PER_DEC = -2.0, 6.0, 200
H_BINS = int((H_HI - H_LO) * H_PER_DEC) + 2

NFR02_FLOOR_UA = 35.0          # sleep floor at the cell (docs/01 NFR-02)
FR02_LATENCY_S = 1.0           # water -> packet on air (docs/01 FR-02)


# ------------------------------------------------------------------------------------------ parsing
def _unit(header: str) -> str:
    m = re.search(r"\(([^)]*)\)", header)
    return m.group(1).strip().lower().replace("μ", "µ") if m else ""


def parse_header(header: list[str]):
    t_idx = c_idx = combined = None
    t_scale = c_scale = 1.0
    digital = {}
    for i, h in enumerate(header):
        hl = h.strip().lower()
        if t_idx is None and "time" in hl:
            t_idx, t_scale = i, TIME_UNITS.get(_unit(h), 1e-3)
        elif c_idx is None and "current" in hl:
            c_idx, c_scale = i, CURRENT_UNITS.get(_unit(h), 1.0)
        elif re.fullmatch(r"d0-d7", hl.replace(" ", "")):
            combined = i
        else:
            m = re.fullmatch(r"d([0-7])", hl.replace(" ", ""))
            if m:
                digital[int(m.group(1))] = i
    if t_idx is None or c_idx is None:
        raise SystemExit(f"cannot find time/current columns in header: {header}")
    return t_idx, t_scale, c_idx, c_scale, combined, digital


def channel_index(name: str | None) -> int | None:
    if not name:
        return None
    m = re.fullmatch(r"[dD]?([0-7])", name.strip())
    if not m:
        raise SystemExit(f"bad logic channel '{name}', use D0..D7")
    return int(m.group(1))


# ------------------------------------------------------------------------------------------ analysis
class Analysis:
    def __init__(self, burst_ua: float, tx_ua: float, merge_s: float, channels: list[int]):
        self.burst_ua, self.tx_ua, self.merge_s = burst_ua, tx_ua, merge_s
        self.n = 0
        self.t_first = self.t_prev = None
        self.q_total = 0.0                      # uA*s
        self.i_max = 0.0
        self.hist = [0] * H_BINS
        self.bursts = []                        # (t_start, t_end, q_uAs, peak_uA)
        self._in = False
        self._b = None
        self.channels = channels
        self.levels = {}                        # channel -> last level
        self.edges = {c: [] for c in channels}  # channel -> [(t, new_level)]

    def _hist_add(self, i_ua: float):
        if i_ua <= 10 ** H_LO:
            k = 0
        else:
            k = min(int((math.log10(i_ua) - H_LO) * H_PER_DEC) + 1, H_BINS - 1)
        self.hist[k] += 1

    def percentile(self, p: float) -> float:
        target = p / 100 * self.n
        acc = 0
        for k, c in enumerate(self.hist):
            acc += c
            if acc >= target and c:
                return 0.0 if k == 0 else 10 ** (H_LO + (k - 0.5) / H_PER_DEC)
        return self.i_max

    def add(self, t: float, i_ua: float, bits: dict[int, int] | None):
        if self.t_first is None:
            self.t_first = self.t_prev = t
        dt = max(t - self.t_prev, 0.0)
        self.t_prev = t
        self.n += 1
        self.q_total += i_ua * dt
        self.i_max = max(self.i_max, i_ua)
        self._hist_add(i_ua)

        if i_ua >= self.burst_ua:
            if not self._in:
                self._in = True
                self._b = [t, t, 0.0, 0.0]
            self._b[1] = t
        if self._in:
            self._b[2] += i_ua * dt
            self._b[3] = max(self._b[3], i_ua)
            if i_ua < self.burst_ua and t - self._b[1] > self.merge_s:
                self.bursts.append(tuple(self._b))
                self._in = False

        if bits:
            for c in self.channels:
                lvl = bits.get(c)
                if lvl is None:
                    continue
                prev = self.levels.get(c)
                if prev is not None and lvl != prev:
                    self.edges[c].append((t, lvl))
                self.levels[c] = lvl

    def finish(self):
        if self._in:
            self.bursts.append(tuple(self._b))
            self._in = False

    @property
    def duration(self) -> float:
        return (self.t_prev - self.t_first) if self.n > 1 else 0.0


def read_capture(path: str, an: Analysis, digital_order: str):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.reader(f)
        header = next(rd)
        t_idx, t_scale, c_idx, c_scale, combined, digital = parse_header(header)
        want = an.channels
        if want and combined is None and not all(c in digital for c in want):
            raise SystemExit(f"logic channels {want} not found in header: {header}")
        for row in rd:
            if len(row) <= max(t_idx, c_idx):
                continue
            try:
                t = float(row[t_idx]) * t_scale
                i_ua = float(row[c_idx]) * c_scale
            except ValueError:
                continue
            bits = None
            if want:
                bits = {}
                if combined is not None and combined < len(row):
                    s = row[combined].strip()
                    for c in want:
                        pos = c if digital_order == "d0first" else len(s) - 1 - c
                        if 0 <= pos < len(s) and s[pos] in "01":
                            bits[c] = int(s[pos])
                else:
                    for c in want:
                        try:
                            bits[c] = 1 if float(row[digital[c]]) >= 0.5 else 0
                        except (ValueError, IndexError):
                            pass
            an.add(t, i_ua, bits)
    an.finish()


# ------------------------------------------------------------------------------------------ reports
def battery_estimate(avg_ua: float, floor_ua: float, vsrc: float) -> dict:
    out = {}
    if pb is None:
        return out
    b = pb.BATTERIES[0]                       # CR123A
    p_w = vsrc * avg_ua * 1e-6
    e_year_wh = p_w * pb.H_PER_YEAR + b.sd_per_year * b.cap_mah / 1000 * b.v_avg
    out["life_years_cr123a"] = b.e_usable_wh / e_year_wh
    model_ua = pb.battery_side_ua(pb.TYPICAL, b)          # at the cell's mean voltage
    out["model_typical_ua_at_vsrc"] = model_ua * b.v_avg / vsrc
    out["model_typical_life_years"] = pb.life_years(pb.TYPICAL, b)
    # chip floor at the 3.3 V rail, the unit of power_budget.py --floor
    out["floor_rail_ua_for_power_budget"] = floor_ua * vsrc * b.eta_floor / pb.V_RAIL
    return out


def leak_events(an: Analysis, trig: int, exc: int, tx_ua: float, window_s: float) -> list[dict]:
    """Match each simulated wet edge (trigger 0->1) with the WET entry (PROBE_EXC 1->0) and the first
    radio burst after it."""
    t_edges = an.edges.get(trig, [])
    e_edges = an.edges.get(exc, [])
    rises = [t for t, lvl in t_edges if lvl == 1]
    falls = [t for t, lvl in t_edges if lvl == 0]
    exc_falls = [t for t, lvl in e_edges if lvl == 0]
    tx_starts = [b[0] for b in an.bursts if b[3] >= tx_ua]
    res = []
    for t0 in rises:
        t_off = next((t for t in falls if t > t0), None)
        width = (t_off - t0) if t_off else None
        exc_before = None
        for t, lvl in e_edges:
            if t >= t0:
                break
            exc_before = lvl
        t1 = next((t for t in exc_falls if t0 < t <= t0 + window_s), None)
        t2 = next((t for t in tx_starts if t1 is not None and t >= t1), None)
        res.append({
            "t_trigger_s": t0,
            "pulse_ms": None if width is None else width * 1e3,
            "armed_before": exc_before != 0,
            "confirmed": t1 is not None,
            "confirm_ms": None if t1 is None else (t1 - t0) * 1e3,
            "report_tx_ms": None if t2 is None else (t2 - t0) * 1e3,
        })
    return res


def wet_pulses(an: Analysis, exc: int) -> list[tuple[float, float]]:
    """(start, width) of short PROBE_EXC pulses = pulsed sampling while WET."""
    out = []
    rise = None
    for t, lvl in an.edges.get(exc, []):
        if lvl == 1:
            rise = t
        elif rise is not None:
            if t - rise < 0.2:
                out.append((rise, t - rise))
            rise = None
    return out


def fmt(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--vsrc", type=float, default=3.0, help="PPK2 source voltage (V), default 3.0")
    ap.add_argument("--burst-ma", type=float, default=1.0, help="burst threshold (mA), default 1")
    ap.add_argument("--tx-ma", type=float, default=20.0, help="radio burst threshold (mA), default 20")
    ap.add_argument("--merge-ms", type=float, default=3.0, help="merge bursts closer than this (ms)")
    ap.add_argument("--trigger", help="logic channel of the water simulator mark, e.g. D0")
    ap.add_argument("--exc", help="logic channel wired to TP7 (PROBE_EXC), e.g. D1")
    ap.add_argument("--digital-order", choices=("d0first", "d7first"), default="d0first",
                    help="character order of a combined D0-D7 column")
    ap.add_argument("--json", help="also write the results to this JSON file")
    a = ap.parse_args()

    trig, exc = channel_index(a.trigger), channel_index(a.exc)
    channels = [c for c in (trig, exc) if c is not None]
    an = Analysis(a.burst_ma * 1e3, a.tx_ma * 1e3, a.merge_ms * 1e-3, channels)
    read_capture(a.csv, an, a.digital_order)
    if an.n < 2 or an.duration <= 0:
        raise SystemExit("not enough samples")

    dur = an.duration
    avg = an.q_total / dur
    floor = an.percentile(50)
    res = {"file": os.path.basename(a.csv), "samples": an.n, "duration_s": dur,
           "sample_rate_hz": (an.n - 1) / dur, "vsrc_v": a.vsrc,
           "avg_ua": avg, "floor_median_ua": floor, "p5_ua": an.percentile(5),
           "p95_ua": an.percentile(95), "max_ua": an.i_max}

    print(f"# PPK2 — {res['file']}\n")
    print(f"| Mục | Giá trị |\n|---|---|")
    print(f"| Thời lượng | {dur:.1f} s ({an.n} mẫu, {res['sample_rate_hz'] / 1e3:.1f} kS/s) |")
    print(f"| Nguồn PPK2 | {a.vsrc:.2f} V vào BAT_RAW |")
    print(f"| **Dòng trung bình** | **{avg:.2f} µA** ({avg * a.vsrc:.1f} µW) |")
    ok = floor <= NFR02_FLOOR_UA
    print(f"| **Dòng sàn** (trung vị) | **{floor:.2f} µA** — NFR-02 ≤ {NFR02_FLOOR_UA:g} µA: "
          f"{'ĐẠT' if ok else 'KHÔNG ĐẠT'} |")
    print(f"| p5 / p95 / max | {res['p5_ua']:.2f} / {res['p95_ua']:.1f} / {an.i_max / 1e3:.1f} mA |")

    # radio / CPU bursts
    bursts = an.bursts
    tx = [b for b in bursts if b[3] >= an.tx_ua]
    if bursts:
        q_above = [(b[2] - floor * (b[1] - b[0])) for b in bursts]
        # slow-poll period: gaps of >= 1 s only (active-mode fast polls are 200 ms apart)
        gaps = [g for g in (b2[0] - b1[0] for b1, b2 in zip(tx, tx[1:])) if g >= 1.0]
        res.update({
            "bursts": len(bursts), "radio_bursts": len(tx),
            "burst_q_uc_median": statistics.median(q_above),
            "burst_q_uc_mean": statistics.mean(q_above),
            "burst_ms_median": statistics.median([(b[1] - b[0]) * 1e3 for b in bursts]),
            "radio_interval_s_median": statistics.median(gaps) if gaps else None,
            "burst_share_pct": 100 * sum(q_above) / an.q_total if an.q_total else 0.0,
        })
        print(f"| Xung > {a.burst_ma:g} mA | {len(bursts)} ({len(bursts) / dur * 60:.1f}/phút), "
              f"radio (> {a.tx_ma:g} mA): {len(tx)} |")
        print(f"| Điện tích mỗi xung (trên sàn) | trung vị {res['burst_q_uc_median']:.1f} µC, "
              f"TB {res['burst_q_uc_mean']:.1f} µC, dài {res['burst_ms_median']:.1f} ms |")
        if gaps:
            print(f"| Chu kỳ slow poll (trung vị, bỏ poll nhanh) | {res['radio_interval_s_median']:.2f} s (đặt 15 s) |")
        if pb is not None:
            b = pb.BATTERIES[0]
            q_model = pb.TYPICAL.q_poll_uc() * pb.V_RAIL / (b.eta_burst * a.vsrc)
            res["model_poll_q_uc_at_vsrc"] = q_model
            print(f"| Mô hình GĐ1: điện tích một lần poll | {q_model:.1f} µC @ {a.vsrc:.2f} V "
                  f"(so với trung vị đo được ở trên) |")
        print(f"| Phần điện tích của các xung | {res['burst_share_pct']:.1f} % |")

    est = battery_estimate(avg, floor, a.vsrc)
    res.update(est)
    if est:
        print(f"| **Tuổi thọ CR123A** (dòng TB này) | **{est['life_years_cr123a']:.2f} năm** |")
        print(f"| Mô hình GĐ1 (điển hình) | {est['model_typical_ua_at_vsrc']:.1f} µA @ {a.vsrc:.2f} V → "
              f"{est['model_typical_life_years']:.2f} năm |")
        print(f"| Sàn quy về rail 3,3 V | {est['floor_rail_ua_for_power_budget']:.1f} µA → "
              f"`python3 tools/power_budget.py --floor {est['floor_rail_ua_for_power_budget']:.1f}` |")
    if dur < 3600:
        print("\n> Bản ghi ngắn hơn 1 giờ nên chưa có báo cáo keep-alive (IdleModeDuration = 1 h) và lần đo pin "
              "6 giờ/lần. Dùng bản ghi này cho dòng sàn và điện tích mỗi lần poll; dòng trung bình để tính "
              "tuổi thọ nên lấy từ bản ghi ≥ 2 giờ ở 1 kS/s.")

    if trig is not None and exc is not None:
        ev = leak_events(an, trig, exc, an.tx_ua, window_s=3.0)
        res["leak_events"] = ev
        print("\n## Báo rò (bộ giả lập trên " + a.trigger.upper() + ", PROBE_EXC trên " + a.exc.upper() + ")\n")
        print("| # | Xung giả lập | Đã ARMED | Xác nhận WET | Gói radio đầu tiên | Đánh giá |\n|---|---|---|---|---|---|")
        for k, e in enumerate(ev, 1):
            p = e["pulse_ms"]
            if not e["armed_before"]:
                verdict = "bỏ qua: thiết bị chưa ở ARMED_DRY"
            elif p is not None and p < 200:
                verdict = "ĐẠT (lọc nhiễu)" if not e["confirmed"] else "KHÔNG ĐẠT (xung ngắn bị báo)"
            elif e["confirmed"]:
                lat = e["report_tx_ms"]
                verdict = ("ĐẠT" if lat is not None and lat <= FR02_LATENCY_S * 1e3
                           else "KHÔNG ĐẠT (> 1 s)" if lat is not None else "không thấy gói radio")
            else:
                verdict = "KHÔNG ĐẠT (không xác nhận)" if (p is None or p >= 300) else "vùng biên 200–300 ms"
            print(f"| {k} | {fmt(p, 0)} ms | {'có' if e['armed_before'] else 'không'} | "
                  f"{fmt(e['confirm_ms'], 0)} ms | {fmt(e['report_tx_ms'], 0)} ms | {verdict} |")
        wp = wet_pulses(an, exc)
        if wp:
            widths = [w * 1e3 for _, w in wp]
            gaps = [b[0] - a_[0] for a_, b in zip(wp, wp[1:])]
            res["wet_pulses"] = {"count": len(wp), "width_ms_median": statistics.median(widths),
                                 "period_s_median": statistics.median(gaps) if gaps else None}
            print(f"\nXung đo khi ướt: {len(wp)} xung, rộng trung vị {statistics.median(widths):.1f} ms"
                  + (f", chu kỳ trung vị {statistics.median(gaps):.2f} s" if gaps else "")
                  + " (đặt 5 ms / 10 s; xung kiểm tra trước khi về khô: 50 ms)")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()

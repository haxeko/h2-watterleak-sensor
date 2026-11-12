#!/usr/bin/env python3
"""
Leak-detection test runner for the h2-watterleak-sensor (phase 6, docs/06-ke-hoach-test.md).

Drives the water simulator (tools/leak_sim/leak_sim.ino on the remote-probe connector J2) and watches
the Matter water-leak entity in Home Assistant through the websocket API. Both use the PC clock, so
the latency is measured end to end: simulated water -> sensor -> Thread -> border router -> HA.

    pip install websockets pyserial
    export HA_TOKEN=...            # HA: Profile -> Security -> Long-lived access tokens

    # end-to-end latency and clear time, 10 cycles
    python3 tools/leak_test_runner.py --ha ws://homeassistant.local:8123/api/websocket \\
        --entity binary_sensor.h2_leak_sensor_water_leak --sim /dev/ttyACM0 latency --cycles 10

    # transient rejection: wet pulses of 50..800 ms (FR-03: < 200 ms must not be reported)
    python3 tools/leak_test_runner.py --ha ... --entity ... --sim /dev/ttyACM0 transient

    # just log state changes (real-water tests, soak tests); no simulator needed
    python3 tools/leak_test_runner.py --ha ... --entity ... --entity sensor.h2_leak_sensor_battery monitor

Every run appends rows to a CSV (--csv, default leak_test_<test>_<date>.csv).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import statistics
import sys
import time

try:
    import websockets
except ImportError:
    sys.exit("missing module: pip install websockets pyserial")

WET, DRY = "on", "off"          # HA binary_sensor (device class moisture): on = water detected


# ------------------------------------------------------------------------------------------ HA
class HomeAssistant:
    def __init__(self, url: str, token: str, entities: list[str]):
        self.url, self.token, self.entities = url, token, set(entities)
        self.states: dict[str, str | None] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.log_cb = None
        self._id = 0

    async def _call(self, payload: dict) -> dict:
        self._id += 1
        payload = dict(payload, id=self._id)
        await self.ws.send(json.dumps(payload))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self._id and msg.get("type") == "result":
                if not msg.get("success"):
                    raise RuntimeError(f"HA error: {msg.get('error')}")
                return msg

    async def connect(self):
        self.ws = await websockets.connect(self.url, max_size=None, ping_interval=20)
        msg = json.loads(await self.ws.recv())
        if msg.get("type") != "auth_required":
            raise RuntimeError(f"unexpected HA greeting: {msg}")
        await self.ws.send(json.dumps({"type": "auth", "access_token": self.token}))
        msg = json.loads(await self.ws.recv())
        if msg.get("type") != "auth_ok":
            raise RuntimeError(f"HA authentication failed: {msg}")
        states = await self._call({"type": "get_states"})
        for st in states.get("result", []):
            if st.get("entity_id") in self.entities:
                self.states[st["entity_id"]] = st.get("state")
        missing = self.entities - set(self.states)
        if missing:
            raise RuntimeError(f"entities not found in HA: {', '.join(sorted(missing))}")
        await self._call({"type": "subscribe_events", "event_type": "state_changed"})
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            t = time.time()                      # arrival time on this PC
            msg = json.loads(raw)
            if msg.get("type") != "event":
                continue
            data = msg.get("event", {}).get("data", {})
            eid = data.get("entity_id")
            if eid not in self.entities:
                continue
            new = (data.get("new_state") or {}).get("state")
            old = self.states.get(eid)
            self.states[eid] = new
            if new != old:
                if self.log_cb:
                    self.log_cb(t, eid, old, new)
                await self.queue.put((t, eid, new))

    async def wait_for(self, entity: str, wanted: set[str], timeout: float):
        """First change of `entity` into one of `wanted` within `timeout`; (time, state) or None."""
        end = time.time() + timeout
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return None
            try:
                t, eid, state = await asyncio.wait_for(self.queue.get(), remaining)
            except asyncio.TimeoutError:
                return None
            if eid == entity and state in wanted:
                return t, state

    def drain(self):
        while not self.queue.empty():
            self.queue.get_nowait()


# ------------------------------------------------------------------------------------------ simulator
class Simulator:
    def __init__(self, port: str):
        import serial
        self.ser = serial.Serial(port, 115200, timeout=2)
        end = time.time() + 6                    # most boards reset when the port opens
        while time.time() < end:
            if self.ser.readline().decode(errors="ignore").strip() == "READY":
                break
        self.cmd("D")

    def cmd(self, c: str) -> tuple[float, str]:
        self.ser.reset_input_buffer()
        self.ser.write((c + "\n").encode())
        self.ser.flush()
        t = time.time()                          # command written: wet edge within ~1 ms (USB)
        ack = self.ser.readline().decode(errors="ignore").strip()
        if not ack.startswith("OK"):
            raise RuntimeError(f"simulator did not acknowledge '{c}': '{ack}'")
        return t, ack


# ------------------------------------------------------------------------------------------ tests
def stamp(t: float | None) -> str:
    return "" if t is None else dt.datetime.fromtimestamp(t).isoformat(timespec="milliseconds")


async def ensure_dry(ha: HomeAssistant, entity: str, timeout: float = 120.0) -> bool:
    if ha.states.get(entity) == DRY:
        return True
    print(f"  waiting for {entity} = {DRY} ...")
    return await ha.wait_for(entity, {DRY}, timeout) is not None


async def test_latency(ha, sim, a, rows):
    for k in range(1, a.cycles + 1):
        if not await ensure_dry(ha, a.entity[0]):
            print("  sensor did not return to dry, stopping")
            break
        ha.drain()
        t_wet, _ = await asyncio.to_thread(sim.cmd, "W")
        ev = await ha.wait_for(a.entity[0], {WET}, a.timeout)
        t_on = ev[0] if ev else None
        await asyncio.sleep(a.hold)
        t_dry, _ = await asyncio.to_thread(sim.cmd, "D")
        ev = await ha.wait_for(a.entity[0], {DRY}, 120.0)
        t_off = ev[0] if ev else None
        lat = None if t_on is None else t_on - t_wet
        clr = None if t_off is None else t_off - t_dry
        print(f"  #{k}: báo rò sau {lat if lat is None else round(lat, 3)} s, "
              f"về khô sau {clr if clr is None else round(clr, 1)} s")
        rows.append({"test": "latency", "n": k, "pulse_ms": "", "entity": a.entity[0], "state": "",
                     "t_wet": stamp(t_wet), "t_on": stamp(t_on),
                     "latency_s": lat, "t_dry": stamp(t_dry), "t_off": stamp(t_off), "clear_s": clr,
                     "reported": t_on is not None, "expected": "báo", "pass": t_on is not None})
        await asyncio.sleep(a.rest)

    lats = [r["latency_s"] for r in rows if r["test"] == "latency" and r["latency_s"] is not None]
    clrs = [r["clear_s"] for r in rows if r["test"] == "latency" and r["clear_s"] is not None]
    if lats:
        lats.sort()
        print(f"\nĐộ trễ đầu-cuối tới HA: n = {len(lats)}/{a.cycles}, min {lats[0]:.3f} s, "
              f"trung vị {statistics.median(lats):.3f} s, max {lats[-1]:.3f} s "
              f"(tiêu chí: trung vị ≤ 1,5 s, max ≤ 3 s)")
    if clrs:
        print(f"Thời gian về khô: min {min(clrs):.1f} s, max {max(clrs):.1f} s (kỳ vọng 30–41 s)")


async def test_transient(ha, sim, a, rows):
    for width in a.widths:
        expected = "không báo" if width < 200 else ("báo" if width >= 300 else "biên")
        for k in range(1, a.repeats + 1):
            if not await ensure_dry(ha, a.entity[0]):
                print("  sensor did not return to dry, stopping")
                return
            ha.drain()
            t_wet, _ = await asyncio.to_thread(sim.cmd, f"P {width}")
            ev = await ha.wait_for(a.entity[0], {WET}, a.timeout)
            reported = ev is not None
            t_off = None
            if reported:
                ev_off = await ha.wait_for(a.entity[0], {DRY}, 120.0)
                t_off = ev_off[0] if ev_off else None
            ok = (expected == "biên") or (reported == (expected == "báo"))
            print(f"  xung {width} ms #{k}: {'BÁO' if reported else 'không báo'} "
                  f"(kỳ vọng: {expected}) {'ĐẠT' if ok else 'KHÔNG ĐẠT'}")
            rows.append({"test": "transient", "n": k, "pulse_ms": width, "entity": a.entity[0], "state": "",
                         "t_wet": stamp(t_wet),
                         "t_on": stamp(ev[0]) if ev else "", "latency_s": (ev[0] - t_wet) if ev else None,
                         "t_dry": "", "t_off": stamp(t_off), "clear_s": None, "reported": reported,
                         "expected": expected, "pass": ok})
            await asyncio.sleep(a.gap)
    bad = [r for r in rows if r["test"] == "transient" and not r["pass"]]
    print(f"\nChống báo giả: {'ĐẠT' if not bad else f'KHÔNG ĐẠT ({len(bad)} lần sai)'}")


async def monitor(ha, a, rows):
    print("Đang theo dõi, Ctrl+C để dừng.")
    for e in sorted(ha.entities):
        print(f"  {e} = {ha.states.get(e)}")
    while True:
        t, eid, state = await ha.queue.get()
        rows.append({"test": "monitor", "n": "", "pulse_ms": "", "entity": eid, "state": state,
                     "t_wet": "", "t_on": stamp(t), "latency_s": None, "t_dry": "", "t_off": "",
                     "clear_s": None, "reported": "", "expected": "", "pass": ""})


# ------------------------------------------------------------------------------------------ main
async def run(a):
    token = a.token or os.environ.get("HA_TOKEN")
    if a.token_file:
        token = open(os.path.expanduser(a.token_file), encoding="utf-8").read().strip()
    if not token:
        sys.exit("no Home Assistant token: use --token-file, --token or HA_TOKEN")

    ha = HomeAssistant(a.ha, token, a.entity)
    ha.log_cb = lambda t, e, old, new: print(f"  [{stamp(t)}] {e}: {old} -> {new}")
    await ha.connect()
    rows: list[dict] = []
    path = a.csv or f"leak_test_{a.test}_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    try:
        if a.test == "monitor":
            await monitor(ha, a, rows)
        else:
            if not a.sim:
                sys.exit(f"'{a.test}' needs the water simulator: --sim <serial port>")
            sim = Simulator(a.sim)
            try:
                if a.test == "latency":
                    await test_latency(ha, sim, a, rows)
                else:
                    await test_transient(ha, sim, a, rows)
            finally:
                sim.cmd("D")
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if rows:
            new = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                if new:
                    w.writeheader()
                w.writerows(rows)
            print(f"\n{len(rows)} dòng đã ghi vào {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ha", required=True, help="ws://<host>:8123/api/websocket")
    ap.add_argument("--token-file", help="file containing a long-lived access token")
    ap.add_argument("--token", help="long-lived access token (prefer --token-file or HA_TOKEN)")
    ap.add_argument("--entity", action="append", required=True,
                    help="water-leak binary_sensor first; repeat to also log e.g. the battery sensor")
    ap.add_argument("--sim", help="serial port of the water simulator")
    ap.add_argument("--csv", help="output CSV (appended)")
    ap.add_argument("--timeout", type=float, default=10.0, help="max wait for a wet report (s)")
    sub = ap.add_subparsers(dest="test", required=True)
    p = sub.add_parser("latency", help="end-to-end latency and clear time")
    p.add_argument("--cycles", type=int, default=10)
    p.add_argument("--hold", type=float, default=5.0, help="wet time per cycle (s)")
    p.add_argument("--rest", type=float, default=20.0, help="pause after each cycle (s)")
    p = sub.add_parser("transient", help="short wet pulses must not be reported (FR-03)")
    p.add_argument("--widths", type=int, nargs="+", default=[50, 100, 150, 250, 400, 800])
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--gap", type=float, default=15.0, help="pause between pulses (s)")
    sub.add_parser("monitor", help="log state changes only")
    a = ap.parse_args()
    try:
        asyncio.run(run(a))
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate the hierarchical KiCad 9 schematic of the h2-watterleak-sensor board.

Style: every pin gets a 2.54 mm wire stub ending in a net label, a global label (nets that cross
sheets), a power symbol (+3V3 / GND) or a no-connect flag. Parts are grouped per functional block.

    python3 hardware/tools/gen_sch.py      # writes hardware/h2-leak-sensor/*.kicad_sch (+ project files)
"""
from __future__ import annotations

import copy
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexpr import Sym, dump, find, find_all, parse  # noqa: E402

PROJECT = "h2-leak-sensor"
PRJ_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", PROJECT))
SYS_SYM = "/usr/share/kicad/symbols"
SCH_VERSION = 20250114
NS = uuid.UUID("a3d5c1f2-9b8e-4c7d-8e6f-5a4b3c2d1e0f")
Y, N = Sym("yes"), Sym("no")
GRID = 1.27


def U(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


def font(size=1.27, hide=False, justify=None, bold=False):
    f = ["font", ["size", size, size]]
    if bold:
        f.append(["bold", Y])
    e = ["effects", f]
    if justify:
        e.append(["justify", *[Sym(j) for j in justify.split()]])
    if hide:
        e.append(["hide", Y])
    return e


# ============================================================================================
# Library access (flattens derived symbols)
# ============================================================================================
class Library:
    def __init__(self):
        self.trees = {}

    def _tree(self, lib):
        if lib not in self.trees:
            path = (os.path.join(PRJ_DIR, "lib", "h2leak.kicad_sym") if lib == "h2leak"
                    else os.path.join(SYS_SYM, f"{lib}.kicad_sym"))
            self.trees[lib] = {s[1]: s for s in find_all(parse(open(path, encoding="utf-8").read()), "symbol")}
        return self.trees[lib]

    def flat(self, lib, name):
        syms = self._tree(lib)
        s = copy.deepcopy(syms[name])
        ext = find(s, "extends")
        if not ext:
            return s
        base = self.flat(lib, ext[1])
        out = [base[0], name]
        child_props = {p[1]: p for p in find_all(s, "property")}
        for item in base[2:]:
            if isinstance(item, list) and item and item[0] == "property" and item[1] in child_props:
                out.append(child_props.pop(item[1]))
            elif isinstance(item, list) and item and item[0] == "symbol":
                sub = copy.deepcopy(item)
                sub[1] = name + sub[1][len(ext[1]):]
                out.append(sub)
            else:
                out.append(item)
        # child-only properties go before the graphic units
        idx = next(i for i, it in enumerate(out) if isinstance(it, list) and it and it[0] == "symbol")
        for p in child_props.values():
            out.insert(idx, p)
            idx += 1
        return out

    def get(self, lib_id):
        lib, name = lib_id.split(":", 1)
        flat = self.flat(lib, name)
        pins = {}

        def walk(node):
            for c in node:
                if isinstance(c, list) and c and c[0] == "symbol":
                    walk(c)
                elif isinstance(c, list) and c and c[0] == "pin":
                    at = find(c, "at")
                    num = find(c, "number")[1]
                    pins.setdefault(num, []).append((float(at[1]), float(at[2]), float(at[3]), str(c[1])))
        walk(flat)
        embedded = copy.deepcopy(flat)
        embedded[1] = lib_id
        props = {p[1]: p for p in find_all(flat, "property")}
        return embedded, pins, props


LIB = Library()


# ============================================================================================
# Geometry helpers (library: Y up; schematic: Y down; rotation CCW on screen)
# ============================================================================================
def rot_screen(dx, dy, r):
    r %= 360
    if r == 0:
        return dx, dy
    if r == 90:
        return dy, -dx
    if r == 180:
        return -dx, -dy
    if r == 270:
        return -dy, dx
    raise ValueError(r)


def lib_to_screen(px, py, x, y, r):
    dx, dy = rot_screen(px, -py, r)
    return snap(x + dx), snap(y + dy)


def pin_outward(angle, r):
    """Library pin angle points from the connection point to the body; outward is the opposite."""
    a = (angle + 180) % 360
    v = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[int(a)]
    return rot_screen(v[0], -v[1], r)


def dir_angle(d):
    return {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}[d]


# ============================================================================================
# Sheet builder
# ============================================================================================
class Counter:
    pwr = 0
    flg = 0


class Part:
    def __init__(self, sheet, lib_id, ref, value, x, y, r, fields, in_bom, dnp, footprint):
        self.sheet, self.lib_id, self.ref, self.value = sheet, lib_id, ref, value
        self.x, self.y, self.r = x, y, r
        self.fields, self.in_bom, self.dnp, self.footprint = fields, in_bom, dnp, footprint
        emb, self.lib_pins, self.lib_props = LIB.get(lib_id)
        sheet.lib_symbols.setdefault(lib_id, emb)

    def pin_pos(self, num):
        px, py, ang, _ = self.lib_pins[str(num)][0]
        return lib_to_screen(px, py, self.x, self.y, self.r), pin_outward(ang, self.r)


class Sheet:
    def __init__(self, name, filename, page, title, paper="A4"):
        self.name, self.filename, self.page, self.title, self.paper = name, filename, page, title, paper
        self.uuid = U("sheet", filename)
        self.parts: list[Part] = []
        self.items: list = []
        self.lib_symbols: dict = {}
        self.used_points: set = set()
        self.path = None   # instance path, set by the project

    # ---------------------------------------------------------------- parts
    def place(self, lib_id, ref, value, x, y, r=0, footprint="", fields=None, in_bom=True, dnp=False,
              ref_at=None, val_at=None, just=None):
        p = Part(self, lib_id, ref, value, snap(x), snap(y), r, fields or {}, in_bom, dnp, footprint)
        p.ref_at, p.val_at, p.just = ref_at, val_at, just
        self.parts.append(p)
        return p

    def connect(self, part, nets: dict, force=False):
        """nets: {pin_number: net_name | None (no-connect)}"""
        for num, net in nets.items():
            (px, py), d = part.pin_pos(num)
            key = (px, py)
            if key in self.used_points and not force:
                continue
            self.used_points.add(key)
            if net is None:
                self.items.append(["no_connect", ["at", px, py], ["uuid", U(self.filename, "nc", px, py)]])
                continue
            ex, ey = snap(px + 2.54 * d[0]), snap(py + 2.54 * d[1])
            self.wire(px, py, ex, ey)
            self.attach(net, ex, ey, d)

    def wire(self, x1, y1, x2, y2):
        self.items.append(["wire", ["pts", ["xy", x1, y1], ["xy", x2, y2]],
                           ["stroke", ["width", 0], ["type", Sym("default")]],
                           ["uuid", U(self.filename, "wire", x1, y1, x2, y2)]])

    def link(self, a: "Part", pa, b: "Part", pb, net=None, branch=None, glabel=False):
        """Direct wire between two pins (straight if aligned, else horizontal-then-vertical)."""
        (x1, y1), _ = a.pin_pos(pa)
        (x2, y2), _ = b.pin_pos(pb)
        self.used_points.update({(x1, y1), (x2, y2)})
        if x1 == x2 or y1 == y2:
            mx, my = snap((x1 + x2) / 2), snap((y1 + y2) / 2)
            if branch is not None:      # split at the branch point: KiCad joins wires only at end points
                self.wire(x1, y1, mx, my)
                self.wire(mx, my, x2, y2)
            else:
                self.wire(x1, y1, x2, y2)
        else:
            self.wire(x1, y1, x2, y1)
            self.wire(x2, y1, x2, y2)
            mx, my = x2, y1          # corner
        if net and branch is None:
            straight = x1 == x2 or y1 == y2
            if straight:
                vertical = x1 == x2
                self.items.append(["label", net, ["at", mx, my, 90 if vertical else 0], ["fields_autoplaced", Y],
                                   font(justify="left bottom"), ["uuid", U(self.filename, "label", net, mx, my)]])
            else:   # label at the corner, text running away from part A
                d = (1, 0) if x2 > x1 else (-1, 0)
                self.attach(net, mx, my, d)
        elif net:
            bx, by = snap(mx + 2.54 * branch[0]), snap(my + 2.54 * branch[1])
            self.wire(mx, my, bx, by)
            self.junction(mx, my)
            self.attach(net, bx, by, branch)

    def junction(self, x, y):
        self.items.append(["junction", ["at", x, y], ["diameter", 0], ["color", 0, 0, 0, 0],
                           ["uuid", U(self.filename, "junction", x, y)]])

    def power_group(self, part, pins, net):
        """Several pins with the same outward direction -> stubs joined by one wire -> one power symbol."""
        ends = []
        for num in pins:
            (px, py), d = part.pin_pos(num)
            self.used_points.add((px, py))
            ex, ey = snap(px + 2.54 * d[0]), snap(py + 2.54 * d[1])
            self.wire(px, py, ex, ey)
            ends.append((ex, ey))
        for (x1, y1), (x2, y2) in zip(ends, ends[1:]):
            self.wire(x1, y1, x2, y2)
        mid = ends[len(ends) // 2]
        if len(ends) > 2:
            self.junction(*mid)
        self.attach(net, mid[0], mid[1], d)

    def power_corner(self, part, pin, net):
        """Horizontal pin -> stub -> turn up (+3V3) or down (GND) -> upright power symbol."""
        (px, py), d = part.pin_pos(pin)
        self.used_points.add((px, py))
        ex, ey = snap(px + 2.54 * d[0]), snap(py + 2.54 * d[1])
        self.wire(px, py, ex, ey)
        turn = (0, -1) if net == "+3V3" else (0, 1)
        tx, ty = snap(ex + 2.54 * turn[0]), snap(ey + 2.54 * turn[1])
        self.wire(ex, ey, tx, ty)
        self.attach(net, tx, ty, turn)

    def attach(self, net, x, y, d):
        ang = dir_angle(d)
        if net in ("GND", "+3V3"):
            body = {"GND": {(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270},
                    "+3V3": {(0, -1): 0, (-1, 0): 90, (0, 1): 180, (1, 0): 270}}[net][d]
            Counter.pwr += 1
            ref = f"#PWR{Counter.pwr:03d}"
            p = Part(self, f"power:{net}", ref, net, x, y, body, {}, False, False, "")
            p.is_power = True
            self.parts.append(p)
            return
        just = "left" if ang in (0, 90) else "right"
        if net in GLOBAL_NETS:
            self.items.append(["global_label", net, ["shape", Sym(GLOBAL_NETS[net])], ["at", x, y, ang],
                               ["fields_autoplaced", Y], font(justify=just),
                               ["uuid", U(self.filename, "glabel", net, x, y)],
                               ["property", "Intersheetrefs", "${INTERSHEET_REFS}", ["at", x, y, 0],
                                font(hide=True, justify=just)]])
        else:
            self.items.append(["label", net, ["at", x, y, ang], ["fields_autoplaced", Y],
                               font(justify=just + " bottom"), ["uuid", U(self.filename, "label", net, x, y)]])

    def note(self, text, x, y, size=1.27, bold=False):
        self.items.append(["text", text, ["exclude_from_sim", N], ["at", snap(x), snap(y), 0],
                           font(size=size, justify="left top", bold=bold),
                           ["uuid", U(self.filename, "text", text[:40], x, y)]])

    def box(self, x1, y1, x2, y2, title):
        self.items.append(["rectangle", ["start", snap(x1), snap(y1)], ["end", snap(x2), snap(y2)],
                           ["stroke", ["width", 0], ["type", Sym("dash")]], ["fill", ["type", Sym("none")]],
                           ["uuid", U(self.filename, "box", x1, y1)]])
        self.note(title, x1 + 1.27, y1 + 1.27, 1.524, bold=True)

    # ---------------------------------------------------------------- serialisation
    def symbol_instance(self, p: Part, root_uuid):
        is_power = getattr(p, "is_power", False) or p.lib_id.startswith("power:")
        props = []

        fa = 90 if p.r in (90, 270) else 0

        def prop(name, value, x, y, hide=False, justify=None, ang=None):
            # KiCad draws field angle + symbol rotation and flips the justification when it normalises
            # 180 deg back to 0 deg, so compensate for symbols rotated by 90 deg.
            if justify and p.r == 90 and (ang is None):
                justify = {"left": "right", "right": "left"}.get(justify, justify)
            props.append(["property", name, value, ["at", snap(x), snap(y), fa if ang is None else ang],
                          font(hide=hide, justify=justify)])

        if is_power:
            base = (0, 1) if p.value == "GND" else (0, -1)          # body direction at rotation 0
            bx, by = rot_screen(base[0], base[1], p.r)
            off = 5.08 if bx else 3.81
            vx, vy = p.x + off * bx, p.y + off * by
            vj = None if not bx else ("left" if bx > 0 else "right")
            prop("Reference", p.ref, p.x, p.y, hide=True)
            prop("Value", p.value, vx, vy, justify=vj)
            prop("Footprint", "", p.x, p.y, hide=True)
            prop("Datasheet", "", p.x, p.y, hide=True)
            prop("Description", "", p.x, p.y, hide=True)
        else:
            if getattr(p, "ref_at", None):
                prop("Reference", p.ref, p.x + p.ref_at[0], p.y + p.ref_at[1], justify=p.just)
                prop("Value", p.value, p.x + p.val_at[0], p.y + p.val_at[1], justify=p.just)
            two_pin_vertical = p.lib_id.split(":")[1] in ("R", "C", "L") and p.r in (0, 180)
            two_pin_horizontal = p.lib_id.split(":")[1] in ("R", "C", "L") and p.r in (90, 270)
            if getattr(p, "ref_at", None):
                pass
            elif two_pin_vertical:
                prop("Reference", p.ref, p.x + 2.54, p.y - 1.27, justify="left")
                prop("Value", p.value, p.x + 2.54, p.y + 1.27, justify="left")
            elif two_pin_horizontal:
                prop("Reference", p.ref, p.x, p.y - 2.54)
                prop("Value", p.value, p.x, p.y + 2.54)
            else:
                for key in ("Reference", "Value"):
                    lp = p.lib_props.get(key)
                    at = find(lp, "at") if lp else None
                    eff = find(lp, "effects") if lp else None
                    jst = find(eff, "justify") if eff else None
                    lx, ly = (float(at[1]), float(at[2])) if at else (0.0, 0.0)
                    sx, sy = lib_to_screen(lx, ly, p.x, p.y, p.r)
                    j = " ".join(str(t) for t in jst[1:]) if (jst and p.r == 0) else None
                    prop(key, p.ref if key == "Reference" else p.value, sx, sy, justify=j)
            prop("Footprint", p.footprint, p.x, p.y, hide=True)
            ds = p.lib_props.get("Datasheet")
            prop("Datasheet", p.fields.get("Datasheet", ds[2] if ds else "~"), p.x, p.y, hide=True)
            de = p.lib_props.get("Description")
            prop("Description", p.fields.get("Description", de[2] if de else ""), p.x, p.y, hide=True)
            for k, v in p.fields.items():
                if k not in ("Datasheet", "Description"):
                    prop(k, v, p.x, p.y, hide=True)
        pins = [["pin", num, ["uuid", U(self.filename, p.ref, "pin", num)]] for num in p.lib_pins]
        return ["symbol", ["lib_id", p.lib_id], ["at", p.x, p.y, p.r], ["unit", 1],
                ["exclude_from_sim", N], ["in_bom", Y if (p.in_bom and not is_power) else N],
                ["on_board", Y], ["dnp", Y if p.dnp else N],
                ["uuid", U(self.filename, "sym", p.ref)], *props, *pins,
                ["instances", ["project", PROJECT,
                               ["path", self.path, ["reference", p.ref], ["unit", 1]]]]]

    def render(self, root_uuid, extra=None):
        doc = ["kicad_sch", ["version", SCH_VERSION], ["generator", "eeschema"], ["generator_version", "9.0"],
               ["uuid", root_uuid if self.page == 1 else self.uuid], ["paper", self.paper],
               ["title_block", ["title", self.title], ["date", "2026-11-12"], ["rev", "A"],
                ["company", "h2-watterleak-sensor"],
                ["comment", 1, "ESP32-H2 Matter-over-Thread water-leak sensor (CR123A, ICD/SED)"],
                ["comment", 2, "Generated by hardware/tools/gen_sch.py - edit the generator, not this file"]],
               ["lib_symbols", *self.lib_symbols.values()]]
        doc += self.items
        doc += [self.symbol_instance(p, root_uuid) for p in self.parts]
        if extra:
            doc += extra
        doc.append(["embedded_fonts", N])
        return doc


# ============================================================================================
# Design data
# ============================================================================================
FP = {
    "R": "Resistor_SMD:R_0603_1608Metric_Pad0.98x0.95mm_HandSolder",
    "C": "Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder",
    "C0805": "Capacitor_SMD:C_0805_2012Metric_Pad1.18x1.45mm_HandSolder",
    "LED": "LED_SMD:LED_0603_1608Metric_Pad1.05x0.95mm_HandSolder",
    "SOT23": "Package_TO_SOT_SMD:SOT-23_Handsoldering",
    "SOD323": "Diode_SMD:D_SOD-323_HandSoldering",
    "XTAL": "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm",
    "L": "h2leak:L_Sunlord_WPN4020H_HandSolder",
    "U2": "h2leak:TPS63900_WSON-10_2.5x2.5mm_HandSolder",
    "U1": "h2leak:ESP32-H2-WROOM-02C",
    "BT": "Battery:BatteryHolder_Bulgin_BX0123_1xCR123",
    "JP": "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm",
    "SW": "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A",
    "J1": "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
    "J2": "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal",
    "TP": "TestPoint:TestPoint_Pad_D1.5mm",
    "PRB": "h2leak:Electrode_Comb_12x8mm",
}

# value -> (LCSC, MPN, manufacturer)
PARTS = {
    "R_10k": ("C25804", "0603WAF1002T5E", "UNI-ROYAL"),
    "R_100k": ("C25803", "0603WAF1003T5E", "UNI-ROYAL"),
    "R_1M": ("C22935", "0603WAF1004T5E", "UNI-ROYAL"),
    "R_470k": ("C23178", "0603WAF4703T5E", "UNI-ROYAL"),
    "R_47k": ("C25819", "0603WAF4702T5E", "UNI-ROYAL"),
    "R_1k": ("C21190", "0603WAF1001T5E", "UNI-ROYAL"),
    "R_22": ("C23345", "0603WAF220JT5E", "UNI-ROYAL"),
    "R_0": ("C21189", "0603WAF0000T5E", "UNI-ROYAL"),
    "R_16k2": ("C22885", "0603WAF1622T5E", "UNI-ROYAL"),
    "C_10u": ("C19702", "CL10A106KP8NNNC", "Samsung"),
    "C_22u": ("C45783", "CL21A226MAQNNNE", "Samsung"),
    "C_100n": ("C14663", "CC0603KRX7R9BB104", "YAGEO"),
    "C_1u": ("C15849", "CL10A105KB8NNNC", "Samsung"),
    "C_10n": ("C57112", "0603B103K500NT", "FH"),
    "C_1n": ("C1588", "CL10B102KB8NNNC", "Samsung"),
    "C_12p": ("C38523", "CL10C120JB8NNNC", "Samsung"),
    "TVS": ("C19224", "PESD5V0S1BA,115", "Nexperia"),
    "NMOS": ("C20917", "AO3400A", "AOS"),
    "PMOS": ("C110499", "DMP2035U-7", "Diodes Inc"),
    "TPS63900": ("C1518762", "TPS63900DSKR", "Texas Instruments"),
    "L": ("C98361", "WPN4020H2R2MT", "Sunlord"),
    "XTAL": ("C99010", "Q13FC13500003", "Seiko Epson"),
    "LED": ("C2286", "KT-0603R", "Hubei KENTO"),
    "SW": ("C318884", "TS-1187A-B-A-B", "XKB"),
    "J2": ("C173752", "S2B-PH-K-S(LF)(SN)", "JST"),
    "J1": ("", "2.54 mm 1x08 header / pogo pads", "-"),
    "BT": ("", "BX0123 (DigiKey 708-1412-ND)", "Bulgin"),
}

GLOBAL_NETS = {   # net -> global-label shape
    "EN": "bidirectional", "BTN_N": "bidirectional", "LED_N": "bidirectional",
    "LEAK_A_N": "output", "LEAK_B_N": "output", "PROBE_EXC": "input",
    "VBAT_SENSE": "output", "VBAT_MEAS_EN": "input",
    "U0TXD": "bidirectional", "U0RXD": "bidirectional", "USB_DN": "bidirectional", "USB_DP": "bidirectional",
    "XTAL32K_P": "passive", "XTAL32K_N": "passive", "USB_DN_C": "bidirectional", "USB_DP_C": "bidirectional",
    "GPIO4": "bidirectional", "GPIO5": "bidirectional", "GPIO22": "bidirectional",
}


def fields(key, **extra):
    lcsc, mpn, mfr = PARTS[key]
    f = {"LCSC": lcsc, "MPN": mpn, "Manufacturer": mfr}
    f.update(extra)
    return f


def R(sh, ref, val, key, x, y, r, n1, n2):
    p = sh.place("Device:R", ref, val, x, y, r, FP["R"], fields(key))
    sh.connect(p, {"1": n1, "2": n2})
    return p


def C(sh, ref, val, key, x, y, r, n1, n2, fp="C"):
    p = sh.place("Device:C", ref, val, x, y, r, FP[fp], fields(key))
    sh.connect(p, {"1": n1, "2": n2})
    return p


def TVS(sh, ref, x, y, net):
    p = sh.place("Device:D_TVS", ref, "PESD5V0S1BA", x, y, 90, FP["SOD323"], fields("TVS"),
                 ref_at=(2.54, -1.27), val_at=(2.54, 1.27), just="left")
    sh.connect(p, {"2": net, "1": "GND"})
    return p


def TP(sh, ref, x, y, net):
    p = sh.place("Connector:TestPoint", ref, net, x, y, 0, FP["TP"], {"LCSC": "", "MPN": "test pad",
                                                                     "Manufacturer": "-"}, in_bom=False)
    sh.connect(p, {"1": net})
    return p


def NMOS(sh, ref, x, y, g, d, s="GND"):
    p = sh.place("Transistor_FET:AO3400A", ref, "AO3400A", x, y, 0, FP["SOT23"], fields("NMOS"))
    sh.connect(p, {"1": g, "3": d, "2": s})
    return p


def build_power():
    sh = Sheet("Power", "power.kicad_sch", 2, "Power: CR123A, protection, TPS63900 3.3 V, battery sense")
    sh.box(12.7, 22.86, 226.06, 81.28, "CR123A -> JP1 (current-measurement jumper) -> Q1 reverse-polarity PFET "
                                      "-> U2 TPS63900 buck-boost -> +3V3")
    bt = sh.place("Device:Battery_Cell", "BT1", "CR123A", 25.4, 50.8, 0, FP["BT"], fields("BT"))
    sh.connect(bt, {"1": "BAT_CELL", "2": "GND"})
    jp = sh.place("Jumper:SolderJumper_2_Bridged", "JP1", "I_MEAS", 45.72, 38.1, 0, FP["JP"],
                  {"LCSC": "", "MPN": "solder jumper (bridged)", "Manufacturer": "-"}, in_bom=False)
    sh.connect(jp, {"1": "BAT_CELL", "2": "BAT_RAW"})
    TVS(sh, "D1", 63.5, 53.34, "BAT_RAW")
    q1 = sh.place("Transistor_FET:Q_PMOS_GSD", "Q1", "DMP2035U-7", 83.82, 50.8, 90, FP["SOT23"], fields("PMOS"),
                  ref_at=(0, -10.16), val_at=(0, -7.62))
    sh.connect(q1, {"3": "BAT_RAW", "2": "VBAT_P", "1": "GND"})
    C(sh, "C1", "10u", "C_10u", 101.6, 53.34, 0, "VBAT_P", "GND")
    TP(sh, "TP1", 116.84, 40.64, "VBAT_P")
    f1 = sh.place("power:PWR_FLAG", "#FLG01", "PWR_FLAG", 109.22, 38.1, 0, "", {}, in_bom=False)
    sh.connect(f1, {"1": "VBAT_P"})
    f2 = sh.place("power:PWR_FLAG", "#FLG02", "PWR_FLAG", 15.24, 50.8, 0, "", {}, in_bom=False)
    sh.connect(f2, {"1": "GND"})
    u2 = sh.place("Regulator_Switching:TPS63900", "U2", "TPS63900DSKR", 144.78, 53.34, 0, FP["U2"],
                  fields("TPS63900"))
    sh.connect(u2, {"10": "VBAT_P", "1": "VBAT_P", "2": "GND", "9": "LX1", "7": "LX2", "8": "GND", "11": "GND",
                    "6": "+3V3", "3": "CFG1", "4": "CFG2", "5": "CFG3"})
    l1 = sh.place("Device:L", "L1", "2.2u", 144.78, 30.48, 90, FP["L"], fields("L"))
    sh.connect(l1, {"1": "LX1", "2": "LX2"})
    R(sh, "R1", "0R", "R_0", 172.72, 58.42, 0, "CFG1", "GND")
    R(sh, "R2", "0R", "R_0", 182.88, 58.42, 0, "CFG2", "GND")
    R(sh, "R3", "16.2k", "R_16k2", 193.04, 58.42, 0, "CFG3", "GND")
    C(sh, "C2", "22u", "C_22u", 210.82, 53.34, 0, "+3V3", "GND", fp="C0805")
    sh.note("U2 config (TPS63900 Table 7-2/7-3, read once at start-up):\n"
            "  SEL = GND -> VO(1) set by R3 on CFG3: 16.2k 1% = 3.3 V\n"
            "  CFG1 = CFG2 = 0R -> input current limit UNLIMITED (VO(2) unused)\n"
            "  L1 2.2 uH Isat >= 2 A, C1 10 uF in, C2 22 uF out (+22 uF at U1)\n"
            "Q1: drain to battery, source to load, gate to GND. Reversed cell -> body diode\n"
            "  blocks and Vgs = 0. Rds(on) 41 mOhm @ -1.8 V. No quiescent current.\n"
            "JP1: bridged by default; cut and fit a 2-pin header to measure the sleep current.",
            14.0, 66.04, 1.27)

    sh.box(12.7, 88.9, 182.88, 162.56, "Switched battery divider (0 A when off) -> ADC1_CH0, ATTEN2 (0..1.9 V)")
    r4 = sh.place("Device:R", "R4", "100k", 50.8, 104.14, 0, FP["R"], fields("R_100k"))
    r5 = sh.place("Device:R", "R5", "100k", 50.8, 121.92, 0, FP["R"], fields("R_100k"))
    q2 = sh.place("Transistor_FET:AO3400A", "Q2", "AO3400A", 48.26, 142.24, 0, FP["SOT23"], fields("NMOS"))
    r6 = sh.place("Device:R", "R6", "1M", 25.4, 146.05, 0, FP["R"], fields("R_1M"))
    sh.connect(r4, {"1": "VBAT_P"})
    sh.link(r4, "2", r5, "1", "VBAT_SENSE", branch=(1, 0))
    sh.link(r5, "2", q2, "3", "VBAT_DIV_LO")
    sh.connect(q2, {"2": "GND"})
    sh.link(r6, "1", q2, "1", "VBAT_MEAS_EN", branch=(0, -1))
    sh.connect(r6, {"2": "GND"})
    C(sh, "C4", "100n", "C_100n", 76.2, 116.84, 0, "VBAT_SENSE", "GND")
    sh.note("VBAT_SENSE = VBAT_P / 2 when Q2 is on (VBAT_MEAS_EN = 1).\n"
            "Q2 off -> no current path; VBAT_SENSE sits at VBAT_P (<= 3.3 V for CR123A) through R4.\n"
            "Settling: tau = (R4||R5) * C4 = 5 ms -> wait >= 30 ms before sampling.\n"
            "R6 keeps Q2 off while GPIO0 floats (reset, light-sleep with TOP power-down).\n"
            "Divider current while measuring: 16.5 uA for ~30 ms, a few times per day.",
            96.52, 101.6, 1.27)
    return sh


def build_mcu():
    sh = Sheet("MCU", "mcu.kicad_sch", 3, "MCU: ESP32-H2-WROOM-02C-H4S, reset, 32.768 kHz, USB/UART")
    u1 = sh.place("h2leak:ESP32-H2-WROOM-02C", "U1", "ESP32-H2-WROOM-02C-H4S", 147.32, 104.14, 0, FP["U1"],
                  {"LCSC": "", "MPN": "ESP32-H2-WROOM-02C-H4S", "Manufacturer": "Espressif",
                   "Datasheet": "https://documentation.espressif.com/esp32-h2-wroom-02c_datasheet_en.pdf"},
                  in_bom=False)
    sh.power_group(u1, ["1", "14"], "+3V3")
    sh.power_group(u1, ["9", "13", "29"], "GND")
    sh.connect(u1, {
        "2": "EN", "8": "BTN_N", "7": "LED_N", "5": "LEAK_A_N", "6": "PROBE_EXC", "10": "LEAK_B_N",
        "11": "XTAL32K_P", "12": "XTAL32K_N", "28": "VBAT_MEAS_EN", "27": "VBAT_SENSE",
        "26": None, "25": None, "3": "GPIO4", "4": "GPIO5",
        "15": "GPIO22", "21": "U0RXD", "22": "U0TXD", "20": None, "23": "USB_DN_C", "24": "USB_DP_C",
        "16": None, "17": None, "18": None, "19": None})
    sh.box(172.72, 22.86, 241.3, 55.88, "Decoupling at U1 pin 1")
    C(sh, "C3", "22u", "C_22u", 190.5, 40.64, 0, "+3V3", "GND", fp="C0805")
    C(sh, "C5", "100n", "C_100n", 205.74, 40.64, 0, "+3V3", "GND")
    sh.box(12.7, 22.86, 99.06, 63.5, "EN power-up delay (datasheet Fig. 5)")
    R(sh, "R7", "10k", "R_10k", 38.1, 43.18, 0, "+3V3", "EN")
    C(sh, "C6", "1u", "C_1u", 58.42, 43.18, 0, "EN", "GND")
    sh.box(12.7, 71.12, 99.06, 121.92, "32.768 kHz RTC crystal (RTC_CLK_SRC_EXT_CRYS)")
    y1 = sh.place("Device:Crystal", "Y1", "32.768kHz 9pF", 50.8, 93.98, 0, FP["XTAL"], fields("XTAL"))
    c7 = sh.place("Device:C", "C7", "12p", 35.56, 104.14, 0, FP["C"], fields("C_12p"))
    c8 = sh.place("Device:C", "C8", "12p", 66.04, 104.14, 0, FP["C"], fields("C_12p"))
    sh.link(y1, "1", c7, "1", "XTAL32K_P")
    sh.link(y1, "2", c8, "1", "XTAL32K_N")
    sh.connect(c7, {"2": "GND"})
    sh.connect(c8, {"2": "GND"})
    sh.box(198.12, 88.9, 276.86, 124.46, "USB Serial/JTAG series resistors")
    R(sh, "R9", "22R", "R_22", 220.98, 99.06, 90, "USB_DN_C", "USB_DN")
    R(sh, "R10", "22R", "R_22", 220.98, 111.76, 90, "USB_DP_C", "USB_DP")
    sh.box(12.7, 129.54, 99.06, 160.02, "Spare GPIO test pads")
    TP(sh, "TP2", 30.48, 142.24, "GPIO4")
    TP(sh, "TP3", 48.26, 142.24, "GPIO5")
    TP(sh, "TP4", 66.04, 142.24, "GPIO22")
    sh.note("Straps: GPIO9 = BOOT (10k pull-up on UI sheet), GPIO8 = LED_N (47k pull-up -> 1 at reset),\n"
            "GPIO25 not connected (only used if eFuse STRAP_JTAG_SEL_ENABLE is burnt - do not burn it).\n"
            "Wake sources: EXT1 ANY_LOW on GPIO9/10/12 (LP IO). PROBE_EXC = GPIO11 held in sleep.\n"
            "Module VBAT pin is the 3.0-3.6 V RTC supply input -> tied to +3V3, never to the CR123A.",
            106.68, 142.24, 1.27)
    return sh


def build_probe():
    sh = Sheet("Probe", "probe.kicad_sch", 4, "Water probes: 2 channels, zero standby current")
    ys = {"A": 30.48, "B": 106.68}
    for ch, y0 in ys.items():
        title = ("Channel A - two comb electrodes on the PCB bottom (in parallel)" if ch == "A"
                 else "Channel B - remote probe on J2 (JST-PH 2 pin)")
        sh.box(12.7, y0 - 10.16, 233.68, y0 + 53.34, title)
        exc, sns, gate, leak = f"EXC_{ch}", f"SNS_{ch}", f"GATE_{ch}", f"LEAK_{ch}_N"
        rs = {"A": ("R11", "R13", "R14", "R15", "C9", "Q3", "D4", "D5"),
              "B": ("R12", "R16", "R17", "R18", "C10", "Q4", "D2", "D3")}[ch]
        R(sh, rs[0], "10k", "R_10k", 40.64, y0 + 7.62, 90, "PROBE_EXC", exc)
        if ch == "A":
            for i, ref in enumerate(("PRB1", "PRB2")):
                pr = sh.place("h2leak:Electrode_Comb", ref, "Comb 12x8 mm", 76.2, y0 + 7.62 + 15.24 * i, 0,
                              FP["PRB"], {"LCSC": "", "MPN": "PCB copper (ENIG)", "Manufacturer": "-"},
                              in_bom=False)
                sh.connect(pr, {"1": exc, "2": sns})
        else:
            j2 = sh.place("Connector_Generic:Conn_01x02", "J2", "Remote probe", 81.28, y0 + 10.16, 0, FP["J2"],
                          fields("J2"))
            sh.connect(j2, {"1": exc, "2": sns})
        TVS(sh, rs[6], 58.42, y0 + 27.94, exc)
        TVS(sh, rs[7], 99.06, y0 + 27.94, sns)
        R(sh, rs[1], "10k", "R_10k", 116.84, y0 + 7.62, 90, sns, gate)
        R(sh, rs[2], "1M", "R_1M", 134.62, y0 + 20.32, 0, gate, "GND")
        C(sh, rs[4], "10n", "C_10n", 149.86, y0 + 20.32, 0, gate, "GND")
        NMOS(sh, rs[5], 175.26, y0 + 20.32, gate, leak)
        R(sh, rs[3], "470k", "R_470k", 198.12, y0 + 7.62, 0, "+3V3", leak)
        TP(sh, "TP5" if ch == "A" else "TP6", 215.9, y0 + 2.54, leak)
        sh.note(f"{exc}: PROBE_EXC (GPIO11) through 10k. {sns} -> 10k -> gate; 1M pull-down sets the trip point,\n"
                "10 nF filters RF / splashes. Dry: open circuit, 0 A. Wet: Vg = 3.3 V * 1M / (1M + Rw + 20k) > Vth\n"
                f"-> {leak} low -> EXT1 wake. Trip Rw ~ 1.3-4 MOhm (AO3400A Vth 0.65-1.45 V).\n"
                "Max DC through water 3.3 uA; firmware then drops PROBE_EXC and pulses it 5 ms every 10 s.",
                14.0, y0 + 40.64, 1.27)
    TP(sh, "TP7", 243.84, 50.8, "PROBE_EXC")
    return sh


def build_ui():
    sh = Sheet("UI_Prog", "ui.kicad_sch", 5, "User interface and programming header")
    sh.box(12.7, 22.86, 99.06, 83.82, "Button: BOOT strap + user (EXT1 wake)")
    R(sh, "R19", "10k", "R_10k", 30.48, 43.18, 0, "+3V3", "BTN_N")
    sw = sh.place("Switch:SW_Push", "SW1", "TS-1187A", 50.8, 53.34, 270, FP["SW"], fields("SW"),
                  ref_at=(3.81, -1.27), val_at=(3.81, 1.27), just="left")
    sh.connect(sw, {"1": "BTN_N", "2": "GND"})
    C(sh, "C11", "1n", "C_1n", 71.12, 55.88, 0, "BTN_N", "GND")
    sh.note("Short press: identify / status. Hold 10 s: factory reset.\n"
            "Hold while EN rises: download mode (GPIO9 = 0, GPIO8 = 1).\n"
            "Keep the RC small: tau = 10k||45k * 1 nF = 8 us << t_H 3 ms.", 14.0, 71.12, 1.27)
    sh.box(106.68, 22.86, 190.5, 83.82, "Status LED (active low on GPIO8 strap)")
    r20 = sh.place("Device:R", "R20", "1k", 124.46, 38.1, 0, FP["R"], fields("R_1k"))
    sh.connect(r20, {"1": "+3V3"})
    led = sh.place("Device:LED", "LED1", "Red", 124.46, 55.88, 90, FP["LED"], fields("LED"),
                   ref_at=(3.81, -1.27), val_at=(3.81, 1.27), just="left")
    sh.link(r20, "2", led, "2", "LED_A")
    sh.connect(led, {"1": "LED_N"})
    R(sh, "R21", "47k", "R_47k", 149.86, 43.18, 0, "+3V3", "LED_N")
    sh.note("I_LED = (3.3 - 1.9) / 1k = 1.4 mA (blinks only).\n"
            "R21 keeps GPIO8 = 1 at reset (download-boot strap)\n"
            "and keeps the LED off while GPIO8 is hi-Z in sleep.", 108.0, 73.66, 1.27)
    sh.box(12.7, 93.98, 190.5, 160.02, "J1 programming / pogo-jig header (fit header or use pogo pins)")
    j1 = sh.place("Connector_Generic:Conn_01x08", "J1", "PROG", 58.42, 121.92, 0, FP["J1"], fields("J1"))
    sh.power_corner(j1, "1", "+3V3")
    sh.power_corner(j1, "8", "GND")
    sh.connect(j1, {"2": "EN", "3": "BTN_N", "4": "U0TXD", "5": "U0RXD", "6": "USB_DN", "7": "USB_DP"})
    sh.note("J1 pin-out: 1 +3V3 (jig supplies 3.3 V, battery removed), 2 EN, 3 IO9/BOOT,\n"
            "4 TXD0 (GPIO24), 5 RXD0 (GPIO23), 6 USB D- (GPIO26), 7 USB D+ (GPIO27), 8 GND.\n"
            "USB Serial/JTAG: esptool can enter download mode by itself.\n"
            "UART: the jig drives EN and IO9 (DTR/RTS auto-reset circuit lives on the jig).",
            83.82, 116.84, 1.27)
    return sh


# ============================================================================================
# Project assembly
# ============================================================================================
def main():
    root_uuid = U("root")
    sheets = [build_power(), build_mcu(), build_probe(), build_ui()]
    for sh in sheets:
        sh.path = f"/{root_uuid}/{sh.uuid}"

    root = Sheet("Root", f"{PROJECT}.kicad_sch", 1, "h2-watterleak-sensor - top level")
    root.path = f"/{root_uuid}"
    sheet_blocks = []
    for i, sh in enumerate(sheets):
        x, y = 25.4 + (i % 2) * 101.6, 45.72 + (i // 2) * 50.8
        w, h = 76.2, 30.48
        sheet_blocks.append(
            ["sheet", ["at", x, y], ["size", w, h], ["exclude_from_sim", N], ["in_bom", Y], ["on_board", Y],
             ["dnp", N], ["fields_autoplaced", Y], ["stroke", ["width", 0.1524], ["type", Sym("solid")]],
             ["fill", ["color", 0, 0, 0, 0.0]], ["uuid", sh.uuid],
             ["property", "Sheetname", sh.name, ["at", x, y - 0.7112, 0], font(justify="left bottom")],
             ["property", "Sheetfile", sh.filename, ["at", x, y + h + 0.5842, 0], font(justify="left top")],
             ["instances", ["project", PROJECT, ["path", f"/{root_uuid}", ["page", str(sh.page)]]]]])
    root.note("h2-watterleak-sensor rev A - ESP32-H2 Matter-over-Thread water-leak detector", 25.4, 20.32, 2.54,
              bold=True)
    root.note("Blocks (one sheet each):\n"
              "  Power   - CR123A, JP1 current jumper, Q1 reverse-polarity PFET, U2 TPS63900 3.3 V, battery divider\n"
              "  MCU     - U1 ESP32-H2-WROOM-02C-H4S, EN RC, 32.768 kHz crystal, USB series resistors\n"
              "  Probe   - channel A (2 bottom comb electrodes) + channel B (J2 remote probe), zero standby current\n"
              "  UI_Prog - BOOT/user button, status LED, J1 programming header\n"
              "Design notes: docs/03-so-do-nguyen-ly.md   |   Power budget: tools/power_budget.py",
              25.4, 152.4, 1.524)
    root_doc = root.render(root_uuid, extra=sheet_blocks + [["sheet_instances", ["path", "/", ["page", "1"]]]])
    os.makedirs(PRJ_DIR, exist_ok=True)
    with open(os.path.join(PRJ_DIR, root.filename), "w", encoding="utf-8") as f:
        f.write(dump(root_doc) + "\n")
    for sh in sheets:
        with open(os.path.join(PRJ_DIR, sh.filename), "w", encoding="utf-8") as f:
            f.write(dump(sh.render(root_uuid)) + "\n")

    pro_path = os.path.join(PRJ_DIR, f"{PROJECT}.kicad_pro")
    pro = json.load(open(pro_path)) if os.path.exists(pro_path) else json.load(
        open("/usr/share/kicad/template/kicad.kicad_pro"))
    pro["meta"]["filename"] = f"{PROJECT}.kicad_pro"
    pro["sheets"] = [[root_uuid, "Root"]] + [[sh.uuid, sh.name] for sh in sheets]
    with open(pro_path, "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")
    with open(os.path.join(PRJ_DIR, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "h2leak")(type "KiCad")'
                '(uri "${KIPRJMOD}/lib/h2leak.kicad_sym")(options "")(descr "h2-watterleak-sensor symbols"))\n)\n')
    with open(os.path.join(PRJ_DIR, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n  (version 7)\n  (lib (name "h2leak")(type "KiCad")'
                '(uri "${KIPRJMOD}/lib/h2leak.pretty")(options "")(descr "h2-watterleak-sensor footprints"))\n)\n')
    n = sum(1 for sh in sheets for p in sh.parts if not getattr(p, "is_power", False))
    print(f"schematic written: {len(sheets)} sheets, {n} symbols (excl. power symbols)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate the project-specific KiCad 9 library (symbols + footprints).

Outputs (relative to the KiCad project directory hardware/h2-leak-sensor/):
    lib/h2leak.kicad_sym
    lib/h2leak.pretty/ESP32-H2-WROOM-02C.kicad_mod
    lib/h2leak.pretty/TPS63900_WSON-10_2.5x2.5mm_HandSolder.kicad_mod
    lib/h2leak.pretty/L_Sunlord_WPN4020H_HandSolder.kicad_mod
    lib/h2leak.pretty/Electrode_Comb_12x8mm.kicad_mod

Sources for the dimensions:
    ESP32-H2-WROOM-02C datasheet v1.2, Fig. 6 (dimensions) and Fig. 7 (land pattern)
    TI TPS63900 SLVSET3D, DSK0010A package / example board layout
    Sunlord WPN series catalogue, recommended land pattern (WPN4020H: a=1.9, b=1.1, c=3.7)
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexpr import Sym, dump  # noqa: E402

PRJ = os.path.join(os.path.dirname(__file__), "..", "h2-leak-sensor")
LIB = os.path.join(PRJ, "lib")
FP_DIR = os.path.join(LIB, "h2leak.pretty")
NS = uuid.UUID("6f1c8f0e-58c7-4a51-9a59-2b7f5e3f0a11")


def U(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


Y, N = Sym("yes"), Sym("no")


def font(size=1.27, hide=False, justify=None, thickness=None):
    f = ["font", ["size", size, size]]
    if thickness:
        f.append(["thickness", thickness])
    e = ["effects", f]
    if justify:
        e.append(["justify", *[Sym(j) for j in justify.split()]])
    if hide:
        e.append(["hide", Y])
    return e


# ============================================================================================
# Symbols
# ============================================================================================
def sym_prop(name, value, x=0.0, y=0.0, rot=0, hide=False, justify=None):
    return ["property", name, value, ["at", x, y, rot], font(hide=hide, justify=justify)]


def pin(etype, x, y, ang, name, number, length=2.54, hide=False):
    p = ["pin", Sym(etype), Sym("line"), ["at", x, y, ang], ["length", length]]
    if hide:
        p.append(["hide", Y])
    p += [["name", name, font()], ["number", str(number), font()]]
    return p


def rect(x1, y1, x2, y2, fill="background", width=0.254):
    return ["rectangle", ["start", x1, y1], ["end", x2, y2],
            ["stroke", ["width", width], ["type", Sym("default")]], ["fill", ["type", Sym(fill)]]]


def polyline(pts, width=0.254):
    return ["polyline", ["pts", *[["xy", x, y] for x, y in pts]],
            ["stroke", ["width", width], ["type", Sym("default")]], ["fill", ["type", Sym("none")]]]


def sym_text(txt, x, y, size=1.27):
    return ["text", txt, ["at", x, y, 0], font(size=size)]


def symbol_wroom02c():
    name = "ESP32-H2-WROOM-02C"
    L, R_, T, B = -20.32, 20.32, 27.94, -27.94
    pins = [
        # top: supplies
        pin("power_in", -2.54, 30.48, 270, "3V3", 1),
        pin("power_in", 2.54, 30.48, 270, "VBAT", 14),
        # bottom: grounds
        pin("power_in", -2.54, -30.48, 90, "GND", 9),
        pin("power_in", 0, -30.48, 90, "GND", 13),
        pin("power_in", 2.54, -30.48, 90, "GND", 29),
        # left
        pin("input", -22.86, 22.86, 0, "EN", 2),
        pin("bidirectional", -22.86, 17.78, 0, "IO9/BOOT", 8),
        pin("bidirectional", -22.86, 15.24, 0, "IO8", 7),
        pin("bidirectional", -22.86, 12.7, 0, "IO10/ZCD0", 5),
        pin("bidirectional", -22.86, 10.16, 0, "IO11/ZCD1", 6),
        pin("bidirectional", -22.86, 7.62, 0, "IO12", 10),
        pin("bidirectional", -22.86, 5.08, 0, "IO13/XTAL_32K_P", 11),
        pin("bidirectional", -22.86, 2.54, 0, "IO14/XTAL_32K_N", 12),
        pin("bidirectional", -22.86, -2.54, 0, "IO0", 28),
        pin("bidirectional", -22.86, -5.08, 0, "IO1/ADC1_CH0", 27),
        pin("bidirectional", -22.86, -7.62, 0, "IO2/ADC1_CH1/MTMS", 26),
        pin("bidirectional", -22.86, -10.16, 0, "IO3/ADC1_CH2/MTDO", 25),
        pin("bidirectional", -22.86, -12.7, 0, "IO4/ADC1_CH3/MTCK", 3),
        pin("bidirectional", -22.86, -15.24, 0, "IO5/ADC1_CH4/MTDI", 4),
        # right
        pin("bidirectional", 22.86, 22.86, 180, "IO22", 15),
        pin("bidirectional", 22.86, 17.78, 180, "RXD0/IO23", 21),
        pin("bidirectional", 22.86, 15.24, 180, "TXD0/IO24", 22),
        pin("bidirectional", 22.86, 10.16, 180, "IO25", 20),
        pin("bidirectional", 22.86, 5.08, 180, "IO26/USB_D-", 23),
        pin("bidirectional", 22.86, 2.54, 180, "IO27/USB_D+", 24),
        pin("no_connect", 22.86, -10.16, 180, "NC", 16),
        pin("no_connect", 22.86, -12.7, 180, "NC", 17),
        pin("no_connect", 22.86, -15.24, 180, "NC", 18),
        pin("no_connect", 22.86, -17.78, 180, "NC", 19),
    ]
    return ["symbol", name,
            ["exclude_from_sim", N], ["in_bom", Y], ["on_board", Y],
            sym_prop("Reference", "U", 0, T + 3.81),
            sym_prop("Value", "ESP32-H2-WROOM-02C-H4S", 0, B - 3.81),
            sym_prop("Footprint", "h2leak:ESP32-H2-WROOM-02C", 0, B - 6.35, hide=True),
            sym_prop("Datasheet",
                     "https://documentation.espressif.com/esp32-h2-wroom-02c_datasheet_en.pdf", 0, 0, hide=True),
            sym_prop("Description", "ESP32-H2 module, 802.15.4 (Thread/Zigbee) + Bluetooth LE 5, "
                     "4 MB flash, PCB antenna, 20x18x3.2 mm", 0, 0, hide=True),
            sym_prop("ki_keywords", "ESP32-H2 Thread Matter Zigbee BLE module", 0, 0, hide=True),
            ["symbol", f"{name}_0_1", rect(L, T, R_, B)],
            ["symbol", f"{name}_1_1", *pins],
            ["embedded_fonts", N]]


def symbol_electrode():
    name = "Electrode_Comb"
    g = [polyline([(-2.54, 1.27), (2.54, 1.27)]), polyline([(-2.54, -1.27), (2.54, -1.27)])]
    for x in (-2.032, -0.508, 1.016):
        g.append(polyline([(x, 1.27), (x, -0.635)]))
    for x in (-1.27, 0.254, 1.778):
        g.append(polyline([(x, -1.27), (x, 0.635)]))
    return ["symbol", name,
            ["pin_names", ["offset", 0.254], ["hide", Y]],
            ["exclude_from_sim", N], ["in_bom", N], ["on_board", Y],
            sym_prop("Reference", "PRB", 0, 3.81),
            sym_prop("Value", "Comb electrode", 0, -3.81),
            sym_prop("Footprint", "h2leak:Electrode_Comb_12x8mm", 0, -6.35, hide=True),
            sym_prop("Datasheet", "~", 0, 0, hide=True),
            sym_prop("Description", "Interdigitated ENIG water-sensing electrode (PCB copper, bottom side)",
                     0, 0, hide=True),
            ["symbol", f"{name}_0_1", *g],
            ["symbol", f"{name}_1_1",
             pin("passive", -5.08, 1.27, 0, "EXC", 1),
             pin("passive", 5.08, -1.27, 180, "SNS", 2)],
            ["embedded_fonts", N]]


def write_symbol_lib():
    lib = ["kicad_symbol_lib", ["version", 20241209], ["generator", "kicad_symbol_editor"],
           ["generator_version", "9.0"], symbol_wroom02c(), symbol_electrode()]
    os.makedirs(LIB, exist_ok=True)
    with open(os.path.join(LIB, "h2leak.kicad_sym"), "w", encoding="utf-8") as f:
        f.write(dump(lib) + "\n")


# ============================================================================================
# Footprints
# ============================================================================================
def fp_prop(fp, name, value, x, y, layer, hide=False, size=1.0):
    p = ["property", name, value, ["at", x, y, 0], ["layer", layer]]
    if hide:
        p.append(["hide", Y])
    p += [["uuid", U(fp, "prop", name)], font(size=size, thickness=0.15)]
    return p


def fp_line(fp, x1, y1, x2, y2, layer, width=0.12, tag=""):
    return ["fp_line", ["start", x1, y1], ["end", x2, y2],
            ["stroke", ["width", width], ["type", Sym("solid")]], ["layer", layer],
            ["uuid", U(fp, "line", layer, x1, y1, x2, y2, tag)]]


def fp_rect(fp, x1, y1, x2, y2, layer, width=0.05):
    return ["fp_rect", ["start", x1, y1], ["end", x2, y2],
            ["stroke", ["width", width], ["type", Sym("solid")]], ["fill", N], ["layer", layer],
            ["uuid", U(fp, "rect", layer, x1, y1, x2, y2)]]


def fp_circle(fp, cx, cy, r, layer, width=0.12, fill=False):
    return ["fp_circle", ["center", cx, cy], ["end", cx + r, cy],
            ["stroke", ["width", width], ["type", Sym("solid")]], ["fill", Y if fill else N],
            ["layer", layer], ["uuid", U(fp, "circle", layer, cx, cy, r)]]


def fp_text(fp, txt, x, y, layer, size=0.8):
    return ["fp_text", Sym("user"), txt, ["at", x, y, 0], ["layer", layer],
            ["uuid", U(fp, "text", txt, layer)], font(size=size, thickness=0.12)]


def smd_pad(fp, num, x, y, w, h, shape="roundrect", paste=True, rratio=0.25, extra=None):
    layers = ["F.Cu", "F.Mask"] + (["F.Paste"] if paste else [])
    p = ["pad", str(num), Sym("smd"), Sym(shape), ["at", x, y], ["size", w, h], ["layers", *layers]]
    if shape == "roundrect":
        p.append(["roundrect_rratio", rratio])
    if extra:
        p += extra
    p.append(["uuid", U(fp, "pad", num, x, y)])
    return p


def th_pad(fp, num, x, y, size, drill, heatsink=True):
    p = ["pad", str(num), Sym("thru_hole"), Sym("circle"), ["at", x, y], ["size", size, size],
         ["drill", drill]]
    if heatsink:
        p.append(["property", Sym("pad_prop_heatsink")])
    p += [["layers", "*.Cu", "*.Mask"], ["remove_unused_layers", N], ["uuid", U(fp, "th", num, x, y)]]
    return p


def footprint(name, descr, tags, items, attr="smd", ref_y=-3.0, val_y=3.0):
    return ["footprint", name, ["version", 20241229], ["generator", "pcbnew"], ["generator_version", "9.0"],
            ["layer", "F.Cu"], ["descr", descr], ["tags", tags],
            fp_prop(name, "Reference", "REF**", 0, ref_y, "F.SilkS"),
            fp_prop(name, "Value", name, 0, val_y, "F.Fab"),
            fp_prop(name, "Datasheet", "", 0, 0, "F.Fab", hide=True),
            fp_prop(name, "Description", "", 0, 0, "F.Fab", hide=True),
            ["attr", Sym(attr)], *items, ["embedded_fonts", N]]


def keepout_zone(fp, pts, name):
    return ["zone", ["net", 0], ["net_name", ""], ["layers", "*.Cu"], ["uuid", U(fp, "zone", name)],
            ["name", name], ["hatch", Sym("full"), 0.5], ["connect_pads", ["clearance", 0]],
            ["min_thickness", 0.25], ["filled_areas_thickness", N],
            ["keepout", ["tracks", Sym("not_allowed")], ["vias", Sym("not_allowed")],
             ["pads", Sym("not_allowed")], ["copperpour", Sym("not_allowed")],
             ["footprints", Sym("not_allowed")]],
            ["placement", ["enabled", N], ["sheetname", ""]],
            ["fill", ["thermal_gap", 0.5], ["thermal_bridge_width", 0.5]],
            ["polygon", ["pts", *[["xy", x, y] for x, y in pts]]]]


def fp_wroom02c():
    """Origin = module centre. Module 18 x 20 mm, antenna in the top 6 mm (y -10 .. -4)."""
    fp = "ESP32-H2-WROOM-02C"
    it = []
    # castellated pads: 1.5 x 0.9 mm, 0.5 mm outside the module edge (Fig. 7)
    for k in range(1, 10):                       # left column, pin 1 at top
        it.append(smd_pad(fp, k, -8.75, -2.9 + 1.5 * (k - 1), 1.5, 0.9))
    for k in range(10, 20):                      # bottom row, left to right
        it.append(smd_pad(fp, k, -6.75 + 1.5 * (k - 10), 9.75, 0.9, 1.5))
    for k in range(20, 29):                      # right column, pin 20 at bottom
        it.append(smd_pad(fp, k, 8.75, 9.1 - 1.5 * (k - 20), 1.5, 0.9))
    # exposed GND pad 29: two rectangles (Fig. 6/7), centre 8.53 mm from the left edge
    ex = 8.53 - 9.0
    it.append(smd_pad(fp, 29, ex, 2.01, 2.8, 0.55, shape="rect"))
    it.append(smd_pad(fp, 29, ex, 3.73, 2.8, 1.6, shape="rect"))
    # thermal vias (Fig. 7) + one 1.0 mm hole for soldering the EPAD from the bottom by hand
    for vx in (ex - 1.11, ex, ex + 1.13):
        it.append(th_pad(fp, 29, round(vx, 3), 2.01, 0.5, 0.3))
    for vx in (ex - 1.11, ex + 1.13):
        for vy in (3.12, 4.24):
            it.append(th_pad(fp, 29, round(vx, 3), vy, 0.5, 0.3))
    it.append(th_pad(fp, 29, ex, 3.73, 1.5, 1.0))
    # fab outline + antenna boundary
    it.append(fp_rect(fp, -9, -10, 9, 10, "F.Fab", 0.1))
    it.append(fp_line(fp, -9, -4, 9, -4, "F.Fab", 0.1, "ant"))
    it.append(fp_text(fp, "ANTENNA", 0, -7, "F.Fab", 1.0))
    # silkscreen: outline segments that do not touch the pads
    it.append(fp_line(fp, -9.12, -10.12, 9.12, -10.12, "F.SilkS"))
    it.append(fp_line(fp, -9.12, -10.12, -9.12, -3.6, "F.SilkS"))
    it.append(fp_line(fp, 9.12, -10.12, 9.12, -3.6, "F.SilkS"))
    it.append(fp_line(fp, -9.12, -4.0, 9.12, -4.0, "F.SilkS", 0.12, "antline"))
    it.append(fp_circle(fp, -10.2, -2.9, 0.25, "F.SilkS", 0.1, fill=True))   # pin-1 dot
    # courtyard
    it.append(fp_rect(fp, -9.75, -10.25, 9.75, 10.75, "F.CrtYd"))
    # antenna keep-out on all copper layers (no copper/pads/vias/parts under the PCB antenna)
    it.append(keepout_zone(fp, [(-9, -10), (9, -10), (9, -4), (-9, -4)], "Antenna keep-out"))
    return footprint(fp, "Espressif ESP32-H2-WROOM-02C (-H2S/-H4S) 20x18 mm, land pattern per datasheet v1.2 "
                     "Fig. 7; EPAD with extra 1.0 mm hole for hand soldering from the bottom side",
                     "ESP32-H2 WROOM-02C Thread Zigbee BLE module", it, ref_y=-11.2, val_y=11.6)


def fp_wson10_handsolder():
    """TI DSK0010A (WSON-10 2.5x2.5, P0.5) with toes extended 0.425 mm for iron soldering."""
    fp = "TPS63900_WSON-10_2.5x2.5mm_HandSolder"
    it = []
    for k in range(5):                       # pins 1..5 left, top to bottom
        it.append(smd_pad(fp, k + 1, -1.425, -1.0 + 0.5 * k, 1.25, 0.25))
    for k in range(5):                       # pins 6..10 right, bottom to top
        it.append(smd_pad(fp, k + 6, 1.425, 1.0 - 0.5 * k, 1.25, 0.25))
    it.append(smd_pad(fp, 11, 0, 0, 1.2, 2.0, shape="rect", paste=False))
    for i, py in enumerate((-0.55, 0.55)):             # paste windowed into 2 squares (~65 % coverage)
        it.append(["pad", "11", Sym("smd"), Sym("rect"), ["at", 0, py], ["size", 0.9, 0.75],
                   ["layers", "F.Paste"], ["uuid", U(fp, "paste", i)]])
    it.append(th_pad(fp, 11, 0, 0, 0.9, 0.6))          # bottom-side soldering hole
    it.append(th_pad(fp, 11, 0, -0.72, 0.5, 0.3))
    it.append(th_pad(fp, 11, 0, 0.72, 0.5, 0.3))
    it.append(fp_rect(fp, -1.25, -1.25, 1.25, 1.25, "F.Fab", 0.1))
    it.append(fp_line(fp, -1.25, -1.6, 1.25, -1.6, "F.SilkS"))
    it.append(fp_line(fp, -1.25, 1.6, 1.25, 1.6, "F.SilkS"))
    it.append(fp_circle(fp, -2.35, -1.45, 0.15, "F.SilkS", 0.1, fill=True))
    it.append(fp_rect(fp, -2.3, -1.85, 2.3, 1.85, "F.CrtYd"))
    return footprint(fp, "TI DSK0010A WSON-10 2.5x2.5 mm P0.5 mm, EP 1.2x2 mm, extended toes + 0.6 mm hole "
                     "in EP for hand soldering (TPS63900)", "WSON DSK TPS63900 handsolder", it,
                     ref_y=-2.6, val_y=2.6)


def fp_inductor_4020():
    fp = "L_Sunlord_WPN4020H_HandSolder"
    it = [smd_pad(fp, 1, -1.7, 0, 1.5, 3.7, rratio=0.1), smd_pad(fp, 2, 1.7, 0, 1.5, 3.7, rratio=0.1),
          fp_rect(fp, -2.0, -2.0, 2.0, 2.0, "F.Fab", 0.1),
          fp_line(fp, -2.1, -2.1, 2.1, -2.1, "F.SilkS"), fp_line(fp, -2.1, 2.1, 2.1, 2.1, "F.SilkS"),
          fp_rect(fp, -2.7, -2.35, 2.7, 2.35, "F.CrtYd")]
    return footprint(fp, "Sunlord WPN4020H 4.0x4.0x2.0 mm power inductor, land pattern a=1.9 b=1.1 c=3.7 with "
                     "pads extended outward for hand soldering", "inductor 4020 Sunlord WPN4020H", it,
                     ref_y=-3.2, val_y=3.2)


def fp_electrode(w=12.0, h=8.0, finger=0.5, gap=0.5, spine=0.8):
    """Two interdigitated combs. Pad 1 = EXC (spine on top), pad 2 = SNS (spine at bottom).
    Designed on F.Cu; the footprint is flipped to the bottom side on the board."""
    fp = f"Electrode_Comb_{int(w)}x{int(h)}mm"
    pitch = finger + gap
    xs = []
    x = -w / 2 + finger / 2
    while x <= w / 2 - finger / 2 + 1e-6:
        xs.append(round(x, 4))
        x += pitch
    y_top, y_bot = -h / 2, h / 2
    prim = {1: [], 2: []}
    ax = {1: (0.0, y_top + spine / 2), 2: (0.0, y_bot - spine / 2)}

    def rect_poly(x1, y1, x2, y2, owner):
        cx, cy = ax[owner]
        pts = [(x1 - cx, y1 - cy), (x2 - cx, y1 - cy), (x2 - cx, y2 - cy), (x1 - cx, y2 - cy)]
        return ["gr_poly", ["pts", *[["xy", round(px, 4), round(py, 4)] for px, py in pts]],
                ["width", 0], ["fill", Y]]

    prim[1].append(rect_poly(-w / 2, y_top, w / 2, y_top + spine, 1))
    prim[2].append(rect_poly(-w / 2, y_bot - spine, w / 2, y_bot, 2))
    for i, xc in enumerate(xs):
        if i % 2 == 0:   # EXC finger hanging from the top spine
            prim[1].append(rect_poly(xc - finger / 2, y_top + spine, xc + finger / 2, y_bot - spine - gap, 1))
        else:            # SNS finger rising from the bottom spine
            prim[2].append(rect_poly(xc - finger / 2, y_top + spine + gap, xc + finger / 2, y_bot - spine, 2))
    it = []
    for num in (1, 2):
        cx, cy = ax[num]
        it.append(["pad", str(num), Sym("smd"), Sym("custom"), ["at", cx, cy], ["size", 0.5, 0.5],
                   ["layers", "F.Cu", "F.Mask"], ["options", ["clearance", Sym("outline")], ["anchor", Sym("rect")]],
                   ["primitives", *prim[num]], ["uuid", U(fp, "pad", num)]])
    it.append(fp_rect(fp, -w / 2, -h / 2, w / 2, h / 2, "F.Fab", 0.1))
    it.append(fp_rect(fp, -w / 2 - 0.3, -h / 2 - 0.3, w / 2 + 0.3, h / 2 + 0.3, "F.CrtYd"))
    it.append(fp_text(fp, "EXC", -w / 2 - 1.6, -h / 2 + 0.4, "F.Fab", 0.6))
    it.append(fp_text(fp, "SNS", -w / 2 - 1.6, h / 2 - 0.4, "F.Fab", 0.6))
    return footprint(fp, f"Interdigitated water-sensing electrode {w}x{h} mm, finger {finger} mm, gap {gap} mm, "
                     "exposed copper (order ENIG); place on the bottom side", "water leak electrode comb ENIG",
                     it, ref_y=-h / 2 - 1.2, val_y=h / 2 + 1.2)


def write_footprints():
    os.makedirs(FP_DIR, exist_ok=True)
    for fpd in (fp_wroom02c(), fp_wson10_handsolder(), fp_inductor_4020(), fp_electrode()):
        with open(os.path.join(FP_DIR, fpd[1] + ".kicad_mod"), "w", encoding="utf-8") as f:
            f.write(dump(fpd) + "\n")


if __name__ == "__main__":
    write_symbol_lib()
    write_footprints()
    print("library written to", os.path.abspath(LIB))

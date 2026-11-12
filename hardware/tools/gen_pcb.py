#!/usr/bin/env python3
"""Create the placed (not yet routed) KiCad 9 board for h2-watterleak-sensor.

    python3 hardware/tools/gen_pcb.py        # -> hardware/h2-leak-sensor/h2-leak-sensor.kicad_pcb (+ rules in .kicad_pro)

Board: 70 x 42 mm, 2 layers, 1.6 mm FR4, ENIG. Origin of the board drawing = (OX, OY).
Coordinates in PLACEMENT are board-local millimetres (x right, y down, (0,0) = top-left corner).
The ESP32-H2 module sits on the left edge with its PCB antenna (6 mm) overhanging the board edge
(Espressif HW guideline: "antenna outside the base board, feed point close to the edge").
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import sexpr  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.abspath(os.path.join(HERE, "..", "h2-leak-sensor"))
PCB_PATH = os.path.join(PRJ, "h2-leak-sensor.kicad_pcb")
SYS_FP = "/usr/share/kicad/footprints"
OX, OY = 100.0, 100.0
W, H = 70.0, 42.0
CORNER_R = 2.0

# ------------------------------------------------------------------ placement (board-local mm)
# ref: (x, y, rotation_deg, side)   side: "F" top, "B" bottom
PLACEMENT = {
    # MCU, antenna overhanging the left edge (module body x -6..14, y 12..30)
    "U1": (4.0, 21.0, 90, "F"),
    # battery holder (pin 1 = +), courtyard x 25.2..67.6, y 10.5..31.5
    "BT1": (27.5, 21.0, 0, "F"),
    # --- top-left block: battery divider + USB series resistors
    "R4": (7.4, 1.6, 0, "F"), "R5": (7.4, 3.4, 0, "F"), "C4": (7.4, 5.2, 0, "F"), "R6": (7.4, 7.0, 0, "F"),
    "Q2": (12.4, 3.0, 0, "F"), "R9": (11.0, 8.0, 90, "F"), "R10": (13.0, 8.0, 90, "F"),
    # --- top strip: power path
    "TP1": (17.4, 2.0, 0, "F"), "D1": (18.4, 8.8, 0, "F"), "Q1": (22.6, 4.4, 0, "F"), "JP1": (23.4, 8.8, 0, "F"),
    "R1": (28.4, 5.0, 0, "F"), "R2": (28.4, 6.8, 0, "F"), "R3": (28.4, 8.6, 0, "F"),
    "C1": (33.6, 2.2, 0, "F"), "U2": (33.6, 6.0, 0, "F"), "L1": (38.8, 6.0, 270, "F"), "C2": (33.8, 9.3, 0, "F"),
    # --- J1 programming header along the top edge (pin 1 = +3V3 at the left, pins towards +x)
    "J1": (45.0, 3.0, 90, "F"),
    # --- column between module and battery
    "C3": (17.0, 20.8, 90, "F"), "Y1": (17.2, 25.8, 270, "F"), "C7": (21.0, 27.4, 0, "F"), "C8": (21.0, 24.4, 0, "F"),
    "TP2": (21.4, 13.0, 0, "F"), "TP3": (21.4, 16.3, 0, "F"), "TP4": (21.4, 19.6, 0, "F"),
    # --- bottom strip: decoupling at module pin 1 + EN RC
    "C5": (5.6, 32.6, 0, "F"), "R7": (5.6, 34.4, 0, "F"), "C6": (5.6, 36.2, 0, "F"),
    # --- bottom strip: probe channel A
    "R11": (9.4, 32.6, 0, "F"), "R15": (12.9, 32.6, 0, "F"), "R13": (9.4, 34.6, 0, "F"),
    "R14": (9.4, 36.6, 0, "F"), "C9": (9.4, 38.6, 0, "F"), "Q3": (15.2, 36.6, 0, "F"),
    "D4": (20.2, 37.4, 90, "F"), "D5": (22.8, 37.4, 90, "F"), "TP5": (18.6, 33.0, 0, "F"), "TP7": (21.8, 33.0, 0, "F"),
    # --- bottom strip: user interface
    "R19": (27.6, 33.0, 0, "F"), "C11": (31.2, 33.0, 0, "F"), "SW1": (30.2, 37.6, 0, "F"),
    "R20": (36.2, 33.0, 0, "F"), "LED1": (36.2, 35.6, 0, "F"), "R21": (36.2, 38.2, 0, "F"),
    # --- bottom strip: probe channel B + J2 at the right edge (opening facing +x)
    "R12": (45.8, 33.0, 0, "F"), "R16": (49.3, 33.0, 0, "F"), "R18": (52.8, 33.0, 0, "F"),
    "R17": (45.8, 35.2, 0, "F"), "C10": (45.8, 37.2, 0, "F"), "Q4": (51.0, 37.0, 0, "F"),
    "D2": (56.4, 37.2, 90, "F"), "D3": (58.8, 37.2, 90, "F"), "TP6": (52.0, 40.6, 0, "F"),
    "J2": (63.4, 38.5, 90, "F"),
    # --- electrodes (bottom side)
    "PRB1": (11.0, 37.0, 0, "B"), "PRB2": (60.0, 27.4, 0, "B"),
}
MOUNT_HOLES = [(2.8, 2.8), (2.8, 39.6), (67.4, 3.0), (40.6, 40.0)]   # 2.2 mm NPTH (M2 / printed pegs)

# copper keep-outs (board-local rectangles): (x1, y1, x2, y2, layers, tracks, vias, pour, name)
KEEPOUTS = [
    (0.0, 0.0, 3.2, 10.6, "both", True, True, True, "Antenna side corner (top)"),
    (0.0, 31.4, 3.2, 42.0, "both", True, True, True, "Antenna side corner (bottom)"),
]

NETCLASS_POWER = ["+3V3", "VBAT_P", "/Power/VBAT_P", "BAT_RAW", "/Power/BAT_RAW", "/Power/BAT_CELL",
                  "/Power/LX1", "/Power/LX2", "GND"]


def mm(v: float) -> int:
    return pcbnew.FromMM(v)


def P(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))


# ------------------------------------------------------------------ netlist
def export_netlist() -> str:
    out = os.path.join(PRJ, "build", "h2-leak-sensor.net")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out,
                    os.path.join(PRJ, "h2-leak-sensor.kicad_sch")], check=True, capture_output=True)
    return out


def read_netlist(path):
    t = sexpr.parse(open(path, encoding="utf-8").read())
    comps = {}
    for c in sexpr.find_all(sexpr.find(t, "components"), "comp"):
        ref = sexpr.find(c, "ref")[1]
        fields = {}
        fl = sexpr.find(c, "fields")
        if fl:
            for f in sexpr.find_all(fl, "field"):
                fields[sexpr.find(f, "name")[1]] = f[2] if len(f) > 2 and not isinstance(f[2], list) else ""
        props = {sexpr.find(p, "name")[1]: sexpr.find(p, "value")[1] for p in sexpr.find_all(c, "property")
                 if sexpr.find(p, "value")}
        sp = sexpr.find(c, "sheetpath")
        comps[ref] = dict(value=sexpr.find(c, "value")[1], footprint=sexpr.find(c, "footprint")[1],
                          fields=fields, props=props, sheet_names=sexpr.find(sp, "names")[1],
                          sheet_tstamps=sexpr.find(sp, "tstamps")[1], tstamp=sexpr.find(c, "tstamps")[1])
    nets = {}
    for n in sexpr.find_all(sexpr.find(t, "nets"), "net"):
        name = sexpr.find(n, "name")[1]
        nets[name] = [(sexpr.find(x, "ref")[1], sexpr.find(x, "pin")[1]) for x in sexpr.find_all(n, "node")]
    return comps, nets


def fp_lib_path(lib):
    return os.path.join(PRJ, "lib", "h2leak.pretty") if lib == "h2leak" else os.path.join(SYS_FP, f"{lib}.pretty")


# ------------------------------------------------------------------ board items
def add_outline(board):
    r = CORNER_R
    segs = [((r, 0), (W - r, 0)), ((W, r), (W, H - r)), ((W - r, H), (r, H)), ((0, H - r), (0, r))]
    for (x1, y1), (x2, y2) in segs:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        s.SetStart(P(x1, y1))
        s.SetEnd(P(x2, y2))
        board.Add(s)
    k = r * (1 - 0.70710678)
    corners = (((0, r), (k, k), (r, 0)), ((W - r, 0), (W - k, k), (W, r)),
               ((W, H - r), (W - k, H - k), (W - r, H)), ((r, H), (k, H - k), (0, H - r)))
    for st, mid, en in corners:
        a = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        a.SetLayer(pcbnew.Edge_Cuts)
        a.SetWidth(mm(0.1))
        a.SetArcGeometry(P(*st), P(*mid), P(*en))
        board.Add(a)


def set_rect_outline(zone, x1, y1, x2, y2):
    """Fill the zone's own outline in place (passing a Python-owned SHAPE_POLY_SET to SetOutline()
    leads to a double free when the board is saved)."""
    ol = zone.Outline()
    ol.RemoveAllContours()
    ol.NewOutline()
    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        ol.Append(mm(OX + x), mm(OY + y))


def add_gnd_zones(board, gnd):
    for i, layer in enumerate((pcbnew.F_Cu, pcbnew.B_Cu)):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(gnd)
        z.SetZoneName(f"GND_{'top' if layer == pcbnew.F_Cu else 'bottom'}")
        set_rect_outline(z, 0.0, 0.0, W, H)
        z.SetLocalClearance(mm(0.25))
        z.SetMinThickness(mm(0.25))
        z.SetThermalReliefGap(mm(0.3))
        z.SetThermalReliefSpokeWidth(mm(0.35))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetAssignedPriority(0)
        board.Add(z)


def add_keepout(board, x1, y1, x2, y2, layers, tracks, vias, pour, name):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    ls = pcbnew.LSET()
    if layers in ("both", "F"):
        ls.AddLayer(pcbnew.F_Cu)
    if layers in ("both", "B"):
        ls.AddLayer(pcbnew.B_Cu)
    z.SetLayerSet(ls)
    set_rect_outline(z, x1, y1, x2, y2)
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(vias)
    z.SetDoNotAllowCopperPour(pour)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetZoneName(name)
    board.Add(z)


def electrode_keepouts(board):
    """Over each bottom electrode: no pour (1 mm margin), no vias (both layers), no foreign tracks
    between the fingers (spines stay reachable from outside)."""
    for ref in ("PRB1", "PRB2"):
        x, y, _, _ = PLACEMENT[ref]
        w, h, spine = 12.0, 8.0, 0.8
        add_keepout(board, x - w / 2 - 1.0, y - h / 2 - 1.0, x + w / 2 + 1.0, y + h / 2 + 1.0, "B",
                    False, False, True, f"{ref} no GND pour")
        add_keepout(board, x - w / 2 - 0.6, y - h / 2 - 0.6, x + w / 2 + 0.6, y + h / 2 + 0.6, "both",
                    False, True, False, f"{ref} no vias")
        add_keepout(board, x - w / 2 - 0.3, y - h / 2 + spine + 0.05, x + w / 2 + 0.3, y + h / 2 - spine - 0.05,
                    "B", True, False, False, f"{ref} no tracks between fingers")


def add_mount_holes(board):
    for i, (x, y) in enumerate(MOUNT_HOLES):
        fp = pcbnew.FootprintLoad(os.path.join(SYS_FP, "MountingHole.pretty"), "MountingHole_2.2mm_M2")
        fp.SetReference(f"H{i + 1}")
        fp.SetValue("MountingHole_M2")
        fp.SetPosition(P(x, y))
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        board.Add(fp)


# ------------------------------------------------------------------ silkscreen placement
SILK_EDGE = 0.4           # text to board edge
SILK_PAD = 0.2            # text to exposed copper / holes (pad bounding boxes)
SILK_GFX = 0.1            # text to footprint silk graphics (outlines, polarity marks)
SILK_GAP = 0.35           # text to text (keeps neighbouring designators apart)
REF_SIZE = 0.8            # reference designator height (JLCPCB: >= 0.8 mm with 0.15 mm stroke)


def _bb(box):
    return (pcbnew.ToMM(box.GetLeft()) - OX, pcbnew.ToMM(box.GetTop()) - OY,
            pcbnew.ToMM(box.GetRight()) - OX, pcbnew.ToMM(box.GetBottom()) - OY)


def _xy(v):
    return pcbnew.ToMM(v.x) - OX, pcbnew.ToMM(v.y) - OY


def _hit(a, b, g=0.0):
    return a[0] < b[2] + g and b[0] < a[2] + g and a[1] < b[3] + g and b[1] < a[3] + g


def _seg_hits_box(x1, y1, x2, y2, r):
    """Liang-Barsky: does the segment touch the axis-aligned box r?"""
    t0, t1 = 0.0, 1.0
    dx, dy = x2 - x1, y2 - y1
    for p, q in ((-dx, x1 - r[0]), (dx, r[2] - x1), (-dy, y1 - r[1]), (dy, r[3] - y1)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


class SilkPlacer:
    """Puts every reference designator and board text where it touches no pad, hole, board edge,
    footprint silk line, other part's courtyard or other text (DRC: silk_over_copper,
    silk_edge_clearance; readability of polarity marks)."""

    def __init__(self, board):
        self.board = board
        L = (pcbnew.F_SilkS, pcbnew.B_SilkS)
        self.boxes = {l: [] for l in L}          # (bbox, margin, owner)
        self.segs = {l: [] for l in L}           # (x1, y1, x2, y2, half width)
        for fp in board.GetFootprints():
            ref = fp.GetReference()
            for pad in fp.Pads():
                bb = _bb(pad.GetBoundingBox())
                for silk, cu in zip(L, (pcbnew.F_Cu, pcbnew.B_Cu)):
                    if pad.IsOnLayer(cu) or pad.HasHole():
                        self.boxes[silk].append((bb, SILK_PAD, None))
            for silk, crt in zip(L, (pcbnew.F_CrtYd, pcbnew.B_CrtYd)):
                c = fp.GetCourtyard(crt)
                if c.OutlineCount():
                    self.boxes[silk].append((_bb(c.BBox()), 0.0, ref))
            for g in fp.GraphicalItems():
                if g.GetLayer() not in self.segs:
                    continue
                if g.GetClass() == "PCB_TEXT":                # e.g. the "+" polarity mark of BT1
                    self.boxes[g.GetLayer()].append((_bb(g.GetEffectiveTextShape().BBox()), SILK_GAP, None))
                    continue
                if g.GetClass() != "PCB_SHAPE":
                    continue
                hw = pcbnew.ToMM(g.GetWidth()) / 2
                st = g.GetShape()
                if st == pcbnew.SHAPE_T_SEGMENT:
                    self.segs[g.GetLayer()].append((*_xy(g.GetStart()), *_xy(g.GetEnd()), hw))
                elif st in (pcbnew.SHAPE_T_RECTANGLE, pcbnew.SHAPE_T_POLY):
                    pts = [_xy(c) for c in g.GetCorners()] if st == pcbnew.SHAPE_T_RECTANGLE else \
                        [_xy(g.GetPolyShape().Outline(0).CPoint(i)) for i in range(g.GetPolyShape().Outline(0).PointCount())]
                    for a, b in zip(pts, pts[1:] + pts[:1]):
                        self.segs[g.GetLayer()].append((*a, *b, hw))
                else:                                   # circles, arcs: small marks
                    self.boxes[g.GetLayer()].append((_bb(g.GetBoundingBox()), SILK_GFX, None))
        self.texts = {l: [] for l in L}
        self.hidden = []
        self.owner = None

    def ok(self, layer, bb):
        if bb[0] < SILK_EDGE or bb[1] < SILK_EDGE or bb[2] > W - SILK_EDGE or bb[3] > H - SILK_EDGE:
            return False
        c = CORNER_R + SILK_EDGE
        for cx, cy in ((0, 0), (W - c, 0), (0, H - c), (W - c, H - c)):
            if _hit(bb, (cx, cy, cx + c, cy + c)):
                return False
        for o, m, own in self.boxes[layer]:
            if own is not None and own == self.owner:
                continue
            if _hit(bb, o, m):
                return False
        for x1, y1, x2, y2, hw in self.segs[layer]:
            m = hw + SILK_GFX
            if _seg_hits_box(x1, y1, x2, y2, (bb[0] - m, bb[1] - m, bb[2] + m, bb[3] + m)):
                return False
        return not any(_hit(bb, o, SILK_GAP) for o in self.texts[layer])

    @staticmethod
    def _rel(item, angle):
        item.SetTextAngle(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T))
        item.SetPosition(P(0, 0))
        return _bb(item.GetEffectiveTextShape().BBox())      # glyph strokes, not the padded text box

    def _try(self, item, cands):
        for ang, pts in cands:
            rel = self._rel(item, ang)
            for x, y in pts:
                bb = (rel[0] + x, rel[1] + y, rel[2] + x, rel[3] + y)
                if self.ok(item.GetLayer(), bb):
                    item.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
                    item.SetPosition(P(x, y))
                    self.texts[item.GetLayer()].append(bb)
                    return True
        return False

    def place_ref(self, fp):
        ref = fp.Reference()
        if not ref.IsVisible():
            return
        self.owner = fp.GetReference()
        ref.SetTextSize(pcbnew.VECTOR2I(mm(REF_SIZE), mm(REF_SIZE)))
        ref.SetTextThickness(mm(0.15))
        crt = fp.GetCourtyard(pcbnew.F_CrtYd if ref.GetLayer() == pcbnew.F_SilkS else pcbnew.B_CrtYd)
        if crt.OutlineCount():
            body = _bb(crt.BBox())
        else:
            bbs = [_bb(p.GetBoundingBox()) for p in fp.Pads()]
            body = (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))
        cx, cy = (body[0] + body[2]) / 2, (body[1] + body[3]) / 2
        cands = []
        for ang in (0, 90):
            rel = self._rel(ref, ang)
            hw, hh = (rel[2] - rel[0]) / 2, (rel[3] - rel[1]) / 2
            g = 0.1
            sides = [((cx, body[1] - g - hh), (1, 0)), ((cx, body[3] + g + hh), (1, 0)),
                     ((body[0] - g - hw, cy), (0, 1)), ((body[2] + g + hw, cy), (0, 1))]
            if ang == 90:
                sides = sides[2:] + sides[:2]
            pts = []
            for d in (0, 0.4, -0.4, 0.8, -0.8, 1.2, -1.2, 1.6, -1.6):
                for (x, y), (ux, uy) in sides:
                    pts.append((x + ux * d, y + uy * d))
            for k in (0.4, 0.8):          # a little further out
                for (x, y), (ux, uy) in sides:
                    pts.append((x + uy * k * (1 if x > cx else -1), y + ux * k * (1 if y > cy else -1)))
            cands.append((ang, pts))
        if not self._try(ref, cands):
            ref.SetVisible(False)
            self.hidden.append(fp.GetReference())
        self.owner = None

    def add_text(self, txt, x, y, layer=pcbnew.F_SilkS, size=1.0, mirror=False, bold=False, search=6.0, owner=None):
        self.owner = owner                 # labels of a part may sit inside that part's courtyard
        t = pcbnew.PCB_TEXT(self.board)
        t.SetText(txt)
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(0.15 if size < 1.2 else 0.2))
        t.SetMirrored(mirror)
        t.SetBold(bold)
        n = int(search / 0.2)
        pts = sorted(((x + i * 0.2, y + j * 0.2) for i in range(-n, n + 1) for j in range(-n, n + 1)),
                     key=lambda p: (p[0] - x) ** 2 + 4 * (p[1] - y) ** 2)
        if not self._try(t, [(0, pts)]):
            t.SetPosition(P(x, y))
            print(f"warning: no free silk spot for '{txt}'")
        self.owner = None
        self.board.Add(t)


# ------------------------------------------------------------------ project rules (JLCPCB 2-layer friendly)
def write_project_rules():
    pro_path = os.path.join(PRJ, "h2-leak-sensor.kicad_pro")
    pro = json.load(open(pro_path))
    pro.setdefault("board", {})["design_settings"] = {
        "defaults": {"board_outline_line_width": 0.1, "copper_line_width": 0.2, "copper_text_size_h": 1.5,
                     "copper_text_size_v": 1.5, "copper_text_thickness": 0.3, "silk_line_width": 0.15,
                     "silk_text_size_h": 1.0, "silk_text_size_v": 1.0, "silk_text_thickness": 0.15},
        "diff_pair_dimensions": [], "drc_exclusions": [],
        "rule_severities": {"silk_overlap": "ignore", "silk_over_copper": "warning", "lib_footprint_issues": "ignore",
                            "lib_footprint_mismatch": "ignore", "text_thickness": "warning"},
        "rules": {"min_clearance": 0.15, "min_track_width": 0.15, "min_via_diameter": 0.5,
                  "min_through_hole_diameter": 0.3, "min_via_annular_width": 0.1, "min_hole_clearance": 0.25,
                  "min_hole_to_hole": 0.25, "min_copper_edge_clearance": 0.3, "min_silk_clearance": 0.0,
                  "min_text_height": 0.8, "min_text_thickness": 0.12, "solder_mask_to_copper_clearance": 0.0,
                  "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "allow_blind_buried_vias": False,
                  "allow_microvias": False, "min_resolved_spokes": 1},
        "track_widths": [0.0, 0.25, 0.4, 0.5],
        "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.6, "drill": 0.3}],
    }
    pro["net_settings"] = {
        "classes": [
            {"name": "Default", "bus_width": 12, "clearance": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
             "diff_pair_width": 0.2, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
             "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
             "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6, "priority": 2147483647},
            {"name": "Power", "bus_width": 12, "clearance": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
             "diff_pair_width": 0.2, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
             "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
             "track_width": 0.5, "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6, "priority": 0}],
        "meta": {"version": 4},
        "net_colors": None,
        "netclass_assignments": None,
        "netclass_patterns": [{"netclass": "Power", "pattern": p} for p in
                              ("+3V3", "GND", "/Power/VBAT_P", "/Power/BAT_RAW", "/Power/BAT_CELL",
                               "/Power/LX1", "/Power/LX2")],
    }
    with open(pro_path, "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")


# ------------------------------------------------------------------ main
def build():
    comps, nets = read_netlist(export_netlist())
    if os.path.exists(PCB_PATH):
        os.remove(PCB_PATH)
    board = pcbnew.NewBoard(PCB_PATH)
    board.SetCopperLayerCount(2)
    bds = board.GetDesignSettings()
    bds.SetBoardThickness(mm(1.6))

    netinfo = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni
    pad_net = {(ref, pin): name for name, nodes in nets.items() for ref, pin in nodes}

    missing = [r for r in comps if r not in PLACEMENT]
    if missing:
        raise SystemExit(f"no placement for: {missing}")
    for ref, c in sorted(comps.items()):
        lib, name = c["footprint"].split(":", 1)
        fp = pcbnew.FootprintLoad(fp_lib_path(lib), name)
        if fp is None:
            raise SystemExit(f"footprint not found: {c['footprint']}")
        fp.SetFPIDAsString(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        for k in ("LCSC", "MPN", "Manufacturer"):
            if k in c["props"]:
                fp.SetField(k, c["props"][k])
                fld = fp.GetFieldByName(k)
                fld.SetVisible(False)
                fld.SetLayer(pcbnew.F_Fab)
        fp.SetPath(pcbnew.KIID_PATH(c["sheet_tstamps"] + c["tstamp"]))
        fp.SetSheetname(c["sheet_names"].strip("/"))
        fp.SetSheetfile(c["props"].get("Sheetfile", ""))
        x, y, rot, side = PLACEMENT[ref]
        board.Add(fp)                     # Flip() needs the footprint to belong to a board
        fp.SetPosition(P(x, y))
        fp.SetOrientationDegrees(rot)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        if ref in ("U1",):
            fp.SetExcludedFromBOM(True)
        if ref.startswith(("PRB", "TP")) or ref == "JP1":
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        for pad in fp.Pads():
            key = (ref, pad.GetNumber())
            if key in pad_net:
                pad.SetNet(netinfo[pad_net[key]])

    add_outline(board)
    add_gnd_zones(board, netinfo["GND"])
    for k in KEEPOUTS:
        add_keepout(board, *k)
    electrode_keepouts(board)
    add_mount_holes(board)
    # silkscreen: board texts first (fixed meaning / position), then every reference designator
    silk = SilkPlacer(board)
    jx, jy = PLACEMENT["J1"][0], PLACEMENT["J1"][1]
    for k, name in enumerate(("3V3", "EN", "IO9", "TX", "RX", "D-", "D+", "GND")):
        silk.add_text(name, jx + 2.54 * k, jy + 1.9, size=0.8, search=0.6, owner="J1")
    silk.add_text("h2-watterleak-sensor rev A", 50.0, 9.6, size=1.0, bold=True)
    silk.add_text("PROBE", 66.0, 33.2, size=0.8, search=2.0, owner="J2")
    silk.add_text("A1", 11.0, 31.6, layer=pcbnew.B_SilkS, size=1.0, mirror=True, search=2.0)
    silk.add_text("A2", 60.0, 22.0, layer=pcbnew.B_SilkS, size=1.0, mirror=True, search=2.0)
    silk.add_text("WATER SENSE: keep A1/A2 bare, seal the rest", 36.0, 40.6, layer=pcbnew.B_SilkS,
                  size=0.8, mirror=True, search=4.0)
    # JLCPCB prints its order number where this marker is ("Remove order number: Specify a location"),
    # so it lands on the bottom away from the electrodes instead of at a random spot
    silk.add_text("JLCJLCJLCJLC", 34.0, 30.0, layer=pcbnew.B_SilkS, size=0.8, mirror=True, search=6.0)
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        r = fp.GetReference()
        if r.startswith(("H", "PRB")):               # mounting holes / electrodes: labelled by board text
            fp.Reference().SetVisible(False)
            continue
        silk.place_ref(fp)
    if silk.hidden:
        print("reference designators hidden (no free silk spot, still on F.Fab):", " ".join(silk.hidden))
    # board origin for fabrication outputs
    bds.SetAuxOrigin(P(0, H))
    bds.SetGridOrigin(P(0, 0))

    write_project_rules()
    pcbnew.SaveBoard(PCB_PATH, board)
    print("placed board written:", PCB_PATH, f"({len(comps)} footprints)")


if __name__ == "__main__":
    build()

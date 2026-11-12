#!/usr/bin/env python3
"""Fabrication outputs for JLCPCB (run after routing + DRC):

    python3 hardware/tools/fab_outputs.py

Creates hardware/h2-leak-sensor/fab/:
    gerber/*.g* + drill files, h2-leak-sensor_gerbers.zip      (upload to JLCPCB)
    h2-leak-sensor_bom_jlc.csv    Comment, Designator, Footprint, LCSC Part #, MPN, Qty  (module excluded)
    h2-leak-sensor_assembly_{top,bottom}.pdf   fab-layer drawings for hand assembly
    h2-leak-sensor_cpl_jlc.csv    Designator, Mid X, Mid Y, Layer, Rotation      (SMD + THT, no test pads)
    h2-leak-sensor_drc.json       DRC report of the released board
"""
from __future__ import annotations

import csv
import glob
import os
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.abspath(os.path.join(HERE, "..", "h2-leak-sensor"))
PCB = os.path.join(PRJ, "h2-leak-sensor.kicad_pcb")
SCH = os.path.join(PRJ, "h2-leak-sensor.kicad_sch")
FAB = os.path.join(PRJ, "fab")
GERB = os.path.join(FAB, "gerber")


def run(args):
    subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    os.makedirs(GERB, exist_ok=True)
    for f in glob.glob(os.path.join(GERB, "*")):
        os.remove(f)
    layers = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
    run(["kicad-cli", "pcb", "export", "gerbers", "--layers", layers, "--subtract-soldermask",
         "--use-drill-file-origin", "-o", GERB + os.sep, PCB])
    run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
         "--drill-origin", "plot", "--excellon-units", "mm", "-o", GERB + os.sep, PCB])
    zpath = os.path.join(FAB, "h2-leak-sensor_gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(glob.glob(os.path.join(GERB, "*"))):
            z.write(f, os.path.basename(f))

    # BOM from the board itself, so the 'Exclude from BOM' flags set by gen_pcb.py (module U1, electrodes,
    # test pads, jumper, mounting holes) are honoured. Grouped by value + footprint + LCSC code.
    import pcbnew
    board = pcbnew.LoadBoard(PCB)
    groups = {}
    for fp in board.GetFootprints():
        if fp.IsExcludedFromBOM() or fp.IsDNP():
            continue
        fld = {f.GetName(): f.GetText() for f in fp.GetFields()}
        key = (fp.GetValue(), str(fp.GetFPID().GetLibItemName()), fld.get("LCSC", ""), fld.get("MPN", ""))
        groups.setdefault(key, []).append(fp.GetReference())

    def refkey(r):
        head = r.rstrip("0123456789")
        return head, int(r[len(head):] or 0)
    rows = sorted(groups.items(), key=lambda kv: refkey(sorted(kv[1], key=refkey)[0]))
    bom_refs = {r for refs in groups.values() for r in refs}
    with open(os.path.join(FAB, "h2-leak-sensor_bom_jlc.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "MPN", "Qty"])
        for (val, fpn, lcsc, mpn), refs in rows:
            refs = sorted(refs, key=refkey)
            w.writerow([val, ",".join(refs), fpn, lcsc, mpn, len(refs)])

    # position file -> JLCPCB CPL
    pos = os.path.join(FAB, "pos_raw.csv")
    run(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
         "--exclude-dnp", "--use-drill-file-origin", "-o", pos, PCB])
    rows = list(csv.DictReader(open(pos, encoding="utf-8")))
    with open(os.path.join(FAB, "h2-leak-sensor_cpl_jlc.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            ref = r["Ref"]
            if ref not in bom_refs:
                continue
            w.writerow([ref, f"{float(r['PosX']):.3f}mm", f"{float(r['PosY']):.3f}mm",
                        "Top" if r["Side"].lower().startswith("top") else "Bottom", f"{float(r['Rot']):.1f}"])
    os.remove(pos)

    # assembly drawings for hand soldering (fab layer shows every reference + outline)
    for side, layers in (("top", "F.Fab,F.SilkS,Edge.Cuts"), ("bottom", "B.Fab,B.SilkS,Edge.Cuts")):
        run(["kicad-cli", "pcb", "export", "pdf", "--layers", layers, "--include-border-title",
             "--black-and-white", "--exclude-value", *(["--mirror"] if side == "bottom" else []),
             "-o", os.path.join(FAB, f"h2-leak-sensor_assembly_{side}.pdf"), PCB])

    run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm",
         "--schematic-parity", "-o", os.path.join(FAB, "h2-leak-sensor_drc.json"), PCB])
    print("fab outputs in", FAB)


if __name__ == "__main__":
    main()

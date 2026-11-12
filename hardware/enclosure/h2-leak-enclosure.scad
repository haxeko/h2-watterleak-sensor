// h2-watterleak-sensor rev A - 3D-printable enclosure (base + lid + button plunger)
// OpenSCAD 2021+.  Export:
//   openscad -o base.stl    -D 'part="base"'    h2-leak-enclosure.scad
//   openscad -o lid.stl     -D 'part="lid"'     h2-leak-enclosure.scad
//   openscad -o plunger.stl -D 'part="plunger"' h2-leak-enclosure.scad
//   openscad -o assembly.png --render -D 'part="assembly"' h2-leak-enclosure.scad
//
// Coordinates of parts are the board-local values from hardware/tools/gen_pcb.py
// (x right, y DOWN, origin = top-left PCB corner); pcb(x, y) converts them to OpenSCAD (y up).
// Print: PETG/ASA, 0.2 mm layers, base bottom-down, lid top-down, no supports needed.

part = "assembly";            // "base" | "lid" | "plunger" | "assembly"
$fn = 48;

// ---------------------------------------------------------------- PCB / parts
PCB_W = 70; PCB_H = 42; PCB_T = 1.6; PCB_R = 2;
ANT_OVERHANG = 6;             // ESP32-H2-WROOM-02C antenna beyond the left PCB edge
ANT_GAP = 2.5;                // plastic-free gap in front of the antenna tip
COMP_H = 24;                  // tallest part above the PCB (CR123A in Bulgin BX0123), with margin
MOUNT = [[2.8, 2.8], [2.8, 39.6], [67.4, 3.0], [40.6, 40.0]];   // M2 holes (H1..H4)
ELECTRODES = [[11.0, 37.0], [60.0, 27.4]];                         // PRB1, PRB2 centres (12 x 8 mm)
SW1 = [30.2, 37.6];  SW_H = 1.5;                                    // TS-1187A body height
LED1 = [36.2, 35.6];
J2 = [63.4, 37.5];                                                  // JST-PH opening at the right edge
THT_RELIEF = [ [[27.5, 21.0], 5.0], [[65.3, 21.0], 5.0],            // battery holder pins
               [[63.4, 36.5], 3.2], [[63.4, 38.5], 3.2],            // J2 pins
               [[7.73, 21.47], 3.0] ];                              // module EPAD solder hole
J1_ROW = [[45.0, 3.0], [62.78, 3.0]];                               // optional header pins

// ---------------------------------------------------------------- enclosure
WALL = 1.8; FLOOR = 1.2; TOP = 1.8; GAP = 0.4;
RELIEF_D = 0.7;               // pocket depth under trimmed THT leads (trim leads <= 0.6 mm)
SPLIT_Z = FLOOR + PCB_T + 6;  // base/lid split height (above J2)
LIP_H = 2.0; LIP_T = 1.0; FIT = 0.25;

CAV_X0 = -(ANT_OVERHANG + ANT_GAP);  CAV_X1 = PCB_W + GAP;
CAV_Y0 = -GAP;                       CAV_Y1 = PCB_H + GAP;
TOTAL_Z = FLOOR + PCB_T + COMP_H + 0.6 + TOP;
PCB_TOP_Z = FLOOR + PCB_T;

function pcb(p) = [p[0], PCB_H - p[1]];

module rrect(x0, y0, x1, y1, r, h) {
    translate([x0 + r, y0 + r, 0]) linear_extrude(h)
        offset(r = r) square([x1 - x0 - 2 * r, y1 - y0 - 2 * r]);
}

module outer_shell(h) { rrect(CAV_X0 - WALL, CAV_Y0 - WALL, CAV_X1 + WALL, CAV_Y1 + WALL, 3, h); }
module cavity(h)      { rrect(CAV_X0, CAV_Y0, CAV_X1, CAV_Y1, 1.5, h); }

// ---------------------------------------------------------------- base
module base() {
    difference() {
        outer_shell(SPLIT_Z);
        translate([0, 0, FLOOR]) cavity(SPLIT_Z);
        // lid lip seat (lid skirt slides inside the base wall top)
        translate([0, 0, SPLIT_Z - LIP_H])
            rrect(CAV_X0 - LIP_T - FIT, CAV_Y0 - LIP_T - FIT, CAV_X1 + LIP_T + FIT, CAV_Y1 + LIP_T + FIT, 2, LIP_H + 1);
        // electrode windows, chamfered 45 deg towards the floor so water reaches the combs
        for (e = ELECTRODES) let (c = pcb(e))
            translate([c[0], c[1], -0.01]) hull() {
                translate([0, 0, FLOOR]) cube([12.6, 8.6, 0.02], center = true);
                cube([12.6 + 2 * FLOOR, 8.6 + 2 * FLOOR, 0.02], center = true);
            }
        // pockets under THT leads / solder blobs
        for (t = THT_RELIEF) let (c = pcb(t[0]))
            translate([c[0], c[1], FLOOR - RELIEF_D]) cylinder(d = t[1], h = RELIEF_D + 0.01);
        hull() for (p = J1_ROW) let (c = pcb(p))
            translate([c[0], c[1], FLOOR - RELIEF_D]) cylinder(d = 3.2, h = RELIEF_D + 0.01);
        // M2 screw holes with countersink from the bottom
        for (m = MOUNT) let (c = pcb(m)) translate([c[0], c[1], -0.01]) {
            cylinder(d = 2.4, h = FLOOR + 0.1);
            cylinder(d1 = 4.4, d2 = 2.4, h = 1.0);
        }
        // JST-PH plug slot in the right wall, open towards the lid
        let (c = pcb(J2)) translate([CAV_X1 - 1, c[1] - 3.8, PCB_TOP_Z - 0.2])
            cube([WALL + 2, 7.6, SPLIT_Z]);
    }
}

// ---------------------------------------------------------------- lid (modelled in place, printed upside down)
module lid() {
    lid_h = TOTAL_Z - SPLIT_Z;
    difference() {
        union() {
            translate([0, 0, SPLIT_Z]) difference() {
                outer_shell(lid_h);
                translate([0, 0, -0.01]) cavity(lid_h - TOP);
            }
            // skirt that drops into the base lip seat
            translate([0, 0, SPLIT_Z - LIP_H]) difference() {
                rrect(CAV_X0 - LIP_T, CAV_Y0 - LIP_T, CAV_X1 + LIP_T, CAV_Y1 + LIP_T, 2, LIP_H);
                translate([0, 0, -0.01]) cavity(LIP_H + 0.02);
            }
            // screw bosses pressing the PCB onto the floor
            for (m = MOUNT) let (c = pcb(m))
                translate([c[0], c[1], PCB_TOP_Z]) cylinder(d = 5.0, h = TOTAL_Z - PCB_TOP_Z - 0.01);
            // guide tube for the button plunger and light tube for the LED
            let (c = pcb(SW1)) translate([c[0], c[1], PCB_TOP_Z + SW_H + 4])
                cylinder(d = 6.4, h = TOTAL_Z - (PCB_TOP_Z + SW_H + 4) - 0.01);
            let (c = pcb(LED1)) translate([c[0], c[1], PCB_TOP_Z + 3.0])
                cylinder(d = 4.0, h = TOTAL_Z - (PCB_TOP_Z + 3.0) - 0.01);
        }
        for (m = MOUNT) let (c = pcb(m)) translate([c[0], c[1], PCB_TOP_Z - 0.01]) cylinder(d = 1.7, h = 12);
        let (c = pcb(SW1)) translate([c[0], c[1], 0]) cylinder(d = 4.2, h = TOTAL_Z + 1);
        let (c = pcb(LED1)) translate([c[0], c[1], 0]) cylinder(d = 2.2, h = TOTAL_Z + 1);
        // JST plug slot continues through the skirt
        let (c = pcb(J2)) translate([CAV_X1 - 1, c[1] - 3.8, SPLIT_Z - LIP_H - 0.5])
            cube([WALL + LIP_T + 2, 7.6, LIP_H + 0.6]);
        // embossed label
        translate([PCB_W / 2 - 4, PCB_H / 2 - 3, TOTAL_Z - 0.6]) linear_extrude(1)
            text("LEAK", size = 7, halign = "center", font = "Liberation Sans:style=Bold");
    }
}

// ---------------------------------------------------------------- plunger (insert from inside before closing)
module plunger() {
    tube_bottom = PCB_TOP_Z + SW_H + 4;
    len = TOTAL_Z + 1.0 - (PCB_TOP_Z + SW_H);
    union() {
        cylinder(d = 3.8, h = len);
        cylinder(d = 5.6, h = 1.2);       // collar below the guide tube, keeps it captive
    }
}

if (part == "base") base();
else if (part == "lid") lid();
else if (part == "plunger") plunger();
else {
    color("SteelBlue") base();
    color("Gainsboro", 0.35) lid();
    color("Orange") let (c = pcb(SW1)) translate([c[0], c[1], PCB_TOP_Z + SW_H]) plunger();
    color("DarkGreen") translate([0, 0, FLOOR]) linear_extrude(PCB_T)
        translate([PCB_R, PCB_R]) offset(r = PCB_R) square([PCB_W - 2 * PCB_R, PCB_H - 2 * PCB_R]);
}

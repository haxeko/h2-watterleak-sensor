#!/usr/bin/env python3
"""Small grid-based A* autorouter for the 2-layer h2-watterleak-sensor board.

    python3 hardware/tools/route.py            # routes h2-leak-sensor.kicad_pcb in place
    python3 hardware/tools/route.py --gnd-only # only re-check / repair GND pour connectivity

Approach (simple and verifiable - KiCad DRC is the final judge):
  * 0.1 mm grid, 2 copper layers, 8-direction moves (45 deg routing), vias = layer changes.
  * Obstacles are kept as exact geometry (pad polygons, track segments, via/hole circles,
    keep-out polygons, board outline). For every net the "forbidden" cells are the grid points
    whose exact distance to foreign copper is < clearance + half width (+ a small epsilon),
    so the routed centre lines meet the 0.2 mm rule by construction.
  * Each net is routed as a tree: repeatedly connect the nearest unconnected pad to the tree.
  * Long nets first (they need the channels), then short nets; failed nets are retried first.
  * GND: the TPS63900 power-loop GND pins are routed first (PRE_GND). Every other GND SMD pad gets
    a short fan-out to a via, stitching vias are sprinkled on free areas, both pours are filled,
    then a union-find over pour islands + GND items finds parts that are cut off; each one is tied
    in by a via, a short GND track, or - when it is fenced in on both layers - by ripping up one
    nearby signal net, routing GND through the gap and re-routing that net.
"""
from __future__ import annotations

import heapq
import math
import os
import time

import numpy as np
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.abspath(os.path.join(HERE, "..", "h2-leak-sensor", "h2-leak-sensor.kicad_pcb"))

RES = 0.1                 # mm per grid cell
CLR = 0.20                # copper clearance rule
EPS = 0.03                # safety margin on top of the exact distances
EDGE = 0.30               # copper to board edge
HOLE_CLR = 0.25           # copper to hole
HOLE_HOLE = 0.25          # hole to hole
VIA_D, VIA_DRILL = 0.6, 0.3
W_DEFAULT = 0.25
WIDTHS = {"/Power/BAT_CELL": 0.4, "/Power/BAT_RAW": 0.4}
VIA_COST = 15.0           # in cells
TURN45, TURN90 = 0.3, 1.0
# GND pins that get real tracks before any signal is routed (not just the pour): the TPS63900 power
# loop - both IC GND pins, its exposed pad and the GND ends of CIN (C1) and COUT (C2).
PRE_GND = [("U2.2", "U2.8", "U2.11", "C1.2", "C2.2")]
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]


def mm(v):
    return pcbnew.FromMM(float(v))


def tomm(v):
    return pcbnew.ToMM(v)


def seg_dist(X, Y, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return np.hypot(X - x1, Y - y1)
    t = np.clip(((X - x1) * dx + (Y - y1) * dy) / L2, 0.0, 1.0)
    return np.hypot(X - (x1 + t * dx), Y - (y1 + t * dy))


def polyline_dist(X, Y, pts):
    """Distance to the boundary of a closed polygon (no inside test)."""
    d = np.full(X.shape, np.inf)
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        d = np.minimum(d, seg_dist(X, Y, x1, y1, x2, y2))
    return d


def poly_dist(X, Y, pts):
    """Distance to a closed polygon; 0 inside."""
    d = np.full(X.shape, np.inf)
    inside = np.zeros(X.shape, bool)
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        d = np.minimum(d, seg_dist(X, Y, x1, y1, x2, y2))
        if y1 != y2:
            cond = (Y >= min(y1, y2)) & (Y < max(y1, y2))
            inside ^= cond & (X < x1 + (Y - y1) * (x2 - x1) / (y2 - y1))
    d[inside] = 0.0
    return d


class Shape:
    __slots__ = ("kind", "net", "data", "bbox")

    def __init__(self, kind, net, data, bbox):
        self.kind, self.net, self.data, self.bbox = kind, net, data, bbox

    def dist(self, X, Y):
        if self.kind == "poly":
            return poly_dist(X, Y, self.data)
        if self.kind == "seg":
            x1, y1, x2, y2, hw = self.data
            return seg_dist(X, Y, x1, y1, x2, y2) - hw
        cx, cy, r = self.data
        return np.hypot(X - cx, Y - cy) - r


def poly_shape(net, pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return Shape("poly", net, pts, (min(xs), min(ys), max(xs), max(ys)))


def seg_shape(net, x1, y1, x2, y2, w):
    hw = w / 2
    return Shape("seg", net, (x1, y1, x2, y2, hw), (min(x1, x2) - hw, min(y1, y2) - hw, max(x1, x2) + hw, max(y1, y2) + hw))


def circle_shape(net, x, y, r):
    return Shape("circle", net, (x, y, r), (x - r, y - r, x + r, y + r))


class Router:
    def __init__(self, board):
        self.b = board
        bb = board.GetBoardEdgesBoundingBox()
        # grid on exact multiples of RES, so that pins placed on the 0.1 mm grid sit on cell centres
        # (a 0.05 mm offset closes the 0.25 mm gaps between 0.5 mm-pitch pins for a 0.25 mm track)
        self.x0 = math.floor(tomm(bb.GetLeft()) / RES + 1e-9) * RES
        self.y0 = math.floor(tomm(bb.GetTop()) / RES + 1e-9) * RES
        self.nx = int(math.ceil((tomm(bb.GetRight()) - self.x0) / RES - 1e-9)) + 1
        self.ny = int(math.ceil((tomm(bb.GetBottom()) - self.y0) / RES - 1e-9)) + 1
        self.N = self.nx * self.ny
        gx = self.x0 + np.arange(self.nx) * RES
        gy = self.y0 + np.arange(self.ny) * RES
        self.GX, self.GY = np.meshgrid(gx, gy)
        self.copper = [[], []]          # per layer: list[Shape]
        self.track_ko = ([], [])        # per layer: polygons
        self.via_ko = []                # polygons
        self.holes = []                 # (x, y, r, net of a PTH pad or None)
        self.vias = []                  # (x, y) of every via placed so far (any net)
        self.via_nets = []              # (x, y, net)
        self.gnd_failed = []
        self.pad_cells = {}             # net -> list of (name, layer, ys, xs, is_th)
        self.nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByNetcode().values()}
        self.netcode = {k: n.GetNetCode() for k, n in self.nets.items()}
        self.purge = set()              # uuids of board tracks/vias to delete on the next apply()
        self.new_items = []
        self._edge_cache = {}
        self._outline()
        self._pads()
        self._rule_areas()

    # ------------------------------------------------------------------ helpers
    def cell(self, x, y):
        return int(round((x - self.x0) / RES)), int(round((y - self.y0) / RES))

    def xy(self, cx, cy):
        return round(float(self.x0 + cx * RES), 4), round(float(self.y0 + cy * RES), 4)

    def patch(self, bbox, grow):
        x1, y1, x2, y2 = bbox
        cx0, cy0 = self.cell(x1 - grow, y1 - grow)
        cx1, cy1 = self.cell(x2 + grow, y2 + grow)
        cx0, cy0 = max(cx0 - 1, 0), max(cy0 - 1, 0)
        cx1, cy1 = min(cx1 + 1, self.nx - 1), min(cy1 + 1, self.ny - 1)
        if cx1 < cx0 or cy1 < cy0:
            return None
        return slice(cy0, cy1 + 1), slice(cx0, cx1 + 1)

    def mark(self, mask, shape, limit):
        sl = self.patch(shape.bbox, limit)
        if sl is None:
            return
        d = shape.dist(self.GX[sl], self.GY[sl])
        mask[sl] |= d < limit

    # ------------------------------------------------------------------ board data
    def _outline(self):
        ps = pcbnew.SHAPE_POLY_SET()
        self.b.GetBoardPolygonOutlines(ps)
        ol = ps.Outline(0)
        self.outline = [(tomm(ol.CPoint(i).x), tomm(ol.CPoint(i).y)) for i in range(ol.PointCount())]
        d = polyline_dist(self.GX, self.GY, self.outline)
        inside = np.zeros(self.GX.shape, bool)
        n = len(self.outline)
        for i in range(n):
            x1, y1 = self.outline[i]
            x2, y2 = self.outline[(i + 1) % n]
            if y1 != y2:
                cond = (self.GY >= min(y1, y2)) & (self.GY < max(y1, y2))
                inside ^= cond & (self.GX < x1 + (self.GY - y1) * (x2 - x1) / (y2 - y1))
        # signed distance to the outline: negative outside
        edge_d = np.full(self.GX.shape, 0.0)
        edge_d = np.where(inside, 0.0, 0.0)
        self.edge_dist = d               # distance to the outline polyline
        self.inside = inside

    def edge_block(self, r):
        key = round(r, 3)
        if key not in self._edge_cache:
            self._edge_cache[key] = (~self.inside) | (self.edge_dist < r)
        return self._edge_cache[key]

    def _pads(self):
        for fp in self.b.GetFootprints():
            for pad in fp.Pads():
                net = pad.GetNetname() if pad.GetNetCode() > 0 else f"__nc_{fp.GetReference()}_{pad.GetNumber()}"
                if pad.HasHole():
                    c = pad.GetPosition()
                    r = max(tomm(pad.GetDrillSize().x), tomm(pad.GetDrillSize().y)) / 2
                    pth = pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and pad.GetNetCode() > 0
                    self.holes.append((tomm(c.x), tomm(c.y), r, pad.GetNetname() if pth else None))
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    continue
                for li, layer in enumerate(LAYERS):
                    if not pad.IsOnLayer(layer):
                        continue
                    ps = pad.GetEffectivePolygon(layer, pcbnew.ERROR_INSIDE)
                    for k in range(ps.OutlineCount()):
                        ol = ps.Outline(k)
                        pts = [(tomm(ol.CPoint(i).x), tomm(ol.CPoint(i).y)) for i in range(ol.PointCount())]
                        shp = poly_shape(net, pts)
                        self.copper[li].append(shp)
                        if pad.GetNetCode() > 0:
                            sl = self.patch(shp.bbox, 0)
                            inside = shp.dist(self.GX[sl], self.GY[sl]) <= 0.0
                            ys, xs = np.nonzero(inside)
                            if ys.size == 0:     # tiny pad: use the nearest cell
                                cx, cy = self.cell(tomm(pad.GetPosition().x), tomm(pad.GetPosition().y))
                                ys, xs = np.array([cy - sl[0].start]), np.array([cx - sl[1].start])
                            pos = pad.GetPosition()
                            key = f"{fp.GetReference()}.{pad.GetNumber()}@{tomm(pos.x):.2f},{tomm(pos.y):.2f}"
                            self.pad_cells.setdefault(net, []).append(
                                (key, li, ys + sl[0].start, xs + sl[1].start,
                                 pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH))

    def _rule_areas(self):
        zones = list(self.b.Zones())
        for fp in self.b.GetFootprints():
            zones += list(fp.Zones())
        for z in zones:
            if not z.GetIsRuleArea():
                continue
            ol = z.Outline().Outline(0)
            pts = [(tomm(ol.CPoint(i).x), tomm(ol.CPoint(i).y)) for i in range(ol.PointCount())]
            for li, layer in enumerate(LAYERS):
                if z.IsOnLayer(layer) and z.GetDoNotAllowTracks():
                    self.track_ko[li].append(poly_shape("__ko", pts))
            if z.GetDoNotAllowVias():
                self.via_ko.append(poly_shape("__ko", pts))

    # ------------------------------------------------------------------ per-net forbidden cells
    def blocked_maps(self, net, w):
        shp = self.GX.shape
        blk = np.zeros((2,) + shp, bool)
        vblk = self.edge_block(EDGE + VIA_D / 2).copy()
        lt = CLR + w / 2 + EPS
        lv = CLR + VIA_D / 2 + EPS
        for li in range(2):
            blk[li] |= self.edge_block(EDGE + w / 2 + EPS)
            for s in self.copper[li]:
                if s.net == net:
                    continue
                self.mark(blk[li], s, lt)
                self.mark(vblk, s, lv)
            for s in self.track_ko[li]:
                self.mark(blk[li], s, w / 2 + EPS)
        for s in self.via_ko:
            self.mark(vblk, s, VIA_D / 2 + EPS)
        for (x, y) in self.vias:
            self.mark(vblk, circle_shape("__via", x, y, VIA_DRILL / 2), HOLE_HOLE + VIA_DRILL / 2 + EPS)
        for (x, y, r, hnet) in self.holes:
            c = circle_shape("__hole", x, y, r)
            if hnet != net:                   # copper-to-hole applies to other nets / NPTH only
                self.mark(blk[0], c, HOLE_CLR + w / 2 + EPS)
                self.mark(blk[1], c, HOLE_CLR + w / 2 + EPS)
            self.mark(vblk, c, max(HOLE_CLR + VIA_D / 2, HOLE_HOLE + VIA_DRILL / 2) + EPS)
        for name, li, ys, xs, is_th in self.pad_cells.get(net, []):
            if not is_th:
                vblk[ys, xs] = True          # no via-in-pad
        return blk, vblk

    # ------------------------------------------------------------------ A*
    def astar(self, sources, tcells, goal, blk, vblk, max_expand=3000000):
        nx, ny, N = self.nx, self.ny, self.N
        tx, ty = goal
        INF = 1e18
        g = {}
        came = {}
        heap = []
        R2 = 0.41421356
        for s in sources:
            li, rem = divmod(s, N)
            y, x = divmod(rem, nx)
            g[(s, -1)] = 0.0
            ddx, ddy = abs(x - tx), abs(y - ty)
            heapq.heappush(heap, (max(ddx, ddy) + R2 * min(ddx, ddy), 0.0, s, -1))
        b0 = blk[0].reshape(-1)
        b1 = blk[1].reshape(-1)
        bl = (b0, b1)
        vb = vblk.reshape(-1)
        expanded = 0
        while heap:
            f, gc, s, d = heapq.heappop(heap)
            if gc > g.get((s, d), INF) + 1e-9:
                continue
            if s in tcells:
                path = [s]
                key = (s, d)
                while key in came:
                    key = came[key]
                    path.append(key[0])
                return path[::-1]
            expanded += 1
            if expanded > max_expand:
                return None
            li, rem = divmod(s, N)
            y, x = divmod(rem, nx)
            b = bl[li]
            base = li * N
            for di in range(8):
                dx, dy = DIRS[di]
                xx, yy = x + dx, y + dy
                if xx < 0 or yy < 0 or xx >= nx or yy >= ny:
                    continue
                r2 = yy * nx + xx
                ns = base + r2
                is_t = ns in tcells
                if b[r2] and not is_t:
                    continue
                if dx and dy and (b[y * nx + xx] or b[yy * nx + x]) and not is_t:
                    continue
                step = 1.41421356 if (dx and dy) else 1.0
                if d >= 0:
                    turn = (di - d) % 8
                    turn = min(turn, 8 - turn)
                    if turn > 2:
                        continue
                    if turn:
                        step += TURN45 if turn == 1 else TURN90
                ng = gc + step
                key = (ns, di)
                if ng < g.get(key, INF):
                    g[key] = ng
                    came[key] = (s, d)
                    ddx, ddy = abs(xx - tx), abs(yy - ty)
                    heapq.heappush(heap, (ng + max(ddx, ddy) + R2 * min(ddx, ddy), ng, ns, di))
            if not vb[rem]:
                ol = 1 - li
                ns = ol * N + rem
                if (not bl[ol][rem]) or ns in tcells:
                    ng = gc + VIA_COST
                    key = (ns, -1)
                    if ng < g.get(key, INF):
                        g[key] = ng
                        came[key] = (s, d)
                        ddx, ddy = abs(x - tx), abs(y - ty)
                        heapq.heappush(heap, (ng + max(ddx, ddy) + R2 * min(ddx, ddy), ng, ns, -1))
        return None

    # ------------------------------------------------------------------ net routing
    def pad_states(self, pad, blk=None):
        """Grid states of a pad. With `blk`, only the cells where a track may start / end without
        breaking clearance to neighbouring copper (e.g. not the inner end of a fine-pitch pin next to
        an exposed pad); all cells if the pad has no such cell."""
        name, li, ys, xs, is_th = pad
        out = set()
        for L in ((0, 1) if is_th else (li,)):
            st = L * self.N + ys * self.nx + xs
            if blk is not None:
                ok = ~blk[L][ys, xs]
                if ok.any():
                    st = st[ok]
            out.update(st.tolist())
        return out

    def route_net(self, net, only=None, width=None):
        """Route `net` as a tree; `only` = set of "REF.PIN" restricting the pins (used for GND groups)."""
        groups = {}
        for p in self.pad_cells.get(net, []):
            if only and p[0].split("@")[0] not in only:
                continue
            groups.setdefault(p[0], []).append(p)
        groups = list(groups.values())
        if len(groups) < 2:
            return True
        # start the tree at the medoid pin so that clusters connect first and long links last
        cent = [(float(np.mean(g[0][3])), float(np.mean(g[0][2]))) for g in groups]
        med = min(range(len(groups)), key=lambda i: sum(abs(cent[i][0] - c[0]) + abs(cent[i][1] - c[1]) for c in cent))
        groups.insert(0, groups.pop(med))
        w = width or WIDTHS.get(net, W_DEFAULT)
        blk, vblk = self.blocked_maps(net, w)
        tree = set()
        for p in groups[0]:
            tree |= self.pad_states(p, blk)
        remaining = groups[1:]
        paths = []
        while remaining:
            sample = np.array([((s % self.N) % self.nx, (s % self.N) // self.nx) for s in list(tree)[:3000]])
            best, bestd = 0, 1e18
            for gi, grp in enumerate(remaining):
                cx, cy = float(np.mean(grp[0][3])), float(np.mean(grp[0][2]))
                dd = float(np.min(np.abs(sample[:, 0] - cx) + np.abs(sample[:, 1] - cy)))
                if dd < bestd:
                    best, bestd = gi, dd
            grp = remaining.pop(best)
            tcells = set()
            for p in grp:
                tcells |= self.pad_states(p, blk)
            goal = (int(np.mean(grp[0][3])), int(np.mean(grp[0][2])))
            path = self.astar(tree, tcells, goal, blk, vblk)
            if path is None:
                return False
            paths.append(path)
            tree |= set(path) | tcells
        for path in paths:
            self.commit(net, path, w)
        return True

    def commit(self, net, path, w):
        nx, N = self.nx, self.N
        pts = [(s // N, (s % N) // nx, (s % N) % nx) for s in path]      # (layer, y, x)
        run = [pts[0]]
        for p in pts[1:]:
            if p[0] != run[-1][0]:
                self._emit_run(net, run, w)
                x, y = self.xy(p[2], p[1])
                self.new_items.append(("via", net, x, y))
                self.vias.append((x, y))
                self.via_nets.append((x, y, net))
                for li in range(2):
                    self.copper[li].append(circle_shape(net, x, y, VIA_D / 2))
                run = [p]
            else:
                run.append(p)
        self._emit_run(net, run, w)

    def _emit_run(self, net, run, w):
        if len(run) < 2:
            return
        L = run[0][0]
        corners = [run[0]]
        for i in range(1, len(run) - 1):
            a, b, c = run[i - 1], run[i], run[i + 1]
            if (b[1] - a[1], b[2] - a[2]) != (c[1] - b[1], c[2] - b[2]):
                corners.append(b)
        corners.append(run[-1])
        for a, b in zip(corners, corners[1:]):
            x1, y1 = self.xy(a[2], a[1])
            x2, y2 = self.xy(b[2], b[1])
            self.new_items.append(("track", net, LAYERS[L], x1, y1, x2, y2, w))
            self.copper[L].append(seg_shape(net, x1, y1, x2, y2, w))

    # ------------------------------------------------------------------ GND
    def gnd_fanout(self, max_r=2.5, only=None):
        net = "GND"
        added = 0
        for name, li, ys, xs, is_th in list(self.pad_cells.get(net, [])):
            if is_th or li != 0 or (only is not None and name not in only):
                continue
            blk, vblk = self.blocked_maps(net, W_DEFAULT)
            cy, cx = int(np.mean(ys)), int(np.mean(xs))
            r = int(max_r / RES)
            y0, y1 = max(cy - r, 0), min(cy + r, self.ny - 1)
            x0, x1 = max(cx - r, 0), min(cx + r, self.nx - 1)
            ok = ~vblk[y0:y1 + 1, x0:x1 + 1] & ~blk[0][y0:y1 + 1, x0:x1 + 1] & ~blk[1][y0:y1 + 1, x0:x1 + 1]
            cand = np.argwhere(ok)
            if cand.size == 0:
                continue
            cand = cand + [y0, x0]
            order = np.argsort(np.hypot(cand[:, 0] - cy, cand[:, 1] - cx))[:80]
            tcells = set((self.N + cand[order, 0] * self.nx + cand[order, 1]).tolist())
            src = self.pad_states((name, li, ys, xs, is_th), blk)
            path = self.astar(src, tcells, (cx, cy), blk, vblk, max_expand=30000)
            if path is None:
                path = self.gnd_to_anchor(src, (cx, cy), blk, vblk)
                if path is None:
                    self.gnd_failed.append(name)
                    continue
            self.commit(net, path, W_DEFAULT)
            added += 1
        return added

    def gnd_anchor_states(self, blk=None):
        """Copper that is certainly tied to both GND pours: GND THT pads (incl. the U2/U1 EPAD vias)
        and GND vias placed so far."""
        st = set()
        for name, li, ys, xs, is_th in self.pad_cells.get("GND", []):
            if is_th:
                st |= self.pad_states((name, li, ys, xs, is_th), blk)
        r = int(round((VIA_D / 2 - 0.05) / RES))
        for (x, y, net) in self.via_nets:
            if net != "GND":
                continue
            cx, cy = self.cell(x, y)
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dx * dx + dy * dy <= r * r and 0 <= cx + dx < self.nx and 0 <= cy + dy < self.ny:
                        for L in (0, 1):
                            if blk is None or not blk[L][cy + dy, cx + dx]:
                                st.add(L * self.N + (cy + dy) * self.nx + cx + dx)
        return st

    def gnd_to_anchor(self, src, goal, blk, vblk):
        anchors = self.gnd_anchor_states(blk)
        if not anchors:
            return None
        # aim the heuristic at the nearest anchor
        gx, gy = goal
        best = min(anchors, key=lambda s: abs((s % self.N) % self.nx - gx) + abs((s % self.N) // self.nx - gy))
        tgoal = ((best % self.N) % self.nx, (best % self.N) // self.nx)
        return self.astar(src, anchors, tgoal, blk, vblk, max_expand=400000)

    def stitch(self, pitch=3.0):
        net = "GND"
        blk, vblk = self.blocked_maps(net, W_DEFAULT)
        free = ~vblk & ~blk[0] & ~blk[1]
        step = int(pitch / RES)
        added = 0
        for y in range(step // 2, self.ny, step):
            for x in range(step // 2, self.nx, step):
                if not free[y, x]:
                    continue
                vx, vy = self.xy(x, y)
                self.new_items.append(("via", net, vx, vy))
                self.vias.append((vx, vy))
                self.via_nets.append((vx, vy, net))
                c = circle_shape(net, vx, vy, VIA_D / 2)
                for li in range(2):
                    self.copper[li].append(c)
                blockm = np.zeros(free.shape, bool)
                self.mark(blockm, c, VIA_D / 2 + HOLE_HOLE + VIA_DRILL)
                free &= ~blockm
                added += 1
        return added

    def stitch_islands(self):
        """Add a via inside every filled GND copper island that has no via / THT GND pad."""
        added = 0
        blk, vblk = self.blocked_maps("GND", W_DEFAULT)
        free = ~vblk & ~blk[0] & ~blk[1]
        anchors = [(x, y) for (x, y) in self.vias]
        for fp in self.b.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == "GND" and pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                    anchors.append((tomm(pad.GetPosition().x), tomm(pad.GetPosition().y)))
        for z in self.b.Zones():
            if z.GetIsRuleArea() or z.GetNetname() != "GND":
                continue
            layer = z.GetLayer()
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                ol = polys.Outline(i)
                if any(ol.PointInside(pcbnew.VECTOR2I(mm(x), mm(y))) for x, y in anchors):
                    continue
                pts = [(tomm(ol.CPoint(k).x), tomm(ol.CPoint(k).y)) for k in range(ol.PointCount())]
                shp = poly_shape("__island", pts)
                sl = self.patch(shp.bbox, 0)
                if sl is None:
                    continue
                inside = shp.dist(self.GX[sl], self.GY[sl]) <= 0.0
                # stay well inside the island so the via copper is fully surrounded by the pour
                deep = np.zeros_like(inside)
                dd = poly_dist(self.GX[sl], self.GY[sl], pts)
                edge = polyline_dist(self.GX[sl], self.GY[sl], pts)
                deep = inside & (edge > VIA_D / 2 + 0.1)
                cand = np.argwhere(deep & free[sl])
                if cand.size == 0:
                    continue
                cy, cx = cand[len(cand) // 2] + [sl[0].start, sl[1].start]
                vx, vy = self.xy(cx, cy)
                self.new_items.append(("via", "GND", vx, vy))
                self.vias.append((vx, vy))
                self.via_nets.append((vx, vy, "GND"))
                anchors.append((vx, vy))
                c = circle_shape("GND", vx, vy, VIA_D / 2)
                self.copper[0].append(c)
                self.copper[1].append(c)
                m = np.zeros(free.shape, bool)
                self.mark(m, c, VIA_D / 2 + HOLE_HOLE + VIA_DRILL)
                free &= ~m
                added += 1
        return added

    # ------------------------------------------------------------------ GND pour connectivity
    def load_existing(self):
        """Post-processing mode: add the tracks / vias already on the board to the obstacle model."""
        for t in self.b.GetTracks():
            net = t.GetNetname()
            if t.GetClass() == "PCB_VIA":
                x, y = tomm(t.GetPosition().x), tomm(t.GetPosition().y)
                self.vias.append((x, y))
                self.via_nets.append((x, y, net))
                c = circle_shape(net, x, y, VIA_D / 2)
                self.copper[0].append(c)
                self.copper[1].append(c)
            else:
                li = 0 if t.GetLayer() == pcbnew.F_Cu else 1
                a, b = t.GetStart(), t.GetEnd()
                self.copper[li].append(seg_shape(net, tomm(a.x), tomm(a.y), tomm(b.x), tomm(b.y), tomm(t.GetWidth())))

    def gnd_islands(self):
        out = []
        for z in self.b.Zones():
            if z.GetIsRuleArea() or z.GetNetname() != "GND":
                continue
            for li, layer in enumerate(LAYERS):
                if not z.IsOnLayer(layer):
                    continue
                polys = z.GetFilledPolysList(layer)
                for i in range(polys.OutlineCount()):
                    ol = polys.Outline(i)
                    bb = ol.BBox()
                    out.append(dict(li=li, polys=polys, idx=i, area=abs(ol.Area()) * 1e-12,
                                    bbox=(tomm(bb.GetLeft()), tomm(bb.GetTop()),
                                          tomm(bb.GetRight()), tomm(bb.GetBottom()))))
        return out

    @staticmethod
    def _in_island(isl, x, y):
        b = isl["bbox"]
        if not (b[0] <= x <= b[2] and b[1] <= y <= b[3]):
            return False
        return isl["polys"].Contains(pcbnew.VECTOR2I(mm(x), mm(y)), isl["idx"])

    def gnd_components(self):
        """Union-find over the filled GND islands of both layers and every GND item (pads, vias,
        tracks), the way copper actually touches. Returns (islands, components, main component)."""
        isl = self.gnd_islands()
        parent = {}

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        def touch(node, li, pts):
            for k, I in enumerate(isl):
                if I["li"] == li and any(self._in_island(I, x, y) for x, y in pts):
                    union(node, ("island", k))

        anchors = {}                 # node -> [(li, x, y)] used as route sources for island-less parts
        for k in range(len(isl)):
            find(("island", k))
        pads = []
        for fp in self.b.GetFootprints():
            for pi, pad in enumerate(fp.Pads()):
                if pad.GetNetname() != "GND":
                    continue
                node = ("pad", f"{fp.GetReference()}.{pad.GetNumber()}#{pi}")
                find(node)
                c = pad.GetPosition()
                cx, cy = tomm(c.x), tomm(c.y)
                bb = pad.GetBoundingBox()
                half = min(tomm(bb.GetWidth()), tomm(bb.GetHeight())) / 2
                if pad.HasHole():
                    rr = [(max(tomm(pad.GetDrillSize().x), tomm(pad.GetDrillSize().y)) / 2 + half) / 2]
                else:
                    rr = [0.0, half * 0.5]
                pts = [(cx, cy)]
                for r_ in rr:
                    for a in range(8):
                        pts.append((cx + r_ * math.cos(a * math.pi / 4), cy + r_ * math.sin(a * math.pi / 4)))
                pts = [p for p in pts if pad.HitTest(pcbnew.VECTOR2I(mm(p[0]), mm(p[1])))] or [(cx, cy)]
                lis = [li for li, L in enumerate(LAYERS) if pad.IsOnLayer(L)]
                for li in lis:
                    touch(node, li, pts)
                anchors[node] = [(li, cx, cy) for li in lis]
                pads.append((node, pad, lis))
        ends = {}
        for ti, t in enumerate(self.b.GetTracks()):
            if t.GetNetname() != "GND":
                continue
            if t.GetClass() == "PCB_VIA":
                node = ("via", ti)
                x, y = tomm(t.GetPosition().x), tomm(t.GetPosition().y)
                find(node)
                for li in (0, 1):
                    touch(node, li, [(x, y)])
                    ends.setdefault((li, round(x, 3), round(y, 3)), []).append(node)
                anchors[node] = [(0, x, y), (1, x, y)]
                continue
            node = ("track", ti)
            find(node)
            li = 0 if t.GetLayer() == pcbnew.F_Cu else 1
            x1, y1, x2, y2 = tomm(t.GetStart().x), tomm(t.GetStart().y), tomm(t.GetEnd().x), tomm(t.GetEnd().y)
            n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.2) + 1)
            touch(node, li, [(x1 + (x2 - x1) * i / (n - 1), y1 + (y2 - y1) * i / (n - 1)) for i in range(n)])
            anchors[node] = [(li, x1, y1), (li, x2, y2)]
            for x, y in ((x1, y1), (x2, y2)):
                ends.setdefault((li, round(x, 3), round(y, 3)), []).append(node)
                P = pcbnew.VECTOR2I(mm(x), mm(y))
                for pnode, pad, lis in pads:
                    if li in lis and pad.HitTest(P):
                        union(node, pnode)
        for nodes in ends.values():
            for o in nodes[1:]:
                union(nodes[0], o)
        comps = {}
        for node in list(parent):
            comps.setdefault(find(node), []).append(node)
        comps = list(comps.values())
        big = max(range(len(isl)), key=lambda k: isl[k]["area"]) if isl else None
        main = next((c for c in comps if ("island", big) in c), max(comps, key=len)) if comps else []
        return isl, comps, main, anchors

    def raster_island(self, I):
        """Grid cells whose centre lies in a filled island (outline minus holes, even-odd rule)."""
        polys, i = I["polys"], I["idx"]
        chains = [polys.Outline(i)] + [polys.Hole(i, h) for h in range(polys.HoleCount(i))]
        X1, Y1, X2, Y2 = [], [], [], []
        for ch in chains:
            pts = np.array([(tomm(ch.CPoint(k).x), tomm(ch.CPoint(k).y)) for k in range(ch.PointCount())])
            X1.append(pts[:, 0]); Y1.append(pts[:, 1])
            X2.append(np.roll(pts[:, 0], -1)); Y2.append(np.roll(pts[:, 1], -1))
        X1, Y1, X2, Y2 = (np.concatenate(v) for v in (X1, Y1, X2, Y2))
        sl = self.patch(I["bbox"], 0)
        ys, xs = self.GY[sl][:, 0], self.GX[sl][0]
        m = np.zeros((len(ys), len(xs)), bool)
        for r_, y in enumerate(ys):
            c = (Y1 <= y) != (Y2 <= y)
            if not c.any():
                continue
            xi = np.sort(X1[c] + (y - Y1[c]) * (X2[c] - X1[c]) / (Y2[c] - Y1[c]))
            for a, b in zip(xi[0::2], xi[1::2]):
                m[r_, np.searchsorted(xs, a):np.searchsorted(xs, b)] = True
        return sl, m

    def link_component(self, isl, comp, main, anchors, lab):
        """Tie one isolated GND component to the main one: a via where the two overlap on
        opposite layers, otherwise a short GND track (A*, may use vias)."""
        ck = [n[1] for n in comp if n[0] == "island"]
        mk = [n[1] for n in main if n[0] == "island"]
        inC = np.isin(lab, ck) if ck else np.zeros(lab.shape, bool)
        inM = np.isin(lab, mk)
        for li, x, y in (a for n in comp if n[0] != "island" for a in anchors.get(n, [])):
            cx, cy = self.cell(x, y)
            inC[li, cy, cx] = True

        def erode(m, k):
            m = m.copy()
            for _ in range(k):
                e = m.copy()
                e[:, 1:, :] &= m[:, :-1, :]; e[:, :-1, :] &= m[:, 1:, :]
                e[:, :, 1:] &= m[:, :, :-1]; e[:, :, :-1] &= m[:, :, 1:]
                m = e
            return m
        blk, vblk = self.blocked_maps("GND", W_DEFAULT)
        eC, eM = erode(inC, 3), erode(inM, 3)
        cand = ~vblk & ~blk[0] & ~blk[1] & ((eC[0] & eM[1]) | (eC[1] & eM[0]))
        if cand.any():
            pts = np.argwhere(cand)
            cy, cx = pts[len(pts) // 2]
            vx, vy = self.xy(cx, cy)
            self.new_items.append(("via", "GND", vx, vy))
            self.vias.append((vx, vy))
            self.via_nets.append((vx, vy, "GND"))
            c = circle_shape("GND", vx, vy, VIA_D / 2)
            self.copper[0].append(c)
            self.copper[1].append(c)
            return f"via @({vx:.2f}, {vy:.2f})"
        return self._link_track(inC, erode(inM, 1), blk, vblk)

    def _link_track(self, inC, inM, blk, vblk, commit=True):
        src_m = inC & ~blk
        dst_m = inM & ~blk
        if not src_m.any() or not dst_m.any():
            return None
        s_idx = np.argwhere(src_m)                    # (layer, y, x)
        if len(s_idx) > 6000:
            s_idx = s_idx[np.linspace(0, len(s_idx) - 1, 6000).astype(int)]
        src = set((s_idx[:, 0] * self.N + s_idx[:, 1] * self.nx + s_idx[:, 2]).tolist())
        d_idx = np.argwhere(dst_m)
        ccy, ccx = s_idx[:, 1].mean(), s_idx[:, 2].mean()
        j = int(np.argmin(np.hypot(d_idx[:, 1] - ccy, d_idx[:, 2] - ccx)))
        goal = (int(d_idx[j, 2]), int(d_idx[j, 1]))
        tcells = set((d_idx[:, 0] * self.N + d_idx[:, 1] * self.nx + d_idx[:, 2]).tolist())
        path = self.astar(src, tcells, goal, blk, vblk, max_expand=1500000)
        if path is None:
            return None
        if commit:
            self.commit("GND", path, W_DEFAULT)
        return path

    def ripup_link(self, isl, comp, main, anchors, lab):
        """Rip-up and reroute: the isolated GND part is fenced in by signal tracks on both layers.
        Try removing one nearby signal net, link GND through the freed space, then re-route that net
        around the new GND track. The first net for which both succeed is kept."""
        ck = [n[1] for n in comp if n[0] == "island"]
        mk = [n[1] for n in main if n[0] == "island"]
        inC = np.isin(lab, ck) if ck else np.zeros(lab.shape, bool)
        for li, x, y in (a for n in comp if n[0] != "island" for a in anchors.get(n, [])):
            cx, cy = self.cell(x, y)
            inC[li, cy, cx] = True
        inM = np.isin(lab, mk)
        inM[:, 1:, :] &= inM[:, :-1, :].copy()
        ys, xs = np.nonzero(inC.any(axis=0))
        bx0, by0 = self.xy(xs.min(), ys.min())
        bx1, by1 = self.xy(xs.max(), ys.max())
        grow = 1.5
        length = {}
        for li in range(2):
            for sh in self.copper[li]:
                if sh.kind == "poly" or sh.net in ("GND", "") or sh.net.startswith("__"):
                    continue
                if sh.kind == "seg":
                    x1, y1, x2, y2, _ = sh.data
                    length[sh.net] = length.get(sh.net, 0.0) + math.hypot(x2 - x1, y2 - y1)
        near = set()
        for li in range(2):
            for sh in self.copper[li]:
                if sh.kind == "poly" or sh.net not in length:
                    continue
                a, b, c, d = sh.bbox
                if a < bx1 + grow and c > bx0 - grow and b < by1 + grow and d > by0 - grow:
                    near.add(sh.net)
        for net in sorted(near, key=lambda n: length[n]):
            snap = ([list(self.copper[0]), list(self.copper[1])], list(self.via_nets), list(self.new_items))
            for li in range(2):
                self.copper[li] = [sh for sh in self.copper[li] if not (sh.net == net and sh.kind != "poly")]
            self.via_nets = [v for v in self.via_nets if v[2] != net]
            self.vias = [(x, y) for (x, y, _) in self.via_nets]
            blk, vblk = self.blocked_maps("GND", W_DEFAULT)
            path = self._link_track(inC, inM, blk, vblk)
            ok = path is not None and self.route_net(net)
            if ok:
                self.purge |= {t.m_Uuid.AsString() for t in self.b.GetTracks() if t.GetNetname() == net}
                return f"rip-up of {net}: GND track {len(path)} cells, {net} re-routed"
            self.copper = [snap[0][0], snap[0][1]]
            self.via_nets, self.new_items = snap[1], snap[2]
            self.vias = [(x, y) for (x, y, _) in self.via_nets]
            print(f"    rip-up of {net}: {'no GND path' if path is None else 're-route failed'}", flush=True)
        return None

    def fix_gnd_connectivity(self, rounds=5):
        """Refill + re-check until both GND pours and all GND items form a single copper component."""
        links = []
        for _ in range(rounds):
            isl, comps, main, anchors = self.gnd_components()
            others = [c for c in comps if c is not main]
            if not others:
                return links, 0
            lab = np.full((2,) + self.GX.shape, -1, np.int32)
            for k, I in enumerate(isl):
                sl, m = self.raster_island(I)
                lab[I["li"]][sl][m] = k
            self.new_items = []
            for c in others:
                desc = [(("F" if isl[n[1]]["li"] == 0 else "B") + ".Cu island",
                         tuple(round(v, 1) for v in isl[n[1]]["bbox"])) if n[0] == "island" else n for n in c]
                how = self.link_component(isl, c, main, anchors, lab)
                if isinstance(how, list):
                    how = f"track, {len(how)} cells"
                if how is None:
                    how = self.ripup_link(isl, c, main, anchors, lab)
                print(f"  isolated GND part {desc[:4]}{' ...' if len(desc) > 4 else ''} -> {how}", flush=True)
                if how:
                    links.append(how)
            if not self.new_items:
                return links, len(others)
            self.apply()
            pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        isl, comps, main, anchors = self.gnd_components()
        return links, len(comps) - 1

    def prune_gnd_tracks(self):
        """Delete GND tracks that lie completely inside one filled GND island of their layer
        (left-overs of linking steps whose job the pour now does). Undone if connectivity suffers."""
        isl = self.gnd_islands()
        drop = []
        for t in self.b.GetTracks():
            if t.GetNetname() != "GND" or t.GetClass() == "PCB_VIA":
                continue
            li = 0 if t.GetLayer() == pcbnew.F_Cu else 1
            x1, y1, x2, y2 = tomm(t.GetStart().x), tomm(t.GetStart().y), tomm(t.GetEnd().x), tomm(t.GetEnd().y)
            hw = tomm(t.GetWidth()) / 2
            L = math.hypot(x2 - x1, y2 - y1)
            ux, uy = ((x2 - x1) / L, (y2 - y1) / L) if L else (1.0, 0.0)
            n = max(2, int(L / 0.1) + 1)
            pts = []
            for i in range(n):
                x, y = x1 + (x2 - x1) * i / (n - 1), y1 + (y2 - y1) * i / (n - 1)
                pts += [(x - uy * hw, y + ux * hw), (x + uy * hw, y - ux * hw)]
            pts += [(x1 - ux * hw, y1 - uy * hw), (x2 + ux * hw, y2 + uy * hw)]
            if any(I["li"] == li and all(self._in_island(I, x, y) for x, y in pts) for I in isl):
                drop.append((t, (t.GetStart(), t.GetEnd(), t.GetWidth(), t.GetLayer())))
        if not drop:
            return 0
        for t, _ in drop:
            self.b.Delete(t)
        pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        if len(self.gnd_components()[1]) == 1:
            return len(drop)
        for _, (a, b_, w, layer) in drop:            # undo
            tr = pcbnew.PCB_TRACK(self.b)
            tr.SetStart(a); tr.SetEnd(b_); tr.SetWidth(w); tr.SetLayer(layer); tr.SetNet(self.nets["GND"])
            self.b.Add(tr)
        pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        return 0

    # ------------------------------------------------------------------ write back
    def apply(self):
        nets = self.nets
        if self.purge:
            for t in [t for t in self.b.GetTracks() if t.m_Uuid.AsString() in self.purge]:
                self.b.Delete(t)
            self.purge = set()
        for it in self.new_items:
            if it[0] == "track":
                _, net, layer, x1, y1, x2, y2, w = it
                tr = pcbnew.PCB_TRACK(self.b)
                tr.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
                tr.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
                tr.SetWidth(mm(w))
                tr.SetLayer(layer)
                tr.SetNet(nets[net])
                self.b.Add(tr)
            else:
                _, net, x, y = it
                v = pcbnew.PCB_VIA(self.b)
                v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
                v.SetWidth(mm(VIA_D))
                v.SetDrill(mm(VIA_DRILL))
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNet(nets[net])
                self.b.Add(v)


def net_order(r):
    nets = [n for n in r.pad_cells if n not in ("GND", "") and not n.startswith("__nc")]

    def hpwl(n):
        ys = np.concatenate([p[2] for p in r.pad_cells[n]])
        xs = np.concatenate([p[3] for p in r.pad_cells[n]])
        return int(xs.max() - xs.min() + ys.max() - ys.min())
    long_nets = sorted([n for n in nets if hpwl(n) > 250 and n != "+3V3"], key=hpwl, reverse=True)
    short_nets = sorted([n for n in nets if hpwl(n) <= 250 and n != "+3V3"], key=hpwl)
    return (["+3V3"] if "+3V3" in nets else []) + long_nets + short_nets


def main():
    t0 = time.time()
    order, failed, board, r = None, [], None, None
    for attempt in range(5):
        board = pcbnew.LoadBoard(PCB)
        for t in list(board.GetTracks()):
            board.Remove(t)
        r = Router(board)
        order = order or net_order(r)
        failed = []
        for grp in PRE_GND:
            ok = r.route_net("GND", only=set(grp))
            print(f"  {'ok  ' if ok else 'FAIL'} GND group {'/'.join(grp)}", flush=True)
        for net in order:
            ok = r.route_net(net)
            print(f"  {'ok  ' if ok else 'FAIL'} {net}  ({time.time() - t0:.0f}s)", flush=True)
            if not ok:
                failed.append(net)
        print(f"attempt {attempt + 1}: failed {failed}", flush=True)
        if not failed:
            break
        order = failed + [n for n in order if n not in failed]
    fan = r.gnd_fanout()
    st = r.stitch()
    if r.gnd_failed:                 # second chance: the stitching vias are new anchors
        retry, r.gnd_failed = set(r.gnd_failed), []
        fan += r.gnd_fanout(only=retry)
        if r.gnd_failed:
            print("GND pads without a fan-out (left to the pour / GND repair):", r.gnd_failed, flush=True)
    r.apply()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    isl = 0
    for _ in range(3):
        r.new_items = []
        n = r.stitch_islands()
        if not n:
            break
        isl += n
        r.apply()
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    links, left = r.fix_gnd_connectivity()
    pruned = r.prune_gnd_tracks()
    pcbnew.SaveBoard(PCB, board)
    print(f"done in {time.time() - t0:.0f}s; failed: {failed}; GND fan-out: {fan}; stitching vias: {st}; "
          f"island vias: {isl}; GND links: {links}; isolated GND parts left: {left}; "
          f"redundant GND tracks removed: {pruned}", flush=True)


def gnd_only():
    """Re-check / repair GND connectivity of the routed board without re-routing."""
    board = pcbnew.LoadBoard(PCB)
    r = Router(board)
    r.load_existing()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    links, left = r.fix_gnd_connectivity()
    pruned = r.prune_gnd_tracks()
    pcbnew.SaveBoard(PCB, board)
    print(f"GND links added: {links}; isolated GND parts left: {left}; redundant GND tracks removed: {pruned}",
          flush=True)


if __name__ == "__main__":
    import sys
    gnd_only() if "--gnd-only" in sys.argv else main()

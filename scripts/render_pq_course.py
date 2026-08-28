"""Render the loaded PQ course to out/course_layout.png for eyeballing:
top-down view (gates, yaw, order, cones, reference line) + side elevation
showing the stacked-gate climb. Elodin-free.

    python scripts/render_pq_course.py
"""

import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.pq_course import load_course  # noqa: E402

S = 22          # px per meter, top-down
MARGIN = 60

BG = (24, 18, 14)
GRID = (48, 40, 34)
GATE = (40, 160, 245)
GATE_TOP = (92, 122, 255)
LINE = (240, 200, 70)
CONE = (60, 90, 200)
TEXT = (235, 230, 222)


def reference_waypoints(c, standoff=2.5):
    wps = [(0.0, 0.0, 0.1)]
    for _ in range(c.laps):
        for x in c.crossings:
            nx, ny = math.cos(x.heading_rad), math.sin(x.heading_rad)
            wps.append((x.x - standoff * nx, x.y - standoff * ny, x.z))
            wps.append((x.x + standoff * nx, x.y + standoff * ny, x.z))
    return wps


def main():
    c = load_course()
    xs = [g.x for g in c.gates] + [k.x for k in c.cones] + [0.0]
    ys = [g.y for g in c.gates] + [k.y for k in c.cones] + [0.0]
    x0, x1 = min(xs) - 4, max(xs) + 4
    y0, y1 = min(ys) - 4, max(ys) + 4

    W = int((x1 - x0) * S) + 2 * MARGIN
    H = int((y1 - y0) * S) + 2 * MARGIN
    img = np.full((H, W, 3), BG, np.uint8)

    def px(x, y):
        return (int(MARGIN + (x - x0) * S), int(H - MARGIN - (y - y0) * S))

    for gx in range(int(math.floor(x0)), int(math.ceil(x1)) + 1, 5):
        cv2.line(img, px(gx, y0), px(gx, y1), GRID, 1)
    for gy in range(int(math.floor(y0)), int(math.ceil(y1)) + 1, 5):
        cv2.line(img, px(x0, gy), px(x1, gy), GRID, 1)

    wps = reference_waypoints(c)
    for a, b in zip(wps, wps[1:]):
        cv2.line(img, px(a[0], a[1]), px(b[0], b[1]), LINE, 2, cv2.LINE_AA)

    for k in c.cones:
        cv2.circle(img, px(k.x, k.y), int(k.radius * S), CONE, -1)

    drawn = set()
    for g in c.gates:
        color = GATE_TOP if g.stacked_member == "top" else GATE
        ax, ay = math.cos(g.yaw_rad), math.sin(g.yaw_rad)
        h = 2.7 / 2
        p0 = px(g.x - ax * h, g.y - ay * h)
        p1 = px(g.x + ax * h, g.y + ay * h)
        cv2.line(img, p0, p1, color, 5)
        o = 1.5 / 2
        q0 = px(g.x - ax * o, g.y - ay * o)
        q1 = px(g.x + ax * o, g.y + ay * o)
        cv2.line(img, q0, q1, (255, 255, 255), 1)
        nx, ny = math.cos(g.heading_rad), math.sin(g.heading_rad)
        cv2.arrowedLine(img, px(g.x, g.y), px(g.x + nx * 2, g.y + ny * 2),
                        color, 2, tipLength=0.3)
        if g.gate_order not in drawn:
            drawn.add(g.gate_order)
            cv2.putText(img, f"g{g.gate_order}",
                        (px(g.x, g.y)[0] + 8, px(g.x, g.y)[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, TEXT, 1, cv2.LINE_AA)

    cv2.drawMarker(img, px(0, 0), (80, 230, 120), cv2.MARKER_CROSS, 18, 2)
    cv2.putText(img, "spawn", (px(0, 0)[0] + 8, px(0, 0)[1] + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 230, 120), 1, cv2.LINE_AA)

    # --- side elevation (y vs z): shows the stacked-gate climb -------------
    SE_H, SZ = 220, 34
    side = np.full((SE_H, W, 3), BG, np.uint8)

    def spx(y, z):
        return (int(MARGIN + (y - y0) * ((W - 2 * MARGIN) / (y1 - y0))),
                int(SE_H - 20 - z * SZ))

    for z in range(0, 6):
        cv2.line(side, spx(y0, z), spx(y1, z), GRID, 1)
    for a, b in zip(wps, wps[1:]):
        cv2.line(side, spx(a[1], a[2]), spx(b[1], b[2]), LINE, 2, cv2.LINE_AA)
    for g in c.gates:
        color = GATE_TOP if g.stacked_member == "top" else GATE
        cv2.line(side, spx(g.y, g.z - 1.35), spx(g.y, g.z + 1.35), color, 3)
        cv2.line(side, spx(g.y, g.z - 0.75), spx(g.y, g.z + 0.75),
                 (255, 255, 255), 1)
    cv2.putText(side, "side elevation (y vs z) - both g10 openings",
                (MARGIN, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT, 1,
                cv2.LINE_AA)

    header = np.full((44, W, 3), BG, np.uint8)
    cv2.putText(
        header,
        f"PQ course in sim frame | {c.source} | {len(c.gates)} gates, "
        f"{len(c.crossings)} crossings/lap x {c.laps} laps | "
        f"{len(c.cones)} cones",
        (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, TEXT, 1, cv2.LINE_AA)

    out = np.vstack([header, img, side])
    out_dir = Path(__file__).resolve().parent.parent / "out"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "course_layout.png"
    cv2.imwrite(str(out_path), out)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

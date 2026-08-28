"""
PQ course: load the extracted AI-GrandPrix course map into the sim frame,
define the crossing sequence, and track race progress.

This module is deliberately elodin-free (numpy + stdlib only) so the frame
math and pass detection are unit-testable without the sim stack. The
elodin-facing pieces (entity spawning, schematics) live in sim/course.py
and consume the data structures defined here.

FRAME RECONCILIATION
--------------------
Map frame (data/course_map.json in the AI-GrandPrix repo):
    ENU-style, grid-anchored: x=0 at the overhead render's "0 m" grid
    label line, y=0 at the bottom grid row, +x along the labeled axis
    (declared east), +y up-course (north), z up. The origin is NOT the
    footprint corner.
Sim frame (Elodin): ENU, +X east, +Z up. The drone spawns at the origin.

Both frames are ENU with +x east, so the rotation between them is zero BY
DECLARATION (the map's "east" is the render's labeled axis; nothing in
either frame pins true north). The transform is therefore a pure
translation, chosen so that the DRONE SPAWN (sim origin) sits
`start_standoff_m` before the order-0 gate along that gate's entry
heading. Every downstream position — gates, cones, waypoints — must go
through `MapToSim`. Nothing is hardcoded: the translation is derived from
the loaded map.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# --- locate the AI-GrandPrix repo (loader + map data) -----------------------
# NOTE: on this machine BOTH `ai-grand-prix` (this repo) and `AI-GrandPrix`
# (the map repo) exist side by side, differing only by case — the parent
# directory has per-directory case sensitivity enabled. Resolve by exact name.
_THIS_REPO = Path(__file__).resolve().parent.parent
_DEFAULT_AIGP = _THIS_REPO.parent / "AI-GrandPrix"

AIGP_REPO = Path(os.environ.get("AIGP_REPO", str(_DEFAULT_AIGP)))
DEFAULT_MAP_PATH = Path(
    os.environ.get("AIGP_COURSE_MAP", str(AIGP_REPO / "data" / "course_map.json"))
)

_AIGP_SRC = str(AIGP_REPO / "src")
if _AIGP_SRC not in sys.path:
    sys.path.insert(0, _AIGP_SRC)

from common import course_map as cm_loader  # noqa: E402  (the ONE map parser)


# --- gate geometry (spec, mirrors sim/course.py constants) ------------------
GATE_OUTER_M = 2.7
GATE_OPENING_M = 1.5
GATE_DEPTH_M = 0.26
OPENING_HALF_M = GATE_OPENING_M / 2.0  # 0.75


def wrap_pi(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


# ===========================================================================
# The map->sim transform. ONE place, named, unit-tested.
# ===========================================================================

@dataclass(frozen=True)
class MapToSim:
    """Rigid 2D transform from map frame to sim frame (z passes through)."""

    dyaw_rad: float
    tx: float
    ty: float

    def xy(self, x: float, y: float) -> Tuple[float, float]:
        c, s = math.cos(self.dyaw_rad), math.sin(self.dyaw_rad)
        return (c * x - s * y + self.tx, s * x + c * y + self.ty)

    def heading(self, h: float) -> float:
        return wrap_pi(h + self.dyaw_rad)


def map_to_sim_transform(course, start_standoff_m: float = 3.0) -> MapToSim:
    """Both frames are ENU / +x east => rotation 0 (see module docstring).

    Translation places the sim origin (drone spawn) `start_standoff_m`
    before the order-0 gate's center along that gate's entry heading.
    """
    start = min(
        (g for g in course.gates if g.order is not None),
        key=lambda g: g.order,
    )
    h = start.entry_heading_rad
    if h is None:
        raise ValueError("order-0 gate has no entry heading; cannot place spawn")
    sx = start.xy[0] - start_standoff_m * math.cos(h)
    sy = start.xy[1] - start_standoff_m * math.sin(h)
    return MapToSim(dyaw_rad=0.0, tx=-sx, ty=-sy)


# ===========================================================================
# Course data in the sim frame
# ===========================================================================

@dataclass(frozen=True)
class Crossing:
    """One required opening crossing: a plane segment + a direction."""

    seq: int                 # index within one lap's crossing sequence
    gate_order: int          # g-number (traversal order, Brian's naming)
    label: str               # "g3", "g10-top", "g10-low"
    x: float                 # opening center, sim frame
    y: float
    z: float                 # opening center height
    heading_rad: float       # required travel direction (crossing normal)
    half_w: float = OPENING_HALF_M
    half_h: float = OPENING_HALF_M


@dataclass(frozen=True)
class SimGate:
    """One physical gate body (the stacked pair contributes two)."""

    label: str
    x: float
    y: float
    z: float                 # opening center height of THIS body
    yaw_rad: float           # bar axis in the sim frame
    heading_rad: float       # opening normal (for visual orientation)
    gate_order: int
    stacked_member: Optional[str] = None   # None | "low" | "top"


@dataclass(frozen=True)
class Cone:
    label: str
    x: float
    y: float
    radius: float
    height: float


@dataclass(frozen=True)
class RaceCourse:
    gates: Tuple[SimGate, ...]           # physical bodies (12 for PQ)
    crossings: Tuple[Crossing, ...]      # per-lap sequence (12 for PQ)
    cones: Tuple[Cone, ...]
    laps: int
    transform: MapToSim
    source: str
    footprint_m: Tuple[float, float]

    @property
    def total_events(self) -> int:
        return self.laps * len(self.crossings)

    def event(self, event_idx: int) -> Crossing:
        return self.crossings[event_idx % len(self.crossings)]

    def lap_of(self, event_idx: int) -> int:
        return event_idx // len(self.crossings)


# Cone geometry is NOT in the map (heights unknown). Conservative defaults;
# override via env or load_course kwargs.
# Drone body radius for gate-frame contact (props included).
DRONE_RADIUS_M = float(os.environ.get("AIGP_DRONE_RADIUS_M", "0.15"))
CONE_RADIUS_M = float(os.environ.get("AIGP_CONE_RADIUS_M", "0.4"))
CONE_HEIGHT_M = float(os.environ.get("AIGP_CONE_HEIGHT_M", "1.5"))

DEFAULT_LAPS = 2


def load_course(
    map_path: Optional[os.PathLike] = None,
    laps: int = DEFAULT_LAPS,
    start_standoff_m: float = 3.0,
    cone_radius_m: float = CONE_RADIUS_M,
    cone_height_m: float = CONE_HEIGHT_M,
) -> RaceCourse:
    """Load data/course_map.json through the AI-GrandPrix loader and express
    everything in the sim frame."""
    path = Path(map_path) if map_path is not None else DEFAULT_MAP_PATH
    cmap = cm_loader.load(str(path))
    tf = map_to_sim_transform(cmap, start_standoff_m)

    ordered = cmap.ordered_gates()  # raises if traversal order is missing

    gates: List[SimGate] = []
    crossings: List[Crossing] = []
    seq = 0
    for g in ordered:
        x, y = tf.xy(*g.xy)
        yaw = tf.heading(g.yaw_rad)
        entry = tf.heading(g.entry_heading_rad)
        if g.type == "single":
            z = float(g.openings[0]["z"])
            gates.append(SimGate(
                label=f"g{g.order}", x=x, y=y, z=z, yaw_rad=yaw,
                heading_rad=entry, gate_order=g.order,
            ))
            crossings.append(Crossing(
                seq=seq, gate_order=g.order, label=f"g{g.order}",
                x=x, y=y, z=z, heading_rad=entry,
            ))
            seq += 1
        else:
            # stacked: openings listed in traversal order (top first), each
            # carrying its own entry heading (out-and-back)
            names = ("top", "low")
            for name, opening in zip(names, g.openings):
                z = float(opening["z"])
                oh = opening.get("entry_heading_rad")
                oh = entry if oh is None else tf.heading(float(oh))
                label = f"g{g.order}-{name}"
                gates.append(SimGate(
                    label=label, x=x, y=y, z=z, yaw_rad=yaw,
                    heading_rad=oh, gate_order=g.order, stacked_member=name,
                ))
                crossings.append(Crossing(
                    seq=seq, gate_order=g.order, label=label,
                    x=x, y=y, z=z, heading_rad=oh,
                ))
                seq += 1

    cones = []
    for i, c in enumerate(_map_cones(cmap)):
        cx, cy = tf.xy(c[0], c[1])
        cones.append(Cone(label=f"cone_{i}", x=cx, y=cy,
                          radius=cone_radius_m, height=cone_height_m))

    return RaceCourse(
        gates=tuple(gates),
        crossings=tuple(crossings),
        cones=tuple(cones),
        laps=laps,
        transform=tf,
        source=f"{path.name} ({cmap.source})",
        footprint_m=tuple(cmap.footprint_m),
    )


def _map_cones(cmap) -> List[Tuple[float, float]]:
    """Cone XY list from the map's meta (obstacles are course furniture the
    extractor records; absent meta -> no cones)."""
    cones = cmap.meta.get("cones_xy")
    return [tuple(c) for c in cones] if cones else []


# ===========================================================================
# Pass detection
# ===========================================================================

def crossing_hit(
    c: Crossing,
    prev_pos: Sequence[float],
    curr_pos: Sequence[float],
) -> bool:
    """Did the segment prev->curr cross this opening, in the required
    direction, inside the 1.5 m square?

    Plane: through (c.x, c.y), normal n = (cos h, sin h) in XY.
    Valid: signed distance goes negative -> non-negative (moving along +n),
    and the interpolated crossing point lies within +-0.75 m along the bar
    axis and +-0.75 m of the opening center height.
    """
    nx, ny = math.cos(c.heading_rad), math.sin(c.heading_rad)
    s0 = (prev_pos[0] - c.x) * nx + (prev_pos[1] - c.y) * ny
    s1 = (curr_pos[0] - c.x) * nx + (curr_pos[1] - c.y) * ny
    if not (s0 < 0.0 <= s1):
        return False
    f = s0 / (s0 - s1)
    px = prev_pos[0] + (curr_pos[0] - prev_pos[0]) * f
    py = prev_pos[1] + (curr_pos[1] - prev_pos[1]) * f
    pz = prev_pos[2] + (curr_pos[2] - prev_pos[2]) * f
    lateral = -(px - c.x) * ny + (py - c.y) * nx   # along bar axis
    if abs(lateral) > c.half_w:
        return False
    if abs(pz - c.z) > c.half_h:
        return False
    return True


def gate_frame_hit(g: SimGate, pos: Sequence[float],
                   r: float = None) -> bool:
    """Is the drone (radius r) touching this gate's physical FRAME?

    Frame = the 2.7 m outer square minus the 1.5 m opening, 0.26 m deep,
    in the gate's own axes (bar axis / opening normal / vertical)."""
    r = DRONE_RADIUS_M if r is None else r
    dx = pos[0] - g.x
    dy = pos[1] - g.y
    nx, ny = math.cos(g.heading_rad), math.sin(g.heading_rad)
    depth = dx * nx + dy * ny                     # along opening normal
    lateral = -dx * ny + dy * nx                  # along bar axis
    dz = pos[2] - g.z
    half_out = GATE_OUTER_M / 2.0
    if abs(depth) > GATE_DEPTH_M / 2.0 + r:
        return False
    if abs(lateral) > half_out + r or abs(dz) > half_out + r:
        return False                              # outside the outer square
    if (abs(lateral) <= OPENING_HALF_M - r
            and abs(dz) <= OPENING_HALF_M - r):
        return False                              # cleanly inside the hole
    return True                                   # in the frame material


@dataclass
class GateContact:
    t: float
    gate: str
    x: float
    y: float
    z: float


@dataclass
class NearMiss:
    t: float
    cone: str
    dist_xy: float
    z: float


class RaceTracker:
    """Ordered 2-lap crossing tracker + cone near-miss log + run record.

    Feed `update(t, (x, y, z))` every tick. Crossings only count for the
    next expected event; the stacked gate's two crossings are separated by
    the z window of each opening (the openings sit 2.7 m apart, far more
    than the +-0.75 m tolerance, so z alone disambiguates them).
    """

    def __init__(self, course: RaceCourse):
        self.course = course
        self.event_idx = 0                       # next expected event
        self.event_times: List[float] = []       # time per completed event
        self.lap_times: List[float] = []         # cumulative time per lap
        self.near_misses: List[NearMiss] = []
        self.gate_contacts: List[GateContact] = []
        self.crashed = False
        self._prev: Optional[Tuple[float, float, float]] = None
        self._near_active: Dict[str, bool] = {}

    @property
    def events_passed(self) -> int:
        return self.event_idx

    @property
    def gates_passed(self) -> int:
        """Tiebreaker metric: opening crossings completed."""
        return self.event_idx

    @property
    def complete(self) -> bool:
        return self.event_idx >= self.course.total_events

    def next_crossing(self) -> Optional[Crossing]:
        if self.complete:
            return None
        return self.course.event(self.event_idx)

    def update(self, t: float, pos: Sequence[float]) -> Optional[Crossing]:
        p = (float(pos[0]), float(pos[1]), float(pos[2]))
        hit: Optional[Crossing] = None
        # Physical contact with any gate frame = crash: scoring freezes and
        # the run record is marked invalid (a clipped gate must never pass
        # as a clean lap - it would be a real-world DQ/crash).
        if not self.crashed:
            for g in self.course.gates:
                if gate_frame_hit(g, p):
                    self.crashed = True
                    self.gate_contacts.append(
                        GateContact(t, g.label, p[0], p[1], p[2]))
                    break
        if (self._prev is not None and not self.complete
                and not self.crashed):
            c = self.course.event(self.event_idx)
            if crossing_hit(c, self._prev, p):
                hit = c
                self.event_times.append(t)
                self.event_idx += 1
                per_lap = len(self.course.crossings)
                if self.event_idx % per_lap == 0:
                    self.lap_times.append(t)
        self._check_cones(t, p)
        self._prev = p
        return hit

    def _check_cones(self, t: float, p: Tuple[float, float, float]):
        for cone in self.course.cones:
            d = math.hypot(p[0] - cone.x, p[1] - cone.y)
            inside = d <= cone.radius and p[2] <= cone.height
            was = self._near_active.get(cone.label, False)
            if inside and not was:
                self.near_misses.append(NearMiss(t, cone.label, d, p[2]))
            self._near_active[cone.label] = inside

    # --- machine-readable run record ---------------------------------------
    def record(self, final_t: float) -> dict:
        per_lap = len(self.course.crossings)
        events = []
        for i, t in enumerate(self.event_times):
            c = self.course.event(i)
            events.append({
                "event": i,
                "lap": self.course.lap_of(i),
                "gate": c.label,
                "z": c.z,
                "t": round(t, 4),
            })
        laps = []
        prev_t = 0.0
        for i, t in enumerate(self.lap_times):
            laps.append({"lap": i, "t_total": round(t, 4),
                         "t_lap": round(t - prev_t, 4)})
            prev_t = t
        return {
            "course_source": self.course.source,
            "laps_required": self.course.laps,
            "crossings_per_lap": per_lap,
            "events_total": self.course.total_events,
            "gates_passed": self.gates_passed,
            "complete": self.complete and not self.crashed,
            "crashed": self.crashed,
            "gate_contacts": [
                {"t": round(c.t, 3), "gate": c.gate,
                 "pos": [round(c.x, 2), round(c.y, 2), round(c.z, 2)]}
                for c in self.gate_contacts
            ],
            "total_time_s": round(
                self.event_times[-1], 4) if self.complete else None,
            "final_t_s": round(final_t, 4),
            "events": events,
            "lap_times": laps,
            "near_misses": [
                {"t": round(n.t, 4), "cone": n.cone,
                 "dist_xy": round(n.dist_xy, 3), "z": round(n.z, 3)}
                for n in self.near_misses
            ],
        }

    def write_record(self, path: os.PathLike, final_t: float) -> dict:
        rec = self.record(final_t)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)
        return rec


# ===========================================================================
# Frame-reconciliation printout (run: python -m sim.pq_course)
# ===========================================================================

def print_frame_report(course: RaceCourse) -> None:
    tf = course.transform
    print("map->sim transform (rotation declared 0: both frames ENU, +x east):")
    print(f"  sim = map + (tx={tf.tx:+.3f}, ty={tf.ty:+.3f}), dyaw={tf.dyaw_rad:.3f} rad")
    print(f"  (sim origin = drone spawn = 3 m before g0 along its entry heading)")
    print(f"\ncourse source: {course.source}")
    print(f"crossing sequence per lap ({len(course.crossings)}), laps={course.laps}:")
    for c in course.crossings:
        print(f"  {c.seq:2d}  {c.label:8s} sim=({c.x:+7.2f},{c.y:+7.2f}) "
              f"z={c.z:.2f}  heading={math.degrees(c.heading_rad):+7.1f} deg")
    xs = [g.x for g in course.gates]
    ys = [g.y for g in course.gates]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    fp = course.footprint_m
    long_side, short_side = max(fp), min(fp)
    print(f"\ngate span: x {min(xs):+.2f}..{max(xs):+.2f} ({span_x:.1f} m), "
          f"y {min(ys):+.2f}..{max(ys):+.2f} ({span_y:.1f} m)")
    ok = (max(span_x, span_y) <= long_side + 1e-6
          and min(span_x, span_y) <= short_side + 1e-6)
    print(f"footprint {fp[0]:.0f} x {fp[1]:.0f} m fit: "
          f"{'OK' if ok else '*** DOES NOT FIT ***'}")
    if course.cones:
        print(f"\ncones ({len(course.cones)}), r={course.cones[0].radius} m, "
              f"h={course.cones[0].height} m (heights UNKNOWN, config default):")
        for c in course.cones:
            print(f"  {c.label:8s} sim=({c.x:+7.2f},{c.y:+7.2f})")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    print_frame_report(load_course())

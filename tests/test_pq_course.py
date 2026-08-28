"""Verification for the PQ course port: frame transform, ordered 2-lap
tracking, stacked-gate z disambiguation, direction/opening rejection, cone
near-miss logging, and the machine-readable run record.

Elodin-free (sim.pq_course only) so it runs without the sim stack:
    python tests/test_pq_course.py      # stdlib runner
    uv run pytest tests/test_pq_course.py
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim import pq_course
from sim.pq_course import (
    Crossing,
    RaceTracker,
    crossing_hit,
    load_course,
    map_to_sim_transform,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def course():
    if not hasattr(course, "_c"):
        course._c = load_course()
    return course._c


def run_path(tracker, waypoints, step=0.1, t0=0.0, dt=0.01):
    """Feed a dense interpolation of the waypoint polyline to the tracker."""
    t = t0
    prev = waypoints[0]
    tracker.update(t, prev)
    for wp in waypoints[1:]:
        seg = math.dist(prev, wp)
        n = max(1, int(seg / step))
        for i in range(1, n + 1):
            f = i / n
            p = tuple(prev[k] + (wp[k] - prev[k]) * f for k in range(3))
            t += dt
            tracker.update(t, p)
        prev = wp
    return t


def reference_waypoints(c, laps=None, standoff=2.5):
    """The scripted verification trajectory: spawn, then pre/post points
    around every crossing of every lap, in order. Ignores realism."""
    laps = c.laps if laps is None else laps
    wps = [(0.0, 0.0, 0.1)]
    for lap in range(laps):
        for x in c.crossings:
            nx, ny = math.cos(x.heading_rad), math.sin(x.heading_rad)
            wps.append((x.x - standoff * nx, x.y - standoff * ny, x.z))
            wps.append((x.x + standoff * nx, x.y + standoff * ny, x.z))
    return wps


# ---------------------------------------------------------------------------
# frame transform
# ---------------------------------------------------------------------------

def test_transform_places_spawn_before_g0():
    c = course()
    tf = c.transform
    assert tf.dyaw_rad == 0.0
    g0 = c.crossings[0]
    # g0's center must sit 3 m from the sim origin along its entry heading
    d = math.hypot(g0.x, g0.y)
    assert abs(d - 3.0) < 1e-6, d
    ang = math.atan2(g0.y, g0.x)
    assert abs(pq_course.wrap_pi(ang - g0.heading_rad)) < 1e-6


def test_transform_math_roundtrip():
    tf = pq_course.MapToSim(dyaw_rad=0.0, tx=-3.0, ty=5.0)
    assert tf.xy(3.0, -5.0) == (0.0, 0.0)
    assert tf.xy(10.0, 2.0) == (7.0, 7.0)
    assert abs(tf.heading(1.0) - 1.0) < 1e-12  # pure translation keeps headings


def test_course_fits_footprint():
    c = course()
    xs = [g.x for g in c.gates]
    ys = [g.y for g in c.gates]
    span = sorted([max(xs) - min(xs), max(ys) - min(ys)])
    fp = sorted(c.footprint_m)
    assert span[0] <= fp[0] and span[1] <= fp[1], (span, fp)


def test_course_shape():
    c = course()
    assert len(c.crossings) == 12          # 12 opening crossings per lap
    assert len(c.gates) == 12              # 12 physical gates
    assert c.laps == 2
    assert c.total_events == 24
    stacked = [x for x in c.crossings if x.gate_order == 10]
    assert [x.label for x in stacked] == ["g10-top", "g10-low"]
    top, low = stacked
    assert top.z == 4.05 and low.z == 1.35
    # out-and-back: the two crossing directions oppose
    assert abs(abs(pq_course.wrap_pi(top.heading_rad - low.heading_rad))
               - math.pi) < 0.05
    assert len(c.cones) == 10


# ---------------------------------------------------------------------------
# crossing geometry
# ---------------------------------------------------------------------------

G = Crossing(seq=0, gate_order=0, label="t", x=5.0, y=0.0, z=1.35,
             heading_rad=0.0)  # opening at x=5, must cross heading +X


def test_hit_centered():
    assert crossing_hit(G, (4.0, 0.0, 1.35), (6.0, 0.0, 1.35))


def test_no_hit_backwards():
    assert not crossing_hit(G, (6.0, 0.0, 1.35), (4.0, 0.0, 1.35))


def test_no_hit_outside_lateral():
    assert not crossing_hit(G, (4.0, 0.8, 1.35), (6.0, 0.8, 1.35))


def test_no_hit_outside_z():
    assert not crossing_hit(G, (4.0, 0.0, 2.2), (6.0, 0.0, 2.2))


def test_hit_interpolates_crossing_point():
    # Steep diagonal step: position is inside bounds only AT the plane
    assert crossing_hit(G, (4.9, 0.6, 1.35), (5.1, 0.65, 1.35))
    assert not crossing_hit(G, (4.9, 2.0, 1.35), (5.1, 2.1, 1.35))


def test_hit_rotated_gate():
    g = Crossing(seq=0, gate_order=0, label="r", x=0.0, y=0.0, z=1.35,
                 heading_rad=math.radians(45.0))
    n = (math.cos(g.heading_rad), math.sin(g.heading_rad))
    prev = (-1.0 * n[0], -1.0 * n[1], 1.35)
    curr = (1.0 * n[0], 1.0 * n[1], 1.35)
    assert crossing_hit(g, prev, curr)
    assert not crossing_hit(g, curr, prev)


# ---------------------------------------------------------------------------
# full 2-lap scripted run
# ---------------------------------------------------------------------------

def test_scripted_two_laps_all_events_in_order():
    c = course()
    tracker = RaceTracker(c)
    final_t = run_path(tracker, reference_waypoints(c))
    assert tracker.complete, (
        f"only {tracker.events_passed}/{c.total_events} events; "
        f"next={tracker.next_crossing()}"
    )
    rec = tracker.record(final_t)
    assert rec["gates_passed"] == 24
    assert [e["event"] for e in rec["events"]] == list(range(24))
    # per lap: 12 crossings, stacked z sequence 4.05 then 1.35 at the end
    for lap in range(2):
        lap_events = [e for e in rec["events"] if e["lap"] == lap]
        assert len(lap_events) == 12
        assert [e["gate"] for e in lap_events[:10]] == [
            f"g{i}" for i in range(10)]
        assert lap_events[10]["gate"] == "g10-top"
        assert lap_events[10]["z"] == 4.05
        assert lap_events[11]["gate"] == "g10-low"
        assert lap_events[11]["z"] == 1.35
    assert len(rec["lap_times"]) == 2
    assert rec["complete"] is True
    assert rec["total_time_s"] is not None
    # times strictly increasing
    ts = [e["t"] for e in rec["events"]]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


def test_backwards_gate_does_not_count():
    c = course()
    tracker = RaceTracker(c)
    g0 = c.crossings[0]
    nx, ny = math.cos(g0.heading_rad), math.sin(g0.heading_rad)
    # approach from the EXIT side and fly through backwards
    run_path(tracker, [
        (g0.x + 2.5 * nx, g0.y + 2.5 * ny, g0.z),
        (g0.x - 2.5 * nx, g0.y - 2.5 * ny, g0.z),
    ])
    assert tracker.events_passed == 0


def test_outside_opening_does_not_count():
    c = course()
    tracker = RaceTracker(c)
    g0 = c.crossings[0]
    nx, ny = math.cos(g0.heading_rad), math.sin(g0.heading_rad)
    ax, ay = -ny, nx  # bar axis
    off = 0.80  # just outside the 0.75 m half-opening
    run_path(tracker, [
        (g0.x - 2.5 * nx + off * ax, g0.y - 2.5 * ny + off * ay, g0.z),
        (g0.x + 2.5 * nx + off * ax, g0.y + 2.5 * ny + off * ay, g0.z),
    ])
    assert tracker.events_passed == 0


def test_stacked_wrong_z_does_not_count():
    """When g10-top (z=4.05) is expected, flying the same track at the
    BOTTOM opening's height must not count — z disambiguates."""
    c = course()
    tracker = RaceTracker(c)
    tracker.event_idx = 10  # next expected: g10-top
    top = c.crossings[10]
    nx, ny = math.cos(top.heading_rad), math.sin(top.heading_rad)
    z_low = 1.35
    run_path(tracker, [
        (top.x - 2.5 * nx, top.y - 2.5 * ny, z_low),
        (top.x + 2.5 * nx, top.y + 2.5 * ny, z_low),
    ])
    assert tracker.events_passed == 10  # unchanged
    # and at the correct height it does count
    run_path(tracker, [
        (top.x - 2.5 * nx, top.y - 2.5 * ny, top.z),
        (top.x + 2.5 * nx, top.y + 2.5 * ny, top.z),
    ])
    assert tracker.events_passed == 11


def test_cone_near_miss_logged():
    c = course()
    tracker = RaceTracker(c)
    cone = c.cones[0]
    run_path(tracker, [
        (cone.x - 2.0, cone.y, 1.0),
        (cone.x + 2.0, cone.y, 1.0),   # straight through the cone radius
    ], step=0.05)
    assert any(n.cone == cone.label for n in tracker.near_misses)
    # one entry per incursion, not one per tick
    assert sum(1 for n in tracker.near_misses if n.cone == cone.label) == 1


def test_cone_overflight_above_height_not_logged():
    c = course()
    tracker = RaceTracker(c)
    cone = c.cones[0]
    run_path(tracker, [
        (cone.x - 2.0, cone.y, cone.height + 0.5),
        (cone.x + 2.0, cone.y, cone.height + 0.5),
    ], step=0.05)
    assert not any(n.cone == cone.label for n in tracker.near_misses)


def test_record_is_json_serializable():
    c = course()
    tracker = RaceTracker(c)
    run_path(tracker, reference_waypoints(c, laps=1))
    rec = tracker.record(99.0)
    s = json.dumps(rec)
    assert "g10-top" in s
    assert rec["complete"] is False
    assert rec["gates_passed"] == 12


def test_transform_named_and_single_source():
    """Every course position must have gone through MapToSim: spot-check
    that reapplying the inverse translation recovers the map coordinates."""
    c = course()
    tf = c.transform
    import common.course_map as cml
    cmap = cml.load(str(pq_course.DEFAULT_MAP_PATH))
    by_order = {g.order: g for g in cmap.gates}
    for gate in c.gates:
        m = by_order[gate.gate_order]
        assert abs(gate.x - tf.tx - m.xy[0]) < 1e-9
        assert abs(gate.y - tf.ty - m.xy[1]) < 1e-9


if __name__ == "__main__":
    import inspect
    failures = 0
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and inspect.isfunction(f)]
    for name, fn in fns:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)

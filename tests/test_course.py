"""Elodin-facing course tests: entity naming, schematic rendering, summary.

Pass-detection geometry and lap tracking are covered elodin-free in
tests/test_pq_course.py; these tests need the `elodin` package installed
(uv run pytest).
"""

import math

from sim.course import (
    GATE_ASSET,
    MAX_GATES,
    entity_name,
    print_summary,
    schematic_for,
)
from sim.pq_course import RaceTracker, load_course


def _course():
    if not hasattr(_course, "_c"):
        _course._c = load_course()
    return _course._c


def test_entity_names_are_kdl_safe():
    assert entity_name("g0") == "gate_g0"
    assert entity_name("g10-top") == "gate_g10_top"
    for g in _course().gates:
        assert "-" not in entity_name(g.label)


def test_schematic_renders_one_glb_per_physical_gate():
    c = _course()
    s = schematic_for(c)
    assert s.count(f'glb path="{GATE_ASSET}"') == len(c.gates) == 12
    for g in c.gates:
        ref = f"{entity_name(g.label)}.world_pos"
        assert s.count(ref) == 1, f"{ref} should appear exactly once"
    for cone in c.cones:
        assert f"{cone.label}.world_pos" in s


def test_event_count_fits_component_slots():
    c = _course()
    assert c.total_events <= MAX_GATES


def test_stacked_bodies_share_xy_and_split_z():
    c = _course()
    stacked = [g for g in c.gates if g.stacked_member]
    assert len(stacked) == 2
    a, b = stacked
    assert math.hypot(a.x - b.x, a.y - b.y) < 1e-9
    assert sorted([a.z, b.z]) == [1.35, 4.05]


def test_print_summary_reports_dnf_and_complete():
    c = _course()
    tracker = RaceTracker(c)
    line = print_summary(tracker, 12.0)
    assert "DNF" in line and "gates_passed=0/24" in line

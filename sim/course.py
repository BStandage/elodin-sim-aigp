"""
AI Grand Prix race course: gate/cone entities, schematics, and race summary.

Gate dimensions follow VADR-TS-002 §3.7 / VADR-TS-004:
  - Outer:  2700 x 2700 mm (square frame)
  - Inner (flyable hole): 1500 x 1500 mm
  - Depth:  260 mm

The course itself (positions, yaws, crossing order, laps, cones) is loaded
from the AI-GrandPrix extracted map via `sim.pq_course.load_course()` —
nothing here hardcodes gate positions. Pass detection and lap accounting
live in `sim.pq_course.RaceTracker` (elodin-free, unit-tested); this module
holds only the elodin-facing pieces: entity spawning, KDL schematic blocks,
and the end-of-run summary line.
"""

import math
import typing as ty
from dataclasses import dataclass, field

import elodin as el
import jax
import jax.numpy as jnp

from sim.pq_course import Cone, RaceCourse, RaceTracker, SimGate

# Gate dimensions, meters.
GATE_OUTER_W = 2.7
GATE_OUTER_H = 2.7
GATE_DEPTH = 0.26
GATE_INNER_W = 1.5
GATE_INNER_H = 1.5

# Frame thickness around the inner hole, per side. Matches AGP outer/inner spec.
GATE_FRAME = (GATE_OUTER_W - GATE_INNER_W) / 2.0  # 0.6 m


# Index of the LAST crossing event completed; -1 before any pass. An "event"
# is one opening crossing in the ordered 2-lap sequence (the stacked gate
# contributes two events per lap). external_control so the post_step
# tracker can write to it.
LastGatePassed = ty.Annotated[
    jax.Array,
    el.Component(
        "last_gate_passed",
        el.ComponentType(el.PrimitiveType.F64, (1,)),
        metadata={
            "priority": 200,
            "external_control": "true",
        },
    ),
]

# Sim seconds when each crossing event was completed. `MAX_GATES` slots;
# -1.0 = "not yet". 2 laps x 12 crossings = 24 events fits in 32.
MAX_GATES = 32

GatePassTimes = ty.Annotated[
    jax.Array,
    el.Component(
        "gate_pass_times",
        el.ComponentType(el.PrimitiveType.F64, (MAX_GATES,)),
        metadata={
            "priority": 199,
            "external_control": "true",
        },
    ),
]


@dataclass
class GateProgress(el.Archetype):
    """Per-drone race progress state."""

    last_gate_passed: LastGatePassed = field(
        default_factory=lambda: jnp.array([-1.0])
    )
    gate_pass_times: GatePassTimes = field(
        default_factory=lambda: jnp.full(MAX_GATES, -1.0)
    )


# Visual asset bound to each gate entity.
GATE_ASSET = "gate.glb"

# Base rotation applied to every gate GLB: the model is authored facing its
# native Y axis; (0, 90, 0) orients the opening to face +X (East). The
# per-gate opening heading is applied as the ENTITY's Z rotation at spawn,
# composing with this base rotation.
GATE_BASE_ROTATE = "(0.0, 90.0, 0.0)"

# KDL primitive visuals for cones. If the installed Elodin build rejects the
# `sphere` primitive in object_3d blocks, set False — near-miss logging in
# RaceTracker does not depend on visuals.
CONE_VISUALS = True


def entity_name(label: str) -> str:
    """Stable Elodin entity name for a course element label like 'g10-top'."""
    return "gate_" + label.replace("-", "_")


def _yaw_quat(theta: float) -> jnp.ndarray:
    """Scalar-last quaternion for a rotation of theta about world Z."""
    return jnp.array([0.0, 0.0, math.sin(theta / 2.0), math.cos(theta / 2.0)])


def _spawn_static(world: el.World, pos, quat, name: str):
    """Static visual body: no Drone archetype, zero velocity, no forces."""
    return world.spawn(
        [
            el.Body(
                world_pos=el.SpatialTransform(
                    linear=jnp.array(pos),
                    angular=el.Quaternion(quat),
                ),
                world_vel=el.SpatialMotion(
                    linear=jnp.zeros(3),
                    angular=jnp.zeros(3),
                ),
                inertia=el.SpatialInertia(
                    mass=1.0,
                    inertia=jnp.array([1.0, 1.0, 1.0]),
                ),
            ),
        ],
        name=name,
    )


def spawn_gates(world: el.World, course: RaceCourse) -> list:
    """One static body per physical gate (the stacked pair = two bodies at
    the same XY, z = 1.35 and 4.05). Entity yaw = the opening's crossing
    heading, so the GLB (which faces +X after GATE_BASE_ROTATE) presents
    its opening along the required travel direction."""
    ids = []
    for g in course.gates:
        ent = _spawn_static(
            world,
            (g.x, g.y, g.z),
            _yaw_quat(g.heading_rad),
            entity_name(g.label),
        )
        ids.append(ent)
    return ids


def spawn_cones(world: el.World, course: RaceCourse) -> list:
    """Static bodies for the course cones (obstacles). Heights are unknown;
    the visual/logging geometry comes from the course's Cone config."""
    ids = []
    for c in course.cones:
        ent = _spawn_static(
            world,
            (c.x, c.y, c.height / 2.0),
            jnp.array([0.0, 0.0, 0.0, 1.0]),
            c.label,
        )
        ids.append(ent)
    return ids


def schematic_for(course: RaceCourse) -> str:
    """KDL visual blocks for gates (+ cones when CONE_VISUALS)."""
    blocks: list = []
    for g in course.gates:
        blocks.append(
            f"    object_3d {entity_name(g.label)}.world_pos {{\n"
            f'        glb path="{GATE_ASSET}" rotate="{GATE_BASE_ROTATE}" translate="(0.0, 0.0, 0.0)"\n'
            f"    }}"
        )
    if CONE_VISUALS:
        for c in course.cones:
            blocks.append(
                f"    object_3d {c.label}.world_pos {{\n"
                f"        sphere radius={c.radius:.2f} {{\n"
                f"            color 230 120 30\n"
                f"        }}\n"
                f"    }}"
            )
    return "\n".join(blocks)


def print_summary(tracker: RaceTracker, final_t: float) -> str:
    """Single-line `[RACE]` summary from the tracker. Returns the line."""
    course = tracker.course
    n = course.total_events
    n_passed = tracker.gates_passed
    status = "COMPLETE" if tracker.complete else "DNF"
    total = tracker.event_times[-1] if tracker.complete else final_t
    laps_str = ",".join(f"{t['t_lap']:.2f}" if isinstance(t, dict) else "--"
                        for t in tracker.record(final_t)["lap_times"]) or "--"
    line = (
        f"[RACE] course={course.source} laps={course.laps} "
        f"gates_passed={n_passed}/{n} total_time={total:.2f}s "
        f"lap_times=[{laps_str}] status={status} "
        f"near_misses={len(tracker.near_misses)}"
    )
    print(line)
    return line

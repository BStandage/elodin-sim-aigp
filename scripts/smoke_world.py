"""Build the race world WITHOUT running it: spawns the drone, all 12 gate
bodies, cones, and registers the full KDL schematic. Exercises every
elodin-dependent code path in sim/course.py short of world.run(), so it
needs no Betaflight build.

    uv run python scripts/smoke_world.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import elodin as el
import jax.numpy as jnp

from sim.config import DEFAULT_CONFIG
from sim.physics import Drone
from sim.sensors import IMU
from sim.visualization import DroneViz
from sim import course as race_course
from sim import pq_course

config = DEFAULT_CONFIG
config.set_as_global()

course = pq_course.load_course()
pq_course.print_frame_report(course)

world = el.World()
drone = world.spawn(
    [
        el.Body(
            world_pos=el.SpatialTransform(
                linear=jnp.array(config.initial_position),
                angular=el.Quaternion(jnp.array(config.initial_quaternion)),
            ),
            world_vel=el.SpatialMotion(
                linear=jnp.zeros(3), angular=jnp.zeros(3)),
            inertia=el.SpatialInertia(
                mass=config.mass, inertia=jnp.array(config.inertia_diagonal)),
        ),
        Drone(),
        DroneViz(),
        IMU(),
        race_course.GateProgress(),
    ],
    name="drone",
)

gate_ids = race_course.spawn_gates(world, course)
cone_ids = race_course.spawn_cones(world, course)
print(f"\nspawned: drone + {len(gate_ids)} gates + {len(cone_ids)} cones")

schematic = (
    "    timeline follow_latest=#true\n"
    + race_course.schematic_for(course)
)
world.schematic(schematic, "smoke.kdl")
print("schematic registered OK (KDL accepted, including cone spheres)")
print("\nSMOKE OK")

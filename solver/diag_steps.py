"""Diagnostic solver: hover + stick step responses, printing the plant's
actual behavior so control signs/gains stop being guesswork.

    RACE_SOLVER=solver.diag_steps ... elodin run sim/main.py

Phases (after arm):
  2-12 s   pure hover, sticks centered      -> is BF's rate loop stable?
  12-13 s  pitch stick +60                  -> which way does it tilt/move?
  13-18 s  recover (centered)
  18-19 s  roll stick +60
  19-24 s  recover
  24-60 s  hover

Prints body z-axis tilt components, gyro, velocity each 0.5 s.
"""

from __future__ import annotations

import math

from .api import RCCommand, SensorUpdate

HOVER_PWM = 1230


def _rot_zcol(wp):
    qx, qy, qz, qw = (float(wp[0]), float(wp[1]), float(wp[2]), float(wp[3]))
    return (2 * (qx * qz + qy * qw),
            2 * (qy * qz - qx * qw),
            1 - 2 * (qx * qx + qy * qy))


_state = {"dbg": 0.0, "i": 0.0, "lt": 0.0}


def autopilot(update: SensorUpdate) -> RCCommand:
    t = update.t
    if t < 0.5:
        return RCCommand(arm=1000, throttle=1000)
    if t < 0.75:
        return RCCommand(arm=1800, throttle=1000)

    z = float(update.world_pos[6])
    vz = float(update.world_vel[5]) if update.world_vel.size > 5 else 0.0
    # simple altitude hold at 2 m so we stay airborne throughout
    err = 2.0 - z
    dt = max(1e-3, t - _state["lt"])
    _state["i"] = max(-150.0, min(150.0, _state["i"] + err * dt * 10.0))
    _state["lt"] = t
    throttle = int(max(1000, min(1700,
                                 HOVER_PWM + 120.0 * err - 60.0 * vz + _state["i"])))

    roll, pitch, yaw = 1500, 1500, 1500
    if 12.0 <= t < 13.0:
        pitch = 1560
    elif 18.0 <= t < 19.0:
        roll = 1560
    elif 24.0 <= t < 25.0:
        yaw = 1560

    if t - _state["dbg"] >= 0.5:
        _state["dbg"] = t
        zb = _rot_zcol(update.world_pos)
        gx = float(update.gyro[0]) if update.gyro.size > 0 else 0.0
        gy = float(update.gyro[1]) if update.gyro.size > 1 else 0.0
        vx = float(update.world_vel[3]) if update.world_vel.size > 3 else 0.0
        vy = float(update.world_vel[4]) if update.world_vel.size > 4 else 0.0
        x = float(update.world_pos[4])
        y = float(update.world_pos[5])
        qx, qy, qz, qw = (float(update.world_pos[i]) for i in range(4))
        yaw_world = math.atan2(2.0 * (qw * qz + qx * qy),
                               1.0 - 2.0 * (qy * qy + qz * qz))
        print(f"[DIAG] t={t:5.1f} stk=({roll},{pitch},{yaw},{throttle}) "
              f"zb=({zb[0]:+.2f},{zb[1]:+.2f},{zb[2]:+.2f}) "
              f"yaw={math.degrees(yaw_world):+7.1f} "
              f"v=({vx:+5.2f},{vy:+5.2f},{vz:+5.2f}) "
              f"p=({x:+6.1f},{y:+6.1f},{z:+5.2f})")

    return RCCommand(arm=1800, throttle=throttle, roll=roll, pitch=pitch,
                     yaw=yaw)

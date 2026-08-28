"""Reference waypoint pilot for the PQ course.

Flies the extracted course's crossing sequence (2 laps, including the
double-gate out-and-back) as position goals, using the same RC-space PD
scheme as solver/baseline.py. Every goal is derived from the loaded map —
nothing is hardcoded.

This is a REFERENCE pilot: it exists to fly the course and exercise the
tracker, not to be fast. Select it with:

    RACE_SOLVER=solver.pq_waypoints uv run elodin run sim/main.py
"""

from __future__ import annotations

import math

from sim import pq_course
from .api import RCCommand, SensorUpdate

# Arming phases, matching the baseline's Betaflight handshake.
T_DISARMED_END = 0.50
T_ARM_IDLE_END = 0.75

MIN_ALT_FOR_TRANSLATION_M = 1.0
BASE_HOVER_PWM = 1240   # measured steady-state hover RC on the fixed plant
TAKEOFF_PWM = 1330

KP_Z = 140.0
KD_Z = 45.0

# Position loop -> desired lateral acceleration (m/s^2)
KP_POS = 1.2
KD_POS = 2.1
A_MAX = 3.0            # ~17 deg max commanded tilt
BRAKE_ZONE_M = 2.5     # taper accel near the goal so approaches converge
                       # instead of ringing around tight gate-center radii

# Attitude loop (acro sticks): tilt-vector error (rad) -> stick PWM,
# with gyro rate damping. Betaflight stays in RATE mode — its own attitude
# estimator is not trustworthy in this SITL setup (angle mode via AUX2
# produced a diverged estimate and the quad never lifted), so we close the
# attitude loop here using the sim's ground-truth quaternion + gyro.
# No gyro-rate damping term: Betaflight's rate loop already damps, and the
# sim gyro's axis conventions are BF-adjusted (adding our own term produced
# a limit cycle that generated airmode lift and a constant climb).
KA_ATT = 120.0
KD_RATE = 0.0
STICK_CLAMP = 45

# Yaw: nose (and FPV camera) tracks the direction of travel so a vision
# solver would see the gates. Measured on this build: +yaw stick = yaw
# RIGHT (world yaw decreases), ~0.31 rad/s per 60 PWM.
KYAW = 200.0
YAW_CLAMP = 100
YAW_LOOKAHEAD_M = 3.0   # aim the nose at the NEXT waypoint once the
YAW_HOLD_DIST_M = 1.5   # current one is close; never chase a target
                        # the drone is on top of (that spins the nose,
                        # couples into the mixer, and orbits)

# A waypoint counts as reached inside this sphere. Generous on purpose:
# the tracker's crossing test carries the strict +-0.75 m bound; waypoints
# only steer, and a radius below cruise tracking error causes orbiting.
REACH_XY_M = 1.3
REACH_Z_M = 0.7

# Standoff before/after each opening. Shorter than the tracker tests' 2.5 m
# so consecutive goals pull the drone straight through the opening.
STANDOFF_M = 2.0


def _build_waypoints():
    course = pq_course.load_course()
    wps = []
    for lap in range(course.laps):
        for c in course.crossings:
            nx, ny = math.cos(c.heading_rad), math.sin(c.heading_rad)
            # pre / CENTER / post. Loose reach on pre/post (they only
            # steer); tight reach on the CENTER so the drone genuinely
            # centers in the opening before moving on — the tracker's
            # crossing bound is +-0.75 m and repeated misses ran ~0.6 m
            # off-center with a loose center radius.
            wps.append((c.x - STANDOFF_M * nx, c.y - STANDOFF_M * ny, c.z,
                        REACH_XY_M))
            wps.append((c.x, c.y, c.z, 0.65))
            wps.append((c.x + STANDOFF_M * nx, c.y + STANDOFF_M * ny, c.z,
                        REACH_XY_M))
    # park past the finish, low
    last = wps[-1]
    wps.append((last[0], last[1], 0.8, REACH_XY_M))
    return course, wps


COURSE, WAYPOINTS = _build_waypoints()

_state = {
    "wp": 0,
    "i_term": 0.0,
    "last_t": 0.0,
    "done_t": None,
}


def reset_state() -> None:
    _state["wp"] = 0
    _state["i_term"] = 0.0
    _state["last_t"] = 0.0
    _state["done_t"] = None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _advance(x: float, y: float, z: float) -> tuple:
    """Advance the waypoint index when the current goal is reached."""
    while _state["wp"] < len(WAYPOINTS) - 1:
        gx, gy, gz, r = WAYPOINTS[_state["wp"]]
        if (math.hypot(gx - x, gy - y) <= r
                and abs(gz - z) <= REACH_Z_M):
            _state["wp"] += 1
        else:
            break
    return WAYPOINTS[_state["wp"]]


def _altitude_throttle(update: SensorUpdate, target_alt_m: float) -> int:
    t = update.t
    altitude = float(update.world_pos[6])
    vertical_speed = float(update.world_vel[5]) if update.world_vel.size > 5 else 0.0
    dt = max(1e-3, t - _state["last_t"])
    err = target_alt_m - altitude
    if update.baro_fresh:
        _state["i_term"] = _clamp(_state["i_term"] + err * dt * 8.0, -120.0, 120.0)
    if altitude < MIN_ALT_FOR_TRANSLATION_M and vertical_speed < 0.7:
        throttle = TAKEOFF_PWM
    else:
        throttle = (BASE_HOVER_PWM + KP_Z * err - KD_Z * vertical_speed
                    + _state["i_term"])
    _state["last_t"] = t
    return int(round(_clamp(throttle, 1000, 1600)))


def _rot_from_quat(wp):
    """3x3 body->world rotation from Elodin scalar-last quat [qx,qy,qz,qw]."""
    qx, qy, qz, qw = (float(wp[0]), float(wp[1]), float(wp[2]), float(wp[3]))
    return (
        (1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)),
        (2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)),
        (2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)),
    )


def autopilot(update: SensorUpdate) -> RCCommand:
    t = update.t
    if t < T_DISARMED_END:
        return RCCommand(arm=1000, throttle=1000)
    if t < T_ARM_IDLE_END:
        return RCCommand(arm=1800, throttle=1000)

    x = float(update.world_pos[4])
    y = float(update.world_pos[5])
    z = float(update.world_pos[6])
    vx = float(update.world_vel[3]) if update.world_vel.size > 3 else 0.0
    vy = float(update.world_vel[4]) if update.world_vel.size > 4 else 0.0

    goal = _advance(x, y, z)
    at_final = _state["wp"] >= len(WAYPOINTS) - 1

    if at_final and math.hypot(goal[0] - x, goal[1] - y) < 1.5:
        if _state["done_t"] is None:
            _state["done_t"] = t
        if t - _state["done_t"] > 1.0:
            return RCCommand(arm=1000, throttle=1000)   # land/disarm

    throttle = _altitude_throttle(update, goal[2])
    pitch = 1500
    roll = 1500
    yaw_stick = 1500
    if z >= MIN_ALT_FOR_TRANSLATION_M:
        # position PD -> desired lateral acceleration (world frame),
        # with authority tapered inside the braking zone
        d_goal = math.hypot(goal[0] - x, goal[1] - y)
        a_lim = A_MAX * min(1.0, max(d_goal / BRAKE_ZONE_M, 0.35))
        ax = _clamp(KP_POS * (goal[0] - x) - KD_POS * vx, -a_lim, a_lim)
        ay = _clamp(KP_POS * (goal[1] - y) - KD_POS * vy, -a_lim, a_lim)
        # desired thrust direction (unit): tilt toward the acceleration
        g = 9.81
        n = math.sqrt(ax * ax + ay * ay + g * g)
        zdx, zdy, zdz = ax / n, ay / n, g / n
        # current body z-axis in world = R @ (0,0,1) = third column of R
        R = _rot_from_quat(update.world_pos)
        zbx, zby, zbz = R[0][2], R[1][2], R[2][2]
        # rotation needed: e = zb x zd (world), expressed in body frame
        ex = zby * zdz - zbz * zdy
        ey = zbz * zdx - zbx * zdz
        ez = zbx * zdy - zby * zdx
        ebx = R[0][0] * ex + R[1][0] * ey + R[2][0] * ez
        eby = R[0][1] * ex + R[1][1] * ey + R[2][1] * ez
        # acro sticks command body rates: +roll stick = +x rotation
        # (tilts right), +pitch stick = +y rotation (nose down / forward) —
        # signs match the upstream baseline's empirically working mapping
        gx = float(update.gyro[0]) if update.gyro.size > 0 else 0.0
        gy = float(update.gyro[1]) if update.gyro.size > 1 else 0.0
        roll = int(round(_clamp(1500.0 + KA_ATT * ebx - KD_RATE * gx,
                                1500 - STICK_CLAMP, 1500 + STICK_CLAMP)))
        pitch = int(round(_clamp(1500.0 + KA_ATT * eby - KD_RATE * gy,
                                 1500 - STICK_CLAMP, 1500 + STICK_CLAMP)))
        # point the nose (camera) along the direction of travel, aiming
        # at a lookahead target so a nearby waypoint never spins the nose
        aim = goal
        if d_goal < YAW_LOOKAHEAD_M and _state["wp"] + 1 < len(WAYPOINTS):
            aim = WAYPOINTS[_state["wp"] + 1]
        d_aim = math.hypot(aim[0] - x, aim[1] - y)
        if d_aim > YAW_HOLD_DIST_M:
            yaw_cur = math.atan2(R[1][0], R[0][0])
            yaw_des = math.atan2(aim[1] - y, aim[0] - x)
            yerr = (yaw_des - yaw_cur + math.pi) % (2 * math.pi) - math.pi
            # +stick = yaw right = world yaw DECREASES, hence the minus
            yaw_stick = int(round(_clamp(1500.0 - KYAW * yerr,
                                         1500 - YAW_CLAMP, 1500 + YAW_CLAMP)))
        if t - _state.get("dbg_t", 0.0) >= 1.0:
            _state["dbg_t"] = t
            print(f"[WP] t={t:5.1f} wp={_state['wp']:2d} "
                  f"goal=({goal[0]:+5.1f},{goal[1]:+5.1f},{goal[2]:.2f}) "
                  f"stk=({roll},{pitch},{throttle}) "
                  f"tilt_err=({ebx:+.2f},{eby:+.2f}) "
                  f"gyro=({gx:+6.2f},{gy:+6.2f})")

    return RCCommand(arm=1800, throttle=throttle, roll=roll, pitch=pitch,
                     yaw=yaw_stick)

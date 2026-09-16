#!/usr/bin/env python3
"""
Configure a fresh Betaflight SITL via its CLI on TCP port 5761.

Sets up the minimum config required for the AI Grand Prix sim:
  - AUX1 = ARM switch (1700-2100)
  - lockstep-friendly gyro/PID loop settings
  - Disable Betaflight's default 5s power-on arming grace
  - Disable arming-disable angle / runaway / takeoff prevention checks
    (we want a sim that arms cleanly from a known-good initial state)
  - Save to eeprom.bin

Run this once after building Betaflight SITL. The resulting eeprom.bin
gets committed so other contributors don't have to repeat this step.

Usage: uv run python scripts/configure_betaflight.py
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BF_BINARY = REPO_ROOT / "betaflight" / "obj" / "main" / "betaflight_SITL.elf"
EEPROM = REPO_ROOT / "eeprom.bin"

CLI_HOST = "127.0.0.1"
CLI_PORT = 5761

# Send these AFTER entering CLI mode. Each line is one command.
CLI_COMMANDS = [
    # Map AUX1 to the ARM mode (mode 0). Trigger when channel value is 1700-2100.
    "aux 0 0 0 1700 2100 0 0",
    # ANGLE mode on AUX2 high (1700-2100): the hardware control shape. A
    # solver that sends aux2=1500 (the default) still flies ACRO with body
    # rate sticks; one that sends aux2=1800 (AIGP_ANGLE_MODE=1 in
    # solvers.follower) gets the FC's own attitude loop with the sticks as
    # tilt angles, full stick = angle_limit.
    "aux 1 1 1 1700 2100 0 0",
    "set angle_limit = 80",
    # 1:1 PID denom for lockstep SITL
    "set gyro_hardware_lpf = NORMAL",
    "set pid_process_denom = 1",
    # The simulator already does bridge warmup before t=0; don't make users
    # wait through Betaflight's default 5 second power-on arming grace.
    "set pwr_on_arm_grace = 0",
    # Stop arming from being blocked when the drone is sitting on the ground.
    "set runaway_takeoff_prevention = OFF",
    "set small_angle = 180",
    # Don't fail on RX loss before we've sent RC packets
    "set failsafe_delay = 200",
    # --- SITL airframe taming (2026-08-27) ---------------------------------
    # The sim airframe (0.8 kg, inertia 0.0025, 8.6 N motors, 20 ms motor
    # lag) is far more torque-rich than a real 5". Stock rate PIDs limit-
    # cycle at ~10 Hz: motors slam min<->max, and with AIRMODE the mixer
    # keeps average thrust high enough that min throttle cannot descend.
    # Soften the rate loop and drop airmode so throttle authority returns.
    # --- Tune sprint (2026-08-28): raising the rate loop back toward stock
    # stepwise, re-measuring solvers.sysid_slew after each step. Wobble-era
    # values were 20/40/12 (yaw 25/45); stock is 45/80/30 (yaw 45/80).
    "feature -AIRMODE",
    # 30/55/20, NOT stock 45/80/30 (2026-08-29): stock rate PIDs churn the
    # motors so hard on this airframe that average output floors near hover
    # and throttle-down cannot descend (flown: z pinned at 1.9 m with
    # throttle commanded 1142-1188 vs hover 1240) - the original taming
    # comment above was right about that. Slew barely cares (measured 25.5
    # at 30/55/20 vs 27.8 at stock); descent authority matters more.
    # (2026-09-08 tried STOCK 45/80/30 for full aggression. 2026-09-09
    # race trace race_000.csv: z pinned at 1.9-2.0 m with the follower
    # commanding throttle 1062-1100 and 2.5-4 m/s^2 of thrust, while the
    # implied vertical thrust stayed 10-12 m/s^2 - the SAME collective
    # floor the note above describes. Descent authority comes from these
    # PIDs, not from the throttle loop. Aggression now comes from the RATE
    # PROFILE below, which is where the slew was measured to live.)
    # (2026-09-09 evening, slew_010-012): with the aerobatic rate map the
    # 30/55/20 rate loop is the slew limiter - every attitude step rotated
    # at 90-125 deg/s whatever the follower gain (120/250), the feedforward
    # smoothing or the rate map shape (super-expo vs linear). The 08-29
    # "slew barely cares about PIDs" was measured on STOCK rates, where the
    # map capped everything at ~25 m/s^3 first. Stock rate PIDs, feedforward
    # still OFF (that was the mixer-slamming term), airmode still off.
    "set p_roll = 45",
    "set i_roll = 80",
    "set d_roll = 30",
    "set p_pitch = 45",
    "set i_pitch = 80",
    "set d_pitch = 30",
    "set p_yaw = 45",
    "set i_yaw = 80",
    # Setpoint FEEDFORWARD OFF (2026-09-09, race_001.csv with motors
    # logged): the solver drives the sticks at 1 kHz from a gyro-damped
    # attitude loop, so the setpoint jitters +-50 PWM tick to tick and a
    # 96 PWM stick step slammed the mixer to idle/0.65 on the very NEXT
    # tick, before the gyro had moved - that is feedforward on the
    # setpoint derivative, not P or D. The clipped mixer then averages
    # ABOVE hover (m_mean 0.30-0.40 vs hover 0.26) and no throttle command
    # can descend (z froze at 1.77 m with -4 m/s^2 commanded). With the
    # sticks static the four motors were equal, so the plant itself is
    # fine. Rate PIDs 30/55/20 above are the tamed values from 08-29.
    # (2026-09-09 evening: feedforward ON with heavy setpoint smoothing was
    # tried and measured NO change in attitude slew - slew_011 vs slew_010,
    # 90% rise 0.36-0.58 s both - so it stays off; the slew limit was the
    # rate map below, not feedforward.)
    "set f_roll = 0",
    "set f_pitch = 0",
    "set f_yaw = 0",
    # I-TERM WINDUP LIMIT (2026-09-10, race_121.csv with all four motors
    # logged): in every banked turn the pitch (or roll) rate I-term sat
    # pinned at its default limit - a 0.40-0.47 motor mix with the sticks
    # within +-30 of centre - and the mixer, which fits the mix before the
    # throttle (throttle = min(throttle, 1 - mixMax)), paid for it out of
    # the collective: one motor at 1.00, mean 0.52 against a 0.70 throttle
    # command, 84% of the high-throttle ticks. The commanded 27 m/s^2
    # arrived as 23 and no climb into g10-top could be flown at speed.
    # iterm_windup is the I limit as a percent of pidsum_limit (default 80
    # -> 400 = 0.4 mix); 20 is the minimum -> 0.1 mix. Anti-gravity
    # (default gain 80) boosts I on throttle transients and is the other
    # I amplifier; off. P and D untouched. Verified backward compatible
    # by re-flying plan_L5_share10 with solvers.follower in the same batch.
    "set iterm_windup = 20",
    "set anti_gravity_gain = 0",
    # (2026-08-29) angle_limit/angle_p_gain sets removed: ANGLE mode was
    # never active (see aux note above) and sysid measured both knobs inert.
    # --- Rate profile (2026-09-08): the REAL slew sandbag. With stock rates
    # (~670 deg/s) sysid measured ~20 m/s^3 slew no matter the PIDs or
    # stick_clamp - because those set stability/authority, not max rotation
    # SPEED. Full stick on stock rates still only rolls at 670 deg/s. Push
    # rc_rate + super_rate toward aerobatic (~1200 deg/s) so the acro
    # airframe rotates like the footage. Re-measure slew after this.
    # (2026-09-09 evening, slew_010/011 + race_032): the super-expo map
    # above only delivers its ~1270 deg/s at FULL stick. The follower's
    # proportional attitude loop puts 50-250 PWM on the sticks, and there
    # the same map commands 30-200 deg/s: measured attitude rotation
    # 90-125 deg/s in every step regardless of amplitude or ka_att (120
    # or 250), thrust vector 0.5 s behind the plan, 2-3 m wide of g4.
    # LINEAR map instead (ACTUAL rates, centre sensitivity = max rate,
    # expo 0): the loop gain is then the same at every stick, 1000 deg/s
    # per full throw, 2 deg/s per PWM. Re-measured with sysid_slew.
    "set rates_type = ACTUAL",
    "set roll_rc_rate = 100",
    "set pitch_rc_rate = 100",
    "set yaw_rc_rate = 100",
    "set roll_srate = 100",
    "set pitch_srate = 100",
    "set yaw_srate = 100",
    "set roll_expo = 0",
    "set pitch_expo = 0",
    "set yaw_expo = 0",
    # Persist
    "save",
]


class CLIClient:
    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.create_connection((host, port), timeout=5.0)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = bytearray()
        self.lock = threading.Lock()
        self._stop = False
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        self.sock.settimeout(0.1)
        while not self._stop:
            try:
                data = self.sock.recv(8192)
                if not data:
                    return
                with self.lock:
                    self.buf.extend(data)
            except socket.timeout:
                continue
            except OSError:
                return

    def drain(self, seconds: float = 0.5) -> str:
        """Wait `seconds`, then snapshot the buffer."""
        time.sleep(seconds)
        with self.lock:
            out = bytes(self.buf).decode(errors="replace")
            self.buf.clear()
        return out

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def main() -> int:
    if not BF_BINARY.exists():
        print(f"ERROR: BF binary not found at {BF_BINARY}", file=sys.stderr)
        return 1

    subprocess.run(["pkill", "-9", "-f", "betaflight_SITL"], capture_output=True)
    time.sleep(0.5)

    # Keep any existing EEPROM as the base config. A completely fresh SITL
    # EEPROM can take a long time to initialize on some Betaflight builds, and
    # this script's job is to update/persist the few settings this simulator
    # needs rather than force a full flash-format cycle every run.

    import hashlib
    before = hashlib.md5(EEPROM.read_bytes()).hexdigest() if EEPROM.exists() else None
    print(f"Starting {BF_BINARY.name}...")
    bf_log = open("/tmp/bf-configure.log", "w")
    bf = subprocess.Popen(
        [str(BF_BINARY)],
        stdout=bf_log,
        stderr=subprocess.STDOUT,
        cwd=str(REPO_ROOT),
    )

    cli: CLIClient | None = None
    try:
        # First boot after a clean build can spend a while initializing EEPROM
        # before the MSP/CLI TCP listener appears.
        deadline = time.time() + 120.0
        while time.time() < deadline:
            try:
                cli = CLIClient(CLI_HOST, CLI_PORT)
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.2)
        if cli is None:
            print("ERROR: CLI port did not open before the deadline", file=sys.stderr)
            return 2

        # 1) wake the line discipline; 2) enter CLI mode; 3) issue each command
        print("Entering CLI mode...")
        cli.send(b"\r")
        time.sleep(0.5)
        cli.send(b"#")
        banner = cli.drain(2.0)
        if "Entering CLI Mode" not in banner:
            print("WARNING: did not see CLI banner. Got:")
            print(repr(banner))
        else:
            print(banner.split("\r\n")[0])

        for cmd in CLI_COMMANDS:
            print(f"\n> {cmd}")
            cli.send((cmd + "\r\n").encode())
            wait = 5.0 if cmd == "save" else 0.5
            print(cli.drain(wait), end="")

        cli.close()

        # save() reboots BF; give it time to flush
        time.sleep(2.0)

    finally:
        if bf.poll() is None:
            try:
                os.kill(bf.pid, signal.SIGTERM)
                bf.wait(timeout=3.0)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.kill(bf.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        bf_log.close()

    if EEPROM.exists():
        sz = EEPROM.stat().st_size
        after = hashlib.md5(EEPROM.read_bytes()).hexdigest()
        if before is not None and after == before:
            print(f"\nWARNING: {EEPROM} unchanged by save ({sz} bytes) - the CLI settings applied live but did not persist")
        else:
            print(f"\nOK: wrote {EEPROM} ({sz} bytes)")
        return 0
    print(f"ERROR: {EEPROM} was not created", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())

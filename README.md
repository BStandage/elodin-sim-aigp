# AI Grand Prix Practice Sim — PQ fork

Fork of [elodin-sys/ai-grand-prix](https://github.com/elodin-sys/ai-grand-prix)
carrying our September Physical Qualifier course and fixes. What's
different from upstream:

- **The extracted PQ course** replaces the 3-gate demo: 12 gates (incl.
  the stacked double gate flown as an out-and-back), ordered 2-lap
  scoring with machine-readable race records. Loaded from the
  `AI-GrandPrix` repo's course map — no positions hardcoded here.
- **Sensor-feed fixes**: the FDM gyro/accel frame conversions upstream
  ships are wrong for `ENABLE_GAZEBO_BRIDGE` builds (inverted yaw rate,
  inverted gravity — Betaflight's attitude estimator thought the quad was
  upside-down). Fixed in `sim/sensors.py`.
- **A reference pilot** (`solver/pq_waypoints.py`) that completes the
  full 2-lap course 24/24 with the FPV camera flying nose-first.
- **`run_race.cmd`** — double-click to race (starts the sim in WSL,
  opens the Windows editor at the right moment).

<p align="center">
  <img src="./drone_race_preview.gif" alt="AI Grand Prix demo flight" width="720">
</p>

## Setup

**You need TWO repos side by side** — this one and
[`AI-GrandPrix`](../AI-GrandPrix) (the course map, its loader, and the
perception codebase live there):

```text
GitRepos/
├── AI-GrandPrix/        <- course map + loader (+ your perception work)
└── elodin-sim-aigp/     <- this repo
```

### Windows (the common case)

1. **Install WSL** — admin PowerShell: `wsl --install`, reboot, set a
   Linux username/password. If WSL is already installed, check
   `wsl uname -r`: anything below **5.10** must be updated
   (`wsl --update --web-download` then `wsl --shutdown`, as admin) or the
   sim dies at startup with an io_uring panic.
2. **One apt line** — in WSL:
   ```bash
   sudo apt update && sudo apt install -y build-essential libasound2t64 git curl
   ```
3. **Everything else is scripted** — in WSL, from this repo:
   ```bash
   bash scripts/setup_wsl.sh
   ```
   Installs uv + the Python env (pinned to 3.13 — elodin breaks on 3.14),
   the Elodin CLI, fetches and builds Betaflight SITL, checks for the
   companion repo, and finishes by running the test suite. Re-run it any
   time as an environment health check.
4. **Windows-side editor** (one-time, PowerShell):
   ```powershell
   [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
   $dst = "$env:LOCALAPPDATA\Programs\elodin"; New-Item -ItemType Directory -Force $dst
   Invoke-WebRequest https://github.com/elodin-sys/elodin/releases/download/v0.17.3/elodin-x86_64-pc-windows-msvc.zip -OutFile $env:TEMP\elodin.zip -UseBasicParsing
   Expand-Archive $env:TEMP\elodin.zip -DestinationPath $dst -Force
   ```
   **Windows 10 only:** the editor crashes on a missing Windows 11 font.
   Download the free pack from https://aka.ms/SegoeFluentIcons, extract,
   then as admin:
   `Copy-Item ".\Segoe Fluent Icons.ttf" "C:\Windows\Fonts\SegoeIcons.ttf"`

### macOS / native Linux

No WSL layer — follow upstream's short path: the apt/xcode line, `uv`,
`bash scripts/install_elodin.sh`, `uv sync`,
`bash scripts/fetch_betaflight.sh && bash scripts/build_betaflight.sh`,
then `elodin editor sim/main.py` directly.

## Racing

**Double-click `run_race.cmd`.** It cleans stale processes, starts the
sim in a WSL window, waits for the render server, and opens the editor
connected to the WSL VM's IP (Windows' localhost relay to WSL is flaky —
if connecting by hand, use `wsl hostname -I` instead of 127.0.0.1).

Manual equivalent:

```bash
# WSL terminal — run the race headless
RACE_SOLVER=solver.pq_waypoints uv run -- elodin run sim/main.py
```
```powershell
# PowerShell — watch it live
& "$env:LOCALAPPDATA\Programs\elodin\elodin.exe" editor <wsl-ip>:2240
```

Healthy output ends like:

```text
[GATE] lap 1 g10-low (event 23) at t=225.30s z_opening=1.35 ...
[RACE] course=course_map.json (estimated_from_overhead_image) laps=2
       gates_passed=24/24 total_time=225.30s lap_times=[114.70,110.60]
       status=COMPLETE near_misses=0
[RACE] run record -> race_result_000.json
```

The `m betaflight` line `git status` shows after building is expected
(the build script toggles lockstep in the submodule) — don't commit it.

## Writing your solver

One function: `autopilot(update: SensorUpdate) -> RCCommand` — the
contract is in [`solver/README.md`](solver/README.md). Select yours with:

```bash
RACE_SOLVER=my_module uv run -- elodin run sim/main.py
```

Modules under `AI-GrandPrix/src` are importable too (the sim puts that
tree on `sys.path`), so a solver can live in the main repo:
`RACE_SOLVER=pilots.my_pilot`. Start from `solver/pq_waypoints.py` — and
note `last_gate_passed` / `next_gate_index` are **crossing-event indices**
(0–23 over 2 laps; the stacked gate is two events per lap).
`solver/diag_steps.py` is a plant-measurement pilot (hover + stick step
responses) — useful before trusting any new control code.

## Inspecting a run

Each run writes `race_result_###.json` (per-event times, lap times,
near-misses) and an auto-numbered `betaflight_db###` database:

```bash
elodin-db export betaflight_db000 --format csv --flatten --join -o dbs/db000-csv
elodin-db export-videos betaflight_db000 -o db000-video   # FPV as video
```

## Tests

```bash
uv run pytest                          # full suite (49)
python tests/test_pq_course.py         # course/tracker only, no elodin needed
uv run python scripts/smoke_world.py   # world construction, no Betaflight
uv run python scripts/render_pq_course.py  # top-down course render -> out/
```

## Going deeper

- `AI-GrandPrix/docs/ELODIN_SIM_SETUP.md` — the long-form setup
  walkthrough with every failure mode we hit and its fix.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — upstream's design doc (lockstep
  cycle, frames, schematic). Still accurate apart from the course.
- [`solver/README.md`](solver/README.md) — the autopilot contract.

## Acknowledgements

Forked from [`elodin-sys/ai-grand-prix`](https://github.com/elodin-sys/ai-grand-prix),
itself built on the Elodin examples. Not affiliated with Anduril, DCL,
Neros, or JobsOhio.

## License

[Apache 2.0](LICENSE), same as upstream.

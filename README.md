# AI Grand Prix Practice Sim (PQ fork)

Fork of [elodin-sys/ai-grand-prix](https://github.com/elodin-sys/ai-grand-prix)
carrying our September Physical Qualifier course and fixes. What's
different from upstream:

- **The extracted PQ course** replaces the 3-gate demo: 12 gates (incl.
  the stacked double gate flown as an out-and-back), ordered 2-lap
  scoring with machine-readable race records. Loaded from the
  `AI-GrandPrix` repo's course map. No positions are hardcoded here.
- **Sensor-feed fixes**: the FDM gyro/accel frame conversions upstream
  ships are wrong for `ENABLE_GAZEBO_BRIDGE` builds (inverted yaw rate,
  inverted gravity, so Betaflight's attitude estimator thought the quad was
  upside-down). Fixed in `sim/sensors.py`.
- **A reference pilot** (`solver/pq_waypoints.py`) that completes the
  full 2-lap course 24/24 with the FPV camera flying nose-first.
- **Double-click to race**: `run_race_docker.cmd` (containerized, any
  platform) or `run_race.cmd` (native WSL). Each starts the sim and
  opens the editor on it at the right moment.

<p align="center">
  <img src="./drone_race_preview.gif" alt="AI Grand Prix demo flight" width="720">
</p>

## Setup

**You need TWO repos side by side**: this one and
[`AI-GrandPrix`](../AI-GrandPrix) (the course map, its loader, and the
perception codebase live there):

```text
GitRepos/
├── AI-GrandPrix/        <- course map + loader
└── elodin-sim-aigp/     <- this repo
```

### Docker (recommended, any platform)

The whole Linux half of the setup (toolchain, Elodin CLI, Python env,
Betaflight SITL build) lives in one container. No WSL, no apt, no uv,
no Betaflight build by hand.

**Fresh machine, start to finish:**

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/),
   launch it once, accept the license.
2. Install [Git LFS](https://git-lfs.com), then `git lfs install`. The
   `.glb` models are LFS-backed. Without it the editor shows no drone
   and no gates.
3. Clone **both** repos side by side (layout above).
4. Race: double-click `run_race_docker.cmd` (Windows) or run
   `./run_race_docker.sh` (macOS/Linux).

That's it. The launcher preflights the rest and stops with a fix-it
message if anything is missing. It also downloads the native Elodin
editor on first run. Budget ~10 minutes the first time (image + SITL
build); after that it starts in seconds.

Both launchers take an optional solver module:
`run_race_docker.cmd solver.pq_waypoints`. On macOS,
`cp run_race_docker.sh run_race_docker.command` makes it double-clickable
too.

Manual equivalents:

```bash
docker compose up --build          # headless race (builds SITL on first run)
docker compose run --rm sim bash   # shell in the environment (uv run pytest, etc.)
elodin editor localhost:2240       # native editor, attach to a running sim
```

Docker publishes 2240 on localhost, so there's no WSL-IP dance. Race
knobs pass through:
`RACE_SOLVER=solver.baseline AIGP_SIM_TIME=60 docker compose up`. Run
artifacts (`race_result_###.json`, `betaflight_db###`) land in the repo
on the host as usual. A `.devcontainer/` is included for opening the
repo in VS Code with everything wired up.

Notes:
- The container runs `seccomp:unconfined` because Elodin needs
  io_uring, which Docker's default seccomp profile blocks.
- **Apple Silicon:** Elodin ships x86_64 Linux binaries only, so the
  image runs emulated. In Docker Desktop enable *Settings → Use Rosetta
  for x86_64/amd64 emulation* first; expect slower-than-realtime sims.
- **Windows 10:** the editor needs the SegoeIcons font or it crashes;
  the launcher warns with the fix (see step 4 of the WSL setup).
- **FPV camera: unconfirmed in the container.** A headless container run
  reported `FPV frames: 0`. It is not yet established whether that is a
  software-rendering limitation (no GPU) or simply what headless
  `elodin run` does with no editor attached. The WSL path has not been
  measured for comparison. Physics, Betaflight lockstep and gate scoring
  are unaffected. Vision-based solvers are unverified in the container
  until this is measured.

### Windows + WSL (native, no Docker)

1. **Install WSL**: admin PowerShell: `wsl --install`, reboot, set a
   Linux username/password. If WSL is already installed, check
   `wsl uname -r`: anything below **5.10** must be updated
   (`wsl --update --web-download` then `wsl --shutdown`, as admin) or the
   sim dies at startup with an io_uring panic.
2. **One apt line**, in WSL:
   ```bash
   sudo apt update && sudo apt install -y build-essential libasound2t64 git curl
   ```
3. **Everything else is scripted**, in WSL, from this repo:
   ```bash
   bash scripts/setup_wsl.sh
   ```
   Installs uv + the Python env (pinned to 3.13; elodin breaks on 3.14),
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

Use the Docker path above - on a Mac it is the supported route (one
install, no toolchain), and the native editor still attaches at
localhost:2240 for watching.

Native setup on macOS/Linux is possible but is the advanced path: the
apt/xcode line, `uv`, `bash scripts/install_elodin.sh`, `uv sync`,
`bash scripts/fetch_betaflight.sh && bash scripts/build_betaflight.sh`,
then `elodin editor sim/main.py`. If `build_betaflight.sh` fails on your
machine, that is the signal to use Docker, not a bug in your clone -
every `... elodin run sim/main.py` command in this README assumes this
full native build exists.

## Racing

**Double-click `run_race_docker.cmd`** (or `./run_race_docker.sh` on
macOS/Linux). It tears down any previous container, starts the sim,
waits for the render server, and opens the native editor on it.

On the native WSL setup use `run_race.cmd` instead: same flow, WSL
instead of a container. It connects to the WSL VM's IP because Windows'
localhost relay to WSL is flaky (connecting by hand, use
`wsl hostname -I`, not 127.0.0.1).

Manual equivalent (needs the full native/WSL setup - with Docker only,
use `docker compose up` instead):

```bash
# WSL terminal: run the race headless
RACE_SOLVER=solvers.follower uv run -- elodin run sim/main.py
```
```powershell
# PowerShell: watch it live
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
(the build script toggles lockstep in the submodule). Don't commit it.

## Writing your solver

One function: `autopilot(update: SensorUpdate) -> RCCommand`. The
contract is in [`solver/README.md`](solver/README.md). Select yours with:

```bash
RACE_SOLVER=my_module uv run -- elodin run sim/main.py
```

Modules under `AI-GrandPrix/src` are importable too (the sim puts that
tree on `sys.path`), so a solver can live in the main repo:
`RACE_SOLVER=pilots.my_pilot`. Start from `solver/pq_waypoints.py`, and
note `last_gate_passed` / `next_gate_index` are **crossing-event indices**
(0–23 over 2 laps; the stacked gate is two events per lap).
`solver/diag_steps.py` is a plant-measurement pilot (hover + stick step
responses). Useful before trusting any new control code.

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

- `AI-GrandPrix/docs/ELODIN_SIM_SETUP.md`: the long-form setup
  walkthrough with every failure mode we hit and its fix.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): upstream's design doc (lockstep
  cycle, frames, schematic). Still accurate apart from the course.
- [`solver/README.md`](solver/README.md): the autopilot contract.

## Acknowledgements

Forked from [`elodin-sys/ai-grand-prix`](https://github.com/elodin-sys/ai-grand-prix),
itself built on the Elodin examples. Not affiliated with Anduril, DCL,
Neros, or JobsOhio.

## License

[Apache 2.0](LICENSE), same as upstream.

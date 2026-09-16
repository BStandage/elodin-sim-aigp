#!/usr/bin/env bash
# Container entrypoint: the runtime half of scripts/setup_wsl.sh.
# Idempotent — finishes whatever the image can't bake in (the mounted
# repo's Python env, the Betaflight SITL build), then execs the command.
set -euo pipefail

REPO=/work/elodin-sim-aigp
cd "$REPO"

if [ ! -f pyproject.toml ]; then
    echo "FATAL: repo not mounted at $REPO." >&2
    echo "Run via docker compose from the repo root (it mounts the repo in)." >&2
    exit 1
fi

# The mounts belong to the host user; git inside the container refuses to
# touch them without this.
git config --global --add safe.directory '*' 2>/dev/null || true

echo "==> Syncing Python environment"
uv sync

if [ ! -f "${AIGP_REPO}/data/course_map.json" ]; then
    echo "FATAL: AI-GrandPrix repo not found at ${AIGP_REPO}." >&2
    echo "Clone it as a sibling of this repo on the HOST:" >&2
    echo "    GitRepos/" >&2
    echo "    +-- AI-GrandPrix/       <- course map + loader" >&2
    echo "    +-- elodin-sim-aigp/    <- this repo" >&2
    echo "(docker-compose.yml mounts ../AI-GrandPrix into the container)" >&2
    exit 1
fi

ELF=betaflight/obj/main/betaflight_SITL.elf
if [ ! -f "$ELF" ]; then
    if [ ! -f betaflight/Makefile ]; then
        echo "==> Initializing Betaflight submodule"
        bash scripts/fetch_betaflight.sh || {
            echo "FATAL: could not init the betaflight submodule from inside the container." >&2
            echo "Run on the HOST from the repo root:" >&2
            echo "    git submodule update --init --recursive --depth 1 betaflight" >&2
            exit 1
        }
    fi
    echo "==> Building Betaflight SITL (one-time; a few minutes)"
    bash scripts/build_betaflight.sh
fi

# Betaflight boots from the persisted eeprom.bin, and configure_betaflight.py
# was a MANUAL step nobody ran (the drone flew a stock eeprom for weeks).
# Regenerate it whenever the script is newer than the eeprom, so editing
# the tune and clicking run_race_docker.cmd is enough.
# Regenerate when the SCRIPT CONTENT changed (sha recorded next to the
# eeprom after a successful run). The old mtime test regenerated on
# every launch: on a Docker Desktop bind mount the SITL's eeprom write
# never updated the host-visible mtime, so eeprom.bin always looked
# older than the script (2026-09-09).
CFG_SHA=$(sha1sum scripts/configure_betaflight.py | cut -c1-40)
OLD_SHA=$(cat eeprom.bin.src-sha 2>/dev/null || true)
if [ "${AIGP_SKIP_BF_CONFIG:-}" != "1" ] && { [ ! -f eeprom.bin ] || [ "$CFG_SHA" != "$OLD_SHA" ]; }; then
    echo "==> eeprom.bin is missing or older than scripts/configure_betaflight.py - regenerating"
    uv run python scripts/configure_betaflight.py && echo "$CFG_SHA" > eeprom.bin.src-sha
fi

# Mirror run_race.cmd: hand plan-following solvers the newest racing-line
# plan from the companion repo, if any exist. Harmless for other solvers.
# The follower must also fly the SAME vehicle.toml the plan was built with
# (a hot plan under conservative clamps corner-cuts and crashes), so the
# toml comes out of the plan's config_path field.
# Pinned plan first (plan_RACE.json, what run_race.cmd/launch_race.sh
# fly), else the newest plan_*.json. Laps come from the plan unless the
# caller set AIGP_LAPS (docker-compose passes it through empty otherwise).
T="${AIGP_TRAJ:-}"
if [ -z "$T" ]; then
    T="${AIGP_REPO}/out/plans/plan_RACE.json"
    [ -f "$T" ] || T=$(ls -t "${AIGP_REPO}"/out/plans/plan_*.json 2>/dev/null | head -1 || true)
    [ -n "$T" ] && export AIGP_TRAJ="$T"
fi
if [ -n "$T" ] && [ -f "$T" ]; then
    echo "==> Using plan: $T"
    if [ -z "${AIGP_LAPS:-}" ]; then
        L=$(grep -o '"laps": [0-9]*' "$T" | head -1 | grep -o '[0-9]*' || true)
        export AIGP_LAPS="${L:-2}"
    fi
    echo "==> Laps: $AIGP_LAPS"
    if [ -z "${AIGP_VEHICLE_TOML:-}" ]; then
        B=$(grep -o '"config_path": "[^"]*"' "$T" | cut -d'"' -f4 || true)
        B="${B//\\//}"        # Windows backslashes -> forward slashes
        if [ -n "$B" ] && [ -f "${AIGP_REPO}/${B}" ]; then
            export AIGP_VEHICLE_TOML="${AIGP_REPO}/${B}"      # repo-relative config_path (config/ladder/... included)
        elif [ -n "$B" ] && [ -f "${AIGP_REPO}/config/${B##*/}" ]; then
            export AIGP_VEHICLE_TOML="${AIGP_REPO}/config/${B##*/}"
        else
            export AIGP_VEHICLE_TOML="${AIGP_REPO}/config/vehicle.toml"
        fi
    fi
fi
[ -z "${AIGP_VEHICLE_TOML:-}" ] && export AIGP_VEHICLE_TOML="${AIGP_REPO}/config/vehicle.toml"
echo "==> Using toml: $AIGP_VEHICLE_TOML"
export AIGP_LAPS="${AIGP_LAPS:-2}"

exec "$@"

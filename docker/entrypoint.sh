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

# Mirror run_race.cmd: hand plan-following solvers the newest racing-line
# plan from the companion repo, if any exist. Harmless for other solvers.
# The follower must also fly the SAME vehicle.toml the plan was built with
# (a hot plan under conservative clamps corner-cuts and crashes), so the
# toml comes out of the plan's config_path field.
if [ -z "${AIGP_TRAJ:-}" ]; then
    T=$(ls -t "${AIGP_REPO}"/out/plans/plan_*.json 2>/dev/null | head -1 || true)
    if [ -n "$T" ]; then
        export AIGP_TRAJ="$T"
        echo "==> Using plan: $T"
        if [ -z "${AIGP_VEHICLE_TOML:-}" ]; then
            B=$(grep -o '"config_path": "[^"]*"' "$T" | cut -d'"' -f4 || true)
            if [ -n "$B" ]; then
                export AIGP_VEHICLE_TOML="${AIGP_REPO}/config/$(basename "$B")"
                echo "==> Using toml: $AIGP_VEHICLE_TOML"
            fi
        fi
    fi
fi

exec "$@"

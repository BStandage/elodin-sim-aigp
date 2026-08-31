#!/usr/bin/env bash
# PQ Race launcher - Docker edition, macOS/Linux.
#
#   1. tears down any previous container
#   2. starts the sim (Betaflight + physics + solver) in a container
#   3. waits for the render server, then opens the native Elodin editor
#
# The macOS/Linux counterpart of run_race_docker.cmd. The sim runs in
# Docker; the EDITOR runs natively on your machine (install it with
# `bash scripts/install_elodin.sh` if you haven't).
#
#   ./run_race_docker.sh                  # default solver
#   ./run_race_docker.sh solver.baseline  # pick a solver
#
# macOS tip: `cp run_race_docker.sh run_race_docker.command` gives you a
# double-clickable version, same as run_race.cmd on Windows.
set -uo pipefail

cd "$(dirname "$0")"

SOLVER="${1:-solvers.follower}"

# ---- preflight: fail fast, BEFORE the 10-minute first build --------------
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker not found on PATH."
    echo "Install Docker Desktop, launch it once, then re-run this script."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is installed but not running."
    echo "Launch Docker Desktop, wait for it to finish starting, then re-run."
    exit 1
fi

# The sim loads the course map from the companion repo; without it the
# container starts, syncs, and only then dies.
if [ ! -f ../AI-GrandPrix/data/course_map.json ]; then
    echo "ERROR: the AI-GrandPrix repo is missing."
    echo "It must sit next to this one:"
    echo "    GitRepos/AI-GrandPrix/      <- course map + loader"
    echo "    GitRepos/elodin-sim-aigp/   <- this repo"
    echo "Clone it, then re-run."
    exit 1
fi

# assets/*.glb are Git LFS. Cloned without git-lfs they are ~130-byte text
# pointers and the editor renders no drone or gates.
GLB=assets/crazyflie.glb
if [ ! -f "$GLB" ] || [ "$(wc -c < "$GLB")" -lt 2000 ]; then
    echo "ERROR: $GLB is a Git LFS pointer, not the real model."
    echo "Install Git LFS (https://git-lfs.com), then from this folder run:"
    echo "    git lfs install"
    echo "    git lfs pull"
    exit 1
fi

# Editor: install it automatically rather than failing after the build.
EDITOR_BIN="$(command -v elodin || true)"
[ -z "$EDITOR_BIN" ] && [ -x "$HOME/.cargo/bin/elodin" ] && EDITOR_BIN="$HOME/.cargo/bin/elodin"
if [ -z "$EDITOR_BIN" ]; then
    echo "The Elodin editor is not installed - installing it now (~1 min)..."
    bash scripts/install_elodin.sh || true
    [ -x "$HOME/.cargo/bin/elodin" ] && EDITOR_BIN="$HOME/.cargo/bin/elodin"
fi
if [ -z "$EDITOR_BIN" ]; then
    echo "WARNING: still no native 'elodin' editor. Install it by hand:"
    echo "    bash scripts/install_elodin.sh"
    echo "Continuing headless - the race still runs, you just won't see it."
fi

echo "Cleaning up any previous run..."
docker compose down --remove-orphans >/dev/null 2>&1 || true

echo "Starting sim (RACE_SOLVER=$SOLVER) in Docker..."
echo "(first run also builds the image and Betaflight SITL - can take 10+ min)"
RACE_SOLVER="$SOLVER" docker compose up --build &
COMPOSE_PID=$!

cleanup() {
    echo
    echo "Stopping the sim..."
    docker compose down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# Docker publishes 2240 on localhost - no VM-IP dance needed.
echo "Waiting for the render server on localhost:2240 ..."
tries=0
until (echo > /dev/tcp/127.0.0.1/2240) >/dev/null 2>&1; do
    # If compose died (build error, crash), stop waiting.
    if ! kill -0 "$COMPOSE_PID" 2>/dev/null; then
        echo "The sim exited before the render server came up - see the log above."
        exit 1
    fi
    tries=$((tries + 1))
    if [ $((tries % 30)) -eq 0 ]; then
        echo "  ... still waiting (${tries}s)"
    fi
    if [ "$tries" -ge 1200 ]; then
        echo "Gave up after ~20 minutes. See the log above for errors."
        exit 1
    fi
    sleep 1
done

if [ -n "$EDITOR_BIN" ]; then
    echo "Render server is up - opening the editor at localhost:2240 ..."
    "$EDITOR_BIN" editor 127.0.0.1:2240
else
    echo "Render server is up. Race running; Ctrl-C to stop."
    wait "$COMPOSE_PID"
fi

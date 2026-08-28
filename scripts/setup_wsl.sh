#!/usr/bin/env bash
# One-shot environment bootstrap for this fork (run inside WSL/Ubuntu from
# the repo root). Idempotent: safe to re-run, and doubles as an
# "is my environment broken?" checker because it ends with the test suite.
#
#   bash scripts/setup_wsl.sh
#
# Prerequisites it can NOT do for you (each prints a clear message):
#   - WSL itself (admin PowerShell: wsl --install) with kernel >= 5.10
#   - the one sudo apt line below
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
FAIL=0

step() { echo; echo "==> $*"; }

# --- 0. kernel check (Elodin needs io_uring: kernel >= 5.10) ---------------
step "Checking WSL kernel"
KERNEL=$(uname -r)
KMAJOR=${KERNEL%%.*}
if [ "$KMAJOR" -lt 5 ]; then
    echo "FATAL: kernel $KERNEL is too old (Elodin needs io_uring, kernel >= 5.10)."
    echo "Fix in an ADMIN PowerShell on Windows:"
    echo "    wsl --update --web-download"
    echo "    wsl --shutdown"
    exit 1
fi
echo "kernel $KERNEL OK"

# --- 1. apt packages -------------------------------------------------------
step "Checking apt packages"
MISSING=""
command -v gcc >/dev/null || MISSING="$MISSING build-essential"
command -v git >/dev/null || MISSING="$MISSING git"
command -v curl >/dev/null || MISSING="$MISSING curl"
ldconfig -p 2>/dev/null | grep -q libasound.so.2 || MISSING="$MISSING libasound2t64"
if [ -n "$MISSING" ]; then
    echo "FATAL: missing packages. Run this (needs your sudo password):"
    echo "    sudo apt update && sudo apt install -y$MISSING"
    exit 1
fi
echo "all present"

# --- 2. uv -----------------------------------------------------------------
step "Checking uv"
UV="$HOME/.local/bin/uv"
if [ ! -x "$UV" ]; then
    echo "installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
"$UV" --version

# --- 3. Python env (pinned to 3.13 via .python-version — do not remove:
#        elodin 0.17.x fails every world.spawn under Python 3.14) ----------
step "Syncing Python environment"
"$UV" sync

# --- 4. Elodin CLI ---------------------------------------------------------
step "Checking Elodin CLI"
ELODIN="$HOME/.cargo/bin/elodin"
if [ ! -x "$ELODIN" ]; then
    bash scripts/install_elodin.sh
fi
"$ELODIN" --version || true   # first invocation prints a welcome banner
grep -q 'cargo/bin' "$HOME/.bashrc" || \
    echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> "$HOME/.bashrc"

# --- 5. Betaflight SITL ----------------------------------------------------
step "Checking Betaflight SITL"
ELF="betaflight/obj/main/betaflight_SITL.elf"
if [ ! -f "$ELF" ]; then
    bash scripts/fetch_betaflight.sh
    bash scripts/build_betaflight.sh
else
    echo "already built: $ELF"
fi

# --- 6. companion repo (course map + loader) -------------------------------
step "Checking AI-GrandPrix companion repo"
AIGP="${AIGP_REPO:-$REPO/../AI-GrandPrix}"
if [ -f "$AIGP/data/course_map.json" ]; then
    echo "found: $AIGP"
else
    echo "WARNING: AI-GrandPrix repo not found at $AIGP"
    echo "Clone it as a sibling of this repo (or set AIGP_REPO)."
    echo "The sim loads the course map from it and will not start without it."
    FAIL=1
fi

# --- 7. verify -------------------------------------------------------------
step "Running the test suite"
"$UV" run pytest

step "Done"
echo "Environment ready. Remaining Windows-side steps (see README):"
echo "  1. Extract the Elodin editor zip to %LOCALAPPDATA%\\Programs\\elodin"
echo "  2. Windows 10 only: install the SegoeIcons font (README gotcha)"
echo "  3. Daily driver: double-click run_race.cmd"
exit $FAIL

#!/bin/bash
# Invoked by run_race.cmd inside WSL. $1 = solver module (default follower).
# Picks the newest plan in AI-GrandPrix/out/plans and exports BOTH the plan
# and the vehicle.toml it was built with (mismatched clamps corner-cut).
cd "$(dirname "$0")/.." || exit 1

# Pinned plan on disk (written by the planner on the host). Do not
# rebuild here — that delayed 2240 and the editor attached to a dead sim.
AIGP="$(cd ../AI-GrandPrix && pwd)"
T="${AIGP}/out/plans/plan_RACE.json"
[ -f "$T" ] || T=$(ls -t "${AIGP}"/out/plans/plan_*.json 2>/dev/null | head -1)
if [ -n "$T" ]; then
    export AIGP_TRAJ="$T"
    echo "Using plan: $T"
    if [ -z "${AIGP_LAPS:-}" ]; then
        L=$(grep -o '"laps": [0-9]*' "$T" | head -1 | grep -o '[0-9]*' || true)
        export AIGP_LAPS="${L:-2}"
    fi
    echo "Laps: $AIGP_LAPS"
    B=$(grep -o '"config_path": "[^"]*"' "$T" | cut -d'"' -f4)
    B="${B//\\//}"
    B="${B##*/}"
    if [ -n "$B" ]; then
        export AIGP_VEHICLE_TOML="${AIGP}/config/${B}"
    else
        export AIGP_VEHICLE_TOML="${AIGP}/config/dev_hot.toml"
    fi
    echo "Using toml: $AIGP_VEHICLE_TOML"
fi

RACE_SOLVER="${1:-solvers.follower}" ~/.local/bin/uv run -- ~/.cargo/bin/elodin run sim/main.py
echo
echo "--- run ended, press Enter to close ---"
read -r _

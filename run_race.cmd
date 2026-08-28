@echo off
REM ==================================================================
REM  PQ Race launcher (double-clickable)
REM   1. kills any stale sim processes in WSL
REM   2. starts the sim (Betaflight + physics + solver) in a WSL window
REM   3. waits for the render server, then opens the Elodin editor
REM
REM  Optional argument: solver module (default: solver.pq_waypoints)
REM    run_race.cmd solver.baseline
REM ==================================================================
setlocal
cd /d "%~dp0"
set "SOLVER=%~1"
if "%SOLVER%"=="" set "SOLVER=solver.pq_waypoints"

echo Cleaning up any previous run...
wsl -e bash -lc "pkill -f betaflight_SITL; pkill -f render-server; pkill -f 'elodin run'; true" >nul 2>&1
timeout /t 1 /nobreak >nul

echo Starting sim (RACE_SOLVER=%SOLVER%) in a WSL window...
REM raceline.follower needs a plan (AIGP_TRAJ): hand it the newest one from
REM the AI-GrandPrix repo, if any exist. Harmless for other solvers.
start "PQ race sim" wsl -e bash -lc "cd $(wslpath -a '%~dp0') && T=$(ls -t $(wslpath -a '%~dp0')../AI-GrandPrix/out/plans/plan_*.json 2>/dev/null | head -1); [ -n \"$T\" ] && export AIGP_TRAJ=\"$T\" && echo Using plan: $T; RACE_SOLVER=%SOLVER% ~/.local/bin/uv run -- ~/.cargo/bin/elodin run sim/main.py; echo; echo --- run ended, press Enter to close ---; read _"

REM Windows' localhost->WSL relay is flaky; talk to the WSL VM's IP directly.
for /f "tokens=1" %%i in ('wsl hostname -I') do set "WSLIP=%%i"
if "%WSLIP%"=="" set "WSLIP=127.0.0.1"

echo Waiting for the render server on %WSLIP%:2240 ...
set /a tries=0
:wait
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try { $c.Connect('%WSLIP%',2240); exit 0 } catch { exit 1 } finally { $c.Close() }" >nul 2>&1
if %errorlevel%==0 goto ready
set /a tries+=1
if %tries% geq 120 (
  echo Gave up after ~2 minutes. Check the sim window for errors.
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait

:ready
echo Render server is up - opening the editor at %WSLIP%:2240 ...
"%LOCALAPPDATA%\Programs\elodin\elodin.exe" editor %WSLIP%:2240
endlocal

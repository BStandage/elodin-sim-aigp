@echo off
REM ==================================================================
REM  PQ Race launcher (double-clickable)
REM   1. kills any stale sim processes in WSL
REM   2. starts the sim (Betaflight + physics + solver) in a WSL window
REM   3. waits for the render server, then opens the Elodin editor
REM
REM  Optional argument: solver module (default: solvers.follower, the
REM  racing-line stack; it flies the newest plan in AI-GrandPrix/out/plans)
REM    run_race.cmd solver.pq_waypoints   (the old stop-and-center pilot)
REM ==================================================================
setlocal
cd /d "%~dp0"
set "SOLVER=%~1"
if "%SOLVER%"=="" set "SOLVER=solvers.follower"

echo Cleaning up any previous run...
wsl -e bash -lc "pkill -f betaflight_SITL; pkill -f render-server; pkill -f 'elodin run'; true" >nul 2>&1
timeout /t 1 /nobreak >nul

echo Starting sim (RACE_SOLVER=%SOLVER%) in a WSL window...
REM All plan/toml/env logic lives in scripts/launch_race.sh (quoting bash
REM inside a batch string breaks cmd's parser - been there).
start "PQ race sim" wsl -e bash -lc "bash $(wslpath -a '%~dp0')scripts/launch_race.sh %SOLVER%"

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

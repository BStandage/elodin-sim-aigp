@echo off
REM ==================================================================
REM  PQ Race launcher - Docker edition (double-clickable)
REM   1. tears down any previous container
REM   2. starts the sim (Betaflight + physics + solver) in a container
REM   3. waits for the render server, then opens the Elodin editor
REM
REM  Same as run_race.cmd, but the sim runs in Docker instead of WSL.
REM  You still need the NATIVE Windows editor installed (README step 4).
REM
REM  Optional argument: solver module (default: solvers.follower, the
REM  racing-line stack; flies the newest plan in AI-GrandPrix/out/plans)
REM    run_race_docker.cmd solver.pq_waypoints   (old stop-and-center pilot)
REM ==================================================================
setlocal
cd /d "%~dp0"
set "SOLVER=%~1"
if "%SOLVER%"=="" set "SOLVER=solvers.follower"

REM ---- preflight: fail fast, BEFORE the 10-minute first build ----------
where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: docker not found on PATH.
  echo Install Docker Desktop, launch it once, then re-run this script.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker is installed but not running.
  echo Launch Docker Desktop, wait for the whale icon to stop animating,
  echo then re-run this script.
  pause
  exit /b 1
)

REM The sim loads the course map from the companion repo; without it the
REM container starts, syncs, and only then dies.
if not exist "%~dp0..\AI-GrandPrix\data\course_map.json" (
  echo ERROR: the AI-GrandPrix repo is missing.
  echo It must sit next to this one:
  echo     GitRepos\AI-GrandPrix\      ^<- course map + loader
  echo     GitRepos\elodin-sim-aigp\   ^<- this repo
  echo Clone it, then re-run:
  echo     git clone ^<AI-GrandPrix url^> "%~dp0..\AI-GrandPrix"
  pause
  exit /b 1
)

REM assets\*.glb are Git LFS. Cloned without git-lfs they are ~130-byte
REM text pointers and the editor renders no drone or gates.
for %%F in ("%~dp0assets\crazyflie.glb") do set "GLBSIZE=%%~zF"
if not defined GLBSIZE set "GLBSIZE=0"
if %GLBSIZE% LSS 2000 (
  echo ERROR: assets\crazyflie.glb is a Git LFS pointer, not the real model.
  echo Install Git LFS ^(https://git-lfs.com^), then from this folder run:
  echo     git lfs install
  echo     git lfs pull
  pause
  exit /b 1
)

REM Editor: fetch it automatically rather than failing after the build.
if not exist "%LOCALAPPDATA%\Programs\elodin\elodin.exe" (
  echo The Elodin editor is not installed - downloading it now ^(~1 min^)...
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $d=Join-Path $env:LOCALAPPDATA 'Programs\elodin'; $z=Join-Path $env:TEMP 'elodin.zip'; New-Item -ItemType Directory -Force $d | Out-Null; Invoke-WebRequest 'https://github.com/elodin-sys/elodin/releases/download/v0.17.3/elodin-x86_64-pc-windows-msvc.zip' -OutFile $z -UseBasicParsing; Expand-Archive $z -DestinationPath $d -Force"
  if not exist "%LOCALAPPDATA%\Programs\elodin\elodin.exe" (
    echo ERROR: automatic download failed. Install it by hand ^(README step 4^).
    pause
    exit /b 1
  )
  echo Editor installed.
)

REM Windows 10 only: the editor crashes on a missing Windows 11 font.
ver | findstr /C:" 10.0.1" >nul 2>&1
if not errorlevel 1 (
  if not exist "%WINDIR%\Fonts\SegoeIcons.ttf" (
    echo.
    echo WARNING: Windows 10 without the SegoeIcons font - the editor may crash.
    echo Fix: download https://aka.ms/SegoeFluentIcons, extract, then in an
    echo ADMIN PowerShell run:
    echo     Copy-Item ".\Segoe Fluent Icons.ttf" "C:\Windows\Fonts\SegoeIcons.ttf"
    echo Continuing anyway in 5 seconds...
    timeout /t 5 /nobreak >nul
  )
)

echo Cleaning up any previous run...
docker compose down --remove-orphans >nul 2>&1

echo Starting sim (RACE_SOLVER=%SOLVER%) in a Docker window...
REM RACE_SOLVER is read by docker-compose.yml from this environment.
set "RACE_SOLVER=%SOLVER%"
start "PQ race sim (docker)" cmd /k "docker compose up --build"

REM Docker publishes 2240 on localhost - no WSL-IP dance needed.
echo Waiting for the render server on localhost:2240 ...
echo (first run also builds the image and Betaflight SITL - can take 10+ min)
set /a tries=0
:wait
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1',2240); exit 0 } catch { exit 1 } finally { $c.Close() }" >nul 2>&1
if %errorlevel%==0 goto ready
set /a tries+=1
set /a rem30=tries %% 30
if %rem30%==0 echo   ... still waiting (%tries%s) - check the sim window for build progress
if %tries% geq 1200 (
  echo Gave up after ~20 minutes. Check the sim window for errors.
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait

:ready
echo Render server is up - opening the editor at localhost:2240 ...
"%LOCALAPPDATA%\Programs\elodin\elodin.exe" editor 127.0.0.1:2240
endlocal

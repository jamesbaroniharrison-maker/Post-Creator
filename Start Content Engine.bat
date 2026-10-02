@echo off
setlocal enabledelayedexpansion
title Content Engine - Starting...
cd /d "%~dp0linkedin_content_engine"

echo ================================================================
echo   LinkedIn Content Engine
echo ================================================================
echo.
echo   Starting up - this can take a minute or two, especially the
echo   first time. Please don't close this window.
echo.
echo ================================================================
echo.

REM --- Clear out THIS app's old server processes, so we always start clean.
REM     8000-8010, not just 8000: when 8000 is busy Reflex silently moves the backend
REM     to 8001, 8002... and a leftover one there means two backends share one
REM     frontend - the page talks to one while uploads/drafts go to the other.
REM     Only processes started from this folder are stopped, so another Reflex app
REM     (e.g. the Ben Holmes content engine) using the same ports is left alone. ---
set "CE_DIR=%~dp0"
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort (@(3000) + (8000..8010)) -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.OwningProcess) -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like ('*' + $env:CE_DIR + '*')) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } }" >nul 2>&1

REM --- Make sure Ollama (needed for drafting posts) is running ---
echo Checking Ollama is running...
curl -s -o nul http://localhost:11434 >nul 2>&1
if errorlevel 1 (
    echo   Ollama isn't running yet - starting it now...
    start "" "ollama" serve
    timeout /t 5 /nobreak >nul
) else (
    echo   Ollama is already running. Good.
)
echo.

REM --- Start the app server in its own window, so this window can watch for it
REM     to be ready and then open the browser automatically. ---
echo Starting the app server...
start "Content Engine - SERVER (leave this open while you work)" cmd /k "call ..\venv\Scripts\activate.bat && reflex run"

echo Waiting for it to finish starting...
set /a attempts=0
:waitloop
set /a attempts+=1
if !attempts! GTR 90 goto timeout_reached
timeout /t 2 /nobreak >nul
curl -s -o nul http://localhost:3000 >nul 2>&1
if errorlevel 1 goto waitloop

echo.
echo ================================================================
echo   Ready! Opening your browser now.
echo ================================================================
start http://localhost:3000/login
echo.
echo You can close THIS window now.
echo Just leave the OTHER window (titled "SERVER") open in the
echo background while you use the app - closing that one will log
echo you out and stop the app from working.
echo.
pause
exit /b 0

:timeout_reached
echo.
echo ================================================================
echo   This is taking longer than expected.
echo ================================================================
echo Look at the other window (titled "SERVER") for a line that says
echo "App running at: http://localhost:...." and open that address
echo in your browser directly.
echo.
echo If that window shows a wall of red text, take a screenshot of it -
echo that's the fastest way to diagnose what went wrong.
echo.
pause
exit /b 1

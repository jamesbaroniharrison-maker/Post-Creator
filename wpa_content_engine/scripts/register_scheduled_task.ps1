<#
Registers the WPA daily research cron as a Windows Scheduled Task (spec Â§5).

Dual trigger, per the spec:
  1. Daily at a fixed time.
  2. At log-on - a catch-up net for days the machine was off at the scheduled time.
The job itself (research_cron/pipeline.py) is idempotent per day via job_runs, so both
triggers firing on the same day is safe - the second one just no-ops.

Usage (run from an elevated PowerShell prompt, from this scripts/ directory):
    .\register_scheduled_task.ps1
    .\register_scheduled_task.ps1 -DailyTime "08:00"

To remove it later:
    Unregister-ScheduledTask -TaskName "WPA Daily Research Cron" -Confirm:$false
#>

param(
    [string]$DailyTime = "07:00"
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path (Split-Path -Parent $AppDir) "venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Venv python not found at $VenvPython - check the path or activate a different venv."
}

$Action = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m wpa_content_engine.research_cron.run" `
    -WorkingDirectory $AppDir

$DailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName "WPA Daily Research Cron" `
    -Action $Action `
    -Trigger @($DailyTrigger, $LogonTrigger) `
    -Settings $Settings `
    -Description "Runs the WPA content engine's daily research cron (spec section 3a/5). Idempotent per day." `
    -RunLevel Limited

Write-Host "Registered 'WPA Daily Research Cron' - daily at $DailyTime, plus at log-on as a catch-up."

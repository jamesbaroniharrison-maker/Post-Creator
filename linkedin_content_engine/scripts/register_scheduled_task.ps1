<#
Registers the daily research cron as a Windows Scheduled Task (spec Â§5).

Dual trigger, per the spec:
  1. Daily at a fixed time.
  2. At log-on - a catch-up net for days the machine was off at the scheduled time.
The job itself (research_cron/pipeline.py) is idempotent per day via job_runs, so both
triggers firing on the same day is safe - the second one just no-ops.

Usage (run from an elevated PowerShell prompt, from this scripts/ directory):
    .\register_scheduled_task.ps1
    .\register_scheduled_task.ps1 -DailyTime "08:00"

To remove it later:
    Unregister-ScheduledTask -TaskName "Content Engine Daily Research Cron" -Confirm:$false
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

# Clean up the old WPA-named task from before this project was repurposed, if present -
# best-effort, so re-running this script after the pivot doesn't leave an orphaned task
# pointing at a module path that no longer exists.
try {
    Unregister-ScheduledTask -TaskName "WPA Daily Research Cron" -Confirm:$false -ErrorAction Stop
    Write-Host "Removed old 'WPA Daily Research Cron' task."
} catch {}

$Action = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m linkedin_content_engine.research_cron.run" `
    -WorkingDirectory $AppDir

$DailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Register-ScheduledTask's own CIM errors don't reliably respect $ErrorActionPreference
# (confirmed live: an Access Denied error printed, then the script carried on and
# printed a false "Registered" success line anyway) - force it with -ErrorAction Stop
# so a real failure (e.g. not actually running elevated) stops the script here instead
# of lying about success.
Register-ScheduledTask `
    -TaskName "Content Engine Daily Research Cron" `
    -Action $Action `
    -Trigger @($DailyTrigger, $LogonTrigger) `
    -Settings $Settings `
    -Description "Runs the LinkedIn content engine's daily research cron (spec section 3a/5). Idempotent per day." `
    -RunLevel Limited `
    -ErrorAction Stop

Write-Host "Registered 'Content Engine Daily Research Cron' - daily at $DailyTime, plus at log-on as a catch-up."

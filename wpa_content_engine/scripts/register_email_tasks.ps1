<#
Registers the two scheduled email jobs as Windows Scheduled Tasks: the weekly
personal-story reminder and the weekly post digest.

Both run HOURLY (not once a day) because both day AND time are independently
configurable from the dashboard's "Email reminders" card - the Python job itself
(email_engine/reminder.py, email_engine/digest.py) checks "is today the right weekday
AND is this the right hour" every time it's invoked, so hourly is what actually makes
an arbitrary time-of-day setting work without ever touching Task Scheduler again.
Each job is also idempotent per week via job_runs, so extra hourly firings are no-ops.

Usage (run from an elevated PowerShell prompt, from this scripts/ directory):
    .\register_email_tasks.ps1

To remove them later:
    Unregister-ScheduledTask -TaskName "WPA Weekly Reminder Email" -Confirm:$false
    Unregister-ScheduledTask -TaskName "WPA Weekly Digest Email" -Confirm:$false
#>

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path (Split-Path -Parent $AppDir) "venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Venv python not found at $VenvPython - check the path or activate a different venv."
}

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$HourlyTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration ([TimeSpan]::MaxValue)
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn

# --- Weekly personal-story reminder ---
$ReminderAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m wpa_content_engine.email_engine.run --job reminder" `
    -WorkingDirectory $AppDir

Register-ScheduledTask `
    -TaskName "WPA Weekly Reminder Email" `
    -Action $ReminderAction `
    -Trigger @($HourlyTrigger, $LogonTrigger) `
    -Settings $Settings `
    -Description "Checks hourly whether it's her chosen reminder day and hour, and sends the personal-story nudge if so. Both are set in the dashboard, not here." `
    -RunLevel Limited

# --- Weekly post digest ---
$DigestAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m wpa_content_engine.email_engine.run --job digest" `
    -WorkingDirectory $AppDir

Register-ScheduledTask `
    -TaskName "WPA Weekly Digest Email" `
    -Action $DigestAction `
    -Trigger @($HourlyTrigger, $LogonTrigger) `
    -Settings $Settings `
    -Description "Checks hourly whether it's her chosen digest day and hour, and sends the week's scheduled posts if so." `
    -RunLevel Limited

Write-Host "Registered 'WPA Weekly Reminder Email' and 'WPA Weekly Digest Email' - both check hourly, day/time are set in the dashboard."

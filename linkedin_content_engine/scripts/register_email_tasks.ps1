<#
Registers the two scheduled email jobs as Windows Scheduled Tasks: the weekly
personal-story reminder and the weekly post digest.

Each runs ONCE A DAY (not hourly) - and each trigger fires at exactly that job's
configured send time, read from the dashboard's "Email reminders" settings at
registration time. Since the two jobs (reminder/digest) can have different times,
they're two separate tasks with two separate daily trigger times - there's no need to
poll every hour, one precise daily firing per job is enough. Each job is also
idempotent per week via job_runs, so the at-logon catch-up trigger firing on top is a
safe no-op if the day's run already happened.

If you change the day/time in the dashboard, the app updates these tasks' trigger
times automatically (see email_engine/settings.py) - you only need to re-run this
script by hand if the tasks aren't registered yet at all, or something's gone wrong.

Usage (run from an elevated PowerShell prompt, from this scripts/ directory):
    .\register_email_tasks.ps1
    .\register_email_tasks.ps1 -ReminderTime "09:00" -DigestTime "12:00"

To remove them later:
    Unregister-ScheduledTask -TaskName "Content Engine Weekly Reminder Email" -Confirm:$false
    Unregister-ScheduledTask -TaskName "Content Engine Weekly Digest Email" -Confirm:$false
#>

param(
    [string]$ReminderTime = "09:00",
    [string]$DigestTime = "12:00"
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path (Split-Path -Parent $AppDir) "venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Venv python not found at $VenvPython - check the path or activate a different venv."
}

# Clean up the old WPA-named tasks from before this project was repurposed, if present -
# best-effort, so re-running this script after the pivot doesn't leave orphaned tasks
# pointing at a module path that no longer exists.
try {
    Unregister-ScheduledTask -TaskName "WPA Weekly Reminder Email" -Confirm:$false -ErrorAction Stop
    Write-Host "Removed old 'WPA Weekly Reminder Email' task."
} catch {}
try {
    Unregister-ScheduledTask -TaskName "WPA Weekly Digest Email" -Confirm:$false -ErrorAction Stop
    Write-Host "Removed old 'WPA Weekly Digest Email' task."
} catch {}

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn

# --- Weekly personal-story reminder ---
$ReminderTrigger = New-ScheduledTaskTrigger -Daily -At $ReminderTime
$ReminderAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m linkedin_content_engine.email_engine.run --job reminder" `
    -WorkingDirectory $AppDir

# -ErrorAction Stop: Register-ScheduledTask's CIM errors don't reliably respect
# $ErrorActionPreference (confirmed live) - without this, a real failure here would
# print an error and then the script would carry on to the false "Registered" line.
Register-ScheduledTask `
    -TaskName "Content Engine Weekly Reminder Email" `
    -Action $ReminderAction `
    -Trigger @($ReminderTrigger, $LogonTrigger) `
    -Settings $Settings `
    -Description "Runs once a day at $ReminderTime and sends the personal-story nudge if today is your chosen reminder day. Day/time are set in the dashboard, which keeps this trigger's time in sync automatically." `
    -RunLevel Limited `
    -Force `
    -ErrorAction Stop

# --- Weekly post digest ---
$DigestTrigger = New-ScheduledTaskTrigger -Daily -At $DigestTime
$DigestAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m linkedin_content_engine.email_engine.run --job digest" `
    -WorkingDirectory $AppDir

Register-ScheduledTask `
    -TaskName "Content Engine Weekly Digest Email" `
    -Action $DigestAction `
    -Trigger @($DigestTrigger, $LogonTrigger) `
    -Settings $Settings `
    -Description "Runs once a day at $DigestTime and sends the week's scheduled posts if today is your chosen digest day. Day/time are set in the dashboard, which keeps this trigger's time in sync automatically." `
    -RunLevel Limited `
    -Force `
    -ErrorAction Stop

Write-Host "Registered 'Content Engine Weekly Reminder Email' (daily at $ReminderTime) and 'Content Engine Weekly Digest Email' (daily at $DigestTime) - each runs once a day, not hourly."

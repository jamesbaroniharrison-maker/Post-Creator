<#
Registers the two scheduled email jobs as Windows Scheduled Tasks: the weekly
personal-story reminder and the Sunday weekly-post digest.

Both run on a DAILY trigger (plus at-logon catch-up, same pattern as the research
cron), but the actual "should I send today" decision lives in Python
(email_engine/reminder.py, email_engine/digest.py), not in the Windows trigger itself.
That's deliberate: the reminder day is changeable from the dashboard's "Email
reminders" card without ever touching Task Scheduler again, and the digest always
checks it's actually Sunday before sending, so a missed-day catch-up run can't send it
on the wrong day.

Usage (run from an elevated PowerShell prompt, from this scripts/ directory):
    .\register_email_tasks.ps1
    .\register_email_tasks.ps1 -ReminderCheckTime "09:00" -DigestCheckTime "12:00"

To remove them later:
    Unregister-ScheduledTask -TaskName "WPA Weekly Reminder Email" -Confirm:$false
    Unregister-ScheduledTask -TaskName "WPA Sunday Digest Email" -Confirm:$false
#>

param(
    [string]$ReminderCheckTime = "09:00",
    [string]$DigestCheckTime = "12:00"
)

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

# --- Weekly personal-story reminder ---
$ReminderAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m wpa_content_engine.email_engine.run --job reminder" `
    -WorkingDirectory $AppDir

Register-ScheduledTask `
    -TaskName "WPA Weekly Reminder Email" `
    -Action $ReminderAction `
    -Trigger @((New-ScheduledTaskTrigger -Daily -At $ReminderCheckTime), (New-ScheduledTaskTrigger -AtLogOn)) `
    -Settings $Settings `
    -Description "Checks daily whether today is her chosen reminder day and sends the personal-story nudge if so. The day itself is set in the dashboard, not here." `
    -RunLevel Limited

# --- Sunday weekly-post digest ---
$DigestAction = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "-m wpa_content_engine.email_engine.run --job digest" `
    -WorkingDirectory $AppDir

Register-ScheduledTask `
    -TaskName "WPA Sunday Digest Email" `
    -Action $DigestAction `
    -Trigger @((New-ScheduledTaskTrigger -Daily -At $DigestCheckTime), (New-ScheduledTaskTrigger -AtLogOn)) `
    -Settings $Settings `
    -Description "Checks daily whether it's Sunday and sends the week's lined-up posts if so." `
    -RunLevel Limited

Write-Host "Registered 'WPA Weekly Reminder Email' (checks daily at $ReminderCheckTime) and 'WPA Sunday Digest Email' (checks daily at $DigestCheckTime, only sends on Sunday)."

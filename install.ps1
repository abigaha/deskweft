param(
    [string]$Root = "$env:LOCALAPPDATA\winmcp"
)

$ErrorActionPreference = "Stop"
$pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe not found at $pythonw - rebuild the venv first"
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m winmcp.server" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Interactive keeps the process in this desktop session; without it the helper
# cannot see any windows.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0

Register-ScheduledTask -TaskName "winmcp-helper" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName "winmcp-helper"
Start-Sleep -Seconds 6

$listening = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    "winmcp-helper installed and listening on 8765"
} else {
    "task registered, but nothing is listening yet - check with: Get-ScheduledTaskInfo winmcp-helper"
}

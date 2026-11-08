param(
    [string]$Root = "$env:LOCALAPPDATA\deskweft"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Root ".venv\Scripts\python.exe"
$runner = Join-Path $Root "run-helper.ps1"

if (-not (Test-Path -LiteralPath $python)) {
    throw "python.exe not found at $python - rebuild the venv first"
}
if (-not (Test-Path -LiteralPath $runner)) {
    throw "run-helper.ps1 not found at $runner"
}
$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source

$action = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$runner`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Interactive keeps the process in this desktop session; without it the helper
# cannot see any windows.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0

Register-ScheduledTask -TaskName "deskweft-helper" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName "deskweft-helper"
$deadline = [DateTime]::UtcNow.AddSeconds(30)
$expectedCommand = '^\s*"?' + [regex]::Escape($python) + '"?\s+-m\s+deskweft\.server(?:\s|$)'
do {
    $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count) {
        if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') {
            throw 'Port 8765 has an unexpected listener'
        }
        $server = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
        if ($server.CommandLine -notmatch $expectedCommand) {
            throw 'Port 8765 belongs to another process; check the task and helper.err.log'
        }
        'deskweft-helper installed and listening on 127.0.0.1:8765'
        return
    }
    Start-Sleep -Milliseconds 250
} while ([DateTime]::UtcNow -lt $deadline)
throw 'Task registered but service did not start within 30 seconds; check helper.err.log and Get-ScheduledTaskInfo deskweft-helper'

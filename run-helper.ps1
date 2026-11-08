# Launch the helper with logs. Used by the deskweft-helper scheduled task.
#
# Start-Process with redirects is deliberate: under Task Scheduler there is no
# console, and a process writing to an invalid stderr handle dies before it
# opens the port. Files give it real handles.
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

$log = Join-Path $Root "helper.log"
$out = Join-Path $Root "helper.out.log"
$err = Join-Path $Root "helper.err.log"

"--- start $(Get-Date -Format s) ---" | Out-File -FilePath $log -Append -Encoding utf8

$p = Start-Process -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
    -ArgumentList "-m", "deskweft.server" `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -PassThru

Start-Sleep -Seconds 10
if ($p.HasExited) {
    "exited with $($p.ExitCode)" | Out-File -FilePath $log -Append -Encoding utf8
} else {
    "running as pid $($p.Id)" | Out-File -FilePath $log -Append -Encoding utf8
}

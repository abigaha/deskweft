# Remove the deskweft helper: scheduled task, running server, client registrations.
# The code and venv stay in place; delete $Root manually if you want them gone.
param(
    [string]$Root = "$env:LOCALAPPDATA\deskweft",
    [switch]$KeepClientConfig
)

$ErrorActionPreference = "Continue"

Unregister-ScheduledTask -TaskName "deskweft-helper" -Confirm:$false -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*deskweft.server*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (-not $KeepClientConfig) {
    $codex = "$env:USERPROFILE\.codex\config.toml"
    if (Test-Path $codex) {
        $text = Get-Content $codex -Raw
        $text = [regex]::Replace($text, '(?ms)(?:^|\r?\n)\[mcp_servers\.deskweft\].*?(?=\r?\n\[|$)', '')
        Set-Content -Path $codex -Value $text.TrimEnd() -Encoding UTF8
    }

    $json = "$env:USERPROFILE\.claude.json"
    if (Test-Path $json) {
        $data = Get-Content $json -Raw | ConvertFrom-Json
        if ($data.mcpServers.PSObject.Properties.Name -contains 'deskweft') {
            $data.mcpServers.PSObject.Properties.Remove('deskweft')
            $data | ConvertTo-Json -Depth 100 | Set-Content $json -Encoding UTF8
        }
    }
    "removed client registrations"
}

"deskweft-helper removed. Code left at $Root"

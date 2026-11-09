# Remove the deskweft helper: scheduled task, running server, client registrations.
# The code and venv stay in place; delete $Root manually if you want them gone.
param(
    [string]$Root = "$env:LOCALAPPDATA\deskweft",
    [switch]$KeepClientConfig
)

$ErrorActionPreference = "Continue"

Unregister-ScheduledTask -TaskName "deskweft-helper" -Confirm:$false -ErrorAction SilentlyContinue

$python = Join-Path ([IO.Path]::GetFullPath($Root)) ".venv\Scripts\python"
$expectedCommand = '^\s*(?:"' + [regex]::Escape($python) + 'w?\.exe"|' +
    [regex]::Escape($python) + 'w?\.exe)\s+-m\s+deskweft\.server(?:\s|$)'
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match $expectedCommand } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (-not $KeepClientConfig) {
    $codex = "$env:USERPROFILE\.codex\config.toml"
    if (Test-Path $codex) {
        $text = Get-Content $codex -Raw
        # Strings, comments and arrays can contain lines that look like table headers.
        $tokens = @'
(?msx)
    """ (?: \\ . | (?! """) . )* "{3,5}
  | ''' .*? '{3,5}
  | " (?: \\ . | [^"\\\r\n] )* "
  | ' [^'\r\n]* '
  | \# [^\r\n]*
  | (?<header> ^ [\t ]* \[ [^\r\n]* \] [\t ]* (?: \# [^\r\n]* )? \r? $ )
  | (?<open> [\[{] )
  | (?<close> [\]}] )
'@
        $depth = 0
        $headers = @([regex]::Matches($text, $tokens) | ForEach-Object {
            if ($_.Groups['header'].Success -and $depth -eq 0) { $_ }
            elseif ($_.Groups['open'].Success) { $depth++ }
            elseif ($_.Groups['close'].Success) { $depth-- }
        })
        $deskweftTable = @'
(?x) ^ [\t ]* \[ \[? [\t ]*
(?: mcp_servers | "mcp_servers" | 'mcp_servers' ) [\t ]* \. [\t ]*
(?: deskweft | "deskweft" | 'deskweft' ) [\t ]* (?: \. | \] )
'@
        for ($i = $headers.Count - 1; $i -ge 0; $i--) {
            if ($headers[$i].Value -cmatch $deskweftTable) {
                $end = if ($i + 1 -lt $headers.Count) { $headers[$i + 1].Index } else { $text.Length }
                $text = $text.Remove($headers[$i].Index, $end - $headers[$i].Index)
            }
        }
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

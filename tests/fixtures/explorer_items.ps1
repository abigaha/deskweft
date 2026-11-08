param(
    [ValidateSet('Open', 'Reveal', 'Close')][string]$Action = 'Open',
    [Parameter(Mandatory = $true)][string]$RunDirectory
)

$ErrorActionPreference = 'Stop'
$runPath = [IO.Path]::GetFullPath($RunDirectory)
$filesPath = Join-Path $runPath 'item-files'
$manifestPath = Join-Path $runPath 'explorer-ready.json'
$shell = New-Object -ComObject Shell.Application

function Get-MatchingFolderWindow([long]$ExpectedHandle, [string]$ExpectedPath) {
    foreach ($candidate in @($shell.Windows())) {
        try {
            if ([long]$candidate.HWND -ne $ExpectedHandle) { continue }
            $location = [Uri]$candidate.LocationURL
            if (-not $location.IsFile) { continue }
            $actualPath = [IO.Path]::GetFullPath($location.LocalPath).TrimEnd('\')
            if ($actualPath -ieq $ExpectedPath.TrimEnd('\')) { return $candidate }
        } catch { continue }
    }
    return $null
}

if ($Action -in @('Reveal', 'Close')) {
    $record = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $owned = Get-MatchingFolderWindow ([long]$record.hwnd) ([string]$record.folder)
    if ($null -eq $owned) { throw 'The exact fixture HWND/folder pair is no longer present; nothing closed' }
    if ($Action -eq 'Close') {
        $owned.Quit()
        @{ hwnd = $record.hwnd; close_requested = $true } | ConvertTo-Json
    } else {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class WinMcpExplorerFixtureNative {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hwnd, int command);
}
'@
        $before = [WinMcpExplorerFixtureNative]::GetForegroundWindow().ToInt64()
        [WinMcpExplorerFixtureNative]::ShowWindowAsync([IntPtr][long]$record.hwnd, 4) | Out-Null
        Start-Sleep -Milliseconds 1000
        @{ hwnd = $record.hwnd; shown_without_activation = $true; foreground_before = $before;
            foreground_after = [WinMcpExplorerFixtureNative]::GetForegroundWindow().ToInt64() } | ConvertTo-Json
    }
    exit 0
}

if ([IO.File]::Exists($manifestPath)) { throw 'Use a fresh run directory for each Explorer fixture' }
[IO.Directory]::CreateDirectory($filesPath) | Out-Null
for ($index = 0; $index -lt 150; $index++) {
    $filePath = Join-Path $filesPath ('fixture-{0:D4}.txt' -f $index)
    $stream = [IO.File]::Open($filePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    $stream.Dispose()
}
$baseline = @($shell.Windows() | ForEach-Object { [long]$_.HWND })
$launchArgs = '/n,/separate,"' + $filesPath + '"'
$launcher = Start-Process -FilePath explorer.exe -ArgumentList $launchArgs -WindowStyle Hidden -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds(15)
$owned = $null
while ([DateTime]::UtcNow -lt $deadline -and $null -eq $owned) {
    foreach ($candidate in @($shell.Windows())) {
        try {
            $candidateHandle = [long]$candidate.HWND
            if ($candidateHandle -in $baseline) { continue }
            $owned = Get-MatchingFolderWindow $candidateHandle $filesPath
            if ($null -ne $owned) { break }
        } catch { continue }
    }
    if ($null -eq $owned) { Start-Sleep -Milliseconds 200 }
}
if ($null -eq $owned) { throw 'No new HWND verified against the synthetic folder; no window claimed' }
$record = [ordered]@{
    hwnd = [long]$owned.HWND
    folder = $filesPath
    item_count = 150
    first_name = 'fixture-0000.txt'
    far_name = 'fixture-0149.txt'
    launcher_pid = $launcher.Id
    ownership = 'new HWND absent from baseline plus exact synthetic folder URL'
}
[IO.File]::WriteAllText($manifestPath, ($record | ConvertTo-Json -Depth 3),
    [Text.UTF8Encoding]::new($false))
$record | ConvertTo-Json -Depth 3

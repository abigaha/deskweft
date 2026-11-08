param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [int]$Count = 300,
    [int]$LifetimeSeconds = 2700
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName WindowsBase
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public sealed class WinMcpFixtureItem {
    public string Key { get; set; }
    public string Label { get; set; }
    public override string ToString() { return Label; }
}
public static class WinMcpFixtureNative {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@

if ($Count -lt 150 -or $Count -gt 10000) { throw 'Count must be 150..10000' }
$runPath = [IO.Path]::GetFullPath($RunDirectory)
[IO.Directory]::CreateDirectory($runPath) | Out-Null
$closePath = Join-Path $runPath 'close.request'
if ([IO.File]::Exists((Join-Path $runPath 'ready.json')) -or [IO.File]::Exists($closePath)) {
    throw 'Use a fresh run directory so stale handles and close requests cannot be reused'
}
$startedAt = [DateTime]::UtcNow
$foregroundBefore = [WinMcpFixtureNative]::GetForegroundWindow().ToInt64()

$window = [System.Windows.Window]::new()
$window.Title = 'deskweft ItemContainer synthetic fixture'
$window.Width = 500
$window.Height = 340
$window.Left = 32
$window.Top = 32
$window.WindowStartupLocation = [System.Windows.WindowStartupLocation]::Manual
$window.ShowActivated = $false
$window.Topmost = $false
[System.Windows.Automation.AutomationProperties]::SetAutomationId($window, 'ItemContainerFixtureWindow')

$layout = [System.Windows.Controls.DockPanel]::new()
$layout.Margin = [System.Windows.Thickness]::new(12)
$label = [System.Windows.Controls.TextBlock]::new()
$label.Text = 'Synthetic items only. Close through close.request; no other app is touched.'
$label.TextWrapping = [System.Windows.TextWrapping]::Wrap
$label.Margin = [System.Windows.Thickness]::new(0, 0, 0, 8)
[System.Windows.Controls.DockPanel]::SetDock($label, [System.Windows.Controls.Dock]::Top)
$layout.Children.Add($label) | Out-Null

$list = [System.Windows.Controls.ListBox]::new()
$list.DisplayMemberPath = 'Label'
[System.Windows.Automation.AutomationProperties]::SetAutomationId($list, 'ItemContainerFixtureList')
[System.Windows.Automation.AutomationProperties]::SetName($list, 'Synthetic virtualized items')
[System.Windows.Controls.VirtualizingStackPanel]::SetIsVirtualizing($list, $true)
[System.Windows.Controls.VirtualizingStackPanel]::SetVirtualizationMode(
    $list, [System.Windows.Controls.VirtualizationMode]::Recycling)
[System.Windows.Controls.ScrollViewer]::SetCanContentScroll($list, $true)
$style = [System.Windows.Style]::new([System.Windows.Controls.ListBoxItem])
$style.Setters.Add([System.Windows.Setter]::new(
    [System.Windows.Automation.AutomationProperties]::AutomationIdProperty,
    [System.Windows.Data.Binding]::new('Key')))
$style.Setters.Add([System.Windows.Setter]::new(
    [System.Windows.Automation.AutomationProperties]::NameProperty,
    [System.Windows.Data.Binding]::new('Label')))
$list.ItemContainerStyle = $style
$items = [System.Collections.Generic.List[WinMcpFixtureItem]]::new()
$duplicates = 0
for ($index = 0; $index -lt $Count; $index++) {
    $item = [WinMcpFixtureItem]::new()
    $item.Key = 'fixture-{0:D4}' -f $index
    if (($index % 25) -eq 0) {
        $item.Label = 'Fixture duplicate'
        $duplicates++
    } else {
        $item.Label = 'Fixture item {0:D4}' -f $index
    }
    $items.Add($item)
}
$list.ItemsSource = $items
$layout.Children.Add($list) | Out-Null
$window.Content = $layout

$window.Add_ContentRendered({
    $list.UpdateLayout()
    $realized = 0
    for ($index = 0; $index -lt $Count; $index++) {
        if ($null -ne $list.ItemContainerGenerator.ContainerFromIndex($index)) { $realized++ }
    }
    $peer = [System.Windows.Automation.Peers.UIElementAutomationPeer]::CreatePeerForElement($list)
    $itemContainer = $peer.GetPattern([System.Windows.Automation.Peers.PatternInterface]::ItemContainer)
    $info = [ordered]@{
        pid = $PID
        hwnd = ([System.Windows.Interop.WindowInteropHelper]::new($window)).Handle.ToInt64()
        selector = @{ automation_id = 'ItemContainerFixtureList' }
        item_count = $Count
        initially_realized_count = $realized
        duplicate_label = 'Fixture duplicate'
        duplicate_count = $duplicates
        far_label = $items[$Count - 1].Label
        far_key = $items[$Count - 1].Key
        itemcontainer_peer_available = ($null -ne $itemContainer)
        foreground_before = $foregroundBefore
        foreground_after = [WinMcpFixtureNative]::GetForegroundWindow().ToInt64()
        close_request = $closePath
        started_utc = $startedAt.ToString('o')
    }
    [IO.File]::WriteAllText((Join-Path $runPath 'ready.json'),
        ($info | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
})

$timer = [System.Windows.Threading.DispatcherTimer]::new()
$timer.Interval = [TimeSpan]::FromMilliseconds(300)
$timer.Add_Tick({
    if ([IO.File]::Exists($closePath) -or
        ([DateTime]::UtcNow - $startedAt).TotalSeconds -ge $LifetimeSeconds) {
        $window.Close()
    }
})
$timer.Start()
try {
    $window.ShowDialog() | Out-Null
} finally {
    $timer.Stop()
    [IO.File]::WriteAllText((Join-Path $runPath 'closed.json'),
        (@{ pid = $PID; closed_utc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json),
        [Text.UTF8Encoding]::new($false))
}

# winmcp

A window-addressed desktop control MCP server for Windows that **never takes
the foreground**.

The core promise: it addresses one window by handle, acts through Win32
messages and UIA patterns, and never moves your cursor or steals your focus.
When an action genuinely needs the foreground, it refuses and returns a
`needs_permission` result instead of doing it — the caller must ask you first.

## Why not patch window-mcp

The model of the usual desktop MCP is "snapshot the whole desktop (every
window's UIA tree), hand back coordinates, move the real cursor, click." That
has three structural costs: a full-desktop traversal takes 11–15 s, a real
cursor cannot coexist with a human, and coordinates only hold for the snapshot
that produced them.

This tool changes the model: **address a single window by hwnd** and act with
window messages and `PrintWindow`.

## Measurements (on a normal Windows desktop)

| Operation | Time | Takes foreground |
|---|---|---|
| `windows()` list | ~1 ms | no |
| `PrintWindow` background capture | 16–31 ms | no |
| UIA tree read | 5 ms – 14 s | no |
| Win32 `BM_CLICK` window message | **0.0 ms** | **no** |
| Win32 `WM_SETTEXT` write | **0.3 ms** | **no** |
| UIA `InvokePattern` | 504–518 ms | **yes** |
| UIA `ValuePattern.SetValue` | 514 ms | **yes** |

The conclusion that shaped the design: **UIA pattern invocation is what steals
the foreground**, and it is three orders of magnitude slower than a window
message. So window messages are the primary route, and UIA is only used after
the user agrees.

## Tools

- `windows()` — visible top-level windows: hwnd, title, class, pid, rect, foreground flag
- `see(hwnd, with_tree=false)` — `PrintWindow` capture plus an optional UIA tree with a hard timeout
- `click(hwnd, target)` — window message first, `needs_permission` otherwise
- `type_text(hwnd, target, text)` — `WM_SETTEXT` first, verified by read-back
- `key(hwnd, keys)` — keystrokes; always needs the foreground
- `scroll(hwnd, target, direction)` — background scrolling is unreliable, expect a refusal
- `open_app(command)` — starts a program **without letting it pop to the front**
- `reveal(hwnd)` — shows a hidden window; this one does take the foreground

### The permission gate

When an action cannot be done without the foreground:

```json
{
  "ok": false,
  "needs_permission": true,
  "reason": "no native control matching 'X' that accepts a window message",
  "detail": "'Window title' can only be reached through UIA or the real cursor...",
  "hint": "Show this to the user. Retry with allow_foreground=true only after they agree."
}
```

## Install

```powershell
git clone <this repo> $env:LOCALAPPDATA\winmcp
cd $env:LOCALAPPDATA\winmcp
uv venv .venv --python 3.14
uv pip install --python .venv\Scripts\python.exe "windows-mcp==0.8.8"
uv pip install --python .venv\Scripts\python.exe -e .
pwsh -File .\install.ps1     # registers the logon task, starts the server
```

The server listens on `http://127.0.0.1:8765/mcp`.

Register it in a client, e.g. Codex `~/.codex/config.toml`:

```toml
[mcp_servers.winmcp]
url = "http://127.0.0.1:8765/mcp"
required = false
```

### Do not install under a directory with capability SIDs

`PrintWindow` returns `ERROR_ACCESS_DENIED` for **every** window when the
interpreter lives under a directory whose ACL carries `S-1-4-*` application
package capability SIDs. Some user profile folders inherit them. If capture
works from one venv and fails from another with identical code and Python
build, check the ACL before anything else:

```powershell
(Get-Acl $path).Access | Where-Object { $_.IdentityReference -like 'S-1-4-*' }
```

Installing under `%LOCALAPPDATA%` avoids the issue.

## Self-check

```powershell
cd $env:LOCALAPPDATA\winmcp
.venv\Scripts\python.exe -m winmcp.check
```

36 assertions. It creates its own window, so it never touches yours.

## Known limits

1. **Chromium / Electron / Flutter / games have no Win32 child controls.** `click`
   always goes through the permission gate there.
2. **Electron apps hide their UI from accessibility unless launched with it on.**
   See below — this is the difference between a readable app and a black box.
3. **Background UIA reads are slow for browsers** (10+ s). The timeout stops it
   and returns `timed_out: true` rather than hanging.
4. **`PrintWindow` returns blank frames** for GPU overlays, protected content and
   minimised windows. Reported as `image_unavailable`, never as a blank picture.
5. **UWP shell windows read as zero elements.** An `ApplicationFrameWindow` really
   does contain only empty title-bar and input-sink children; the content lives in
   a separate `CoreWindow`.
6. **Win32 multiline edits expose no `ScrollPattern`.** Only the mouse wheel moves
   them.
7. **Chromium inputs return `None` from `ValuePattern.Value`** even when the text
   is there, so read-back verification is impossible; pixel comparison is the only
   check.

### Electron apps are black boxes until accessibility is switched on

Chromium builds its accessibility tree lazily, and an outside UIA client asking
for it is *not* enough to switch it on. Measured on QQ (Chromium 9.9.22):

| Launch | Elements read | Named |
|---|---|---|
| plain | 9 | 0 |
| `--force-renderer-accessibility` | 128 | 126 |

Those 9 are empty `PaneControl` shells wrapping the D3D surface — no names, no
addressable controls, nothing to click by name.

**And Chromium throws the tree away again as soon as another window comes
forward.** Same window, same session, only the foreground changed:

| Foreground | Elements |
|---|---|
| QQ | 132 |
| your editor | 0 |
| QQ again | 132 |

That is why an agent can read a window one moment and find nothing the next.
Two flags stop it, and either one alone is enough:

- `--disable-backgrounding-occluded-windows`
- `--disable-features=CalculateNativeWinOcclusion`

`open_app(..., accessibility=True)` passes all three flags. With them a
backgrounded QQ reads 132 elements on every poll while your editor keeps the
foreground.

### Clicks that never steal the foreground

UIA `InvokePattern` on Chromium goes through IA2, which focuses the widget and
takes the foreground. `LegacyIAccessible.DoDefaultAction` does the same work
through MSAA and leaves focus alone. Measured on the same backgrounded window:

| Route | Effect landed | Cursor moved | Foreground moved |
|---|---|---|---|
| `LegacyIAccessible.DoDefaultAction` | yes | no | **no** |
| `InvokePattern` | no | no | **yes** |
| posted `WM_LBUTTONDOWN` to render host | no | no | no |

So `click()` tries the legacy route first, before touching the window's
activation state at all. Only if that finds no target does it bring the window
forward and fall back to the modern patterns.

### False successes this tool had to fix

Three separate times an API reported success while nothing happened. They are now
guarded, and the lesson is in the code:

- **`SetForegroundWindow` on a hidden window returns success** and
  `GetForegroundWindow` points at it, but the screen does not change. Guarded by
  also requiring `IsWindowVisible` and `not IsIconic`.
- **`ValuePattern.SetValue` on a Chromium input returns silently** and stores
  nothing. Guarded by reading the value back and falling back to
  click-then-type.
- **`PostMessage(BM_CLICK)` to a render host returns 1** and does nothing. Guarded
  by only messaging real button classes.

## Real-world testing

128 assertions across seven suites, against real applications — Notepad, Paint,
VS Code, Explorer, Calculator, Notepad++, and a live browser session.

| Suite | Covers | Result |
|---|---|---|
| T1 | `windows()` completeness, accuracy, cost | 9/9 |
| T2 | `see()` across Win32 / WinUI / Electron / UWP / desktop | 5/5 |
| T3 | `click()` every route | 10/10 |
| T4 | `type_text()` every route plus encoding edges | 9/9 |
| T5 | `key()` notation and real keystrokes | 10/10 |
| T6 | `scroll()` capability and honest degradation | 1/1 |
| T7 | `open_app()` / `reveal()` | 30/30 |
| T8 | hostile input, concurrency, leaks | 31/31 |
| T9 | MCP protocol, schemas, error shapes | 23/23 |

Verified end to end: drove a real browser to a search page, read the results from
the UIA tree, and clicked through to a repository page; filled and submitted an
HTML form and confirmed every field arrived by reading the server's JSON response.

## Design notes worth keeping

**Key notation is translated, not passed through.** `SendKeys` wants `{Ctrl}s`;
a caller writing `^s` would get those characters typed literally into the
document. `_normalise_keys` accepts `^s`, `Ctrl+s`, `^{END}` and emits the right
form. A chord is only a chord when every part before the last is a modifier name
— otherwise `1+1` becomes `{1}{1}` and the plus disappears.

**Pattern getters are not universal.** `GroupControl` has no `GetInvokePattern`,
`WindowControl` has no `GetScrollPattern`. Every pattern access goes through one
guarded helper; a bare attribute access crashes on real UIs.

**Silent launch is a fight, not a race.** A launched app calls
`SetForegroundWindow` about 200 ms in, sooner than any hook can hide its window.
So the tool hides new windows every pass and takes the foreground back every pass
until the situation is stable. `foreground_contests` reports how often the app
tried.

**Verify screen changes with a screenshot.** Every failure mode above reported
success. No API return value is trusted for anything visible.

**Credential dialogs stall git commands.** On Windows, `git push` / `git remote
add` can trigger Git Credential Manager's "Select an account" window (an
Avalonia top-level window, class `Avalonia-*`). It blocks the command until an
account is chosen. Its title has no "git" keyword, so a keyword-based window
scan misses it and the agent waits forever with no output. The rule is shipped
to every connected client in the server's MCP `instructions`: if a git command
stalls, call `windows()`, find the new window, then `see(hwnd, with_tree=True)`
to click the account `ListItem` and `Continue`. Match by title/class, not by pid
— the dialog belongs to a different process.

## License

MIT

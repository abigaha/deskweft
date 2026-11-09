# DeskWeft

A Windows automation framework combining a skill, local app/version memory,
and a controlled, window-addressed MCP execution layer.

The skill guides exploration, route selection, validation and recovery. Memory
keeps observations and reusable plans with their evidence and trust state. The
MCP layer targets windows by handle, validates requests and runs UIA work in a
bounded worker. Background execution requires protection verified for the
current target and method; provider calls can activate windows. Foreground
routes require authorization covering the action.

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

The conclusion that shaped the design: **a UIA pattern call can take the
foreground**, and it is orders of magnitude slower than a window message. So
window messages are the primary route, and UIA is only used after the user
agrees. These are historical observations from one machine, not a property of
every provider: the read-only members `invoke_pattern` allows in the background
are still subject to a provider that behaves badly, which is why a measured
counterexample belongs in memory with `uses_foreground=true`.

## Tools

Sixteen tools cover windows, generic queries, item-container enumeration and memory.

**Reading and acting on one window**

- `windows()` — visible top-level windows: hwnd, title, class, pid, rect, foreground flag
- `app_info(hwnd)` — exe, version **and the evidence behind it**: `path_segment` /
  `child_cmdline` are strong, `sole_candidate` / `file_version` / `sibling_dir` are
  weaker and carry a warning, `source=null` means no evidence
- `see(hwnd, with_tree=false)` — `PrintWindow` capture, the accessibility tree, the
  native child control handles, and the diagnostics (`timed_out`,
  `limit_reached`, `identity_complete`, `tree_diagnostics`) that say whether the
  read was complete
- `find_items(hwnd, target="", property_id=0, value=null, start_index=0,
  max_items=100, timeout_ms=8000)` — bounded ItemContainer queries, including
  items outside the visible tree. NULL and continuation references stay inside
  one worker call; results are plain metadata, with paging and completeness
  diagnostics. It calls no Realize, scrolling, selection or focus operation
- `click(hwnd, target)` — a uniquely matching native control takes a window
  message and reports `delivery="queued"`; anything else needs `allow_foreground`.
  A missing, ambiguous or incompletely read target is refused — it never clicks
  the window centre or picks the first lookalike. `target` accepts the existing
  string form or the exact selector below
- `type_text(hwnd, target, text)` — `WM_SETTEXT` first, verified by read-back
  (`effect_verified`, or `text readback mismatch`)
- `key(hwnd, keys)` — keystrokes; always needs the foreground, and only when the
  window really holds it
- `scroll(hwnd, target, direction)` — UIA `ScrollPattern` with the documented
  enum pair; compares the position before and after, so a no-op is a failure
- `reveal(hwnd)` — shows a hidden window; this one does take the foreground
- `open_app(command, accessibility=false)` — starts a program **without letting
  it pop to the front**. Only windows proven to descend from the new process are
  hidden; anything else is listed as a candidate and left alone

**The generic routes**

- `invoke_pattern(hwnd, pattern, target, method, args=[])` — read or call one
  public UIA pattern member (`Value`, `GetSelection`, `DocumentRange.GetText`).
  Members on the explicit read-only table run in the background; everything else
  needs `allow_foreground`. Results are projected to plain data: a TextRange
  becomes bounded text, a Control becomes its metadata, and an object without a
  projection is reported as `result unsupported` rather than dropped. This
  includes background queries of Legacy `Name` / `Description` / `Value` and
  Window `WindowVisualState`; unknown members and setters still need permission
- `post_message(hwnd, msg, ...)` — raw window messages: `wait=true` sends with
  `SendMessageTimeoutW` and returns the message's own signed result, `wait=false`
  queues with `PostMessageW` and reports only `queued`. `WM_GETTEXT`/`WM_SETTEXT`
  are marshalled for you — no pointer ever crosses the protocol — and a write is
  verified by reading the control back inside the same budget. Broadcasts,
  `WM_COPYDATA`, `WM_DROPFILES` and same-process windows are refused

**Memory**

- `recall(query, ...)` — exact key, or that app's versions as candidates. Each
  plan carries `uses_foreground`, `reviewed`, `proven`, `rank` and its body. A
  truncated body comes with `next_body_offset`; continue with
  `recall(key, plan_id=..., body_offset=next)` and only trust the steps when
  every piece shares one `revision`
- `remember(app, version, plan_id, summary, cost, body, uses_foreground)` —
  stores one plan per `app@version`. `version=null` means "not known yet": it is
  stored as `app@unversioned`, can never be marked reviewed or proven, and is
  never upgraded in place
- `approve(...)`, `confirm_proven(...)` — the two trust bits, kept separate.
  Reviewed means the user read the plan; proven means it repeated real successes.
  Both take the `expected_revision` you showed the user, so a plan that changed
  underneath returns `stale plan` instead of inheriting an old confirmation
- `forget(app, version, plan_id, expected_revision, confirm)` — deletes a plan
  that is no longer true. Errors are evidence and stay; a superseded fact does
  not, because `recall` would otherwise hand it to the next caller as current.
  Removing one plan needs its revision (the same guard `approve` uses); removing
  the last plan removes the record, and an empty `plan_id` deletes the whole
  record only with `confirm=true`. Inherited `see` records are pointers and are
  refused here

**A desktop you can look at**

- `private_desktop(action, name="", allow_foreground=false)` — creates a separate
  desktop for automation and, on request, brings it to your screen. `status` is
  read-only; `create` does not switch anything; `show`, `hide` and `close` change
  what you are looking at and need `allow_foreground=true`. Every result reports
  `visible_desktop` as the desktop that really receives input — a refused switch
  names where the screen actually is instead of claiming success. This is not a
  sandbox: a program on another desktop still runs with your rights.

### Exact target selectors

`click`, `type_text`, `scroll`, `invoke_pattern` and `find_items` accept a selector object:

```json
{"automation_id": "search", "control_type": "EditControl", "rect": [120, 80, 300, 28]}
```

The only fields are `name`, `automation_id`, `control_type` (strict strings),
`native_hwnd` (a positive strict integer), and `rect` (four strict integers in
screen `[x, y, width, height]` form, with positive width and height). Include at
least one nonempty string identity or `native_hwnd`; a rectangle alone is
refused. Unknown fields, `nth`, index selectors and substring selectors are
refused. Every supplied field must match exactly, with case preserved, on one
unique element in the current complete tree. Use `see.elements[].control_type`
for the control type. An unreadable required field, incomplete tree, changed
rectangle, missing control or ambiguity refuses the action before it starts.
Readable anonymous nodes remain candidates even when their seven common pattern
probes are empty; omitting them could make a type selector appear falsely unique.
Keeping those nodes can reach the tree limit sooner; an incomplete read still
refuses the action, and selectors do not imply an automatic speedup.

Structured click/type targets resolve all predicates first. A verified matching
native child HWND with an allowed control class can use the existing background
message route; other targets keep the UIA permission gate. Selectors carry plain
data across the worker boundary and retain no cached UIA objects. Existing
string matching stays unchanged, including `invoke_pattern`'s exact-only string
matching and its explicit `target=""` root-window form.

### Querying item containers

`find_items` uses `property_id=0,value=null` to enumerate a provider sequence;
positive property IDs accept a strict bool, int32, finite float or string up to
6000 characters. For example, after confirming the actual window/container:

```json
{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":0,"max_items":100,"timeout_ms":8000}
```

`start_index` skips matches, and each page rescans from NULL. Inspect `items`,
`read_errors`, `metadata_complete`, `result_truncated`, `has_more` and
`next_start_index`. `snapshot` is always false. `complete` requires offset zero,
an explicit provider end, and lossless metadata; a later page's `reached_end`
only describes that suffix. Compare overlapping pages and an independent
business total before claiming coverage. Provider order can change, equal data
items can be skipped, and runtime IDs are only evidence of identity/cycles in
the current enumeration, not stable cross-page keys. Duplicate names are kept.

The generic `invoke_pattern.args` contract still rejects null list items and
arbitrary Control references. `find_items` is the dedicated adaptation for this
container query. See the [implementation contract](docs/specs/2026-11-08-implementation-handoff.md)
for limits, result fields and failure semantics.

### What "success" means

`returned`, `queued`, `call_completed` and a pattern's `False` all mean only that
the call reached something. Verify the effect: read the text back, check the
control state, compare the scroll position. A worker timeout is
`execution_state="unknown"` — the action may have run, so look at the window
before doing anything else, and never resend a write or a click automatically.

### The companion skill

`skills/windows-app-automation/SKILL.md` is a single self-contained skill for
choosing a route across native controls, UIA/Legacy, Electron, UWP/WinUI,
self-drawn interfaces and virtualised lists — including the failure branches and
the directions nobody has tried yet. Its historical starting observations stay
explicitly labelled; new application facts belong in memory, per version.

The skill compares the current baseline with plausible alternatives using the
whole cost of locating, invoking and verifying an effect. Memory `rank` records
trust, not efficiency. It supplies concrete routes: native child text/status
queries, direct root-pattern reads when the root owns the content, Value/Text/
Legacy cross-checks, Selection/Grid metadata, list search/pagination/export,
official APIs/CLIs, UWP content hosts and controlled Electron launch comparisons.
Each route explains its trigger, operation, verification and permission or
adapter gap. An available route is checked against the actual task and total
cost; the skill does not claim an unmeasured speedup.

One stalled scrolling loop produces a partial result and ends that loop;
discovery continues through relevant remaining routes. Record the reason for
each untried, blocked or deferred alternative. This requires neither brute-force
experimentation nor automatic replay or unauthorized application restarts.

### The permission gate

When an action cannot be done without the foreground, or a generic member is
not on the read-only table:

```json
{
  "ok": false,
  "needs_permission": true,
  "reason": "no single native control matching 'X' that accepts a window message",
  "detail": "'Window title' can only be reached through UIA or the real cursor, and both may move the foreground to that window.",
  "execution_state": "not_started",
  "effect_verified": false,
  "retry_safe": true,
  "hint": "Show this to the user. Retry with allow_foreground=true only after they agree."
}
```

Every window tool also reports `foreground_before`, `foreground_after` and
`foreground_changed`. That is two samples around one call — it cannot prove
focus was never taken in between, and it never replaces asking first.

## Install

DeskWeft was previously named `winmcp`. New installations use the `deskweft`
package, CLI and client registration, and the `deskweft-helper` scheduled task.
During migration, replace the old task and registration so only one service
writes the memory store.

Memory resolves `DESKWEFT_MEMORY_DIR`, then the legacy `WINMCP_MEMORY_DIR`, then
`%LOCALAPPDATA%\winmcp\memory`. The old default data path is intentional: this
rename does not move or rewrite existing records. Historical live reports keep
their original commands, paths and source hashes; naming changes require new
offline and deployment checks and do not repeat those GUI measurements.

```powershell
git clone https://github.com/abigaha/deskweft.git $env:LOCALAPPDATA\deskweft
cd $env:LOCALAPPDATA\deskweft
uv venv .venv --python 3.14
uv pip install --python .venv\Scripts\python.exe "windows-mcp==0.8.8"
uv pip install --python .venv\Scripts\python.exe -e .
pwsh -File .\install.ps1     # registers the logon task, starts the server
```

The installer waits up to 30 seconds for a single local listener and verifies
that it belongs to this installation. The server listens on
`http://127.0.0.1:8765/mcp`; task registration alone does not prove readiness.

Register it in a client, e.g. Codex `~/.codex/config.toml`:

```toml
[mcp_servers.deskweft]
url = "http://127.0.0.1:8765/mcp"
required = false
```

Reload existing client sessions to pick up the renamed registration and
synchronized skill.

### If `PrintWindow` returns blank frames

A blank frame is reported as `image_unavailable`, and the cause is not always
the same: a GPU overlay, protected content, a minimised window, a zero-sized
rectangle, a failed `GetWindowDC`/`PrintWindow`/`GetDIBits`, or a single-colour
image. Record which one applies before attributing it to the GPU — and note that
the tree is separate: a blank capture does not stop the semantic routes.

An earlier version of this README blamed directory ACLs and called
`S-1-4-*` "capability SIDs". Microsoft documents application package capability
SIDs with the prefix `S-1-15-3`, so that classification was wrong, and the
causal claim was never reproduced. If capture works from one interpreter and
fails from another, keep the full interpreter path, the ACL, the real API error
and a comparable environment rather than assuming a cause:

```powershell
(Get-Acl $path).Access | Select-Object IdentityReference, FileSystemRights, AccessControlType
```

Installing under `%LOCALAPPDATA%` remains a reasonable default; it is not a
diagnosis.

## Self-check

```powershell
cd $env:LOCALAPPDATA\deskweft
.venv\Scripts\python.exe -m deskweft.check
```

This interactive diagnostic launches a synthetic fixture and supported apps.
Cleanup is limited to windows whose ownership is verified; skipped or
unconfirmed cases are reported. The GUI self-check was not run as part of
the rename.

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

### Historical QQ click routes

UIA `InvokePattern` on Chromium goes through IA2, which focuses the widget and
takes the foreground. `LegacyIAccessible.DoDefaultAction` does the same work
through MSAA and leaves focus alone. Measured on the same backgrounded window:

| Route | Effect landed | Cursor moved | Foreground moved |
|---|---|---|---|
| `LegacyIAccessible.DoDefaultAction` | yes | no | **no** |
| `InvokePattern` | no | no | **yes** |
| posted `WM_LBUTTONDOWN` to render host | no | no | no |

After native matching, `click()` tries the Legacy route only after
`allow_foreground` is authorized. The current default background route is a
verified native control message. The table is a historical QQ observation, not
a guarantee that Legacy never takes focus. Once an action may have run, failure
returns its actual state for verification; it does not automatically try another
write or click route.

### False successes this tool had to fix

Three separate times an API reported success while nothing happened. They are now
guarded, and the lesson is in the code:

- **`SetForegroundWindow` on a hidden window returns success** and
  `GetForegroundWindow` points at it, but the screen does not change. Guarded by
  also requiring `IsWindowVisible` and `not IsIconic`.
- **`ValuePattern.SetValue` on a Chromium input returns silently** and stores
  nothing. Guarded by reading the value back. A mismatch or unavailable read-back
  is reported for verification; it does not automatically replay the input.
- **`PostMessage(BM_CLICK)` to a render host returns 1** and does nothing. Guarded
  by only messaging real button classes.

The original ItemContainer gap came from `invoke_pattern` rejecting NULL and
Control-reference inputs. The dedicated `find_items` route now handles both
inside one call. Arbitrary Control inputs to other generic members remain
unsupported; projected metadata is not a reusable element handle.

## Real-world testing

On November 8, 2026, separate live `find_items` tests matched 300 synthetic WPF
items (including 12 duplicate labels) and 150 Explorer files against independent
fixture data, using overlapping pages. WPF preserved readable names and IDs
despite offscreen-property errors; Explorer returned all sampled metadata.
These used an in-process MCP client, a real worker and Windows providers, rather
than HTTP or the installed service. See the [ItemContainer live report](docs/reports/2026-11-08-itemcontainer-live.md)
for timings, the observed RuntimeId changes, timeout recovery and evidence limits.

The [QQ / WeChat live report](docs/reports/2026-11-08-qq-wechat-live.md)
separates successful navigation and search from foreground effects, failed
protection attempts, private-desktop experiments, and incomplete data coverage.
It records complete measured request costs and identifies unmeasured setup and
cleanup costs; the historical results below remain a separate record.

Historical report: 128 assertions, described at the time as seven suites,
against real applications — Notepad, Paint,
VS Code, Explorer, Calculator, Notepad++, and a live browser session.
The table actually lists nine suites. These results and the browser/form account
below are preserved history; this correction adds no new live measurements.

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

"""MCP server: address one window, never take the foreground.

Every desktop call goes through uia_worker.call: UIA objects belong to the
thread that made them, and a wedged provider call can only be stopped by
killing the process that runs it. This module therefore touches no COM object
and does no window I/O of its own beyond cheap metadata.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pydantic import StrictBool, StrictInt, StrictStr

from . import appinfo, launch as _launch_module, memory, uia_worker, win32

# Bound at import time so tests can replace one name instead of the module.
_launch = _launch_module.launch

INSTRUCTIONS = """\
Window-addressed desktop control for Windows. Never takes the foreground unless
the user has agreed; anything that might is refused with needs_permission
before it acts.

Start with windows() to get an hwnd, then app_info(hwnd) for the executable and
the evidence behind its version. recall("name@version") reads what earlier work
recorded for that version; recall("name") lists the versions that exist. A
reviewed/proven rank is a hint about where to look, never permission to act.

Reading is free, acting is not:
  - see(hwnd, with_tree=true) returns elements, native_children, timed_out,
    limit_reached and identity_complete. An empty tree can mean a timeout, a
    filter, a wrong window or a missing accessibility flag; it is not proof the
    application has no accessibility.
  - click/type_text/key/scroll act through a native control message when one
    matches uniquely. Otherwise they need allow_foreground=true, which the user
    must agree to first. A missing, ambiguous or incompletely read target is
    refused - the tool never clicks the window centre or picks the first
    lookalike.
  - invoke_pattern(hwnd, pattern, target, method, args) reaches members the
    fixed tools do not cover. Members on the read-only table work in the
    background; anything else needs allow_foreground=true. A Get prefix is not
    proof of safety.
  - post_message(hwnd, msg, ...) is the raw window-message route: wait=true for
    SendMessageTimeoutW, wait=false to queue with PostMessageW. WM_GETTEXT and
    WM_SETTEXT are marshalled for you; WM_SETTEXT is verified by reading back in
    the same budget. Pointers, broadcasts and unmanaged payloads are refused.

"returned", "queued", call_completed and a False from a pattern all mean only
that the call reached something. Verify the effect: read the text back, check
the control state, compare the scroll position. A worker timeout is
execution_state="unknown" - the action may have run, so inspect the window
before deciding anything; do not resend automatically.

Chromium/Electron applications (QQ, VS Code, Slack, Discord, Teams) keep their
accessibility tree off until it is asked for at launch. open_app(...,
accessibility=true) passes the flags that turn it on and keep it alive while
another window is in front. A tree of empty PaneControls means the app was
started without them. Re-running open_app does not restart an existing single-
instance app, so its flags may never apply - check the process instead of
retrying.

When a window is started with open_app, only windows proven to descend from the
new process are hidden; anything else that appears is listed as a candidate.
The foreground is handed back only when the window that took it is one of
those. If you switch to another application meanwhile, it stays in front.

Credential dialogs can appear for unrelated commands: Windows Credential
Manager opens "Select an account" (Avalonia classes) while a git command waits.
Find it with windows(), read it with see(), then let the user choose the
account - to select one on their behalf, ask them first.
"""


@asynccontextmanager
async def _lifespan(_server):
    """Recycle the worker when the serving process stops."""
    try:
        yield {}
    finally:
        await _shutdown()


async def _shutdown() -> None:
    uia_worker.close()


mcp = FastMCP(name="winmcp", instructions=INSTRUCTIONS, lifespan=_lifespan,
              strict_input_validation=True)


def _foreground() -> dict:
    before = win32.foreground()
    after = win32.foreground()
    return {"foreground_before": before, "foreground_after": after,
            "foreground_changed": before != after}


def _worker_call(action: str, parameters: dict, timeout_ms: int) -> dict:
    """The single path from a tool to UIA. Adds the shared foreground sample."""
    result = uia_worker.call(action, parameters, timeout_ms)
    if isinstance(result, dict):
        result.update(_foreground())
    return result


@mcp.tool
def open_app(command: StrictStr, args: StrictStr = "", settle: float = 2.5,
             show: StrictBool = False, accessibility: StrictBool = False) -> dict:
    """Start a program without letting it grab the screen.

    Only windows proven to descend from the new process are hidden, and the
    foreground is handed back only when one of those took it. Windows that
    cannot be attributed appear under window_candidates and are left alone.

    Set accessibility=True for Electron apps. Chromium keeps its tree off until
    launch (measured on QQ: 9 unnamed shell nodes without the flag, 128 named
    ones with it) and throws it away when another window comes forward; the
    flags here stop that. Re-running this does not restart a single-instance
    app, so the flags may not be adopted - check the process.
    """
    # settle stays a float for signature compatibility, but a JSON string would
    # reach `time.time() + settle` and raise; reject it as an argument instead.
    if isinstance(settle, bool) or not isinstance(settle, (int, float)) \
            or not 0 <= settle <= 120:
        return {"ok": False, "reason": "invalid arguments",
                "detail": "settle must be a number of seconds in 0..120",
                "execution_state": "not_started", "retry_safe": True}
    result = _launch(
        command, args, settle=settle, hide_new_windows=not show,
        accessibility=accessibility,
    )
    if result.get("hidden_windows"):
        result["hint"] = (
            "Windows are hidden. Use see(hwnd) to inspect one, or reveal(hwnd) "
            "to show it - reveal moves the foreground, so ask first."
        )
    result.update(_foreground())
    return result


@mcp.tool
def reveal(hwnd: StrictInt) -> dict:
    """Put a hidden window on screen. This DOES take the foreground.

    Ask the user before calling this: it is the one operation that changes what
    they are looking at.
    """
    if not win32.title(hwnd) and not win32.class_name(hwnd):
        return {"ok": False, "reason": "no such window", "detail": f"hwnd {hwnd} is gone"}
    ok = _launch_module.force_foreground(hwnd)
    return {
        "ok": ok,
        "hwnd": hwnd,
        "title": win32.title(hwnd),
        "is_foreground": win32.foreground() == hwnd,
        "visible": bool(win32.user32.IsWindowVisible(hwnd)),
        "note": "" if ok else "the window did not become visible and foreground; nothing changed on screen",
    }


@mcp.tool
def windows() -> list[dict]:
    """List visible top-level windows: hwnd, title, class, pid, rect, foreground.

    Cheap - window metadata only, no UI tree and no screenshot. Start here to
    find the hwnd every other tool needs. Hidden windows are not listed; a
    window returned by open_app comes with its own hwnd.
    """
    return win32.list_windows()


@mcp.tool
def see(hwnd: StrictInt, with_tree: StrictBool = False, timeout_ms: StrictInt = 1500,
        max_elements: StrictInt = 200):
    """Look at one window without disturbing the user.

    Captures the window with PrintWindow whether or not it is in front, without
    moving the cursor or changing the foreground. with_tree=True adds the
    accessibility tree, the native child control handles, and the diagnostics
    that say whether the read was complete.

    An empty elements list is not proof the application has no accessibility:
    check timed_out, limit_reached, identity_complete and tree_diagnostics.
    Buttons and editors are often found more reliably through native_children.
    """
    result = _worker_call("see", {"hwnd": hwnd, "with_tree": with_tree,
                                  "timeout_ms": timeout_ms,
                                  "max_elements": max_elements},
                          max(3000, timeout_ms + 1000))
    if not isinstance(result, dict) or not result.get("ok"):
        return [json.dumps(result if isinstance(result, dict) else
                           {"ok": False, "reason": "worker result invalid"}, ensure_ascii=False)]
    meta = result["meta"]
    # see returns content blocks rather than a dict, so the shared foreground
    # sample has to be merged into meta - the one place it can survive.
    for field in ("foreground_before", "foreground_after", "foreground_changed"):
        if field in result:
            meta[field] = result[field]
    # Text first, image second: FastMCP only turns Image instances into image
    # content blocks when they sit beside plain text, not beside a dict.
    response: list = [json.dumps(meta, ensure_ascii=False)]
    if result.get("png"):
        response.append(Image(data=result["png"], format="png"))
    return response


@mcp.tool
def click(hwnd: StrictInt, target: StrictStr = "", allow_foreground: StrictBool = False) -> dict:
    """Click one named control.

    A uniquely matching native control takes a window message (measured 0.0 ms,
    foreground untouched) and reports delivery="queued" - the click still has to
    be verified. Otherwise the routes that may move the foreground need
    allow_foreground=true, which the user must agree to first.

    A missing, ambiguous or incompletely read target is refused: nothing is
    sent and the window centre is never clicked.
    """
    return _worker_call("click", {"hwnd": hwnd, "target": target,
                                  "allow_foreground": allow_foreground}, 8000)


@mcp.tool
def type_text(hwnd: StrictInt, target: StrictStr = "", text: StrictStr = "",
              allow_foreground: StrictBool = False) -> dict:
    """Write text into one named control.

    A uniquely matching native editor takes WM_SETTEXT and is verified by
    reading the text back; effect_verified says whether it matched. Anything
    else needs allow_foreground=true, exactly like click(). A readback that
    differs is reported as "text readback mismatch", and an unreadable value as
    verification_reason="readback unavailable" - neither is "nothing written".
    """
    return _worker_call("type_text", {"hwnd": hwnd, "target": target, "text": text,
                                      "allow_foreground": allow_foreground}, 8000)


@mcp.tool
def key(hwnd: StrictInt, keys: StrictStr = "", allow_foreground: StrictBool = False) -> dict:
    """Send keystrokes such as "Ctrl+s" or "Enter".

    Keyboard focus belongs to the foreground window, so this needs the user's
    permission and returns needs_permission until allow_foreground=true. Even
    then the target must be the foreground window and on screen, or nothing is
    sent - keystrokes would land in whatever is really in front.
    """
    return _worker_call("key", {"hwnd": hwnd, "keys": keys,
                                "allow_foreground": allow_foreground}, 8000)


@mcp.tool
def scroll(hwnd: StrictInt, target: StrictStr = "", direction: StrictStr = "down",
           allow_foreground: StrictBool = False) -> dict:
    """Scroll one control with UIA's ScrollPattern.

    direction is "up" or "down"; the call uses the documented ScrollAmount pair,
    reports the provider's own return value, and compares the scroll position
    before and after. An unchanged position is a failure, not a success. Win32
    controls with no ScrollPattern can only move with the mouse wheel, which
    this tool does not do.
    """
    return _worker_call("scroll", {"hwnd": hwnd, "target": target,
                                   "direction": direction,
                                   "allow_foreground": allow_foreground}, 8000)


@mcp.tool
def app_info(hwnd: StrictInt) -> dict:
    """Executable, version and the evidence behind that version.

    No single source covers every application, so `source` says which rung
    answered: path_segment (exe path names the build) and child_cmdline (a
    renderer's --app-path names it) are strong; sole_candidate, file_version and
    sibling_dir are weaker and come with a warning; source=null means no
    evidence, and then the honest record is version=None -> app@unversioned.

    version_candidates is diagnostic only - it never decides the version.
    """
    return appinfo.app_info(hwnd)


@mcp.tool
def invoke_pattern(hwnd: StrictInt, pattern: StrictStr, target: StrictStr,
                   method: StrictStr, args: list | None = None,
                   allow_foreground: StrictBool = False,
                   timeout_ms: StrictInt = 8000) -> dict:
    """Read or call one public UIA pattern member on a uniquely named control.

    method is a public member path: "Value", "GetSelection",
    "DocumentRange.GetText". The last part is called when it is a method and
    read when it is a property. args holds finite JSON scalars only.

    Members on the read-only table run in the background; every other member
    needs allow_foreground=true first. That table is explicit - a Get prefix is
    not treated as proof of safety, and an application whose getter steals focus
    belongs in memory with uses_foreground=true.

    target="" means the window's root element. Any other target must resolve to
    exactly one control by exact AutomationId or exact name, from a complete
    tree; a miss, a tie or an incomplete tree refuses before the provider is
    called. Results are plain data: a TextRange becomes bounded text, a Control
    becomes its metadata, and an unsupported object is reported as
    result unsupported rather than silently succeeding.
    """
    return _worker_call("invoke_pattern",
                        {"hwnd": hwnd, "pattern": pattern, "target": target,
                         "method": method, "args": args,
                         "allow_foreground": allow_foreground,
                         "timeout_ms": timeout_ms},
                        timeout_ms)


@mcp.tool
def post_message(hwnd: StrictInt, msg: StrictInt, wparam: StrictInt = 0,
                 lparam: StrictInt = 0, allow_unsafe: StrictBool = False,
                 allow_foreground: StrictBool = False, wait: StrictBool = True,
                 timeout_ms: StrictInt = 1000, text: StrictStr | None = None,
                 max_chars: StrictInt = 4096) -> dict:
    """Send one window message: bounded sync, async queueing, or managed text.

    wait=true uses SendMessageTimeoutW and reports delivery="returned" with the
    message's own signed result; wait=false queues with PostMessageW and reports
    only delivery="queued". Neither proves the user's goal happened.

    WM_GETTEXT and WM_SETTEXT are marshalled here - you never pass a pointer.
    WM_SETTEXT is verified by reading the control back inside the same budget,
    and a mismatch or an unreadable value keeps the real state visible.

    Setter, click, keyboard, wheel and unknown messages all need
    allow_foreground=true; unknown scalars also need allow_unsafe=true, and
    messages that carry pointers (WM_COPYDATA, WM_DROPFILES) are refused either
    way. Permission is judged by effect, not by payload shape: WM_LBUTTONDOWN,
    WM_MOUSEWHEEL and WM_KEYDOWN are no-pointer messages that still click and
    type. Mouse parameters follow the Win32 convention: button messages use
    client coordinates, WM_MOUSEWHEEL uses screen coordinates and a signed wheel
    delta in the high word of wparam.
    """
    return win32.post_message(hwnd, msg, wparam, lparam, allow_unsafe,
                              allow_foreground, wait, timeout_ms, text, max_chars)


@mcp.tool
def recall(query: StrictStr, max_body_chars: StrictInt = 6000,
           plan_id: StrictStr = "", body_offset: StrictInt = 0) -> dict:
    """Look up what earlier work recorded, by app, version or exact key.

    An empty query returns only the stored keys. "name@version" is an exact key;
    a miss falls back to that app's other versions with exact=false. A Windows
    path or "app.exe" is reduced to the executable name first.

    Each plan carries uses_foreground, reviewed, proven, rank and its body. The
    whole response has one body budget; a plan marked truncated has
    next_body_offset, and you continue with recall(key, plan_id=..., body_offset=
    next). Only use steps once every piece was read with the same revision - a
    revision change means the plan changed and the pieces no longer belong
    together.

    Inherited plans (inherits != null) and family matches are candidates to
    explore, not this version's verified results: their rank is 0 on purpose.
    reviewed/proven describe the plan as a whole, never permission for the
    action you are about to take.
    """
    return memory.recall(query, max_body_chars, plan_id, body_offset)


@mcp.tool
def remember(app: StrictStr, version: StrictStr | None, plan_id: StrictStr,
             summary: StrictStr, cost: StrictStr, body: StrictStr,
             uses_foreground: StrictBool, overwrite: StrictBool = False) -> dict:
    """Store one plan for one app@version. Returns its revision.

    version=None records an observation whose actual version is unknown; it is
    stored as app@unversioned, can never be marked reviewed or proven, and is
    never upgraded in place - when the version is known, write a normal version
    record instead.

    Write the body with the documented sections so the knowledge survives:
    目标, 环境与适用条件, 已验证步骤, 已尝试但失败, 实测记录, 未解决, 未试方向,
    更新记录. Missing facts say "尚未记录" - not guessed, and never deleted.
    Keep failure paths and untried directions; the `## 未解决` section is what
    recall turns into unresolved gaps.

    Overwriting an existing plan id needs overwrite=true, and changed content
    resets that plan's reviewed and proven. Unknown side effects mean
    uses_foreground=true. This is text storage only: nothing in a body ever
    executes.
    """
    return memory.remember(app, version, plan_id, summary, cost, body,
                           uses_foreground, overwrite)


@mcp.tool
def approve(app: StrictStr, version: StrictStr | None, plan_id: StrictStr,
            expected_revision: StrictStr, reviewed: StrictBool = True) -> dict:
    """Mark one plan as reviewed by the user, or clear that mark.

    Pass the revision you actually showed the user. If the plan changed since
    then the call returns "stale plan" and writes nothing: read it again and ask
    again rather than refreshing the revision quietly, which would hand an old
    confirmation to new content.

    reviewed is the user's judgement of the plan - not proof it ran, and never
    permission to perform the action it describes.
    """
    return memory.approve(app, version, plan_id, expected_revision, reviewed)


@mcp.tool
def confirm_proven(app: StrictStr, version: StrictStr | None, plan_id: StrictStr,
                   expected_revision: StrictStr, proven: StrictBool = True) -> dict:
    """Mark one plan as repeatedly successful in real runs, or clear that mark.

    Only after several real successes, and after the user has confirmed this
    key, id and revision. Same revision check as approve: a stale revision
    writes nothing. The tool does not count runs by itself.
    """
    return memory.confirm_proven(app, version, plan_id, expected_revision, proven)


def main() -> None:
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, stateless_http=True)


if __name__ == "__main__":
    main()

"""MCP server: address one window and report execution and foreground evidence.

Every desktop call goes through uia_worker.call: UIA objects belong to the
thread that made them, and a wedged provider call can only be stopped by
killing the process that runs it. This module therefore touches no COM object
and does no window I/O of its own beyond cheap metadata.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Annotated, TypedDict

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from mcp.types import TextContent
from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr, with_config

from . import appinfo, launch as _launch_module, memory, uia_worker, win32
from .private_desktop import DesktopSession

# Bound at import time so tests can replace one name instead of the module.
_launch = _launch_module.launch

# One desktop per service process: it owns the handle and the record of what the
# screen was on before the first switch.
_desktop_session = DesktopSession()


@with_config(ConfigDict(extra="forbid"))
class Selector(TypedDict, total=False):
    """All supplied fields must match one current control exactly."""

    name: StrictStr
    automation_id: StrictStr
    control_type: StrictStr
    native_hwnd: Annotated[StrictInt, Field(gt=0)]
    rect: Annotated[list[StrictInt], Field(min_length=4, max_length=4)]


Target = StrictStr | Selector

INSTRUCTIONS = """\
Use the least intrusive source that covers the request. An authorized export,
file, CLI or API may answer it without a window. For a desktop task, windows()
lists visible windows; app_info(hwnd) reports executable and version evidence.
recall("name@version", max_body_chars=0) lists route summaries. Read the
selected plan with its returned key and id; its trust rank is not permission.

needs_permission is a tool gate, not foreground protection. A UIA provider can
activate its window even on a read. Check protection for the actual target and
method, or obtain authorization for a foreground route before calling it.
  - see(hwnd, native_only=true) lists native children without capturing an
    image or walking UIA. Check native_children_truncated before drawing
    conclusions about a missing or unique control.
  - see(hwnd, with_tree=true) returns elements, native_children, timed_out,
    limit_reached and identity_complete. An empty tree can mean a timeout, a
    filter, a wrong window or a missing accessibility flag; it is not proof the
    application has no accessibility.
  - click/type_text try a native control message when one matches uniquely.
    Other routes need allow_foreground=true, as do key and scroll. A missing,
    ambiguous or incompletely read target is
    refused - the tool never clicks the window centre or picks the first
    lookalike.
    target also accepts a selector object: name, automation_id, control_type,
    native_hwnd and rect [x,y,width,height]. All fields match exactly together;
    require at least one non-empty identity field or positive native_hwnd.
    rect is an additional filter, never a standalone coordinate click. A
    structured native target must first resolve uniquely in the complete tree.
  - invoke_pattern(hwnd, pattern, target, method, args) reaches members the
    fixed tools do not cover. Only listed read-only members can pass the gate
    without allow_foreground. A Get prefix is not proof of safety.
  - find_items(hwnd, target, ...) traverses ItemContainer inside one worker
    call, including virtualized items. Use property_id=0/value=null for all.
    Inspect reached_end, read_errors and truncation; pages rescan a live query,
    so compare independent IDs and known counts. RuntimeId is not a durable key.
  - post_message(hwnd, msg, ...) is the raw window-message route: wait=true for
    SendMessageTimeoutW, wait=false to queue with PostMessageW. WM_GETTEXT and
    WM_SETTEXT are marshalled for you; WM_SETTEXT is verified by reading back in
    the same budget. Pointers, broadcasts and unmanaged payloads are refused.

"returned", "queued", call_completed and a False from a pattern all mean only
that the call reached something. Verify the effect: read the text back, check
the control state, compare the scroll position. A worker timeout is
execution_state="unknown" - the action may have run, so inspect the window
before deciding anything; do not resend automatically.

Some tested Chromium/Electron versions needed accessibility flags for a usable
tree. open_app(..., accessibility=true) appends the documented Chromium flags;
verify the running process and read the target page again. This does not
guarantee a tree, background actions or complete data. Empty PaneControls can
be a clue to missing flags, occlusion, a wrong host or a provider failure;
check the evidence. Re-running
open_app does not restart an existing single-
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


mcp = FastMCP(name="deskweft", instructions=INSTRUCTIONS, lifespan=_lifespan,
              strict_input_validation=True)


def _worker_call(action: str, parameters: dict, timeout_ms: int) -> dict:
    """The single path from a tool to UIA. Adds the shared foreground sample."""
    before = win32.foreground()
    result = uia_worker.call(action, parameters, timeout_ms)
    if isinstance(result, dict):
        # Worker observations surround the action; replacing them loses evidence.
        result.setdefault("foreground_before", before)
        result.setdefault("foreground_after", win32.foreground())
        result["foreground_changed"] = result["foreground_before"] != result["foreground_after"]
    return result


@mcp.tool
def open_app(command: StrictStr, args: StrictStr = "", settle: float = 2.5,
             show: StrictBool = False, accessibility: StrictBool = False) -> dict:
    """Start a program and attempt to hide its newly owned windows.

    Only windows proven to descend from the new process are hidden, and the
    foreground is handed back only when one of those took it. Windows that
    cannot be attributed appear under window_candidates and are left alone.

    Hiding is attempted after launch, so a transient foreground change remains
    possible. Check visibility_control, hidden_windows[].still_visible and
    foreground samples; they do not prove it never appeared between samples.

    accessibility=True appends Chromium accessibility/occlusion flags. Check
    their actual adoption and the target page's tree for this app version;
    they do not guarantee background actions or complete data. Re-running
    this does not restart a single-instance app, so check its process.
    """
    # settle stays a float for signature compatibility, but a JSON string would
    # reach `time.time() + settle` and raise; reject it as an argument instead.
    if isinstance(settle, bool) or not isinstance(settle, (int, float)) \
            or not 0 <= settle <= 120:
        return {"ok": False, "reason": "invalid arguments",
                "detail": "settle must be a number of seconds in 0..120",
                "execution_state": "not_started", "retry_safe": True}
    before = win32.foreground()
    result = _launch(
        command, args, settle=settle, hide_new_windows=not show,
        accessibility=accessibility,
    )
    if result.get("hidden_windows"):
        result["hint"] = (
            "Windows are hidden. Use see(hwnd) to inspect one, or reveal(hwnd) "
            "to show it - reveal moves the foreground and needs the user's authorization."
        )
    result.setdefault("foreground_before", before)
    result.setdefault("foreground_after", win32.foreground())
    result["foreground_changed"] = result["foreground_before"] != result["foreground_after"]
    return result


@mcp.tool
def reveal(hwnd: StrictInt) -> dict:
    """Put a hidden window on screen. This DOES take the foreground.

    This explicitly restores a hidden window. Use the user's existing
    authorization when it covers this action; otherwise ask before calling.
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
        "note": "" if ok else "the window was not confirmed both shown and foreground; inspect visible and is_foreground before retrying",
    }


@mcp.tool
def windows() -> list[dict]:
    """List visible top-level windows: hwnd, title, class, pid, rect, foreground.

    Window metadata only, no UI tree and no screenshot. Use this when a
    desktop route needs an HWND. Hidden windows are not listed; a
    window returned by open_app comes with its own hwnd.
    """
    return win32.list_windows()


@mcp.tool
def see(hwnd: StrictInt, with_tree: StrictBool = False, timeout_ms: StrictInt = 1500,
        max_elements: StrictInt = 200, native_only: StrictBool = False):
    """Inspect one window using only the observation route needed.

    By default, capture a PrintWindow frame. with_tree=True also queries UIA
    and lists native children; a provider may take focus even on a read.
    Alternatively, native_only=True lists just native children in the worker:
    no screenshot or UIA tree. Do not combine it with with_tree=True. Check
    native_children_truncated before using the list to rule out duplicates.

    An empty elements list is not proof the application has no accessibility:
    check timed_out, limit_reached, identity_complete and tree_diagnostics.
    Buttons and editors are often found more reliably through native_children.
    """
    result = _worker_call("see", {"hwnd": hwnd, "with_tree": with_tree,
                                  "timeout_ms": timeout_ms,
                                  "max_elements": max_elements, "native_only": native_only},
                          max(3000, timeout_ms + 1000))
    if not isinstance(result, dict) or not result.get("ok"):
        return [TextContent(type="text", text=json.dumps(
            result if isinstance(result, dict) else
            {"ok": False, "reason": "worker result invalid"}, ensure_ascii=False))]
    meta = result["meta"]
    # see returns content blocks rather than a dict, so the shared foreground
    # sample has to be merged into meta - the one place it can survive.
    for field in ("foreground_before", "foreground_after", "foreground_changed"):
        if field in result:
            meta[field] = result[field]
    # An explicit block prevents FastMCP serializing a text-only list as an array.
    response: list = [TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))]
    if result.get("png"):
        response.append(Image(data=result["png"], format="png"))
    return response


@mcp.tool
def click(hwnd: StrictInt, target: Target = "", allow_foreground: StrictBool = False) -> dict:
    """Click one uniquely named control or exact composite selector.

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
def type_text(hwnd: StrictInt, target: Target = "", text: StrictStr = "",
              allow_foreground: StrictBool = False) -> dict:
    """Write text into one uniquely named control or exact composite selector.

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
def scroll(hwnd: StrictInt, target: Target = "", direction: StrictStr = "down",
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
def find_items(hwnd: StrictInt, target: Target = "", property_id: StrictInt = 0,
               value: StrictBool | StrictInt | Annotated[float, Field(strict=True, allow_inf_nan=False)] | StrictStr | None = None,
               start_index: StrictInt = 0, max_items: StrictInt = 100,
               timeout_ms: StrictInt = 8000) -> dict:
    """Query ItemContainer with NULL start and worker-local element continuation.

    property_id=0/value=null enumerates all; otherwise pass a property ID and
    bool/int32/finite float/string (Name=30005, AutomationId=30011,
    IsSelected=30079). Unsupported properties produce provider errors.
    max_items is 1..100; start_index is 0..10000 in the MATCHING sequence.
    Each page rescans a live list, not a snapshot; compare overlapping pages
    and known counts before claiming full coverage. Duplicate names survive.
    complete requires start_index=0, explicit provider end and lossless metadata.
    reached_end alone only proves the queried suffix ended. If a later row is
    clipped, the cursor revisits that row with a fresh budget. A clipped first
    row stays partial; only follow an advancing cursor. has_more=true without
    a cursor means the next offset exceeds the supported range. Inspect
    read_errors and result_truncated. COM references stay in the worker; this
    tool requests no Realize, selection, scrolling or focus operation.
    The parent deadline can discard a stuck worker; timeout state is unknown.
    """
    return _worker_call("find_items", {"hwnd": hwnd, "target": target,
                        "property_id": property_id, "value": value,
                        "start_index": start_index, "max_items": max_items,
                        "timeout_ms": timeout_ms}, timeout_ms)


@mcp.tool
def invoke_pattern(hwnd: StrictInt, pattern: StrictStr, target: Target,
                   method: StrictStr, args: list | None = None,
                   allow_foreground: StrictBool = False,
                   timeout_ms: StrictInt = 8000) -> dict:
    """Read or call one public UIA pattern member on a uniquely named control.

    method is a public member path: "Value", "GetSelection",
    "DocumentRange.GetText". The last part is called when it is a method and
    read when it is a property. args holds bool/int/finite float/str, or a
    {"$control": {"hwnd": ..., "automation_id": ...}} description resolved
    uniquely in this same window's current complete tree. These descriptions
    retain no COM identity; optional rect checks movement after a unique match.
    Cross-window controls, raw metadata and null list items are refused.
    args=null means no arguments.

    Members on the read-only table may be called without allow_foreground;
    other members require it. A getter can still take focus: check protection
    for this provider or obtain authorization for foreground use.

    target="" means the window's root element. Any other target must resolve to
    exactly one control by exact AutomationId/name or all selector fields, from a complete
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
    a known-version miss falls back to that app's other versions with
    exact=false. A missing app@unversioned observation returns no matches.
    A Windows path or "app.exe" is reduced to the executable name first.

    To choose a route without reading every body, use max_body_chars=0 with no
    plan_id. Compare summaries, cost and uses_foreground; then read only the
    selected plan using the returned key and plan_id with a positive budget.
    The body budget is shared across results. Continue at next_body_offset
    until it is null, even if the final suffix is marked truncated. Keep the
    same key for inherited plans and restart if the revision changes.

    Inherited plans (inherits != null) have rank 0. Family matches retain the
    returned version's own rank; they are candidates to explore, not the
    requested version's verified results. reviewed/proven describe the stored
    plan, never permission for the action you are about to take.
    """
    return memory.recall(query, max_body_chars, plan_id, body_offset)


@mcp.tool
def remember(app: StrictStr, version: StrictStr | None, plan_id: StrictStr,
             summary: StrictStr, cost: StrictStr, body: StrictStr,
             uses_foreground: StrictBool, overwrite: StrictBool = False,
             expected_revision: StrictStr | None = None) -> dict:
    """Store one plan for one app@version. Returns its revision.

    version=None records an observation whose actual version is unknown; it is
    stored as app@unversioned, can never be marked reviewed or proven, and is
    never upgraded in place - when the version is known, write a normal version
    record instead.

    In summary, name the task and condition, any known failed route and what
    would justify retrying or trying a different route. Do not invent evidence.
    Write the body with the documented sections so the knowledge survives:
    目标, 环境与适用条件, 已验证步骤, 已尝试但失败, 实测记录, 未解决, 未试方向,
    更新记录. Missing facts say "尚未记录" - not guessed, and never deleted.
    Keep failure paths and untried directions; the `## 未解决` section is what
    recall turns into unresolved gaps.

    For an update, pass overwrite=true and the revision you actually read as
    expected_revision. A stale plan is not written; re-read and reconcile the
    new evidence. Omitting the revision keeps the old unguarded overwrite.
    Changed content resets reviewed and proven. Unknown side effects mean
    uses_foreground=true. This is text storage only: nothing in a body ever
    executes.

    Memory holds routes, not evidence. Store what was measured and where, and
    keep the raw JSON, screenshots and reports in the repository; a plan whose
    only copy is here is one bad write away from being lost. Replacing a whole
    record to "clean it up" also deletes failure paths and untried directions,
    which are exactly the parts the next session needs.
    """
    return memory.remember(app, version, plan_id, summary, cost, body,
                           uses_foreground, overwrite, expected_revision)


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


@mcp.tool
def forget(app: StrictStr, version: StrictStr | None, plan_id: StrictStr = "",
           expected_revision: StrictStr = "", confirm: StrictBool = False) -> dict:
    """Delete a plan that is no longer true, or a whole record.

    Errors are evidence and should stay; a fact that has been superseded is not -
    recall would hand it to the next caller as current. Deleting one plan needs
    its id and the `expected_revision` you were shown, so a plan that changed
    underneath returns "stale plan" instead of deleting newer content. Removing
    the last plan removes the record, and an empty plan_id deletes the whole
    record only with confirm=true.

    An inherited record (`see`) cannot be deleted here: it is a pointer, and the
    stored version it points at is what carries the content. This never touches
    other versions or other applications.
    """
    return memory.forget(app, version, plan_id, expected_revision, confirm)


@mcp.tool
def private_desktop(action: StrictStr, name: StrictStr = "",
                    allow_foreground: StrictBool = False) -> dict:
    """Create or inspect a private desktop, or switch to it on request.

    A private desktop is a separate screen: a program started on it does not
    appear in front of you, and it keeps running while you use your own desktop.
    `show` brings that desktop to your screen so you can look at it and take
    over yourself; `hide` sends it back to where you were.

    These actions do not start or move an application or the UIA worker onto
    that desktop. Creating one does not isolate an existing target, and show
    switches the user's screen rather than providing a background preview.

    Actions: `status` (read only), `create` (does not switch), `show`, `hide`,
    `close`. Showing or hiding changes what you are looking at, so both need
    allow_foreground=true. The result always reports `visible_desktop` as the
    desktop that actually receives input, never what this call hoped for - a
    refused switch says so and names where the screen really is.

    Switching desktops is not a sandbox: a program on another desktop still runs
    with your rights, and anything it writes is still written.
    """
    before = win32.foreground()
    if action == "status":
        result = _desktop_session.status()
    elif action == "create":
        created = _desktop_session.create(name or f"DeskWeft_{int(time.time())}")
        if created.get("ok"):
            created.update(_desktop_session.status())
        result = created
    elif action in ("show", "hide", "close"):
        if not allow_foreground:
            result = {
                "ok": False, "needs_permission": True,
                "reason": f"{action} changes what is on your screen",
                "detail": "Switching desktops hides whatever you are looking at. "
                          "Ask the user first, then retry with allow_foreground=true.",
                "execution_state": "not_started", "effect_verified": False,
                "retry_safe": True,
            }
        else:
            result = getattr(_desktop_session, action)()
            if isinstance(result, dict) and result.get("ok"):
                # The switch happened; whether the user's work survived is not
                # something this call can verify.
                result["effect_verified"] = False
    else:
        result = {"ok": False, "reason": "invalid arguments",
                  "detail": f"unknown action {action!r}; use status, create, "
                            "show, hide or close",
                  "execution_state": "not_started", "retry_safe": True}
    result.setdefault("visible_desktop", _desktop_session.visible_desktop())
    result["foreground_before"] = before
    result["foreground_after"] = win32.foreground()
    result["foreground_changed"] = before != result["foreground_after"]
    return result


def main() -> None:
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, stateless_http=True)


if __name__ == "__main__":
    main()

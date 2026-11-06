"""MCP server: address one window, never take the foreground."""

from __future__ import annotations

import json

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from . import act, launch, tree, win32

INSTRUCTIONS = """\
Window-addressed desktop control for Windows. Never takes the foreground unless
the user has agreed; blocked actions return needs_permission.

Watch for credential dialogs on git operations. `git push` / `git remote add`
can make Windows Credential Manager open a window titled "Select an account"
(Avalonia, class `Avalonia-*`). It blocks the git command while it waits, and
because its title contains no "git" keyword a keyword-based window scan misses
it - agents then wait forever with no output. If any git command stalls, run
windows() and look for new top-level windows, then use see(hwnd, with_tree=True)
to find the account ListItem and the "Continue" button and click them. The
dialog belongs to a different process, so match by title/class, not by pid.
"""

mcp = FastMCP(name="winmcp", instructions=INSTRUCTIONS)


@mcp.tool
def open_app(command: str, args: str = "", settle: float = 2.5, show: bool = False) -> dict:
    """Start a program without letting it grab the screen.

    Plainly starting an app pops its window in front of whatever the user is
    doing - the app calls SetForegroundWindow itself about 200 ms in. This
    hides the new windows as they appear and hands the foreground back, so the
    user's screen never jumps.

    Left at show=False the app runs hidden; call see() on the returned window
    handle to look at it, or reveal() to put it on screen on purpose.
    """
    result = launch.launch(command, args, settle=settle, hide_new_windows=not show)
    if result.get("hidden_windows"):
        result["hint"] = (
            "Windows are hidden. Use see(hwnd) to inspect one, or reveal(hwnd) "
            "to show it - reveal moves the foreground, so ask first."
        )
    return result


@mcp.tool
def reveal(hwnd: int) -> dict:
    """Put a hidden window on screen. This DOES take the foreground.

    Ask the user before calling this: it is the one operation that changes what
    they are looking at.
    """
    if not win32.title(hwnd) and not win32.class_name(hwnd):
        return {"ok": False, "reason": "no such window", "detail": f"hwnd {hwnd} is gone"}
    ok = launch.force_foreground(hwnd)
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

    Cheap (~15 ms) - window metadata only, no UI tree, no screenshot. Start here
    to find the hwnd every other tool needs.
    """
    return win32.list_windows()


@mcp.tool
def see(hwnd: int, with_tree: bool = False, timeout_ms: int = 1500, max_elements: int = 200):
    """Look at one window without disturbing the user.

    Captures the window with PrintWindow (~20-30 ms) whether or not it is in
    front, without moving the cursor or changing the foreground. Set
    with_tree=True for the accessibility tree - that is what you need to find
    controls by name.

    Two known limits, both reported rather than hidden: browsers and Electron
    apps can take 10+ s to read in the background (the timeout stops that and
    sets timed_out), and windows drawn through a GPU overlay come back blank
    (reported as image_unavailable).
    """
    if not win32.title(hwnd):
        return {"ok": False, "reason": "no such window", "detail": f"hwnd {hwnd} is gone"}

    meta = {"ok": True, "hwnd": hwnd, "title": win32.title(hwnd), "class": win32.class_name(hwnd)}
    image = None

    grabbed = win32.grab(hwnd)
    if grabbed is None:
        meta["image_unavailable"] = (
            "PrintWindow returned a blank frame: GPU overlay, protected content, or minimised"
        )
    else:
        data, w, h = grabbed
        meta["image_size"] = [w, h]
        image = Image(data=data, format="png")

    if with_tree:
        elements, timed_out = tree.read(hwnd, timeout_ms, max_elements)
        meta["elements"] = [{k: v for k, v in e.items() if k != "_el"} for e in elements]
        meta["element_count"] = len(elements)
        meta["timed_out"] = timed_out
        if timed_out:
            meta["tree_note"] = f"stopped at {timeout_ms} ms - raise timeout_ms or target a smaller window"

    # Text first, image second: FastMCP only turns Image instances into image
    # content blocks when they sit beside plain text, not beside a dict.
    response: list = [json.dumps(meta, ensure_ascii=False)]
    if image is not None:
        response.append(image)
    return response


@mcp.tool
def click(hwnd: int, target: str = "", allow_foreground: bool = False) -> dict:
    """Click a control by name, without taking the foreground.

    Tries a window message to a native control first (measured 0.0 ms, foreground
    untouched). When the window has no such control, the only remaining route
    moves the foreground, so this returns needs_permission rather than acting.
    Call again with allow_foreground=true only after the user agrees.
    """
    return act.act(hwnd, "click", target=target, allow_foreground=allow_foreground)


@mcp.tool
def type_text(hwnd: int, target: str = "", text: str = "", allow_foreground: bool = False) -> dict:
    """Write text into a control, without taking the foreground.

    Native text controls take WM_SETTEXT (measured 0.3 ms, foreground untouched,
    Unicode included). Anything else needs the foreground and returns
    needs_permission, exactly like click().
    """
    return act.act(hwnd, "type", target=target, text=text, allow_foreground=allow_foreground)


@mcp.tool
def key(hwnd: int, keys: str = "", allow_foreground: bool = False) -> dict:
    """Send keystrokes such as "Ctrl+s" or "Enter".

    Keyboard focus belongs to the foreground window, so this needs the user's
    permission and will not act until allow_foreground=true.
    """
    return act.act(hwnd, "key", text=keys, allow_foreground=allow_foreground)


@mcp.tool
def scroll(hwnd: int, target: str = "", direction: str = "down", allow_foreground: bool = False) -> dict:
    """Scroll a control.

    Background scrolling is unreliable on this machine (the scroll pattern
    raised COMError in testing), so expect needs_permission.
    """
    return act.act(hwnd, "scroll", target=target, text=direction, allow_foreground=allow_foreground)


def main() -> None:
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, stateless_http=True)


if __name__ == "__main__":
    main()

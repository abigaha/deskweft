"""Start a program without letting it grab the screen.

A freshly launched app calls SetForegroundWindow about 200 ms after start, which
is earlier than any hook can hide its window - the event arrives after the
window is already visible. Racing it loses, so this contends instead: hide every
new top-level window as it appears, and take the foreground back on every pass
until the app settles. Windows honours the restore because the target window is
the one the user was already using.
"""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes

from . import win32

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_HIDEWINDOW = 0x0080

user32 = win32.user32
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL


SW_RESTORE = 9
SW_SHOWNORMAL = 1


def is_shown(hwnd: int) -> bool:
    """True when the window is actually on screen.

    A minimised window reports IsWindowVisible=True and still sits at (-32000,
    -32000), so visibility alone is not enough - it must not be iconic either.
    """
    try:
        return bool(user32.IsWindowVisible(hwnd)) and not bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def force_foreground(hwnd: int) -> bool:
    """Make `hwnd` foreground and actually put it on screen.

    Two traps, both measured:
      - A window hidden with SWP_HIDEWINDOW is still a valid window, so
        SetForegroundWindow "succeeds" on it while nothing appears.
      - A minimised window reports IsWindowVisible=True but lives at
        (-32000,-32000); foreground and visible both look fine while the screen
        still shows the previous window.
    So restore first, skip the early exit unless the window is really shown, and
    judge success by both foreground and is_shown.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return False

    if not is_shown(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.2)

    if win32.foreground() == hwnd and is_shown(hwnd):
        return True

    me = ctypes.windll.kernel32.GetCurrentThreadId()
    fg = win32.foreground()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    attached = False
    try:
        if fg_thread and fg_thread != me:
            attached = bool(user32.AttachThreadInput(me, fg_thread, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)

    time.sleep(0.2)
    if not is_shown(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.2)
    return win32.foreground() == hwnd and is_shown(hwnd)


def launch(
    command: str,
    args: str = "",
    settle: float = 2.5,
    hide_new_windows: bool = True,
    keep_foreground: bool = True,
) -> dict:
    """Start a program. Its windows are hidden and the user keeps the foreground.

    Returns what actually happened, including whether the foreground held. A
    caller that needs the new window visible afterwards can pass
    hide_new_windows=False, but then the user will see it appear.
    """
    cmd = command if not args else f"{command} {args}"
    known = {ctypes.c_void_p(w["hwnd"]).value for w in win32.list_windows()}
    fg_before = win32.foreground()
    title_before = win32.title(fg_before)
    started = time.perf_counter()

    try:
        proc = subprocess.Popen(cmd, shell=False)
    except OSError as e:
        return {
            "ok": False,
            "reason": "could not start the program",
            "detail": f"{cmd!r}: {e}",
        }

    hidden: list[dict] = []
    hidden_hwnds: dict[int, str] = {}
    wander = 0
    deadline = time.time() + settle
    while time.time() < deadline:
        if hide_new_windows:
            for w in win32.list_windows():
                h = ctypes.c_void_p(w["hwnd"]).value
                if h in known:
                    continue
                # Hide every pass, not just the first: UWP apps re-show their
                # own window after being hidden, and Calculator did it 14 times.
                user32.SetWindowPos(
                    w["hwnd"], None, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_HIDEWINDOW,
                )
                hidden_hwnds[h] = w["class"]
                if not any(x["hwnd"] == h for x in hidden):
                    hidden.append({"hwnd": h, "class": w["class"], "title": w["title"][:60]})
        if keep_foreground and fg_before and win32.foreground() != fg_before:
            wander += 1
            force_foreground(fg_before)
        time.sleep(0.05)

    # A stubborn app keeps re-showing for a moment after the loop ends, so make
    # final passes before declaring the foreground preserved. UWP apps are the
    # worst case: Calculator re-creates its ApplicationFrameWindow every time it
    # is hidden, so hiding has to keep running until nothing new appears.
    quiet = 0
    for _ in range(40):
        appeared = False
        if hide_new_windows:
            for w in win32.list_windows():
                h = ctypes.c_void_p(w["hwnd"]).value
                if h in known:
                    continue
                user32.SetWindowPos(
                    w["hwnd"], None, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_HIDEWINDOW,
                )
                hidden_hwnds[h] = w["class"]
                if not any(x["hwnd"] == h for x in hidden):
                    hidden.append({"hwnd": h, "class": w["class"], "title": w["title"][:60]})
                    appeared = True
        if keep_foreground:
            force_foreground(fg_before)
        # Stop once the situation looks stable and the foreground is ours.
        stable = (not appeared) and (not keep_foreground or win32.foreground() == fg_before)
        quiet = quiet + 1 if stable else 0
        if quiet >= 8:
            break
        time.sleep(0.08)

    fg_after = win32.foreground()
    # Report the real state of the windows, not the state we asked for.
    for item in hidden:
        item["still_visible"] = bool(user32.IsWindowVisible(item["hwnd"])) if user32.IsWindow(item["hwnd"]) else None
    return {
        "ok": True,
        "pid": proc.pid,
        "command": cmd,
        "hidden_windows": hidden,
        "foreground_before": fg_before,
        "foreground_before_title": title_before[:60],
        "foreground_after": fg_after,
        "foreground_preserved": fg_after == fg_before,
        # How often the app tried to take focus; useful for judging the app.
        "foreground_contests": wander,
        "took_ms": round((time.perf_counter() - started) * 1000),
    }

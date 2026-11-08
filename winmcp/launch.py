"""Start a program without letting it grab the screen.

A freshly launched app calls SetForegroundWindow about 200 ms after start, which
is earlier than any hook can hide its window. Racing it loses, so this contends
instead: hide the new windows and take the foreground back while the app
settles.

Hiding a window is only safe when the window is proven to belong to what we
started. "A window appeared after I launched" is not proof - another program
can open one at the same moment - so ownership comes from the process tree
(parent chain plus creation time), and a window whose owner cannot be proven is
reported, never hidden.
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
SW_RESTORE = 9
SW_SHOWNORMAL = 1

MAX_CANDIDATES = 200

user32 = win32.user32
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
]
_kernel32.GetProcessTimes.restype = wintypes.BOOL


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002

# How long the hiding loop may run: launch contention, not a measurement.
_SETTLE_POLL = 0.05


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


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _all_top_level_windows() -> list[int]:
    """Every top-level window, hidden ones included.

    win32.list_windows() only lists visible, titled windows, which cannot prove
    that a window did not exist before the launch.
    """
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _):
        found.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _process_identity(pid: int) -> dict | None:
    """(pid, creation FILETIME) - an integer, so two PIDs are never confused.

    The creation time is what distinguishes a reused PID from the process that
    was actually started; the raw FILETIME stays an int to avoid losing its low
    bits in a float.
    """
    if not pid:
        return None
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                         ctypes.byref(kernel), ctypes.byref(user)):
            return None
        stamp = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return {"pid": int(pid), "created": int(stamp)}
    finally:
        _kernel32.CloseHandle(handle)


def _snapshot_parents() -> dict[int, int]:
    """pid -> parent pid for every process, from one Toolhelp snapshot."""
    parents: dict[int, int] = {}
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return parents
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return parents
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        _kernel32.CloseHandle(snapshot)
    return parents


def _descends_from(pid: int, root: int, parents: dict[int, int]) -> bool:
    """Walk the parent chain once, with a depth cap against cycles."""
    seen = 0
    current = parents.get(pid)
    while current and seen < 64:
        if current == root:
            return True
        current = parents.get(current)
        seen += 1
    return False


def _owned_window(hwnd: int, baseline: set[int], owned: dict[int, dict]) -> dict | None:
    """Is this window an owned one? Returns the basis for hiding it, or None."""
    if hwnd in baseline:
        return None
    pid = _window_pid(hwnd)
    if not pid or pid not in owned:
        return None
    now = _process_identity(pid)
    if now is None:
        return None
    record = owned[pid]
    # The PID alone proves nothing after a reuse; the creation time is what
    # ties this window to the process we started.
    if now["created"] != record["created"]:
        return None
    return {"pid": pid, "process_created_at": record["created"],
            "ownership_basis": record["basis"]}


def _owned_processes(root_pid: int, root_identity: dict) -> dict[int, dict]:
    """The launched process and every descendant whose identity still matches."""
    owned = {root_pid: {"created": root_identity["created"], "basis": "direct_process"}}
    parents = _snapshot_parents()
    if not parents:
        return owned
    for pid in list(parents):
        if pid == root_pid or pid in owned:
            continue
        if not _descends_from(pid, root_pid, parents):
            continue
        identity = _process_identity(pid)
        if identity is None:
            continue
        # A child of the right parent that started before the launch cannot be
        # ours; the parent link alone is not ownership.
        if identity["created"] < root_identity["created"]:
            continue
        owned[pid] = {"created": identity["created"], "basis": "observed_descendant"}
    return owned


def _hide(hwnd: int) -> bool:
    """Hide one window and say whether it really went away."""
    placed = user32.SetWindowPos(
        hwnd, None, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_HIDEWINDOW,
    )
    if not placed:
        return False
    return not bool(user32.IsWindowVisible(hwnd))


def launch(
    command: str,
    args: str = "",
    settle: float = 2.5,
    hide_new_windows: bool = True,
    keep_foreground: bool = True,
    accessibility: bool = False,
) -> dict:
    """Start a program. Its own windows are hidden and the user keeps the foreground.

    Windows are only hidden when the process tree proves they belong to this
    launch; anything else that appears meanwhile is listed as an unconfirmed
    candidate and left alone.
    """
    cmd = command if not args else f"{command} {args}"
    if accessibility:
        # Three flags, each measured on QQ (a Chromium app):
        #   --force-renderer-accessibility turns the tree on at all (9 -> 128 elements)
        #   --disable-backgrounding-occluded-windows and
        #   --disable-features=CalculateNativeWinOcclusion stop Chromium from throwing
        #   the tree away when another window comes forward.
        for flag in (
            "--force-renderer-accessibility",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
        ):
            if flag not in cmd:
                cmd = f"{cmd} {flag}"

    baseline = set(_all_top_level_windows())
    fg_before = win32.foreground()
    fg_identity = _process_identity(_window_pid(fg_before)) if fg_before else None
    title_before = win32.title(fg_before)
    started = time.perf_counter()

    try:
        proc = subprocess.Popen(cmd, shell=False)
    except OSError as error:
        return {
            "ok": False,
            "reason": "could not start the program",
            "detail": f"{cmd!r}: {error}",
        }

    root_pid = int(proc.pid)
    root_identity = _process_identity(root_pid)
    warnings: list[str] = []
    if root_identity is None:
        warnings.append("process identity unreadable: the launch's windows cannot be confirmed")

    hidden: list[dict] = []
    hidden_hwnds: set[int] = set()
    candidates: dict[int, dict] = {}
    candidates_truncated = False
    contested = 0
    deadline = time.time() + settle
    passes = 0
    quiet = 0

    while True:
        passes += 1
        appeared = False
        # Recompute ownership each pass: a launcher spawns its renderer a moment
        # after Popen returns, so a one-shot snapshot would miss every child.
        owned = (_owned_processes(root_pid, root_identity)
                 if root_identity else {})
        owned_hwnds: set[int] = set()
        for hwnd in _all_top_level_windows():
            if hwnd in baseline or hwnd in hidden_hwnds:
                continue
            record = _owned_window(hwnd, baseline, owned) if root_identity else None
            if record is None:
                if hwnd not in candidates and len(candidates) < MAX_CANDIDATES:
                    pid = _window_pid(hwnd)
                    candidates[hwnd] = {
                        "hwnd": hwnd, "pid": pid, "class": win32.class_name(hwnd),
                        "title": win32.title(hwnd)[:60], "ownership": "unknown",
                        "reason": ("process identity unreadable" if root_identity is None
                                   else "not proven to descend from the launched process"),
                    }
                elif hwnd not in candidates:
                    candidates_truncated = True
                continue
            appeared = True
            owned_hwnds.add(hwnd)
            if not hide_new_windows:
                continue
            hidden_hwnds.add(hwnd)
            succeeded = _hide(hwnd)
            if not succeeded:
                warnings.append(f"hide failed for hwnd {hwnd}")
            item = {"hwnd": hwnd, "class": win32.class_name(hwnd),
                    "title": win32.title(hwnd)[:60], "pid": record["pid"],
                    "process_created_at": record["process_created_at"],
                    "ownership_basis": record["ownership_basis"],
                    "hide_succeeded": succeeded}
            item["still_visible"] = (bool(user32.IsWindowVisible(hwnd))
                                     if user32.IsWindow(hwnd) else None)
            hidden.append(item)

        if keep_foreground and fg_before and win32.foreground() != fg_before:
            if _may_restore(fg_before, fg_identity, owned_hwnds):
                contested += 1
                force_foreground(fg_before)

        settled = time.time() > deadline
        stable = not appeared and (not keep_foreground or win32.foreground() == fg_before
                                   or not _may_restore(fg_before, fg_identity, owned_hwnds))
        quiet = quiet + 1 if stable else 0
        # Phase 1 contends for `settle` seconds; phase 2 keeps watching for a
        # moment so a window that appears late is still caught. Both phases are
        # hard-bounded, so a stubborn app cannot hold the call open.
        if settled and quiet >= 8:
            break
        if settled and passes > 400:
            break
        time.sleep(_SETTLE_POLL)

    for item in hidden:
        item["still_visible"] = (bool(user32.IsWindowVisible(item["hwnd"]))
                                 if user32.IsWindow(item["hwnd"]) else None)

    fg_after = win32.foreground()
    applied = [item for item in hidden if item["hide_succeeded"]]
    if not hide_new_windows:
        control = "not_requested"
    elif not hidden:
        control = "unconfirmed"
    elif len(applied) == len(hidden):
        control = "applied"
    else:
        control = "partial"
    return {
        "ok": True,
        "pid": root_pid,
        "command": cmd,
        "hidden_windows": hidden,
        "foreground_before": fg_before,
        "foreground_before_title": title_before[:60],
        "foreground_after": fg_after,
        "foreground_preserved": fg_after == fg_before,
        "foreground_contests": contested,
        "took_ms": round((time.perf_counter() - started) * 1000),
        "target_window_confirmed": bool(hidden),
        "visibility_control": control,
        "window_candidates": list(candidates.values()),
        "candidates_truncated": candidates_truncated,
        "warnings": warnings,
    }


def _may_restore(fg_before: int, fg_identity: dict | None,
                 owned_hwnds: set[int] | None = None) -> bool:
    """Take the foreground back only from the app we started.

    Two conditions, both required: the window the user was using still belongs
    to the same process (so a reused HWND is not "their" window anymore), and
    the window holding the foreground now is one we proved we launched. If the
    user switched to something else meanwhile - a chat, their editor - that was
    their choice, and pulling focus back would be the exact bug this tool
    exists to avoid.
    """
    if not fg_before or not fg_identity:
        return False
    current = win32.foreground()
    if not current or current == fg_before:
        return False
    if owned_hwnds is not None and current not in owned_hwnds:
        return False
    if not is_shown(fg_before):
        return False
    now = _process_identity(_window_pid(fg_before))
    return now is not None and now["created"] == fg_identity["created"]

"""A private desktop the user can see and drive on request.

Automation can run on a desktop that is not the input desktop, which keeps it out
of the user's way. The same capability, used deliberately, lets the user *look*
at that desktop and take over: SwitchDesktop makes it the visible one.

The rules that make that safe:
  - switching is never a side effect of automating. `create` only creates;
    `show` and `hide` are separate calls, and the tool that exposes them
    requires its own permission flag;
  - the desktop the user had is captured before the first switch, and going
    back uses that value rather than assuming "Default";
  - the reported state is what OpenInputDesktop says, not what this module
    hoped for. A refused switch reports the real desktop.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

DESKTOP_ALL_ACCESS = 0x01FF
DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2

_lock = threading.Lock()


def _load_user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      ctypes.c_void_p, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p]
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL,
                                    wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    user32.SwitchDesktop.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    return user32


def _name_of(user32, handle) -> str | None:
    """The desktop's name, or None if it cannot be read.

    The size-query form of GetUserObjectInformationW (NULL buffer) fails on some
    desktop handles, so a fixed buffer is used directly and grown once if the
    name does not fit.
    """
    if not handle:
        return None
    for chars in (256, 1024):
        buffer = ctypes.create_unicode_buffer(chars)
        needed = wintypes.DWORD(0)
        ok = user32.GetUserObjectInformationW(
            handle, UOI_NAME, buffer, chars * ctypes.sizeof(ctypes.c_wchar),
            ctypes.byref(needed))
        if ok:
            return buffer.value or None
        if ctypes.get_last_error() != 122:  # ERROR_INSUFFICIENT_BUFFER
            return None
    return None


class DesktopSession:
    """Owns at most one private desktop and the record of what is visible."""

    def __init__(self, user32=None):
        self._user32 = user32 or _load_user32()
        self._name: str | None = None
        self._handle = 0
        self._previous: str | None = None
        self._created_at: float | None = None

    # ---- queries ----

    def visible_desktop(self) -> str | None:
        """The desktop that is on screen, read from the input desktop."""
        handle = self._user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
        if not handle:
            return None
        try:
            return _name_of(self._user32, handle)
        finally:
            self._user32.CloseDesktop(handle)

    def status(self) -> dict:
        visible = self.visible_desktop()
        return {
            "ok": True,
            "private_desktop": self._name,
            "created": self._name is not None,
            "visible_desktop": visible,
            "private_is_visible": bool(self._name) and visible == self._name,
            "previous_desktop": self._previous,
        }

    # ---- actions ----

    def create(self, name: str) -> dict:
        with _lock:
            if self._name is not None:
                return {"ok": True, "name": self._name, "reused": True}
            if not name:
                return {"ok": False, "reason": "invalid arguments",
                        "detail": "the desktop needs a name"}
            handle = self._user32.CreateDesktopW(name, None, None, 0,
                                                 DESKTOP_ALL_ACCESS, None)
            if not handle:
                error = ctypes.get_last_error()
                return {"ok": False, "reason": "could not create desktop",
                        "detail": f"CreateDesktopW failed, error={error}"}
            self._name = name
            self._handle = handle
            self._created_at = time.time()
            return {"ok": True, "name": name, "reused": False}

    def show(self) -> dict:
        with _lock:
            if self._name is None or not self._handle:
                return {"ok": False, "reason": "no private desktop",
                        "detail": "create one before showing it",
                        "visible_desktop": self.visible_desktop()}
            current = self.visible_desktop()
            if current == self._name:
                return {"ok": True, "visible_desktop": current,
                        "previous_desktop": self._previous,
                        "already_visible": True}
            if self._previous is None:
                self._previous = current
            switched = self._user32.SwitchDesktop(self._handle)
            after = self.visible_desktop()
            if not switched or after != self._name:
                return {"ok": False, "reason": "desktop switch refused",
                        "detail": f"SwitchDesktop did not make {self._name!r} "
                                  f"visible; the screen is on {after!r}",
                        "visible_desktop": after,
                        "previous_desktop": self._previous}
            return {"ok": True, "visible_desktop": after,
                    "previous_desktop": self._previous}

    def hide(self) -> dict:
        with _lock:
            return self._hide_locked()

    def _hide_locked(self) -> dict:
        """The body of hide(); the caller already holds _lock."""
        current = self.visible_desktop()
        # An unreadable "current" must not be treated as "already hidden": that
        # is how a screen stayed on a private desktop after close() reported ok.
        if self._name is None or (current is not None and current != self._name):
            return {"ok": True, "visible_desktop": current,
                    "previous_desktop": self._previous,
                    "already_hidden": True}
        target = self._previous or "Default"
        if target == self._name:
            # The recorded "previous" is the private desktop itself, which
            # would switch to where we already are and loop forever.
            target = "Default"
        handle = self._user32.OpenDesktopW(target, 0, False, DESKTOP_ALL_ACCESS)
        if not handle:
            return {"ok": False, "reason": "could not open the previous desktop",
                    "detail": f"OpenDesktopW({target!r}) failed",
                    "visible_desktop": current}
        try:
            switched = self._user32.SwitchDesktop(handle)
        finally:
            self._user32.CloseDesktop(handle)
        after = self.visible_desktop()
        if not switched or after != target:
            return {"ok": False, "reason": "desktop switch refused",
                    "detail": f"could not return to {target!r}; "
                              f"the screen is on {after!r}",
                    "visible_desktop": after}
        self._previous = None
        return {"ok": True, "visible_desktop": after}

    def close(self) -> dict:
        with _lock:
            if self._name is None:
                return {"ok": True, "visible_desktop": self.visible_desktop(),
                        "closed": False}
            # One attempt: retrying a refused switch here could spin, and the
            # honest report is where the screen ended up.
            back = self._hide_locked()
            if not back.get("ok"):
                return {"ok": False, "closed": False, "name": self._name,
                        "visible_desktop": self.visible_desktop(), "hiding": back}
            name, handle = self._name, self._handle
            self._name = None
            self._handle = 0
            self._created_at = None
            self._previous = None
            if handle:
                self._user32.CloseDesktop(handle)
            return {"ok": back.get("ok", True), "closed": True, "name": name,
                    "visible_desktop": self.visible_desktop(),
                    "hiding": back}

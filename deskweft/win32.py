"""Window-targeted desktop control that never takes the foreground.

Three rules, in order:
  1. Address one window by handle, never the whole desktop.
  2. Act through window messages and UIA patterns - neither moves the cursor.
  3. UIA pattern calls DO steal the foreground (measured, 504-518 ms each).
     So the only way to touch a window that has no reachable control is to ask
     the user first, then retry with allow_foreground=True.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from windows_mcp.uia import ControlFromHandle, Control

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
DWORD_PTR = ctypes.c_size_t
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(DWORD_PTR),
]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT
]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if not n:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def foreground() -> int:
    return user32.GetForegroundWindow()


def list_windows() -> list[dict]:
    """Top-level visible windows. PrintWindow only needs these; no tree walk."""
    out: list[dict] = []
    fg = foreground()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        t = title(hwnd)
        if not t:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        out.append(
            {
                "hwnd": int(hwnd),
                "title": t,
                "class": class_name(hwnd),
                "pid": int(pid.value),
                "rect": [r.left, r.top, r.right - r.left, r.bottom - r.top],
                "foreground": hwnd == fg,
            }
        )
        return True

    user32.EnumWindows(_cb, 0)
    return out


def grab(hwnd: int) -> tuple[bytes, int, int] | None:
    """PrintWindow capture of one window, foreground untouched. None if blank."""
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    try:
        # PW_RENDERFULLCONTENT: needed for DirectComposition-backed windows.
        if not user32.PrintWindow(hwnd, mdc, 2):
            return None
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h
        bi.biPlanes = 1
        bi.biBitCount = 32
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0):
            return None
        from PIL import Image

        img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1).convert("RGB")
        # Windows that render through a GPU overlay come back a flat colour;
        # reporting that as a success would hand the model a blank picture.
        # getcolors returns None once there are more than maxcolors, which
        # means "lots of colours" - the good case, not a blank frame.
        palette = img.getcolors(maxcolors=2)
        if palette is not None and len(palette) <= 1:
            return None
        import io

        out = io.BytesIO()
        # Level 1 rather than the default 6: a photo-like wallpaper takes 245 ms
        # to encode at 6 and 76 ms at 1. The extra bytes are cheaper than making
        # every desktop capture wait a quarter second.
        img.save(out, "PNG", compress_level=1)
        return out.getvalue(), w, h
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)


def center(hwnd: int) -> tuple[int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left + r.right) // 2, (r.top + r.bottom) // 2


user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.c_void_p]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

GA_ROOT = 2


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def window_at(x: int, y: int) -> int:
    """The root window that owns screen point (x, y), or 0.

    This is what a real cursor click would hit. A tool that addresses one window
    must compare this against that window before moving the mouse, because
    otherwise the click lands on whatever happens to be on top.
    """
    hit = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hit:
        return 0
    root = user32.GetAncestor(hit, GA_ROOT)
    return int(root or hit)


def focus_window() -> int:
    """The focused control of the foreground window's thread, or 0.

    GetFocus() only answers for the calling thread, so a tool looking at another
    process must ask that thread instead.
    """
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return 0
    thread = user32.GetWindowThreadProcessId(foreground, None)
    if not thread:
        return 0
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
        return 0
    return int(info.hwndFocus or 0)



HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SW_RESTORE = 9
SW_SHOWNORMAL = 1

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL


def activate(hwnd: int) -> bool:
    """Try to make `hwnd` the foreground window. True if it ended up there.

    A background process may not call SetForegroundWindow - Windows silently
    refuses. Attaching to the current foreground thread's input queue lifts
    that restriction, which is the documented workaround. The topmost flicker
    is the last resort. Returning the truth matters: callers that type into a
    window which never came forward would send keys somewhere else.
    """
    if foreground() == hwnd:
        return True

    user32.ShowWindow(hwnd, SW_RESTORE if _is_iconic(hwnd) else SW_SHOWNORMAL)
    time.sleep(0.15)

    me = _kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(foreground(), None)

    attached = False
    try:
        if fg_thread and fg_thread != me:
            attached = bool(user32.AttachThreadInput(me, fg_thread, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)

    time.sleep(0.25)
    if foreground() == hwnd:
        return True

    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    time.sleep(0.25)
    return foreground() == hwnd


def _is_iconic(hwnd: int) -> bool:
    try:
        return bool(user32.IsIconic(hwnd))
    except Exception:
        return False


user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL


def children(hwnd: int) -> list[dict]:
    """Native child windows (classic Win32 controls have their own HWND)."""
    out: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(h, _):
        r = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        out.append(
            {
                "hwnd": int(h),
                "class": class_name(h),
                "text": title(h),
                "rect": [r.left, r.top, r.right - r.left, r.bottom - r.top],
            }
        )
        return True

    user32.EnumChildWindows(hwnd, _cb, 0)
    return out


# ---------- window messages ----------

WM_NULL = 0x0000
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
CB_GETCURSEL = 0x0147
LB_GETCURSEL = 0x0188

# Messages whose payload is a pointer, a handle or a struct this service does not
# marshal. allow_unsafe only relaxes the unknown-scalar check, never these.
_UNMANAGED = frozenset({0x004A, 0x0233})  # WM_COPYDATA, WM_DROPFILES

# Known messages that carry no pointer. Being on this list only means "no
# payload to marshal" - it says nothing about safety.
_SCALARS = frozenset({
    0x0000, 0x000E, 0x00F5, 0x00F0, 0x0147, 0x0188,
    0x0100, 0x0101, 0x0102, 0x0201, 0x0202, 0x020A,
})

# The ones that only answer a question. Everything else - a click, a keystroke,
# a wheel, a setter, an unknown scalar - changes the application and needs the
# same permission as any other action, even though it carries no pointer.
# Managed does not mean read-only: WM_GETTEXT is a query, WM_SETTEXT is a write.
_READ_ONLY_MESSAGES = frozenset({WM_NULL, WM_GETTEXTLENGTH, BM_GETCHECK,
                                 CB_GETCURSEL, LB_GETCURSEL, WM_GETTEXT})
_MANAGED_MESSAGES = frozenset({WM_GETTEXT, WM_SETTEXT})

# Class tokens that make a checkbox or list message meaningful. WindowsForms
# names its classes WindowsForms10.BUTTON..., so match anywhere in the string.
_CLASS_FOR_MESSAGE = {
    BM_GETCHECK: ("button",),
    CB_GETCURSEL: ("combobox",),
    LB_GETCURSEL: ("listbox",),
}

_BUTTON, _SETTER = BM_CLICK, frozenset({WM_SETTEXT})

SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002
SMTO_ERRORONEXIT = 0x0020

_PTR_BITS = ctypes.sizeof(ctypes.c_void_p) * 8
_WPARAM_MAX = (1 << _PTR_BITS) - 1
_LPARAM_MIN, _LPARAM_MAX = -(1 << (_PTR_BITS - 1)), (1 << (_PTR_BITS - 1)) - 1
_MAX_UTF16 = 65536


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _payload_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _repair_text(text: str) -> tuple[str, bool]:
    """Replace lone surrogates so the result can always be encoded as JSON."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace"), True
    return text, False


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _send_scalar(hwnd: int, msg: int, wp: int, lp: int,
                 timeout_ms: int) -> tuple[int, int, int]:
    """SendMessageTimeoutW with the result read as a signed pointer-width int."""
    output = DWORD_PTR()
    ctypes.set_last_error(0)
    completed = user32.SendMessageTimeoutW(
        hwnd, msg, wp, lp,
        SMTO_BLOCK | SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT,
        timeout_ms, ctypes.byref(output),
    )
    error = ctypes.get_last_error() if not completed else 0
    result = ctypes.c_ssize_t(output.value).value
    return int(bool(completed)), result, error


def _foreground_fields(before: int) -> dict:
    after = foreground()
    return {"foreground_before": before, "foreground_after": after,
            "foreground_changed": before != after}


def _fail(reason: str, detail: str, before: int, *, state: str = "not_started",
          **extra) -> dict:
    out = {"ok": False, "reason": reason, "detail": detail,
           "execution_state": state, "effect_verified": False,
           "retry_safe": state == "not_started"}
    out.update(_foreground_fields(before))
    out.update(extra)
    return out


def post_message(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0,
                 allow_unsafe: bool = False,
                 allow_foreground: bool = False, wait: bool = True,
                 timeout_ms: int = 1000, text: str | None = None,
                 max_chars: int = 4096) -> dict:
    """Send one window message: bounded sync, async queue, or managed text.

    wait=True uses SendMessageTimeoutW and reports `delivery: "returned"` with
    the message's own result. wait=False queues with PostMessageW and reports
    only `delivery: "queued"` - a message that arrives later can still change
    the window after the foreground sample. Neither is proof the user's goal
    happened; read the window back.

    WM_GETTEXT/WM_SETTEXT are marshalled here, so no pointer ever crosses the
    protocol. Their read-back verification shares the same timeout budget.
    """
    before = foreground()
    if not _is_int(hwnd) or hwnd <= 0 or hwnd == 0xFFFF or hwnd >= 0x10000000:
        return _fail("invalid hwnd", f"{hwnd!r} is not a single window handle", before)
    if not user32.IsWindow(hwnd):
        return _fail("no such window", f"hwnd {hwnd} is gone", before)
    if not _is_int(msg) or not 0 <= msg <= 0xFFFF:
        return _fail("invalid arguments", "msg must be 0..0xffff", before)
    if not _is_int(wparam) or not 0 <= wparam <= _WPARAM_MAX:
        return _fail("invalid arguments", f"wparam must be 0..{_WPARAM_MAX}", before)
    if not _is_int(lparam) or not _LPARAM_MIN <= lparam <= _LPARAM_MAX:
        return _fail("invalid arguments",
                     f"lparam must be {_LPARAM_MIN}..{_LPARAM_MAX}", before)
    if not _is_int(timeout_ms) or not 1 <= timeout_ms <= 30000:
        return _fail("invalid arguments", "timeout_ms must be 1..30000", before)
    if not _is_int(max_chars) or not 1 <= max_chars <= _MAX_UTF16:
        return _fail("invalid arguments", "max_chars must be 1..65536", before)
    if not isinstance(wait, bool) or not isinstance(allow_unsafe, bool) \
            or not isinstance(allow_foreground, bool):
        return _fail("invalid arguments", "wait/allow_unsafe/allow_foreground must be bools",
                     before)
    if msg in _UNMANAGED:
        return _fail("message payload unsupported",
                     f"0x{msg:04X} carries a payload this service cannot marshal", before)

    is_text = msg in _MANAGED_MESSAGES
    if is_text:
        # Validate the managed-text contract before any permission gate, so a
        # caller learns its own arguments are wrong instead of being denied.
        bad = _text_argument_error(msg, wparam, lparam, text)
        if bad:
            return _fail("invalid arguments", bad, before)
        if not wait:
            return _fail("invalid arguments", "managed text needs a synchronous call", before)
    else:
        checks = _CLASS_FOR_MESSAGE.get(msg)
        if checks:
            actual = class_name(hwnd).casefold()
            if not any(token in actual for token in checks):
                return _fail("control class mismatch",
                             f"class {class_name(hwnd)!r} cannot answer 0x{msg:04X}", before)
        elif msg in _SCALARS:
            pass
        elif not allow_unsafe:
            return _fail("unsafe message",
                         f"0x{msg:04X} is not a known scalar; pass allow_unsafe=true "
                         "only after confirming it carries no pointer or handle", before)

    # The permission gate is about effect, not about payload shape: a click, a
    # keystroke or a wheel message changes the application just as much as a
    # setter does, and carries no pointer to make that obvious.
    if msg not in _READ_ONLY_MESSAGES \
            and not allow_foreground:
        result = _fail("needs permission",
                       f"0x{msg:04X} may change the window or its data", before)
        result["needs_permission"] = True
        return result
    if not wait and msg in (WM_GETTEXT, WM_GETTEXTLENGTH, BM_GETCHECK,
                            CB_GETCURSEL, LB_GETCURSEL):
        return _fail("query requires wait",
                     f"0x{msg:04X} asks a question; queuing it would drop the answer", before)
    if wait and _window_pid(hwnd) == os.getpid():
        return _fail("same process",
                     "a same-queue window can block past the timeout and outlive the buffer",
                     before)

    if is_text:
        return _post_text(hwnd, msg, wait, timeout_ms, text, max_chars, before)

    if wait:
        completed, result, error = _send_scalar(hwnd, msg, wparam, lparam, timeout_ms)
        if not completed:
            reason = "message timed out" if error == 1460 else "message delivery failed"
            return _fail(reason, f"SendMessageTimeoutW returned 0, LastError={error}",
                         before, state="unknown", error=error)
        out = {"ok": True, "delivery": "returned", "result": result,
               "call_completed": True, "execution_state": "completed",
               "effect_verified": False}
        # -1 from a list or combo is a real "nothing selected", not a 64-bit value.
        if msg in (CB_GETCURSEL, LB_GETCURSEL):
            out["selection_index"] = result
        out.update(_foreground_fields(before))
        return out

    posted = user32.PostMessageW(hwnd, msg, wparam, lparam)
    if not posted:
        error = ctypes.get_last_error()
        return _fail("message delivery failed", f"PostMessageW returned 0, LastError={error}",
                     before, error=error)
    out = {"ok": True, "delivery": "queued", "effect_verified": False, "call_completed": True}
    out.update(_foreground_fields(before))
    return out


def _text_argument_error(msg: int, wparam: int, lparam: int, text) -> str | None:
    """The managed-text rules, checked before anything is sent."""
    if wparam or lparam:
        return "managed text sets wparam/lparam itself; pass both as 0"
    if msg == WM_GETTEXT:
        return None if text is None else "WM_GETTEXT does not take text"
    if text is None or not isinstance(text, str) or "\x00" in text:
        return "text must be a string without NULs"
    units = _payload_units(text)
    if units > _MAX_UTF16:
        return f"text is {units} UTF-16 units; the limit is {_MAX_UTF16}"
    return None


def _post_text(hwnd: int, msg: int, wait: bool, timeout_ms: int, text: str | None,
               max_chars: int, before: int) -> dict:
    """WM_GETTEXT/WM_SETTEXT with a service-owned buffer; no pointer is exposed."""
    if msg == WM_GETTEXT:
        return _read_text(hwnd, WM_GETTEXT, max_chars, timeout_ms, before)
    return _write_text(hwnd, text, _payload_units(text), timeout_ms, max_chars, before)


def _read_text(hwnd: int, msg: int, capacity: int, timeout_ms: int,
               before: int, *, internal: bool = False) -> dict:
    """Read text into a buffer this service owns for the whole call."""
    buf = ctypes.create_unicode_buffer(capacity + 1)
    completed, result, error = _send_scalar(hwnd, msg, capacity + 1,
                                            ctypes.cast(buf, ctypes.c_void_p).value,
                                            timeout_ms)
    if not completed:
        reason = "message timed out" if error == 1460 else "message delivery failed"
        # A timed-out read has no trustworthy contents; report no fragment.
        return _fail(reason, f"LastError={error}; the buffer was not read",
                     before, state="unknown", error=error)
    if not 0 <= result < capacity + 1:
        return _fail("invalid message result",
                     f"0x{msg:04X} reported {result} for a {capacity}-unit buffer",
                     before, state="completed")
    raw = buf.value if result else ""
    value, repaired = _repair_text(raw)
    out = {"ok": True, "delivery": "returned", "result": result, "text": value,
           "capacity": capacity, "call_completed": True, "execution_state": "completed",
           "effect_verified": False, "possibly_truncated": result >= capacity}
    if repaired:
        out["text_repaired"] = True
    if internal:
        return out
    out.update(_foreground_fields(before))
    return out


def _write_text(hwnd: int, text: str, units: int, timeout_ms: int, max_chars: int,
                before: int) -> dict:
    """WM_SETTEXT, then read back within the same budget; malformed is not success."""
    started = time.monotonic()
    deadline = started + timeout_ms / 1000
    buf = ctypes.create_unicode_buffer(text, units + 1)
    completed, result, error = _send_scalar(hwnd, WM_SETTEXT, 0,
                                            ctypes.cast(buf, ctypes.c_void_p).value,
                                            timeout_ms)
    if not completed:
        reason = "message timed out" if error == 1460 else "message delivery failed"
        return _fail(reason, f"LastError={error}; do not resend automatically",
                     before, state="unknown", error=error)
    if result == 0:
        out = {"ok": False, "reason": "control rejected text",
               "detail": "WM_SETTEXT returned 0", "result": 0, "delivery": "returned",
               "call_completed": True, "execution_state": "completed",
               "effect_verified": False, "retry_safe": False}
        out.update(_foreground_fields(before))
        return out

    preview, _repaired = _repair_text(text[:max_chars])
    out = {"ok": True, "delivery": "returned", "result": result, "call_completed": True,
           "effect_verified": False, "text_preview": preview,
           "possibly_truncated": len(text) > max_chars}
    remaining = int((deadline - time.monotonic()) * 1000)
    if remaining <= 0:
        out.update(_foreground_fields(before))
        out["verification_reason"] = "budget exhausted"
        return out

    # n+2 units: enough to see one trailing unit beyond the input, so a longer
    # existing value shows up as a mismatch instead of a silent match.
    capacity = min(units + 1, _MAX_UTF16 + 2)
    back = _read_text(hwnd, WM_GETTEXT, capacity, remaining, before,
                      internal=True)
    out.update(_foreground_fields(before))
    if not back["ok"]:
        out["verification_reason"] = "readback unavailable"
        out["verification_error"] = back["reason"]
        return out
    if back["result"] >= capacity:
        out["verification_reason"] = "readback incomplete"
        return out
    if back["text"] == text:
        out["effect_verified"] = True
        return out
    failed = {"ok": False, "reason": "text readback mismatch",
              "detail": f"the control now holds {back['text'][:80]!r}",
              "result": result, "delivery": "returned", "call_completed": True,
              "execution_state": "completed", "effect_verified": False,
              "retry_safe": False}
    failed.update(_foreground_fields(before))
    return failed

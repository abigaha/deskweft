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
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
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

"""Which build is this process actually running?

No single source covers every application (handoff §3.0, measured 2026-11-08):
QQ's launcher exe carries no `versions/` segment and its FileVersion lags the
running build, while Edge's exe does carry a sibling build directory and its
FileVersion is correct. So the version is a ladder: each rung proves a
different amount, the first hit wins, and `source` says which rung answered.
"""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from pathlib import Path

import psutil

# `-(build)` is part of the name: the short form misses 9.9.22-40824 and then
# the candidate list is forever empty (a trap this project already fell into).
VER_EXACT = re.compile(r"\d+(?:\.\d+)+(?:-\d+)?\Z")
VER_SHORT = re.compile(r"\d+(?:\.\d+)+\Z")
_VER_PATH = re.compile(r"[\\/]versions[\\/](\d+(?:\.\d+)+(?:-\d+)?)", re.I)
_RUNGS = ("path_segment", "child_cmdline", "sole_candidate", "file_version", "sibling_dir")


def version_sort_key(version: str) -> tuple:
    """Numeric ordering, so 10.0.0 sorts after 9.9.22 - never string order."""
    numbers = re.split(r"[.-]", version)
    return tuple(int(part) if part.isdigit() else -1 for part in numbers)


# ---------- ctypes ----------


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_version = ctypes.WinDLL("version", use_last_error=True)

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

_version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_version.GetFileVersionInfoW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p
]
_version.GetFileVersionInfoW.restype = wintypes.BOOL
_version.VerQueryValueW.argtypes = [
    ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.UINT)
]
_version.VerQueryValueW.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD), ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD), ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD), ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD), ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD), ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD), ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


# ---------- process ----------


def _hwnd_pid(hwnd: int) -> int:
    from . import win32

    pid = wintypes.DWORD()
    win32.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _process_path(pid: int) -> str | None:
    """The executable's full path, or None when the process is gone or denied."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value or None
    finally:
        _kernel32.CloseHandle(handle)


def _file_version_info(exe: str) -> dict:
    """Complete four-part FileVersion, plus product/company strings."""
    info: dict = {}
    try:
        size = _version.GetFileVersionInfoSizeW(exe, None)
        if not size:
            return info
        block = ctypes.create_string_buffer(size)
        if not _version.GetFileVersionInfoW(exe, 0, size, block):
            return info

        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if _version.VerQueryValueW(block, "\\", ctypes.byref(pointer), ctypes.byref(length)) and pointer:
            fixed = _VS_FIXEDFILEINFO.from_address(pointer.value)
            # Never shorten: 9.9.19.35469 becoming "9.9" is a wrong answer.
            info["file_version"] = "{}.{}.{}.{}".format(
                fixed.dwFileVersionMS >> 16, fixed.dwFileVersionMS & 0xFFFF,
                fixed.dwFileVersionLS >> 16, fixed.dwFileVersionLS & 0xFFFF)
        for label, key in (("ProductVersion", "product_version"), ("ProductName", "product"),
                           ("CompanyName", "company")):
            if _version.VerQueryValueW(block, f"\\StringFileInfo\\040904B0\\{label}",
                                       ctypes.byref(pointer), ctypes.byref(length)) and pointer:
                info[key] = ctypes.wstring_at(pointer.value, length.value).rstrip("\x00")
    except OSError:
        return info
    return info


def _child_cmdline_version(pid: int) -> tuple[str | None, str | None]:
    """Rung 2: the launcher's renderer child names the active build directory.

    Measured on QQ: the launcher exe carries no versions/ segment and its
    FileVersion lags, but five child processes all pass
    --app-path=<install>\\versions\\9.9.22-40824\\resources\\app. psutil reads
    that without elevation, so no PEB walk is needed.
    """
    warnings: list[str] = []
    try:
        children = psutil.Process(pid).children(recursive=False)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as error:
        return None, f"cmdline unreadable: {type(error).__name__}"
    for child in children:
        try:
            arguments = child.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as error:
            warnings.append(f"cmdline unreadable: {type(error).__name__}")
            continue
        for argument in arguments:
            match = _VER_PATH.search(argument)
            if match:
                return match.group(1).split("-")[0], "; ".join(warnings) or None
    return None, "; ".join(warnings) or None


def _child_version(pid: int) -> str | None:
    """The rung-2 value alone, for callers that only need the version."""
    return _child_cmdline_version(pid)[0]


def _candidate_dirs(exe: str) -> list[str]:
    """Directory names under <exe dir>/versions that are complete versions.

    Must be `isdir` plus the full regex: real installs mix channel.json,
    config.json and setting.json into that folder (measured on QQ).
    """
    folder = Path(os.path.dirname(exe)) / "versions"
    try:
        names = [entry.name for entry in folder.iterdir() if entry.is_dir()]
    except OSError:
        return []
    return sorted((name for name in names if VER_EXACT.match(name)), key=version_sort_key)


def _sibling_version(exe: str) -> str | None:
    """Rung 5: <exe dir>/<version>/ is where Edge keeps its build."""
    folder = Path(os.path.dirname(exe))
    try:
        names = [entry.name for entry in folder.iterdir() if entry.is_dir()]
    except OSError:
        return None
    versions = sorted((n for n in names if VER_EXACT.match(n)), key=version_sort_key)
    return versions[-1] if versions else None


def _version_evidence(pid: int, exe: str | None,
                      info: dict) -> tuple[str | None, str | None, list[str]]:
    """Walk the ladder, stop at the first rung that answers."""
    warnings: list[str] = []
    if exe:
        match = _VER_PATH.search(exe)
        if match:
            return match.group(1).split("-")[0], "path_segment", warnings

    if pid:
        child_version, child_warning = _child_cmdline_version(pid)
        if child_warning:
            warnings.append(child_warning)
        if child_version:
            return child_version, "child_cmdline", warnings

    if exe:
        candidates = _candidate_dirs(exe)
        if len(candidates) == 1:
            warnings.append("inferred from sole candidate, not verified")
            return candidates[0].split("-")[0], "sole_candidate", warnings
        if len(candidates) > 1:
            warnings.append(f"multiple version candidates {candidates}; not guessing")

    file_version = (info or {}).get("file_version")
    if file_version:
        return file_version, "file_version", warnings

    if exe:
        sibling = _sibling_version(exe)
        if sibling:
            warnings.append("inferred from sibling version directory, not verified")
            return sibling, "sibling_dir", warnings

    warnings.append("no version evidence; store this as app@unversioned")
    return None, None, warnings


def _valid_hwnd(hwnd) -> bool:
    return (isinstance(hwnd, int) and not isinstance(hwnd, bool)
            and 0 < hwnd < 0x10000000 and hwnd != 0xFFFF)


def app_info(hwnd: int) -> dict:
    """Identity and version evidence for the process that owns one window."""
    if not _valid_hwnd(hwnd):
        return {"ok": False, "reason": "invalid hwnd", "detail": repr(hwnd)}
    pid = _hwnd_pid(hwnd)
    if not pid:
        return {"ok": False, "reason": "no such window", "detail": f"hwnd {hwnd} has no process"}
    exe = _process_path(pid)
    if not exe:
        return {"ok": False, "reason": "process unavailable",
                "detail": f"pid {pid} exited or denies PROCESS_QUERY_LIMITED_INFORMATION",
                "hwnd": hwnd, "pid": pid}
    info = _file_version_info(exe)
    version, source, warnings = _version_evidence(pid, exe, info)
    return {
        "ok": True, "hwnd": hwnd, "pid": pid, "name": Path(exe).stem,
        "exe": exe, "version": version, "source": source,
        "file_version": info.get("file_version"),
        "product": info.get("product"), "company": info.get("company"),
        "version_candidates": _candidate_dirs(exe), "warnings": warnings,
    }

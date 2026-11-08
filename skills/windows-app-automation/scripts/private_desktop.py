"""Run one cooperating Python runner on a disposable, non-input Windows desktop.

CLI::

    python private_desktop.py --out parent.json -- runner.py [runner arguments]

The current interpreter starts runner.py with two appended arguments:
``--expected-desktop <unique name> --out <unique child.json>``. The runner must
accept these arguments, write a JSON object to that output, and set
``completed: true`` only after its own business/effect checks pass. A zero exit
code alone is insufficient. Runner output is kept in its separate file; stdout
from this launcher contains only a short summary, without window titles or text.

Import desktop_identity() and verify_dispatch_thread() in the actual provider
dispatch thread, before and after each operation (also in exception paths).
Verify application root AND renderer HWND ownership separately. Other runtime
threads can be unconnected to USER; a foreign-thread NULL desktop is not proof
that the actual dispatch thread escaped. This helper does not patch MCP or
automatically guard a runner's worker threads.

Isolation covers ordinary activation of windows which remain on this private
desktop. It is not a security sandbox: a cooperating runner must reject reused
instances on the input desktop. Same-user programs with sufficient rights can
explicitly switch desktops or invoke external brokers. Job cleanup covers job
members/ordinary descendants, not unrelated or broker-created processes.

No SwitchDesktop call is made. Hooks and 50ms input-desktop samples OBSERVE;
they do not prevent activation or guarantee that no event was missed. Parent
monitoring remains active through job termination. All paths request job
termination, release local process references, and query ActiveProcesses=0
before normal desktop/job closure. Cleanup failures are reported as failures;
CloseDesktop success never substitutes for the job-zero proof.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid


U = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
K = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
        ("max_ws", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD)]


class EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [("basic", BASIC_LIMIT), ("io", ctypes.c_ulonglong * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class BASIC_ACCOUNTING(ctypes.Structure):
    _fields_ = [("user_time", ctypes.c_longlong), ("kernel_time", ctypes.c_longlong),
        ("period_user_time", ctypes.c_longlong), ("period_kernel_time", ctypes.c_longlong),
        ("page_faults", wintypes.DWORD), ("total_processes", wintypes.DWORD),
        ("active_processes", wintypes.DWORD), ("terminated_processes", wintypes.DWORD)]


if U is not None:
    WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
        wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    # Real Win32 prototypes are essential on 64-bit Python; handles are pointers.
    _bindings = [
        (U, "CreateDesktopW", [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p], wintypes.HANDLE),
        (U, "CloseDesktop", [wintypes.HANDLE], wintypes.BOOL),
        (U, "GetThreadDesktop", [wintypes.DWORD], wintypes.HANDLE),
        (U, "SetThreadDesktop", [wintypes.HANDLE], wintypes.BOOL),
        (U, "GetProcessWindowStation", [], wintypes.HANDLE),
        (U, "OpenInputDesktop", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        (U, "GetUserObjectInformationW", [wintypes.HANDLE, ctypes.c_int,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (U, "GetForegroundWindow", [], wintypes.HWND),
        (U, "GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        (U, "SetWinEventHook", [wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
            WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        (U, "UnhookWinEvent", [wintypes.HANDLE], wintypes.BOOL),
        (U, "PeekMessageW", [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        (U, "TranslateMessage", [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        (U, "DispatchMessageW", [ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
        (K, "GetCurrentProcessId", [], wintypes.DWORD),
        (K, "GetCurrentThreadId", [], wintypes.DWORD),
        (K, "ProcessIdToSessionId", [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (K, "CreateProcessW", [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p,
            wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
            ctypes.POINTER(PROCESS_INFORMATION)], wintypes.BOOL),
        (K, "CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        (K, "SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int,
            ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        (K, "QueryInformationJobObject", [wintypes.HANDLE, ctypes.c_int,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (K, "AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        (K, "ResumeThread", [wintypes.HANDLE], wintypes.DWORD),
        (K, "WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        (K, "GetExitCodeProcess", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (K, "TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        (K, "TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        (K, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
    ]
    for _dll, _name, _args, _result in _bindings:
        _function = getattr(_dll, _name)
        _function.argtypes, _function.restype = _args, _result


def _require(value, operation):
    if not value:
        code = ctypes.get_last_error()
        raise OSError(code, f"{operation} failed (WinError {code})")
    return value


def object_name(handle):
    """Name a desktop/window-station handle without closing the borrowed handle."""
    if U is None:
        raise OSError("Windows is required")
    if not handle:
        raise RuntimeError("object_name received NULL; capture the querying thread/stage")
    needed = wintypes.DWORD()
    U.GetUserObjectInformationW(handle, 2, None, 0, ctypes.byref(needed))
    if not needed.value or needed.value > 65536:
        raise OSError(ctypes.get_last_error(), "GetUserObjectInformationW size failed")
    buffer = ctypes.create_unicode_buffer(needed.value // ctypes.sizeof(ctypes.c_wchar) + 1)
    _require(U.GetUserObjectInformationW(handle, 2, buffer, ctypes.sizeof(buffer),
                                       ctypes.byref(needed)), "GetUserObjectInformationW")
    return buffer.value


def desktop_identity():
    """Self-report the CALLING native thread, not an enumeration of runtime threads."""
    if U is None:
        raise OSError("Windows is required")
    pid, tid = K.GetCurrentProcessId(), K.GetCurrentThreadId()
    session = wintypes.DWORD()
    _require(K.ProcessIdToSessionId(pid, ctypes.byref(session)), "ProcessIdToSessionId")
    station = object_name(U.GetProcessWindowStation())
    current = object_name(U.GetThreadDesktop(tid))
    active_handle = _require(U.OpenInputDesktop(0, False, 1), "OpenInputDesktop")
    try:
        active = object_name(active_handle)
    finally:
        _require(U.CloseDesktop(active_handle), "CloseDesktop(input handle)")
    prefix = f"{session.value}/{station}/"
    return {"pid": pid, "native_tid": tid, "session": session.value,
            "window_station": station, "current_desktop": current,
            "input_desktop": active, "current_full": prefix + current,
            "input_full": prefix + active, "isolated": current != active}


def verify_dispatch_thread(expected_desktop, *, expected_input="Default",
                           expected_session=None, expected_window_station="WinSta0"):
    """Call inside the real dispatch thread; mismatch raises before business work."""
    proof = desktop_identity()
    if (not expected_desktop or not proof["isolated"]
            or proof["current_desktop"] != expected_desktop
            or proof["input_desktop"] != expected_input
            or proof["window_station"] != expected_window_station
            or (expected_session is not None and proof["session"] != expected_session)):
        raise RuntimeError("dispatch thread desktop/session/window-station mismatch")
    return proof


class _Native:
    """Small syscall boundary so lifecycle tests never create a desktop/process."""
    identity = staticmethod(desktop_identity)

    def foreground(self):
        return U.GetForegroundWindow()

    def create_job(self):
        return _require(K.CreateJobObjectW(None, None), "CreateJobObjectW")

    def configure_job(self, job):
        limits = EXTENDED_LIMIT()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        _require(K.SetInformationJobObject(job, 9, ctypes.byref(limits),
                                          ctypes.sizeof(limits)), "SetInformationJobObject")

    def create_desktop(self, name):
        return _require(U.CreateDesktopW(name, None, None, 0, 0x01FF, None), "CreateDesktopW")

    def spawn(self, argv, desktop):
        startup, process = STARTUPINFOW(), PROCESS_INFORMATION()
        startup.cb, startup.lpDesktop = ctypes.sizeof(startup), desktop
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        # No inherited desktop/job handles; suspend before any runner code executes.
        _require(K.CreateProcessW(sys.executable, command, None, None, False,
            0x08000004, None, str(Path.cwd()), ctypes.byref(startup),
            ctypes.byref(process)), "CreateProcessW")  # NO_WINDOW | SUSPENDED
        return process

    def assign(self, job, process):
        _require(K.AssignProcessToJobObject(job, process), "AssignProcessToJobObject")

    def resume(self, thread):
        if K.ResumeThread(thread) == 0xFFFFFFFF:
            _require(False, "ResumeThread")

    def wait(self, process, milliseconds):
        value = K.WaitForSingleObject(process, milliseconds)
        if value not in (0, 0x102):
            _require(False, "WaitForSingleObject")
        return value == 0

    def exit_code(self, process):
        code = wintypes.DWORD()
        _require(K.GetExitCodeProcess(process, ctypes.byref(code)), "GetExitCodeProcess")
        return code.value

    def terminate_job(self, job):
        _require(K.TerminateJobObject(job, 125), "TerminateJobObject")

    def terminate_process(self, process):
        _require(K.TerminateProcess(process, 125), "TerminateProcess(unassigned runner)")

    def active_processes(self, job):
        accounting = BASIC_ACCOUNTING()
        _require(K.QueryInformationJobObject(job, 1, ctypes.byref(accounting),
            ctypes.sizeof(accounting), None), "QueryInformationJobObject")
        return accounting.active_processes

    def close_handle(self, handle):
        _require(K.CloseHandle(handle), "CloseHandle")

    def close_desktop(self, desktop):
        _require(U.CloseDesktop(desktop), "CloseDesktop(private)")


def _error(error, stage):
    # Deliberately omit arbitrary exception text/runner arguments from the parent.
    return {"stage": stage, "type": type(error).__name__,
            "winerror": getattr(error, "winerror", None) or getattr(error, "errno", None)}


class ForegroundMonitor:
    """Current-input-desktop event observer; its hooks do not prevent activation."""
    EVENT_NAMES = {3: "foreground", 0x8005: "focus", 0x20: "desktop_switch"}

    def __init__(self, api, expected_full, clock):
        self.expected_full, self.clock = expected_full, clock
        self.events, self.errors = [], []
        self.installed = self.removed = False
        self.stop_event, self.ready = threading.Event(), threading.Event()
        self.desktop = U.GetThreadDesktop(K.GetCurrentThreadId())
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(5) or self.errors or not self.installed:
            raise RuntimeError("foreground observer failed to install")

    def _loop(self):
        hooks = []
        try:
            _require(U.SetThreadDesktop(self.desktop), "SetThreadDesktop(observer)")
            self.identity = desktop_identity()
            if self.identity["current_full"] != self.expected_full:
                raise RuntimeError("observer attached to a different desktop")
            self.callback = WINEVENTPROC(self._event)
            for event in self.EVENT_NAMES:
                hooks.append(_require(U.SetWinEventHook(event, event, None,
                    self.callback, 0, 0, 0), "SetWinEventHook"))
            self.installed = True
            self.ready.set()
            message = wintypes.MSG()
            while not self.stop_event.is_set():
                while U.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    U.TranslateMessage(ctypes.byref(message))
                    U.DispatchMessageW(ctypes.byref(message))
                self.stop_event.wait(0.005)
            # Drain already queued out-of-context events before unhooking.
            while U.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                U.TranslateMessage(ctypes.byref(message))
                U.DispatchMessageW(ctypes.byref(message))
        except BaseException as error:
            self.errors.append(_error(error, "observer"))
        finally:
            removed = True
            for hook in hooks:
                if not U.UnhookWinEvent(hook):
                    removed = False
                    self.errors.append(_error(OSError(ctypes.get_last_error(), "unhook"), "observer cleanup"))
            self.removed = removed
            self.ready.set()

    def _event(self, hook, event, hwnd, object_id, child_id, tid, event_time):
        try:
            pid = wintypes.DWORD()
            if hwnd:
                U.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            self.events.append({"event": self.EVENT_NAMES[event], "hwnd": hwnd,
                "pid": pid.value, "native_tid": tid, "object_id": object_id,
                "child_id": child_id, "event_time_ms": event_time,
                "observed_monotonic_ms": round(self.clock() * 1000, 3)})
        except BaseException as error:
            self.errors.append(_error(error, "observer callback"))

    def close(self):
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join(5)
            if self.thread.is_alive():
                self.errors.append(_error(TimeoutError(), "observer join"))

    def report(self):
        return {"events": list(self.events), "errors": list(self.errors),
                "installed": self.installed, "removed": self.removed,
                "identity": getattr(self, "identity", None),
                "delivery": "out-of-context queued; message pump; observation only"}


def launch(runner, out, *, timeout=100.0, cleanup_timeout=8.0, api=None,
           monitor_factory=None, clock=time.monotonic, sleep=time.sleep):
    """Launch one runner; injected boundaries are for offline tests, not CLI flags."""
    if (not runner or not math.isfinite(timeout) or not math.isfinite(cleanup_timeout)
            or timeout <= 0 or cleanup_timeout <= 0):
        raise ValueError("runner and positive timeouts are required")
    if any(a.split("=", 1)[0] in ("--out", "--expected-desktop") for a in runner[1:]):
        raise ValueError("runner output/expected-desktop arguments are supplied by the launcher")
    script = Path(runner[0]).resolve(strict=True)
    if not script.is_file() or script.suffix.lower() != ".py":
        raise ValueError("runner must be a Python file")
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    api, monitor_factory = api or _Native(), monitor_factory or ForegroundMonitor
    began = clock()
    name = "DeskWeft_" + uuid.uuid4().hex
    child_out = out.with_name(out.stem + "-" + name + "-child.json")
    result = {"ok": False, "private_desktop": name, "child_out": str(child_out),
        "started_monotonic_ms": round(began * 1000, 3),
        "input_sample_interval_ms": 50, "input_samples": [],
        "input_desktop_changes": [], "runner_exit_code": None,
        "cleanup": {"complete": False, "active_processes": None, "errors": []}}
    job = desktop = process = monitor = None
    assigned = False
    stage = "preflight"
    baseline = None

    def sample():
        proof = api.identity()
        entry = {"elapsed_ms": round((clock() - began) * 1000, 3),
                 "input_full": proof["input_full"]}
        result["input_samples"].append(entry)
        if proof["input_full"] != baseline["input_full"]:
            result["input_desktop_changes"].append(entry)
            raise RuntimeError("input desktop changed")
        if proof["current_full"] != baseline["current_full"]:
            raise RuntimeError("launcher thread desktop changed")

    try:
        baseline = result["before"] = api.identity()
        if baseline["current_full"] != baseline["input_full"]:
            raise RuntimeError("launcher must run on the input desktop")
        if baseline["window_station"] != "WinSta0":
            raise RuntimeError("launcher must use the interactive window station")
        result["foreground_before"] = api.foreground()
        sample()
        stage = "create job"
        job = api.create_job()
        api.configure_job(job)
        result["job_kill_on_close"] = True
        stage = "create desktop"
        desktop = api.create_desktop(name)
        stage = "install observer"
        monitor = monitor_factory(api, baseline["input_full"], clock)
        monitor.start()
        stage = "create suspended runner"
        argv = [sys.executable, "-B", str(script), *runner[1:],
                "--expected-desktop", name, "--out", str(child_out)]
        process = api.spawn(argv, baseline["window_station"] + "\\" + name)
        result["runner_pid"] = process.dwProcessId
        stage = "assign runner to job"
        api.assign(job, process.hProcess)
        assigned = True
        stage = "resume runner"
        api.resume(process.hThread)
        result["preparation_ms"] = round((clock() - began) * 1000, 3)
        stage = "runner"
        deadline = clock() + timeout
        while True:
            exited = api.wait(process.hProcess, 50)
            sample()
            if monitor.errors:
                raise RuntimeError("foreground observer failed during runner execution")
            if any(e.get("event") == "desktop_switch" for e in monitor.events):
                raise RuntimeError("desktop switch event observed")
            if exited:
                break
            if clock() >= deadline:
                raise TimeoutError("runner deadline exceeded")
        result["runner_exit_code"] = api.exit_code(process.hProcess)
    except BaseException as error:
        result["error"] = _error(error, stage)
    finally:
        cleanup_began = clock()
        deadline = cleanup_began + cleanup_timeout
        cleanup = result["cleanup"]

        def attempt(label, function, *args):
            try:
                return function(*args)
            except BaseException as error:
                cleanup["errors"].append(_error(error, label))
                return None

        if job is not None:
            attempt("terminate job", api.terminate_job, job)
        if process is not None:
            if not assigned:
                attempt("terminate unassigned suspended runner", api.terminate_process, process.hProcess)
            stopped = False
            while clock() < deadline and not stopped:
                stopped = attempt("wait runner exit", api.wait, process.hProcess, 50)
                if stopped is None:
                    break
                if baseline is not None:
                    attempt("sample during cleanup", sample)
            if not stopped:
                cleanup["errors"].append(_error(TimeoutError(), "runner exit not confirmed"))
            # Job accounting may retain a process until references are released.
            attempt("close runner thread", api.close_handle, process.hThread)
            attempt("close runner process", api.close_handle, process.hProcess)
        if job is not None:
            while True:
                active = attempt("query job active processes", api.active_processes, job)
                cleanup["active_processes"] = active
                if active == 0 or active is None:
                    break
                if clock() >= deadline:
                    cleanup["errors"].append(_error(TimeoutError(), "job did not reach zero"))
                    break
                sleep(min(0.05, max(0, deadline - clock())))
                if baseline is not None:
                    attempt("sample during job cleanup", sample)
        job_zero = job is None or cleanup["active_processes"] == 0
        if not job_zero and job is not None:
            # Last-handle closure is a fallback kill request, never a zero proof.
            attempt("close job fallback", api.close_handle, job)
            job = None
        if desktop is not None:
            attempt("close private desktop", api.close_desktop, desktop)
        if job is not None:
            attempt("close job", api.close_handle, job)
        if baseline is not None:
            result["after"] = attempt("final identity", api.identity)
            result["foreground_after"] = attempt("final foreground", api.foreground)
            if result["after"] is not None:
                final = result["after"]
                if final["input_full"] != baseline["input_full"]:
                    result["input_desktop_changes"].append({"elapsed_ms":
                        round((clock() - began) * 1000, 3), "input_full": final["input_full"]})
                if final["current_full"] != baseline["current_full"]:
                    cleanup["errors"].append(_error(RuntimeError(), "final launcher desktop mismatch"))
        if monitor is not None:
            attempt("stop observer", monitor.close)
            result["observation"] = monitor.report()
        else:
            result["observation"] = {"installed": False, "removed": True,
                                     "events": [], "errors": []}
        cleanup["complete"] = job_zero and not cleanup["errors"]
        result["cleanup_ms"] = round((clock() - cleanup_began) * 1000, 3)
        result["lifecycle_ms"] = round((clock() - began) * 1000, 3)

    observation = result["observation"]
    result["foreground_or_focus_changed"] = any(
        e.get("event") in ("foreground", "focus") for e in observation["events"])
    result["desktop_switch_observed"] = any(
        e.get("event") == "desktop_switch" for e in observation["events"])
    result["background_observation"] = (
        "events observed; their cause is not attributed" if result["foreground_or_focus_changed"]
        else "no foreground/focus event observed; this is not a prevention guarantee")
    try:
        child = json.loads(child_out.read_text(encoding="utf-8"))
        if not isinstance(child, dict) or child.get("completed") is not True:
            raise ValueError("runner JSON must contain completed:true")
        result["runner_completed"] = True
    except (OSError, ValueError) as error:
        result["runner_completed"] = False
        result.setdefault("error", _error(error, "runner result"))
    observer_ok = observation["installed"] and observation["removed"] and not observation["errors"]
    result["ok"] = ("error" not in result and result["runner_exit_code"] == 0
        and result["runner_completed"] and cleanup["complete"] and observer_ok
        and not result["input_desktop_changes"] and not result["desktop_switch_observed"])
    result["lifecycle_ms"] = round((clock() - began) * 1000, 3)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=100.0)
    parser.add_argument("runner", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    runner = args.runner[1:] if args.runner[:1] == ["--"] else args.runner
    try:
        result = launch(runner, args.out, timeout=args.timeout)
    except (OSError, ValueError) as error:
        parser.error(type(error).__name__ + ": invalid launcher inputs or report path")
    print(json.dumps({"ok": result["ok"], "runner_exit_code": result["runner_exit_code"],
        "cleanup_complete": result["cleanup"]["complete"],
        "input_desktop_change_samples": len(result["input_desktop_changes"]),
        "foreground_focus_events": sum(e.get("event") in ("foreground", "focus")
            for e in result["observation"]["events"]),
        "lifecycle_ms": result["lifecycle_ms"]}, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

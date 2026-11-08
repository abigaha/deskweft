"""Private-desktop QQ search probe; never sends chat or chooses an account.

Run only through private_desktop.py, with permission to launch and close this
new QQ instance. Existing-account login needs the explicit command-line flag.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace


PROBE_TEXT = "deskweft_private_desktop_probe"
_RUNTIME = None


def safe_text(value):
    if value in ("", "QQ", "登录", "搜索", PROBE_TEXT):
        return value
    return {"chars": len(value), "sha256_12": hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]}


def summarize_result(result):
    """Keep operational evidence, never tree labels, screenshots or raw values."""
    summary = {key: result[key] for key in (
        "ok", "execution_state", "delivery", "call_completed", "effect_verified", "retry_safe",
        "foreground_before", "foreground_after", "foreground_changed", "element_count",
        "timed_out", "limit_reached", "identity_complete", "pattern", "method", "_probe_worker",
    ) if key in result}
    if isinstance(result.get("result"), str):
        summary["result"] = safe_text(result["result"])
    if "elements" in result:
        summary["types"] = dict(Counter(row.get("control_type") for row in result["elements"]))
        summary["named_count"] = sum(bool(row.get("name")) for row in result["elements"])
    if result.get("reason"):
        summary["reason"] = safe_text(str(result["reason"]))
    return summary


def complete_elements(tree):
    if not tree.get("ok") or not tree.get("identity_complete") or tree.get("timed_out") \
            or tree.get("limit_reached") or not isinstance(tree.get("elements"), list):
        raise RuntimeError("complete target tree unavailable")
    return tree["elements"]


def search_selector(tree):
    controls = [row for row in complete_elements(tree) if row.get("control_type") == "ComboBoxControl"]
    if len(controls) != 1:
        raise RuntimeError("no unique search ComboBoxControl")
    return {"control_type": "ComboBoxControl"}


def login_selector(tree, *, allow_existing_account_login):
    controls = [row for row in complete_elements(tree)
                if row.get("name") == "登录" and row.get("control_type") == "ButtonControl"]
    if len(controls) > 1:
        raise RuntimeError("ambiguous login button")
    if controls and not allow_existing_account_login:
        raise PermissionError("existing-account login is outside this runner scope")
    return {"name": "登录", "control_type": "ButtonControl"} if controls else None


def restoration_value(current, original, probe):
    if current not in (original, probe):
        raise RuntimeError("unknown concurrent search change; do not overwrite")
    return original


def error_record(error, stage):
    return {"type": type(error).__name__, "stage": stage, "message": safe_text(str(error))}


def record_error(output, error, stage):
    record = error_record(error, stage)
    if "error" not in output:
        output["error"] = record
    else:
        output.setdefault("secondary_errors", []).append(record)


def guard_dispatch(function, verify, *, action, parameters):
    proof = {"pid": os.getpid(), "tid": threading.get_native_id(), "before": None, "after": None}
    try:
        proof["before"] = verify()
    except BaseException as error:
        proof["before_error"] = error_record(error, "before_guard")
        return {"ok": False, "execution_state": "not_started", "reason": "private guard failed",
                "_probe_worker": proof}
    result = None
    try:
        result = function(**parameters)
        if not isinstance(result, dict):
            raise TypeError("worker result must be a dictionary")
    except BaseException as error:
        proof["function_error"] = error_record(error, "provider")
    try:
        proof["after"] = verify()
    except BaseException as error:
        proof["after_error"] = error_record(error, "after_guard")
    if proof.get("function_error") or proof.get("after_error"):
        if isinstance(result, dict):
            proof["function_result"] = summarize_result(result.get("meta", result))
        return {"ok": False, "execution_state": "unknown", "reason": "private dispatch failed",
                "_probe_worker": proof}
    where = result["meta"] if action == "see" and "meta" in result else result
    where["_probe_worker"] = proof
    return result


async def search_roundtrip(value, set_value, output):
    """Restore only a completed write while subsequent provider calls remain known."""
    original = await value("original_search")
    write_completed = False
    primary = None
    try:
        await set_value("write_search", PROBE_TEXT)
        write_completed = True
        output["effect_verified"] = await value("readback_search") == PROBE_TEXT
        if not output["effect_verified"]:
            raise RuntimeError("search effect not verified")
    except BaseException as error:
        primary = error
        if "error" not in output:
            record_error(output, error, output.get("stage", "search"))
        raise
    finally:
        if not write_completed or output.get("continuation_blocked"):
            output["search_restored_exactly"] = False
            output["restoration_skipped"] = "write completion or dispatch guard unverified; end owned Job"
        else:
            try:
                current = await value("before_restore")
                restore = restoration_value(current, original, PROBE_TEXT)
                if current != restore:
                    await set_value("restore_search", restore)
                output["search_restored_exactly"] = await value("restored_search") == original
                if not output["search_restored_exactly"]:
                    raise RuntimeError("search restoration not verified")
            except BaseException as error:
                output["search_restored_exactly"] = False
                record_error(output, error, "search_restore")
                if primary is None:
                    raise


def finish_run(runtime, output, out, started):
    if runtime is not None:
        try:
            runtime.uia_worker.close()
            output["worker_closed"] = runtime.uia_worker._worker is None
            if not output["worker_closed"]:
                raise RuntimeError("worker close did not finish")
        except BaseException as error:
            output["worker_closed"] = False
            record_error(output, error, "worker_close")
    output["completed"] = bool(output.get("completed")) and "error" not in output
    output["runner_wall_ms"] = round((time.monotonic() - started) * 1000, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if output["completed"] else 1


def load_runtime(repo):
    """Spawn reimports this module, so install the guard there as well."""
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME
    sys.path.insert(0, str(repo))
    import private_desktop as desktop
    import psutil
    from fastmcp import Client
    from deskweft import appinfo, launch, server, uia_worker, win32

    original_dispatch = uia_worker._make_dispatch

    def verify():
        return desktop.verify_dispatch_thread(
            os.environ["DESKWEFT_PRIVATE_EXPECTED"],
            expected_input=os.environ["DESKWEFT_PRIVATE_INPUT"],
            expected_session=int(os.environ["DESKWEFT_PRIVATE_SESSION"]),
            expected_window_station=os.environ["DESKWEFT_PRIVATE_STATION"],
        )

    def checked_dispatch():
        def wrap(name, function):
            def checked(**parameters):
                return guard_dispatch(function, verify, action=name, parameters=parameters)
            return checked
        return {name: wrap(name, function) for name, function in original_dispatch().items()}

    uia_worker._make_dispatch = checked_dispatch
    _RUNTIME = SimpleNamespace(desktop=desktop, psutil=psutil, Client=Client, appinfo=appinfo,
                               launch=launch, server=server, uia_worker=uia_worker, win32=win32)
    return _RUNTIME


def response_data(response):
    text = next(block.text for block in response.content if block.type == "text")
    result = json.loads(text)
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], str):
        result = json.loads(result[0])
    if not isinstance(result, dict):
        raise RuntimeError("unexpected MCP response")
    return result


def qq_processes(runtime):
    processes = []
    for process in runtime.psutil.process_iter(["pid", "name"]):
        if (process.info["name"] or "").lower() == "qq.exe":
            processes.append(process)
    return processes


def main_window(runtime, owned_pids):
    matches = [hwnd for hwnd in runtime.launch._all_top_level_windows()
               if runtime.launch._window_pid(hwnd) in owned_pids and runtime.launch.is_shown(hwnd)
               and runtime.win32.class_name(hwnd) == "Chrome_WidgetWin_1"
               and runtime.win32.title(hwnd) == "QQ"]
    if len(matches) != 1:
        raise RuntimeError("no unique owned QQ window")
    return matches[0]


def verify_windows(runtime, hwnd, owned_pids, expected):
    handles = {hwnd, *[row["hwnd"] for row in runtime.win32.children(hwnd)],
               *[window for window in runtime.launch._all_top_level_windows()
                 if runtime.launch._window_pid(window) in owned_pids]}
    checks = []
    for window in sorted(handles):
        tid = runtime.desktop.U.GetWindowThreadProcessId(window, None)
        bound = runtime.desktop.object_name(runtime.desktop.U.GetThreadDesktop(tid))
        if bound != expected:
            raise RuntimeError("owned QQ window desktop mismatch")
        checks.append({"hwnd": window, "pid": runtime.launch._window_pid(window),
                       "tid": tid, "desktop": bound})
    return checks


async def run(args, runtime, output):
    def save():
        args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    async with runtime.Client(runtime.server.mcp) as client:
        async def call(label, tool, **parameters):
            output["stage"] = label
            began = time.monotonic()
            try:
                result = response_data(await client.call_tool(tool, parameters))
                entry = {"stage": label, "tool": tool, "wall_ms": round((time.monotonic() - began) * 1000, 1),
                         **summarize_result(result)}
                if tool == "invoke_pattern":
                    entry["request"] = {key: parameters[key] for key in ("pattern", "method")}
                    entry["request"]["target"] = {
                        key: safe_text(value) if isinstance(value, str) and key != "control_type" else value
                        for key, value in parameters["target"].items()}
                    entry["request"]["args"] = [
                        safe_text(value) if isinstance(value, str) else value for value in parameters.get("args", [])]
                output.setdefault("calls", []).append(entry)
                save()
                if tool != "open_app":
                    evidence = result.get("_probe_worker")
                    worker = runtime.uia_worker._worker
                    if not evidence or not worker or evidence["pid"] != worker["process"].pid \
                            or any(evidence.get(key) for key in ("before_error", "after_error", "function_error")):
                        raise RuntimeError("actual dispatch worker evidence unavailable")
                    expected = output["desktop"]
                    if not all(isinstance(evidence.get(stage), dict) and
                               evidence[stage].get("current_desktop") == args.expected_desktop and
                               evidence[stage].get("input_full") == expected["input_full"] and
                               evidence[stage].get("session") == expected["session"] and
                               evidence[stage].get("window_station") == expected["window_station"]
                               for stage in ("before", "after")):
                        raise RuntimeError("worker desktop evidence mismatch")
                if result.get("execution_state") in ("unknown", "queued") \
                        or result.get("delivery") == "queued" or result.get("queued") is True:
                    raise RuntimeError("provider outcome unknown; stop further calls")
                return result
            except BaseException as error:
                output["continuation_blocked"] = True
                record_error(output, error, label)
                raise

        # Invalid HWND is rejected in the real worker without touching a provider.
        preflight = await call("worker_preflight", "see", hwnd=0, with_tree=False, timeout_ms=5000)
        if preflight.get("execution_state") != "not_started":
            raise RuntimeError("identity preflight unexpectedly reached a target")
        output["actual_worker"] = preflight["_probe_worker"]
        if args.phase == "identity":
            return
        if qq_processes(runtime):
            raise RuntimeError("existing QQ would defeat isolated startup; do not launch")

        root = None
        primary = None
        try:
            launched = await call("launch", "open_app", command=subprocess.list2cmdline([str(args.exe)]),
                                  accessibility=True, show=True, settle=4.0)
            if not launched.get("ok"):
                raise RuntimeError("QQ launch failed")
            root = runtime.psutil.Process(launched["pid"])
            created = root.create_time()
            if Path(root.exe()).resolve() != args.exe.resolve():
                raise RuntimeError("launched executable identity mismatch")

            def target():
                if root.create_time() != created:
                    raise RuntimeError("launched process identity changed")
                owned = {root.pid, *[process.pid for process in root.children(recursive=True)]}
                if any(process.pid not in owned for process in qq_processes(runtime)):
                    raise RuntimeError("QQ instance outside the owned process tree")
                hwnd = main_window(runtime, owned)
                output["window_desktop_checks"] = verify_windows(runtime, hwnd, owned, args.expected_desktop)
                return hwnd

            hwnd = target()
            tree = await call("initial_tree", "see", hwnd=hwnd, with_tree=True, max_elements=600, timeout_ms=5000)
            login = login_selector(tree, allow_existing_account_login=args.allow_existing_account_login)
            if login:
                logged_in = await call("existing_account_login", "invoke_pattern", hwnd=hwnd,
                                       target=login, pattern="LegacyIAccessiblePattern",
                                       method="DoDefaultAction", args=[], allow_foreground=True)
                if not logged_in.get("ok") or logged_in.get("execution_state") != "completed" \
                        or logged_in.get("call_completed") is not True:
                    output["continuation_blocked"] = True
                    raise RuntimeError("existing-account semantic login failed or result unknown")
                await asyncio.sleep(3.0)
                hwnd = target()
                tree = await call("main_tree", "see", hwnd=hwnd, with_tree=True, max_elements=600, timeout_ms=5000)
            selector = search_selector(tree)
            info = runtime.appinfo.app_info(hwnd)
            output["application"] = {key: info.get(key) for key in ("exe", "version", "source", "file_version")}

            async def value(label):
                result = await call(label, "invoke_pattern", hwnd=target(), target=selector,
                                    pattern="ValuePattern", method="Value", args=[])
                if not result.get("ok") or not isinstance(result.get("result"), str):
                    raise RuntimeError("search value unavailable")
                return result["result"]

            async def set_value(label, value):
                result = await call(label, "invoke_pattern", hwnd=target(), target=selector,
                                    pattern="ValuePattern", method="SetValue", args=[value], allow_foreground=True)
                if not result.get("ok") or result.get("execution_state") != "completed" \
                        or result.get("call_completed") is not True:
                    output["continuation_blocked"] = True
                    raise RuntimeError("search setter failed or result unknown")

            await search_roundtrip(value, set_value, output)
        except BaseException as error:
            primary = error
            if "error" not in output:
                record_error(output, error, output.get("stage", "qq"))
            raise
        finally:
            try:
                if root is not None and root.is_running():
                    if root.create_time() != created:
                        raise RuntimeError("process identity changed; rely on owning Job cleanup")
                    owned = [*root.children(recursive=True), root]
                    owned = [(process, process.create_time()) for process in owned
                             if Path(process.exe()).resolve() == args.exe.resolve()]
                    for process, stamp in owned:
                        if process.is_running() and process.create_time() == stamp:
                            process.terminate()
                    _, alive = runtime.psutil.wait_procs([process for process, _ in owned], timeout=5)
                    output["isolated_qq_closed"] = not alive
                    if alive:
                        raise RuntimeError("QQ processes remain; owning Job must complete cleanup")
            except BaseException as error:
                record_error(output, error, "qq_cleanup")
                if primary is None:
                    raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("identity", "qq"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--allow-existing-account-login", action="store_true")
    parser.add_argument("--expected-desktop", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not (args.repo / "deskweft" / "server.py").is_file():
        parser.error("--repo must contain the production deskweft source")
    if args.phase == "qq" and (not args.exe or not args.exe.is_file() or args.exe.name.lower() != "qq.exe"):
        parser.error("qq requires the current --exe path to QQ.exe")

    import private_desktop as desktop
    output = {"phase": args.phase, "completed": False}
    started = time.monotonic()
    runtime = None
    code = 1
    try:
        identity = desktop.verify_dispatch_thread(args.expected_desktop)
        output["desktop"] = identity
        os.environ.update({"DESKWEFT_PRIVATE_REPO": str(args.repo.resolve()),
                           "DESKWEFT_PRIVATE_EXPECTED": args.expected_desktop,
                           "DESKWEFT_PRIVATE_INPUT": identity["input_desktop"],
                           "DESKWEFT_PRIVATE_SESSION": str(identity["session"]),
                           "DESKWEFT_PRIVATE_STATION": identity["window_station"]})
        runtime = load_runtime(args.repo)
        asyncio.run(run(args, runtime, output))
        if args.phase == "qq" and not output.get("isolated_qq_closed"):
            raise RuntimeError("QQ cleanup not verified")
        output["completed"] = True
        code = 0
    except Exception as error:
        record_error(output, error, "runner_exit" if "error" in output else output.get("stage", "startup"))
    finally:
        code = finish_run(runtime, output, args.out, started)
    print(json.dumps({"completed": output["completed"], "phase": args.phase,
                      "effect_verified": output.get("effect_verified"),
                      "search_restored_exactly": output.get("search_restored_exactly")}, ensure_ascii=False))
    return code


if __name__ == "__mp_main__":
    load_runtime(Path(os.environ["DESKWEFT_PRIVATE_REPO"]))

if __name__ == "__main__":
    raise SystemExit(main())

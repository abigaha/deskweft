"""Explicit read-only probe of an installed Edge in a fresh private desktop/profile."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from shutil import rmtree
import subprocess
import sys
from tempfile import gettempdir, mkdtemp

import psutil
import win32api
import win32gui

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "skills/windows-app-automation/scripts"))
import private_desktop as desktop
from qq_private_probe import load_runtime, response_data

LABEL, TITLE, EXPECTED = "DeskWeft synthetic stock count", "DeskWeft offline stock fixture", "93"
NATIVE_LIMIT = 16
PAGE = f"""<!doctype html><meta charset=utf-8>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; form-action 'none'">
<input id="stock" aria-label="{LABEL}" value="not-computed" readonly>
<script>document.getElementById('stock').defaultValue = 7 * 15 - 12;
document.title = '{TITLE}';</script>"""


class ProbeFailure(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise ProbeFailure(reason)


async def read_field(root, identity, output):
    runtime = load_runtime(REPO)
    expected = identity["current_desktop"]
    output["stage"] = "locate owned window"
    for _ in range(80):
        require(root.is_running(), "browser exited before window discovery")
        matches = [h for h in runtime.launch._all_top_level_windows()
                   if runtime.launch._window_pid(h) == root.pid and runtime.win32.title(h).startswith(TITLE)]
        require(len(matches) <= 1, "ambiguous fixture window")
        if matches:
            break
        await asyncio.sleep(0.15)
    require(matches, "fixture window not found")
    hwnd = matches[0]

    def verify_windows():
        require(root.is_running() and runtime.launch._window_pid(hwnd) == root.pid
                and runtime.win32.title(hwnd).startswith(TITLE),
                "fixture window ownership changed")
        owned = {root.pid, *(p.pid for p in root.children(recursive=True))}
        children = {}

        def snapshot(h, _):
            children[h] = win32gui.GetClassName(h)
            return len(children) <= NATIVE_LIMIT

        win32gui.EnumChildWindows(hwnd, snapshot, None)
        require(len(children) <= NATIVE_LIMIT, "independent child snapshot exceeded cap")
        for h in (hwnd, *children):
            tid = desktop.U.GetWindowThreadProcessId(h, None)
            require(runtime.launch._window_pid(h) in owned and desktop.object_name(
                desktop.U.GetThreadDesktop(tid)) == expected, "unowned or non-private window")
        return children

    def verify_worker(data):
        worker = runtime.uia_worker._worker
        proof = data.get("_probe_worker", {})
        tid = proof.get("tid")
        require(worker and proof.get("pid") == worker["process"].pid
                and isinstance(tid, int) and tid > 0
                and not any(k in proof for k in ("before_error", "after_error", "function_error"))
                and all(isinstance(proof.get(stage), dict) and all(proof[stage].get(k) == identity[k]
                        for k in ("current_full", "input_full"))
                        and proof[stage].get("pid") == proof["pid"] and proof[stage].get("native_tid") == tid
                        for stage in ("before", "after"))
                and desktop.object_name(desktop.U.GetThreadDesktop(tid)) == expected,
                "missing worker dispatch proof")
        return worker, tid

    output["stage"] = "verify owned window before native see"
    before = verify_windows()
    output["owned_windows_checked_before"] = len(before) + 1
    async with runtime.Client(runtime.server.mcp) as client:
        output["stage"] = "native see transport"
        reply = await client.call_tool("see", {"hwnd": hwnd, "native_only": True,
                                              "max_elements": NATIVE_LIMIT, "timeout_ms": 8000})
        require([block.type for block in reply.content] == ["text"], "expected one text block only")
        data = response_data(reply)
        output["stage"] = "native see worker identity"
        native_worker, native_tid = verify_worker(data)
        output["stage"] = "native see against independent child snapshot"
        require(data.get("ok") is True and data.get("hwnd") == hwnd and data.get("native_only") is True
                and not ({"elements", "element_count", "tree_diagnostics", "tree_note", "image_size",
                          "image_unavailable", "identity_complete", "timed_out", "limit_reached"} & data.keys()),
                "expected native-only metadata without image or UIA tree")
        rows = data.get("native_children")
        require(isinstance(rows, list) and data.get("native_children_truncated") is False,
                "expected a complete native child list within the cap")
        host_class = win32gui.GetClassName(hwnd)
        require(data.get("class") == host_class and len(rows) == len(before)
                and {row["hwnd"]: row["class"] for row in rows} == before == verify_windows(),
                "native child identity or class mismatch")
        candidates = sum(row.get("text") == LABEL for row in rows)
        output["native_see"] = {"max_elements": NATIVE_LIMIT, "text_blocks": 1, "image_or_uia_tree": False,
                                "truncated": False, "children": len(rows), "host_class": host_class,
                                "child_classes": sorted(set(before.values())), "field_label_matches": candidates,
                                "field_uniquely_located": candidates == 1}

        output["stage"] = "invoke_pattern"
        data = response_data(await client.call_tool("invoke_pattern", {
            "hwnd": hwnd, "target": {"name": LABEL, "control_type": "EditControl"},
            "pattern": "ValuePattern", "method": "Value", "timeout_ms": 8000,
            "allow_foreground": False,
        }))
        output["stage"] = "UIA worker identity"
        worker, tid = verify_worker(data)
        require(worker is native_worker and tid == native_tid, "worker changed between adjacent reads")
        output["same_worker_for_adjacent_reads"] = True
        output["worker_dispatch_private_before_after"] = True
        output["stage"] = "check UIA result"
        require(data.get("ok") and data.get("call_completed") and not data.get("result_truncated")
                and data.get("execution_state") == "completed",
                "provider did not return a complete field")
        output["execution_state"] = "completed"
        output["owned_windows_checked_after"] = len(verify_windows()) + 1
        return data.get("result")


def run_child(exe, name, out):
    try:
        report = out.open("x", encoding="ascii")
    except OSError:
        print(json.dumps({"completed": False, "stage": "create runner result"}))
        return 1
    output = {"transport": "FastMCP in-process -> DeskWeft worker IPC -> Win32 native see, then UIA ValuePattern.Value",
              "stage": "private runner preflight", "completed": False,
              "field": LABEL, "expected": EXPECTED, "actual": None, "matched": False}
    try:
        identity = desktop.verify_dispatch_thread(name)
        os.environ.update(DESKWEFT_PRIVATE_EXPECTED=name, DESKWEFT_PRIVATE_INPUT=identity["input_desktop"],
                          DESKWEFT_PRIVATE_SESSION=str(identity["session"]),
                          DESKWEFT_PRIVATE_STATION=identity["window_station"])
        output["stage"] = "create fixture HTML"
        page = out.with_suffix(".html")
        with page.open("x", encoding="ascii") as fixture:
            fixture.write(PAGE)
        output["stage"] = "create temporary profile"
        profile = out.with_suffix(".profile")
        profile.mkdir()
        profile_flag = f"--user-data-dir={profile}"
        flags = [profile_flag, "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                 "--disable-background-networking", "--disable-component-update", "--disable-sync",
                 "--disable-quic", "--host-resolver-rules=MAP * ~NOTFOUND",
                 "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",
                 "--force-renderer-accessibility", f"--app={page.as_uri()}"]
        startup = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW,
                                         wShowWindow=subprocess.SW_HIDE)
        output["stage"] = "launch and verify Edge process"
        process = subprocess.Popen([str(exe), *flags], creationflags=subprocess.CREATE_NO_WINDOW,
                                   startupinfo=startup, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL)
        root = psutil.Process(process.pid)
        require(Path(root.exe()).resolve() == exe and profile_flag in root.cmdline(),
                "unexpected executable or profile")
        version = win32api.GetFileVersionInfo(str(exe), "\\")
        words = version["FileVersionMS"], version["FileVersionLS"]
        output["edge"] = {"image": "msedge.exe", "process_image_and_temp_profile_verified": True,
                          "file_version": ".".join(str(x) for w in words for x in (w >> 16, w & 0xffff))}
        actual = asyncio.run(read_field(root, identity, output))
        if isinstance(actual, str) and (actual == "not-computed" or actual.isascii() and actual.isdecimal()):
            output["actual"] = actual
        output["stage"] = "compare calculated field"
        require(actual == EXPECTED, "calculated field does not match")
        output["matched"] = output["completed"] = True
    except ProbeFailure as error:
        output["failure"] = str(error)
    except Exception as error:
        output["error_type"] = type(error).__name__
    try:
        with report:
            json.dump(output, report)
    except OSError:
        print(json.dumps({"completed": False, "stage": "write runner result"}))
        return 1
    return 0 if output["completed"] else 1


def launch_probe(exe, root):
    result = desktop.launch([__file__, "--exe", str(exe)], root / "uia.json", timeout=45)
    child = Path(result["child_out"])
    try:
        data = json.loads(child.read_text(encoding="ascii"))
        if not isinstance(data, dict):
            raise ValueError("runner result must be an object")
    except (OSError, ValueError):
        data = {"completed": False, "stage": "read runner result"}
    data.update(launcher_ok=result["ok"], launcher_error=result.get("error"),
                job_active_after_cleanup=result["cleanup"]["active_processes"],
                cleanup_complete=result["cleanup"]["complete"],
                input_desktop_change_samples=len(result["input_desktop_changes"]),
                desktop_switch_observed=result["desktop_switch_observed"],
                foreground_or_focus_event_count=sum(e["event"] in ("foreground", "focus")
                                                    for e in result["observation"]["events"]),
                input_desktop_sample_count=len(result["input_samples"]))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=Path(os.environ["ProgramFiles(x86)"]) /
                        "Microsoft/Edge/Application/msedge.exe")
    parser.add_argument("--expected-desktop")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    require(exe.name.lower() == "msedge.exe" and exe.is_file(), "installed msedge.exe required")
    if args.expected_desktop or args.out:
        require(args.expected_desktop and args.out, "launcher arguments must be paired")
        return run_child(exe, args.expected_desktop, args.out)
    base = Path(gettempdir()).resolve(strict=True)
    root = Path(mkdtemp(prefix="deskweft-edge-field-", dir=base))
    identity = root.stat()
    require(root.resolve(strict=True) == root and root.parent == base, "unexpected temporary root")
    uia = launch_probe(exe, root)
    if uia["cleanup_complete"]:
        require(root.resolve(strict=True) == root and root.parent == base and os.path.samestat(identity, root.stat()),
                "temporary root changed")
        rmtree(root)
    uia["temporary_root_removed"] = not root.exists()
    print(json.dumps(uia, indent=2))
    passed = (uia["launcher_ok"] and uia["cleanup_complete"] and uia["temporary_root_removed"]
              and uia.get("completed") is True and uia.get("matched") is True and uia.get("actual") == EXPECTED
              and uia["job_active_after_cleanup"] == 0 and uia["input_desktop_change_samples"] == 0
              and uia["desktop_switch_observed"] is False)
    return 0 if passed else 1


if __name__ == "__mp_main__":
    load_runtime(REPO)
elif __name__ == "__main__":
    raise SystemExit(main())

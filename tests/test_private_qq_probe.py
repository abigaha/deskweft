"""Offline checks for the shipped QQ probe's data and action boundaries."""

from __future__ import annotations

import importlib.util
import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = (Path(__file__).resolve().parents[1] / "skills" / "windows-app-automation"
          / "scripts" / "qq_private_probe.py")


class TestPrivateQQProbe(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "the skill does not yet ship a standalone QQ runner")
        spec = importlib.util.spec_from_file_location("qq_private_probe_test", SCRIPT)
        self.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.probe)

    def test_log_summary_does_not_save_conversation_or_search_text(self):
        secret = "private-contact-and-original-search"
        summary = self.probe.summarize_result({
            "ok": True, "result": secret, "detail": secret, "title": secret,
            "elements": [{"control_type": "ComboBoxControl", "name": secret,
                          "automation_id": secret}],
            "native_children": [{"text": secret}],
        })
        self.assertNotIn(secret, json.dumps(summary))
        self.assertEqual(summary["types"], {"ComboBoxControl": 1})
        self.assertEqual(summary["result"]["chars"], len(secret))

    def test_complete_unique_search_control_can_be_selected(self):
        tree = {"ok": True, "identity_complete": True, "timed_out": False,
                "limit_reached": False, "elements": [{"control_type": "ComboBoxControl"}]}
        self.assertEqual(self.probe.search_selector(tree), {"control_type": "ComboBoxControl"})

    def test_incomplete_or_ambiguous_search_tree_cannot_trigger_a_write(self):
        for tree in (
            {"ok": True, "identity_complete": False,
             "elements": [{"control_type": "ComboBoxControl"}]},
            {"ok": True, "identity_complete": True, "timed_out": True,
             "elements": [{"control_type": "ComboBoxControl"}]},
            {"ok": True, "identity_complete": True,
             "elements": [{"control_type": "ComboBoxControl"},
                          {"control_type": "ComboBoxControl"}]},
        ):
            with self.subTest(tree=tree), self.assertRaises(RuntimeError):
                self.probe.search_selector(tree)

    def test_existing_account_login_requires_explicit_runner_scope(self):
        tree = {"ok": True, "identity_complete": True,
                "elements": [{"name": "登录", "control_type": "ButtonControl"}]}
        with self.assertRaises(PermissionError):
            self.probe.login_selector(tree, allow_existing_account_login=False)
        self.assertEqual(self.probe.login_selector(tree, allow_existing_account_login=True),
                         {"name": "登录", "control_type": "ButtonControl"})

    def test_ambiguous_login_is_rejected_even_when_login_is_authorized(self):
        tree = {"ok": True, "identity_complete": True,
                "elements": [{"name": "登录", "control_type": "ButtonControl"}] * 2}
        with self.assertRaises(RuntimeError):
            self.probe.login_selector(tree, allow_existing_account_login=True)

    def test_restore_accepts_our_change_but_preserves_unknown_concurrent_text(self):
        self.assertEqual(self.probe.restoration_value("probe", "original", "probe"), "original")
        self.assertEqual(self.probe.restoration_value("original", "original", "probe"), "original")
        with self.assertRaises(RuntimeError):
            self.probe.restoration_value("someone-elses-change", "original", "probe")

    def test_unknown_write_stops_without_reading_or_restoring(self):
        self.assertTrue(hasattr(self.probe, "search_roundtrip"), "search needs an explicit safe restoration boundary")
        calls, output = [], {}

        async def value(label):
            calls.append(label)
            return "original"

        async def set_value(label, text):
            calls.append(label)
            raise TimeoutError("provider outcome unknown")

        with self.assertRaises(TimeoutError):
            asyncio.run(self.probe.search_roundtrip(value, set_value, output))
        self.assertEqual(calls, ["original_search", "write_search"])
        self.assertFalse(output["search_restored_exactly"])

    def test_guard_loss_after_write_stops_without_restore(self):
        self.assertTrue(hasattr(self.probe, "search_roundtrip"), "search needs an explicit safe restoration boundary")
        calls, output = [], {}

        async def value(label):
            calls.append(label)
            if label == "original_search":
                return "original"
            output["continuation_blocked"] = True
            raise RuntimeError("actual worker proof unavailable")

        async def set_value(label, text):
            calls.append(label)

        with self.assertRaises(RuntimeError):
            asyncio.run(self.probe.search_roundtrip(value, set_value, output))
        self.assertEqual(calls, ["original_search", "write_search", "readback_search"])
        self.assertFalse(output["search_restored_exactly"])

    def test_provider_and_after_guard_errors_both_survive(self):
        self.assertTrue(hasattr(self.probe, "guard_dispatch"), "dispatch needs structured error preservation")
        checks = iter([{"current_desktop": "private"}, RuntimeError("after guard failed")])

        def verify():
            value = next(checks)
            if isinstance(value, Exception):
                raise value
            return value

        def provider():
            raise ValueError("original provider failure")

        result = self.probe.guard_dispatch(provider, verify, action="invoke_pattern", parameters={})
        self.assertEqual(result["execution_state"], "unknown")
        self.assertEqual(result["_probe_worker"]["function_error"]["type"], "ValueError")
        self.assertEqual(result["_probe_worker"]["after_error"]["type"], "RuntimeError")
        self.assertEqual(result["_probe_worker"]["before"], {"current_desktop": "private"})

    def test_worker_close_error_still_writes_primary_error_to_json(self):
        self.assertTrue(hasattr(self.probe, "finish_run"), "outer cleanup must always write its report")

        def close():
            raise OSError("close failed")

        runtime = SimpleNamespace(uia_worker=SimpleNamespace(close=close, _worker=object()))
        output = {"completed": True, "error": {"type": "TimeoutError", "stage": "write_search"}}
        with tempfile.TemporaryDirectory(dir=SCRIPT.parents[3]) as directory:
            path = Path(directory) / "child.json"
            code = self.probe.finish_run(runtime, output, path, time.monotonic())
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertFalse(saved["completed"])
        self.assertEqual(saved["error"], {"type": "TimeoutError", "stage": "write_search"})
        self.assertEqual(saved["secondary_errors"][0]["type"], "OSError")
        self.assertEqual(saved["secondary_errors"][0]["stage"], "worker_close")

    def run_with_tool_results(self, *, incomplete_setter=False, queued_getter=False,
                              login=False, login_result=None, requests=None):
        proof = {"pid": 200, "native_tid": 300, "session": 1, "window_station": "WinSta0",
                 "current_desktop": "private", "input_desktop": "Default",
                 "current_full": "1/WinSta0/private", "input_full": "1/WinSta0/Default", "isolated": True}
        worker = {"pid": 200, "tid": 300, "before": proof, "after": proof}
        methods = []

        class Client:
            current = "original"
            logged_in = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def call_tool(self, tool, parameters):
                if requests is not None:
                    requests.append((tool, parameters))
                result = {"ok": True, "execution_state": "completed", "call_completed": True,
                          "_probe_worker": worker}
                if tool == "see" and parameters["hwnd"] == 0:
                    result.update(ok=False, execution_state="not_started")
                elif tool == "open_app":
                    result["pid"] = 100
                elif tool == "see":
                    controls = ([{"name": "登录", "control_type": "ButtonControl"}]
                                if login and not self.logged_in else [{"control_type": "ComboBoxControl"}])
                    result.update(identity_complete=True, elements=controls)
                elif tool == "click":
                    self.logged_in = True
                elif tool == "invoke_pattern":
                    methods.append(parameters["method"])
                    if parameters["method"] == "DoDefaultAction":
                        self.logged_in = True
                        if login_result == "unavailable":
                            result.update(ok=False, execution_state="not_started", reason="pattern unavailable")
                            del result["call_completed"]
                        elif login_result == "incomplete":
                            del result["call_completed"]
                        elif login_result == "queued":
                            result["delivery"] = "queued"
                    elif parameters["method"] == "SetValue":
                        self.current = parameters["args"][0]
                        if incomplete_setter:
                            del result["call_completed"]
                    else:
                        result["result"] = self.current
                        if queued_getter:
                            result["delivery"] = "queued"
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(result))])

        exe = Path("QQ.exe").resolve()
        process = SimpleNamespace(pid=100, create_time=lambda: 1, exe=lambda: str(exe),
                                  is_running=lambda: True, children=lambda **kw: [], terminate=lambda: None)
        runtime = SimpleNamespace(Client=lambda mcp: Client(), server=SimpleNamespace(mcp=object()),
                                  uia_worker=SimpleNamespace(_worker={"process": SimpleNamespace(pid=200)}),
                                  psutil=SimpleNamespace(Process=lambda pid: process, wait_procs=lambda p, timeout: (p, [])),
                                  appinfo=SimpleNamespace(app_info=lambda hwnd: {}))
        output, error = {"desktop": proof}, None
        with tempfile.TemporaryDirectory(dir=SCRIPT.parents[3]) as directory:
            args = SimpleNamespace(phase="qq", expected_desktop="private", exe=exe,
                                   allow_existing_account_login=login, out=Path(directory) / "child.json")
            with patch.object(self.probe, "qq_processes", return_value=[]), \
                    patch.object(self.probe, "main_window", return_value=100), \
                    patch.object(self.probe, "verify_windows", return_value=[]), \
                    patch.object(self.probe.asyncio, "sleep", return_value=None):
                try:
                    asyncio.run(self.probe.run(args, runtime, output))
                except RuntimeError as caught:
                    error = caught
        return methods, output, error

    def test_real_run_login_uses_only_explicit_semantic_action_and_logs_safe_arguments(self):
        requests = []
        methods, output, error = self.run_with_tool_results(login=True, requests=requests)
        self.assertIsNone(error)
        self.assertNotIn("click", [tool for tool, _ in requests])
        self.assertEqual(methods[0], "DoDefaultAction")
        login_call = next(row for row in output["calls"] if row["stage"] == "existing_account_login")
        self.assertEqual(login_call["tool"], "invoke_pattern")
        self.assertEqual(login_call["request"], {
            "pattern": "LegacyIAccessiblePattern", "method": "DoDefaultAction",
            "target": {"name": "登录", "control_type": "ButtonControl"}, "args": [],
        })
        restore = next(row for row in output["calls"] if row["stage"] == "restore_search")
        self.assertEqual(restore["request"]["args"], [self.probe.safe_text("original")])

    def test_real_run_login_failure_stops_without_fallback_or_search(self):
        for mode in ("unavailable", "incomplete", "queued"):
            with self.subTest(mode=mode):
                requests = []
                methods, output, error = self.run_with_tool_results(
                    login=True, login_result=mode, requests=requests)
                self.assertIsInstance(error, RuntimeError)
                self.assertEqual(methods, ["DoDefaultAction"])
                self.assertNotIn("click", [tool for tool, _ in requests])
                self.assertTrue(output["continuation_blocked"])
                self.assertEqual(output["error"]["stage"], "existing_account_login")
                self.assertEqual(output["calls"][-1]["stage"], "existing_account_login")
                self.assertTrue(output["isolated_qq_closed"])

    def test_real_run_stops_at_setter_without_completed_call_evidence(self):
        methods, output, error = self.run_with_tool_results(incomplete_setter=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(methods, ["Value", "SetValue"])
        self.assertTrue(output["continuation_blocked"])
        self.assertFalse(output["search_restored_exactly"])
        self.assertEqual(output["error"]["stage"], "write_search")

    def test_real_run_treats_delivery_queued_as_unfinished(self):
        methods, output, error = self.run_with_tool_results(queued_getter=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(methods, ["Value"])
        self.assertTrue(output["continuation_blocked"])
        self.assertEqual(output["error"]["stage"], "original_search")


if __name__ == "__main__":
    unittest.main()

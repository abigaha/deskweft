"""Offline lifecycle tests: no desktop, GUI, process or hook is created."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "skills/windows-app-automation/scripts/private_desktop.py"
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location("private_desktop_tested", SCRIPT)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
else:
    helper = None


def identity(current="Default", active="Default", session=1, station="WinSta0"):
    prefix = f"{session}/{station}/"
    return {"pid": 10, "native_tid": 11, "session": session,
            "window_station": station, "current_desktop": current,
            "input_desktop": active, "current_full": prefix + current,
            "input_full": prefix + active, "isolated": current != active}


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeAPI:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.fail = None
        self.active_counts = [0]
        self.identities = [identity()]
        self.child = {"completed": True}
        self.code = 0
        self.keep_running = False
        self.terminated = False

    def record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail == name:
            raise OSError(5, "synthetic failure")

    def identity(self):
        self.record("identity")
        return self.identities.pop(0) if len(self.identities) > 1 else self.identities[0]

    def foreground(self):
        return 101

    def create_job(self):
        self.record("create_job")
        return "job"

    def configure_job(self, job):
        self.record("configure_job", job)

    def create_desktop(self, name):
        self.record("create_desktop", name)
        return "desktop"

    def spawn(self, argv, desktop):
        self.record("spawn", argv, desktop)
        if self.child is not None:
            Path(argv[-1]).write_text(json.dumps(self.child), encoding="utf-8")
        return SimpleNamespace(hProcess="process", hThread="thread", dwProcessId=42)

    def assign(self, job, process):
        self.record("assign", job, process)

    def resume(self, thread):
        self.record("resume", thread)

    def wait(self, process, milliseconds):
        self.record("wait", process, milliseconds)
        self.clock.sleep(milliseconds / 1000)
        return self.terminated or not self.keep_running

    def exit_code(self, process):
        self.record("exit_code", process)
        return self.code

    def terminate_job(self, job):
        self.record("terminate_job", job)
        self.terminated = True

    def terminate_process(self, process):
        self.record("terminate_process", process)
        self.terminated = True

    def active_processes(self, job):
        self.record("active_processes", job)
        return self.active_counts.pop(0) if len(self.active_counts) > 1 else self.active_counts[0]

    def close_handle(self, handle):
        self.record("close_handle", handle)

    def close_desktop(self, desktop):
        self.record("close_desktop", desktop)


class FakeMonitor:
    def __init__(self, *args):
        self.events = []
        self.errors = []
        self.removed = False
        self.started = False

    def start(self):
        self.started = True

    def close(self):
        self.removed = True

    def report(self):
        return {"events": self.events, "errors": self.errors,
                "installed": self.started, "removed": self.removed}


class TestPrivateDesktopPresence(unittest.TestCase):
    def test_deliverable_exists(self):
        self.assertIsNotNone(helper, "the skill must ship its own private_desktop.py")


@unittest.skipIf(helper is None, "helper not implemented yet")
class TestPrivateDesktop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="private-desktop-test-", dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / "runner with spaces.py"
        self.runner.write_text("# never executed\n", encoding="utf-8")
        self.clock = Clock()
        self.api = FakeAPI(self.clock)
        self.monitor = FakeMonitor()

    def launch(self, **kwargs):
        return helper.launch([str(self.runner), "safe value"], self.root / "parent.json",
                             api=self.api, monitor_factory=lambda *a: self.monitor,
                             clock=self.clock, sleep=self.clock.sleep, **kwargs)

    def names(self):
        return [call[0] for call in self.api.calls]

    def test_suspend_assign_resume_and_unique_child_contract(self):
        result = self.launch()
        self.assertTrue(result["ok"], result)
        names = self.names()
        self.assertLess(names.index("assign"), names.index("resume"))
        argv, desktop = next(c[1:] for c in self.api.calls if c[0] == "spawn")
        self.assertEqual(argv[:3], [helper.sys.executable, "-B", str(self.runner)])
        self.assertEqual(argv[3], "safe value")
        self.assertEqual(argv[-4], "--expected-desktop")
        self.assertEqual(argv[-2], "--out")
        self.assertEqual(desktop, "WinSta0\\" + argv[-3])
        self.assertIn(argv[-3], Path(argv[-1]).name)
        self.assertEqual(result["runner_exit_code"], 0)
        self.assertTrue(result["cleanup"]["complete"])
        self.assertTrue(result["observation"]["removed"])

    def test_release_process_references_then_prove_job_zero_before_desktop_close(self):
        self.api.active_counts = [2, 0]
        result = self.launch()
        calls = self.api.calls
        first_query = next(i for i, c in enumerate(calls) if c[0] == "active_processes")
        process_close = calls.index(("close_handle", "process"))
        desktop_close = calls.index(("close_desktop", "desktop"))
        job_close = calls.index(("close_handle", "job"))
        self.assertLess(calls.index(("terminate_job", "job")), process_close)
        self.assertLess(process_close, first_query)
        self.assertLess(first_query, desktop_close)
        self.assertLess(desktop_close, job_close)
        self.assertEqual(result["cleanup"]["active_processes"], 0)
        self.assertGreaterEqual(len(result["input_samples"]), 3)

    def test_assignment_failure_kills_the_unassigned_suspended_process(self):
        self.api.fail = "assign"
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertNotIn("resume", self.names())
        self.assertIn(("terminate_process", "process"), self.api.calls)
        self.assertTrue(result["cleanup"]["complete"])

    def test_resume_failure_terminates_job_and_proves_zero(self):
        self.api.fail = "resume"
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertIn("terminate_job", self.names())
        self.assertEqual(result["cleanup"]["active_processes"], 0)

    def test_create_process_failure_still_cleans_job_and_desktop(self):
        self.api.fail = "spawn"
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertIn("terminate_job", self.names())
        self.assertIn("close_desktop", self.names())
        self.assertNotIn("resume", self.names())

    def test_job_configuration_failure_never_creates_a_process(self):
        self.api.fail = "configure_job"
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertNotIn("spawn", self.names())
        self.assertIn(("close_handle", "job"), self.api.calls)

    def test_launcher_on_non_input_desktop_refuses_before_resource_creation(self):
        self.api.identities = [identity("Other")]
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertNotIn("create_desktop", self.names())
        self.assertNotIn("create_job", self.names())

    def test_timeout_kills_the_whole_job(self):
        self.api.keep_running = True
        result = self.launch(timeout=0.1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "TimeoutError")
        self.assertIn("terminate_job", self.names())
        self.assertTrue(result["cleanup"]["complete"])

    def test_input_desktop_change_is_reported_and_stops_runner(self):
        self.api.identities = [identity(), identity(), identity(active="Winlogon")]
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertTrue(result["input_desktop_changes"])
        self.assertIn("terminate_job", self.names())

    def test_cleanup_timeout_is_not_hidden_by_successful_close_desktop(self):
        self.api.active_counts = [1]
        result = self.launch(cleanup_timeout=0.1)
        self.assertFalse(result["ok"])
        self.assertFalse(result["cleanup"]["complete"])
        self.assertEqual(result["cleanup"]["active_processes"], 1)
        self.assertIn("close_desktop", self.names())

    def test_observer_failure_prevents_spawn(self):
        self.monitor.start = mock.Mock(side_effect=RuntimeError("hook unavailable"))
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertNotIn("spawn", self.names())
        self.assertTrue(self.monitor.removed)

    def test_nonzero_runner_exit_is_failure_even_with_completed_json(self):
        self.api.code = 7
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertEqual(result["runner_exit_code"], 7)
        self.assertTrue(result["cleanup"]["complete"])

    def test_missing_or_incomplete_child_json_cannot_claim_success(self):
        for child in [None, {}, {"completed": False}, []]:
            with self.subTest(child=child):
                self.api.child = child
                self.assertFalse(self.launch()["ok"])

    def test_monitor_changes_are_observations_not_a_guarantee(self):
        self.monitor.events = [{"event": "foreground", "hwnd": 123}]
        result = self.launch()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["foreground_or_focus_changed"])
        self.assertEqual(result["observation"]["events"], self.monitor.events)
        self.assertNotIn("foreground_preserved", result)

    def test_desktop_switch_during_cleanup_cannot_be_reported_as_success(self):
        def close():
            self.monitor.events.append({"event": "desktop_switch", "hwnd": None})
            self.monitor.removed = True
        self.monitor.close = close
        result = self.launch()
        self.assertFalse(result["ok"])
        self.assertTrue(result["desktop_switch_observed"])

    def test_nonfinite_timeouts_are_rejected_before_resource_creation(self):
        for value in [float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.launch(timeout=value)
        self.assertNotIn("create_job", self.names())

    def test_reserved_runner_arguments_are_rejected_without_spawn(self):
        with self.assertRaises(ValueError):
            helper.launch([str(self.runner), "--out", "old.json"], self.root / "p.json",
                          api=self.api, monitor_factory=lambda *a: self.monitor)
        self.assertNotIn("spawn", self.names())

    def test_dispatch_proof_checks_name_session_station_and_input(self):
        good = identity("Private")
        with mock.patch.object(helper, "desktop_identity", return_value=good):
            self.assertEqual(helper.verify_dispatch_thread("Private", expected_session=1), good)
        for bad in [identity("Other"), identity("Private", "Other"),
                    identity("Private", session=2), identity("Private", station="Other")]:
            with self.subTest(bad=bad), mock.patch.object(helper, "desktop_identity", return_value=bad):
                with self.assertRaises(RuntimeError):
                    helper.verify_dispatch_thread("Private", expected_session=1)


if __name__ == "__main__":
    unittest.main()

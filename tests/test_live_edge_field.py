"""Offline resource-boundary regressions for the live Edge field probe."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


class TestLiveEdgeField(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.exe = self.root / "msedge.exe"
        self.exe.touch()
        self.enterContext(mock.patch.dict(os.environ, {"ProgramFiles(x86)": str(self.root)}))
        self.desktop = mock.Mock()
        spec = importlib.util.spec_from_file_location(
            "live_edge_field_tested", Path(__file__).with_name("live_edge_field.py"))
        self.probe = importlib.util.module_from_spec(spec)
        imports = {name: mock.Mock() for name in ("psutil", "win32api", "win32gui", "qq_private_probe")}
        with mock.patch.dict(sys.modules, imports, private_desktop=self.desktop), \
                mock.patch.object(sys, "path", sys.path.copy()):
            spec.loader.exec_module(self.probe)
        self.popen = self.enterContext(mock.patch.object(
            self.probe.subprocess, "Popen", side_effect=RuntimeError("mock Edge launch")))
        self.addCleanup(self.popen.assert_not_called)

    def run_probe(self, *args):
        with mock.patch.object(sys, "argv", ["live_edge_field.py", "--exe", str(self.exe), *args]), \
                contextlib.redirect_stdout(io.StringIO()):
            return self.probe.main()

    def test_invalid_child_result_cleans_root_after_job_reaches_zero(self):
        for payload in (b'{"completed":', b"[]"):
            with self.subTest(payload=payload):
                def launch(_runner, out, **_kwargs):
                    child = out.with_name("child.json")
                    child.write_bytes(payload)
                    return {
                        "ok": False, "child_out": str(child), "runner_exit_code": 1,
                        "cleanup": {"complete": True, "active_processes": 0, "errors": []},
                        "input_desktop_changes": [], "desktop_switch_observed": False,
                        "observation": {"events": []}, "input_samples": [],
                    }

                self.desktop.launch.reset_mock()
                self.desktop.launch.side_effect = launch
                with mock.patch.object(self.probe, "gettempdir", return_value=str(self.root)):
                    self.assertEqual(self.run_probe(), 1)
                self.desktop.launch.assert_called_once()
                self.assertEqual(list(self.root.iterdir()), [self.exe])

    def test_existing_child_files_are_preserved_without_launching_edge(self):
        for suffix, dispatch_allowed in ((".json", False), (".json", True), (".html", True)):
            with self.subTest(suffix=suffix, dispatch_allowed=dispatch_allowed):
                with tempfile.TemporaryDirectory(dir=self.root) as directory:
                    out = Path(directory) / "child.json"
                    existing = out.with_suffix(suffix)
                    original = b"existing bytes\x00\xff\r\n"
                    existing.write_bytes(original)
                    self.desktop.verify_dispatch_thread.return_value = {
                        "current_desktop": "private", "input_desktop": "Default",
                        "session": 1, "window_station": "WinSta0",
                    }
                    self.desktop.verify_dispatch_thread.side_effect = (
                        None if dispatch_allowed else RuntimeError("mock desktop mismatch"))
                    self.assertEqual(self.run_probe("--expected-desktop", "private", "--out", str(out)), 1)
                    self.assertEqual(existing.read_bytes(), original)

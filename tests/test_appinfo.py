"""app_info: a version evidence ladder, one rung at a time, source reported.

Every rung is mocked here; no real process, file version resource or window is
touched, so the tests say nothing about any installed application.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deskweft import appinfo

QQ_EXE = r"C:\Program Files\Tencent\QQ.exe"
QQ_BUILD = r"C:\Program Files\Tencent\versions\9.9.22-40824"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
EDGE_BUILD = r"C:\Program Files (x86)\Microsoft\Edge\Application\157.0.4341.42"


class TestVersionRegex(unittest.TestCase):
    def test_regex_keeps_the_build_suffix(self):
        match = appinfo._VER_PATH.search(r"C:\x\versions\9.9.22-40824\resources\app")
        self.assertEqual(match.group(1), "9.9.22-40824")

    def test_short_regex_would_miss_the_candidate(self):
        # Written as an assertion so the short form cannot creep back in.
        self.assertIsNone(appinfo.VER_SHORT.fullmatch("9.9.22-40824"))
        self.assertIsNotNone(appinfo.VER_EXACT.fullmatch("9.9.22-40824"))

    def test_version_sorting_is_not_string_order(self):
        self.assertEqual(sorted(["10.0.0", "9.9.9", "9.9.22"], key=appinfo.version_sort_key),
                         ["9.9.9", "9.9.22", "10.0.0"])


class TestEvidenceLadder(unittest.TestCase):
    def ladder(self, *, exe=QQ_EXE, children=(), candidates=None, info=None):
        child = (lambda pid: (children[0], None)) if children else (lambda pid: (None, None))
        with mock.patch.object(appinfo, "_process_path", return_value=exe), \
             mock.patch.object(appinfo, "_child_cmdline_version", side_effect=child), \
             mock.patch.object(appinfo, "_candidate_dirs", return_value=candidates or []), \
             mock.patch.object(appinfo, "_file_version_info", return_value=info or {}):
            return appinfo._version_evidence(1234, exe, info or {})

    def test_rung_1_path_segment_wins(self):
        version, source, warnings = self.ladder(
            exe=QQ_BUILD + r"\QQ.exe",
            children=["1.1.1"],
            candidates=["2.2.2"],
            info={"file_version": "3.3.3"})
        self.assertEqual((version, source, warnings), ("9.9.22", "path_segment", []))

    def test_rung_2_child_cmdline_beats_candidates_and_file_version(self):
        version, source, warnings = self.ladder(
            children=["9.9.22"], candidates=["9.9.22-40824"],
            info={"file_version": "9.9.19.35469"})
        self.assertEqual((version, source), ("9.9.22", "child_cmdline"))
        self.assertEqual(warnings, [])

    def test_rung_3_sole_candidate_needs_a_warning(self):
        version, source, warnings = self.ladder(candidates=["9.9.22-40824"],
                                                info={"file_version": "9.9.19.35469"})
        self.assertEqual((version, source), ("9.9.22", "sole_candidate"))
        self.assertTrue(any("not verified" in w for w in warnings), warnings)

    def test_rung_3_never_guesses_between_candidates(self):
        version, source, warnings = self.ladder(candidates=["9.9.22-40824", "9.9.23-1"],
                                                info={"file_version": "9.9.19.35469"})
        self.assertEqual((version, source), ("9.9.19.35469", "file_version"))
        self.assertTrue(any("candidate" in w for w in warnings), warnings)

    def test_rung_4_file_version_is_complete(self):
        version, source, _ = self.ladder(info={"file_version": "157.0.4341.42"})
        self.assertEqual((version, source), ("157.0.4341.42", "file_version"))

    def test_rung_5_sibling_dir(self):
        version, source, warnings = self.ladder(exe=EDGE_EXE, info={})
        self.assertEqual((version, source), ("157.0.4341.42", "sibling_dir"))
        self.assertTrue(warnings)

    def test_rung_6_no_evidence(self):
        version, source, warnings = self.ladder(exe=r"C:\nowhere\mystery.exe", info={})
        self.assertIsNone(version)
        self.assertIsNone(source)
        self.assertTrue(warnings)

    def test_file_version_is_never_shortened(self):
        version, _, _ = self.ladder(info={"file_version": "9.9.19.35469"})
        self.assertEqual(version, "9.9.19.35469")
        self.assertNotEqual(version, "9.9")


class TestCandidates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_non_directories_and_plain_files_are_not_candidates(self):
        versions = self.root / "versions"
        versions.mkdir()
        (versions / "9.9.22-40824").mkdir()
        for name in ("channel.json", "config.json", "setting.json"):
            (versions / name).write_text("{}", encoding="utf-8")
        self.assertEqual(appinfo._candidate_dirs(str(self.root / "app.exe")), ["9.9.22-40824"])

    def test_sibling_directories_are_a_separate_fallback(self):
        application = self.root / "Application"
        application.mkdir()
        (application / "157.0.4341.42").mkdir()
        (application / "msedge.exe").write_text("", encoding="utf-8")
        self.assertEqual(appinfo._sibling_version(str(application / "msedge.exe")),
                         "157.0.4341.42")
        missing = self.root / "no-such-folder"
        self.assertIsNone(appinfo._sibling_version(str(missing / "msedge.exe")))


class TestAppInfo(unittest.TestCase):
    def test_success_shape(self):
        with mock.patch.object(appinfo, "_hwnd_pid", return_value=42), \
             mock.patch.object(appinfo, "_process_path", return_value=QQ_EXE), \
             mock.patch.object(appinfo, "_file_version_info",
                               return_value={"file_version": "9.9.19.35469",
                                             "product": "QQ", "company": "Tencent"}), \
             mock.patch.object(appinfo, "_version_evidence",
                               return_value=("9.9.22", "child_cmdline", [])), \
             mock.patch.object(appinfo, "_candidate_dirs", return_value=["9.9.22-40824"]):
            result = appinfo.app_info(1234)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["hwnd"], 1234)
        self.assertEqual(result["pid"], 42)
        self.assertEqual(result["name"], "QQ")
        self.assertEqual(result["exe"], QQ_EXE)
        self.assertEqual(result["version"], "9.9.22")
        self.assertEqual(result["source"], "child_cmdline")
        self.assertEqual(result["file_version"], "9.9.19.35469")
        self.assertEqual(result["version_candidates"], ["9.9.22-40824"])
        self.assertEqual(result["warnings"], [])

    def test_readable_exe_without_version_still_succeeds(self):
        with mock.patch.object(appinfo, "_hwnd_pid", return_value=42), \
             mock.patch.object(appinfo, "_process_path", return_value=QQ_EXE), \
             mock.patch.object(appinfo, "_file_version_info", return_value={}), \
             mock.patch.object(appinfo, "_version_evidence", return_value=(None, None, ["none"])), \
             mock.patch.object(appinfo, "_candidate_dirs", return_value=[]):
            result = appinfo.app_info(1234)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["version"])
        self.assertIsNone(result["source"])
        self.assertEqual(result["warnings"], ["none"])

    def test_dead_window_and_unreadable_exe_are_structured_errors(self):
        with mock.patch.object(appinfo, "_hwnd_pid", return_value=0):
            dead = appinfo.app_info(999)
        self.assertFalse(dead["ok"])
        self.assertEqual(dead["reason"], "no such window")
        with mock.patch.object(appinfo, "_hwnd_pid", return_value=42), \
             mock.patch.object(appinfo, "_process_path", return_value=None):
            gone = appinfo.app_info(1234)
        self.assertFalse(gone["ok"])
        self.assertEqual(gone["reason"], "process unavailable")

    def test_invalid_hwnd_is_rejected_before_any_call(self):
        for bad in (0, -1, 0xFFFF, True, "1234"):
            with mock.patch.object(appinfo, "_hwnd_pid") as pid:
                result = appinfo.app_info(bad)
            self.assertFalse(result["ok"], bad)
            self.assertEqual(result["reason"], "invalid hwnd", bad)
            pid.assert_not_called()


class TestChildCommandLine(unittest.TestCase):
    def test_access_denied_on_children_is_a_warning_not_a_crash(self):
        import psutil

        with mock.patch.object(appinfo.psutil, "Process",
                               side_effect=psutil.AccessDenied(pid=7)):
            version, warning = appinfo._child_cmdline_version(7)
        self.assertIsNone(version)
        self.assertIn("AccessDenied", warning)

    def test_a_failing_child_is_skipped(self):
        import psutil

        good = mock.Mock()
        good.cmdline.return_value = ["QQ.exe", r"--app-path=C:\x\versions\9.9.22-40824\resources\app"]
        bad = mock.Mock()
        bad.cmdline.side_effect = psutil.AccessDenied(pid=8)
        proc = mock.Mock()
        proc.children.return_value = [bad, good]
        with mock.patch.object(appinfo.psutil, "Process", return_value=proc):
            version, warning = appinfo._child_cmdline_version(7)
        self.assertEqual(version, "9.9.22")
        self.assertIn("AccessDenied", warning)

    def test_every_argument_is_searched(self):
        child = mock.Mock()
        child.cmdline.return_value = ["QQ.exe", "--type=renderer",
                                      "--app-path=C:\\x\\versions\\9.9.22-40824\\resources\\app"]
        proc = mock.Mock()
        proc.children.return_value = [child]
        with mock.patch.object(appinfo.psutil, "Process", return_value=proc):
            version, _ = appinfo._child_cmdline_version(7)
        self.assertEqual(version, "9.9.22")


if __name__ == "__main__":
    unittest.main()

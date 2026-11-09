"""launch.py: hide only windows proven to belong to the launch.

Everything process-level is mocked. No program is started and no real window
is touched.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from deskweft import launch


class LaunchCase(unittest.TestCase):
    def setUp(self):
        for name, value in (("title", "Launcher"), ("class_name", "Win32Window")):
            patch = mock.patch.object(launch.win32, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(launch.time, "sleep", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)
        self.windows = []          # (hwnd, pid, class, title)
        self.pids = {}             # pid -> created FILETIME
        self.parents = {}          # pid -> ppid
        self.baseline = set()
        self.baseline_pids = {}
        self.foreground = 100
        self.popen_pid = 500

    def install(self, *, popen_pid=None, identity_error=()):
        self.windows_after = []

        def all_windows():
            return list(self.baseline) + [w[0] for w in self.windows_after]

        def window_pid(hwnd):
            for w in self.windows_after:
                if w[0] == hwnd:
                    return w[1]
            # Baseline windows exist before the launch; the foreground one must
            # still have a readable process identity.
            return self.baseline_pids.get(hwnd, 0)

        def identity(pid):
            if pid in identity_error or pid not in self.pids:
                return None
            return {"pid": pid, "created": self.pids[pid]}

        pid = self.popen_pid if popen_pid is None else popen_pid
        proc = mock.Mock(pid=pid)
        ctx = [
            mock.patch.object(launch, "_all_top_level_windows", side_effect=all_windows),
            mock.patch.object(launch, "_window_pid", side_effect=window_pid),
            mock.patch.object(launch, "_process_identity", side_effect=identity),
            mock.patch.object(launch, "_snapshot_parents", return_value=self.parents),
            mock.patch.object(launch.subprocess, "Popen", return_value=proc),
            mock.patch.object(launch.win32, "list_windows",
                              side_effect=lambda: [
                                  {"hwnd": h, "class": c, "title": t, "pid": p,
                                   "rect": [0, 0, 10, 10], "foreground": False}
                                  for h, p, c, t in self.windows_after]),
            mock.patch.object(launch.win32, "foreground",
                              side_effect=lambda: self.foreground),
            mock.patch.object(launch.win32, "activate", return_value=True),
            mock.patch.object(launch.win32, "grab", return_value=None),
        ]
        for patch in ctx:
            patch.start()
            self.addCleanup(patch.stop)
        # SetWindowPos must actually look like a hide, and IsWindowVisible must
        # report the new state, or the "did it really hide?" check is untested.
        self.visible: dict[int, bool] = {}
        self.hide_ok = True
        self._set_window_pos = mock.patch.object(
            launch.user32, "SetWindowPos", side_effect=self._place)
        self.set_window_pos = self._set_window_pos.start()
        self.addCleanup(self._set_window_pos.stop)
        self._visible = mock.patch.object(
            launch.user32, "IsWindowVisible", side_effect=lambda h: 1 if self._shown(h) else 0)
        self._visible.start()
        self.addCleanup(self._visible.stop)
        for name, value in (("IsIconic", 0), ("IsWindow", 1)):
            patch = mock.patch.object(launch.user32, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def _shown(self, hwnd):
        key = int(hwnd)
        # Everything starts visible; only a successful hide changes that.
        return self.visible.get(key, True)

    def _place(self, hwnd, insert_after, x, y, cx, cy, flags):
        # Only the hide flags (SWP_HIDEWINDOW set, not NOACTIVATE-only) count.
        if self.hide_ok and flags & 0x0080:
            self.visible[int(hwnd)] = False
        return 1 if self.hide_ok else 0

    def hide_calls(self):
        return [c for c in self.set_window_pos.call_args_list
                if c.args and c.args[1] is None]

    def run_launch(self, spawn=None, **kwargs):
        """Launch with a `spawn` hook that adds windows when Popen is called."""
        target = launch.subprocess.Popen
        if spawn is not None:
            def popen(*args, **kw):
                spawn()
                return target(*args, **kw)
            with mock.patch.object(launch.subprocess, "Popen", side_effect=popen):
                return launch.launch("x.exe", settle=0.02, **kwargs)
        return launch.launch("x.exe", settle=0.02, **kwargs)


class TestOwnership(LaunchCase):
    def setUp(self):
        super().setUp()
        self.baseline = {100, 101}
        self.pids = {500: 1000, 900: 2000, 600: 3000}
        self.parents = {500: 1, 600: 500}
        self.install()
        self.foreground = 100

    def test_baseline_uses_all_top_level_windows_including_hidden(self):
        with mock.patch.object(launch, "_all_top_level_windows",
                               return_value=[100, 101]) as all_windows:
            self.run_launch()
        all_windows.assert_called()

    def test_direct_process_window_is_hidden_and_attributed(self):
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
        result = self.run_launch(spawn=spawn)
        hidden = [w for w in result["hidden_windows"] if w["hwnd"] == 200]
        self.assertTrue(hidden, result["hidden_windows"])
        self.assertEqual(hidden[0]["ownership_basis"], "direct_process")
        self.assertEqual(hidden[0]["pid"], 500)
        self.assertEqual(hidden[0]["process_created_at"], 1000)
        self.assertTrue(hidden[0]["hide_succeeded"])
        self.assertEqual(result["visibility_control"], "applied")
        self.assertTrue(result["target_window_confirmed"])

    def test_verified_descendant_window_is_hidden(self):
        def spawn():
            self.windows_after.append((300, 600, "Chrome_WidgetWin_1", "Render"))
        result = self.run_launch(spawn=spawn)
        hidden = [w for w in result["hidden_windows"] if w["hwnd"] == 300]
        self.assertTrue(hidden)
        self.assertEqual(hidden[0]["ownership_basis"], "observed_descendant")

    def test_a_reused_root_pid_does_not_own_new_descendant_windows(self):
        def recycle():
            self.pids[500] = 4000
            self.pids[600] = 5000
            self.windows_after[:] = [(300, 600, "Other", "Unrelated child")]
            return self.parents

        with mock.patch.object(launch, "_snapshot_parents", side_effect=recycle):
            result = self.run_launch()
        self.assertTrue(self._shown(300))
        self.assertFalse(result["target_window_confirmed"])
        self.assertEqual(result["visibility_control"], "unconfirmed")

    def test_unrelated_new_window_is_never_touched(self):
        def spawn():
            self.windows_after.append((400, 900, "Notepad", "Someone else"))
        result = self.run_launch(spawn=spawn)
        touched = [c.args[0] for c in self.set_window_pos.call_args_list]
        self.assertNotIn(400, touched)
        self.assertFalse(result["target_window_confirmed"])
        self.assertEqual(result["visibility_control"], "unconfirmed")
        self.assertTrue(any(c["hwnd"] == 400 and c["ownership"] == "unknown"
                            for c in result["window_candidates"]), result["window_candidates"])

    def test_pid_reuse_is_not_ownership(self):
        # The launcher's PID is recycled by an unrelated process after the
        # window appears; that window must not be hidden on the strength of it.
        original = self.pids[500]
        self.windows_after.append((700, 500, "Win32Window", "Impostor"))

        def identity(pid):
            return {"pid": pid, "created": self.pids[pid]} if pid in self.pids else None

        def popen(*args, **kw):
            proc = mock.Mock(pid=500)
            # Recycle after the launcher identity is established.
            self.pids[500] = 9999
            return proc

        with mock.patch.object(launch.subprocess, "Popen", side_effect=popen), \
             mock.patch.object(launch, "_process_identity", side_effect=identity):
            result = launch.launch("x.exe", settle=0.02)
        self.assertNotEqual(original, self.pids[500])
        self.assertEqual(result["visibility_control"], "unconfirmed")
        self.assertEqual([w for w in result["hidden_windows"] if w["hwnd"] == 700], [])

    def test_baseline_window_is_never_hidden(self):
        def spawn():
            self.windows_after.append((101, 500, "Win32Window", "Preexisting"))
        result = self.run_launch(spawn=spawn)
        touched = [c.args[0] for c in self.set_window_pos.call_args_list]
        self.assertNotIn(101, touched)
        self.assertFalse(result["target_window_confirmed"])

    def test_unreadable_process_identity_leaves_windows_unknown(self):
        self.install(identity_error={500})
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
        result = self.run_launch(spawn=spawn)
        touched = [c.args[0] for c in self.set_window_pos.call_args_list]
        self.assertNotIn(200, touched)
        self.assertEqual(result["visibility_control"], "unconfirmed")
        self.assertTrue(result["warnings"])

    def test_show_true_requests_no_hiding(self):
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
        result = self.run_launch(spawn=spawn, show=True) if False else launch.launch(
            "x.exe", settle=0.02, hide_new_windows=False)
        self.assertEqual(result["visibility_control"], "not_requested")
        self.assertEqual(self.hide_calls(), [])


class TestForeground(LaunchCase):
    def setUp(self):
        super().setUp()
        self.baseline = {100}
        self.baseline_pids = {100: 80}
        self.pids = {80: 1000, 500: 1000, 900: 2000}
        self.install()

    def test_foreground_is_restored_only_to_the_original_window(self):
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
            self.foreground = 200  # the launched app takes the foreground
        with mock.patch.object(launch, "force_foreground", return_value=True) as force:
            self.run_launch(spawn=spawn)
        forced = [c.args[0] for c in force.call_args_list]
        self.assertTrue(forced, "the launch's own window was never contended for")
        self.assertTrue(all(h == 100 for h in forced), forced)

    def test_a_window_the_user_switched_to_is_not_overridden(self):
        """The user moving to their own app must survive the launch."""
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
            self.foreground = 400  # the user picked another app mid-launch
        with mock.patch.object(launch, "force_foreground", return_value=True) as force:
            self.run_launch(spawn=spawn)
        self.assertEqual(force.call_args_list, [])

    def test_original_foreground_identity_is_rechecked(self):
        """If the original window's process changed, that window is not ours to restore."""
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
            self.foreground = 200
            self.pids[80] = 7777
        self.pids[80] = 5555
        self.windows_after.append((100, 80, "Old", "Original"))
        with mock.patch.object(launch, "force_foreground", return_value=True) as force:
            self.run_launch(spawn=spawn)
        self.assertTrue(all(c.args[0] == 100 for c in force.call_args_list),
                        force.call_args_list)

    def test_a_window_that_reappears_is_hidden_again_and_focus_restored(self):
        polls = 0

        def windows():
            nonlocal polls
            polls += 1
            if polls == 3:
                self.visible[200] = True
                self.foreground = 200
            return list(self.baseline) + [w[0] for w in self.windows_after]

        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
            self.foreground = 200

        def restore(hwnd):
            self.foreground = hwnd
            return True

        with mock.patch.object(launch, "_all_top_level_windows", side_effect=windows), \
             mock.patch.object(launch, "force_foreground", side_effect=restore):
            result = self.run_launch(spawn=spawn)
        self.assertFalse(self.visible[200])
        self.assertTrue(result["foreground_preserved"], result)
        self.assertEqual(len(result["hidden_windows"]), 1)
        self.assertFalse(result["hidden_windows"][0]["still_visible"])
        self.assertEqual(result["visibility_control"], "applied")

    def test_a_reused_window_handle_is_not_hidden_for_its_previous_owner(self):
        polls = 0

        def windows():
            nonlocal polls
            polls += 1
            if polls == 3:
                self.windows_after[:] = [(200, 900, "Other", "Reused")]
                self.visible[200] = True
                self.foreground = 200
            return list(self.baseline) + [w[0] for w in self.windows_after]

        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))

        with mock.patch.object(launch, "_all_top_level_windows", side_effect=windows), \
             mock.patch.object(launch, "force_foreground") as restore:
            result = self.run_launch(spawn=spawn)
        self.assertTrue(self.visible[200])
        self.assertFalse(result["foreground_preserved"])
        restore.assert_not_called()

    def test_a_window_still_visible_after_hiding_is_not_reported_applied(self):
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))

        # The app reappears after the final hiding pass, before result sampling.
        with mock.patch.object(launch.time, "time", side_effect=[0, 2, 2]), \
             mock.patch.object(launch.user32, "IsWindowVisible", side_effect=[0, 0, 1]):
            result = self.run_launch(spawn=spawn)
        self.assertTrue(result["hidden_windows"][0]["hide_succeeded"])
        self.assertTrue(result["hidden_windows"][0]["still_visible"])
        self.assertEqual(result["visibility_control"], "partial")


class TestFailures(LaunchCase):
    def setUp(self):
        super().setUp()
        self.baseline = {100}
        self.pids = {500: 1000}
        self.install()

    def test_a_failed_hide_is_partial(self):
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
        self.set_window_pos.stop()
        patch = mock.patch.object(launch.user32, "SetWindowPos", return_value=0)
        patch.start()
        self.addCleanup(patch.stop)
        result = self.run_launch(spawn=spawn)
        self.assertEqual(result["visibility_control"], "partial")
        self.assertFalse(result["hidden_windows"][0]["hide_succeeded"])
        self.assertTrue(result["warnings"])

    def test_single_instance_handoff_stays_unconfirmed(self):
        def spawn():
            self.windows_after.append((400, 900, "Win32Window", "Handed over"))
        result = self.run_launch(spawn=spawn)
        self.assertEqual(result["visibility_control"], "unconfirmed")
        self.assertFalse(result["target_window_confirmed"])
        self.assertEqual(result["hidden_windows"], [])

    def test_popen_failure_is_reported(self):
        with mock.patch.object(launch.subprocess, "Popen",
                               side_effect=OSError("nope")):
            result = launch.launch("x.exe", settle=0.02)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "could not start the program")

    def test_candidates_are_capped(self):
        def spawn():
            for i in range(250):
                self.windows_after.append((1000 + i, 900 + i, "Other", f"w{i}"))
        result = self.run_launch(spawn=spawn)
        self.assertLessEqual(len(result["window_candidates"]), 200)
        self.assertTrue(result["candidates_truncated"])

    def test_original_fields_stay(self):
        def spawn():
            self.windows_after.append((200, 500, "Win32Window", "New"))
        result = self.run_launch(spawn=spawn)
        for field in ("ok", "pid", "command", "hidden_windows", "foreground_before",
                      "foreground_before_title", "foreground_after",
                      "foreground_preserved", "foreground_contests", "took_ms"):
            self.assertIn(field, result)
        self.assertEqual(result["pid"], 500)
        item = result["hidden_windows"][0]
        for field in ("hwnd", "class", "title", "still_visible", "pid",
                      "process_created_at", "ownership_basis", "hide_succeeded"):
            self.assertIn(field, item)


class TestProcessQueries(unittest.TestCase):
    def test_a_reused_parent_pid_does_not_make_an_unrelated_process_owned(self):
        identities = {500: 1000, 600: 4000, 700: 2000}
        with mock.patch.object(launch, "_snapshot_parents",
                               return_value={500: 1, 600: 500, 700: 600}), \
             mock.patch.object(launch, "_process_identity",
                               side_effect=lambda pid: {"pid": pid,
                                                        "created": identities[pid]}):
            owned = launch._owned_processes(500, {"pid": 500, "created": 1000})
        self.assertIn(600, owned)
        self.assertNotIn(700, owned)

    def test_a_current_descendant_chain_is_owned(self):
        identities = {500: 1000, 600: 2000, 700: 3000}
        with mock.patch.object(launch, "_snapshot_parents",
                               return_value={500: 1, 600: 500, 700: 600}), \
             mock.patch.object(launch, "_process_identity",
                               side_effect=lambda pid: {"pid": pid,
                                                        "created": identities[pid]}):
            owned = launch._owned_processes(500, {"pid": 500, "created": 1000})
        self.assertEqual(set(owned), {500, 600, 700})

    def test_missing_pid_has_no_identity(self):
        self.assertIsNone(launch._process_identity(0))
        self.assertIsNone(launch._process_identity(999999))

    def test_real_self_identity_is_readable(self):
        import os

        identity = launch._process_identity(os.getpid())
        self.assertIsNotNone(identity)
        self.assertEqual(identity["pid"], os.getpid())
        self.assertIsInstance(identity["created"], int)

    def test_creation_time_is_an_integer_fil_time(self):
        import os

        identity = launch._process_identity(os.getpid())
        self.assertGreater(identity["created"], 10 ** 17)


if __name__ == "__main__":
    unittest.main()

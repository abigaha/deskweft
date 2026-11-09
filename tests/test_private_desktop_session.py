"""C5/C6: a private desktop you can see and drive.

The capability: keep an automation target on a desktop that is NOT the input
desktop while it works, then bring that desktop to the screen on request so the
user can look at it and take over, then send it back.

Rules this enforces:
  - switching away from the user's desktop is never automatic: it is its own tool
    call, with its own permission flag;
  - the user's original desktop is remembered before the first switch and used to
    go back, so "back" never guesses;
  - the state is explicit: which desktop is visible, which one holds the target,
    and whether the target is confirmed to be on the private desktop;
  - a failed switch leaves the recorded state honest rather than pretending.
"""

from __future__ import annotations

import ctypes
import time
import unittest
from ctypes import wintypes
from unittest import mock

from deskweft import private_desktop as pd


class FakeUser32:
    """A stand-in that keeps one piece of state: which desktop is visible."""

    def __init__(self, *, create_ok=True, switch_ok=True, visible="Default"):
        self.create_ok = create_ok
        self.switch_ok = switch_ok
        self.visible = visible
        self.calls = []
        self._names = {}
        self._next = 100

    def CreateDesktopW(self, name, device, devmode, flags, access, attributes):
        self.calls.append(("create", name))
        if not self.create_ok:
            return 0
        return self._register(name)

    def OpenDesktopW(self, name, flags, inherit, access):
        self.calls.append(("open", name))
        for handle, known in self._names.items():
            if known == name:
                return handle
        return self._register(name)

    def OpenInputDesktop(self, flags, inherit, access):
        if self.visible is None:
            return 0
        return self._register(self.visible)

    def SwitchDesktop(self, handle):
        name = self._names.get(handle)
        self.calls.append(("switch", name))
        if not self.switch_ok:
            return 0
        # A real switch changes where input goes; model that.
        self.visible = name
        return 1

    def CloseDesktop(self, handle):
        self.calls.append(("close", self._names.get(handle)))
        return 1

    def GetUserObjectInformationW(self, handle, index, buffer, length, needed):
        name = self._names.get(handle, "")
        size = (len(name) + 1) * ctypes.sizeof(ctypes.c_wchar)
        out = ctypes.cast(needed, ctypes.POINTER(wintypes.DWORD))
        if not buffer:
            out[0] = size
            return 1
        if length < size:
            return 0
        ctypes.memmove(buffer, name, size)
        out[0] = size
        return 1

    def _register(self, name):
        handle = self._next
        self._next += 1
        self._names[handle] = name
        return handle

    def GetUserObjectInformationW(self, handle, index, buffer, length, needed):
        name = self._names.get(handle, "")
        size = (len(name) + 1) * ctypes.sizeof(ctypes.c_wchar)
        out = ctypes.cast(needed, ctypes.POINTER(wintypes.DWORD))
        if not buffer:
            out[0] = size
            return 1
        if length < size:
            return 0
        ctypes.memmove(buffer, name, size)
        out[0] = size
        return 1


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.user32 = FakeUser32()
        self.session = pd.DesktopSession(user32=self.user32)

    def test_no_private_desktop_until_one_is_created(self):
        self.assertEqual(self.session.status()["private_desktop"], None)
        self.assertFalse(self.session.status()["created"])

    def test_creating_a_desktop_does_not_switch_to_it(self):
        created = self.session.create("probe")
        self.assertTrue(created["ok"], created)
        self.assertEqual(self.session.status()["visible_desktop"], "Default")
        self.assertNotIn(("switch", "probe"), self.user32.calls)

    def test_showing_a_desktop_is_an_explicit_step(self):
        self.session.create("probe")
        shown = self.session.show()
        self.assertTrue(shown["ok"], shown)
        self.assertEqual(shown["visible_desktop"], "probe")
        self.assertEqual(shown["previous_desktop"], "Default")

    def test_hiding_returns_to_the_desktop_the_user_had(self):
        self.session.create("probe")
        self.session.show()
        hidden = self.session.hide()
        self.assertTrue(hidden["ok"], hidden)
        self.assertEqual(hidden["visible_desktop"], "Default")

    def test_hiding_without_showing_is_a_no_op(self):
        self.session.create("probe")
        hidden = self.session.hide()
        self.assertTrue(hidden["ok"], hidden)
        self.assertEqual(hidden["visible_desktop"], "Default")
        self.assertNotIn(("switch", "probe"), self.user32.calls)

    def test_a_failed_switch_reports_where_the_screen_really_is(self):
        self.user32.switch_ok = False
        self.session.create("probe")
        shown = self.session.show()
        self.assertFalse(shown["ok"])
        self.assertEqual(shown["reason"], "desktop switch refused")
        self.assertEqual(shown["visible_desktop"], "Default")

    def test_show_without_a_desktop_is_refused(self):
        shown = self.session.show()
        self.assertFalse(shown["ok"])
        self.assertEqual(shown["reason"], "no private desktop")

    def test_creating_twice_reuses_the_first_desktop(self):
        first = self.session.create("one")
        second = self.session.create("two")
        self.assertTrue(second["ok"], second)
        self.assertEqual(second["name"], first["name"])
        self.assertEqual(len([c for c in self.user32.calls if c[0] == "create"]), 1)

    def test_a_failed_creation_is_reported_and_leaves_no_handle(self):
        self.user32.create_ok = False
        created = self.session.create("probe")
        self.assertFalse(created["ok"])
        self.assertEqual(created["reason"], "could not create desktop")
        self.assertIsNone(self.session.status()["private_desktop"])

    def test_close_returns_to_default_first_and_forgets_the_handle(self):
        self.session.create("probe")
        self.session.show()
        closed = self.session.close()
        self.assertTrue(closed["ok"], closed)
        self.assertEqual(closed["visible_desktop"], "Default")
        self.assertIsNone(self.session.status()["private_desktop"])
        self.assertIn(("close", "probe"), self.user32.calls)

    def test_an_unreadable_visible_desktop_still_attempts_to_go_back(self):
        """Measured: an unreadable desktop name made hide() believe it was
        already hidden, so close() reported ok while the screen stayed on the
        private desktop. The switch back must be attempted anyway."""
        self.session.create("probe")
        self.session.show()
        self.session.user32_visible_broken = True
        broken = FakeUser32()
        broken._names = dict(self.user32._names)
        broken._next = self.user32._next
        broken.visible = "probe"

        original_open = broken.OpenInputDesktop
        calls = {"n": 0}

        def flaky(flags, inherit, access):
            calls["n"] += 1
            if calls["n"] == 1:
                return 0  # the first read fails, as it did on the real machine
            return original_open(flags, inherit, access)

        broken.OpenInputDesktop = flaky
        self.session._user32 = broken
        hidden = self.session.hide()
        self.assertTrue(hidden["ok"], hidden)
        self.assertEqual(hidden["visible_desktop"], "Default")

    def test_status_always_answers_the_real_visible_desktop(self):
        self.session.create("probe")
        self.assertEqual(self.session.status()["visible_desktop"], "Default")
        self.user32.visible = "probe"
        self.assertEqual(self.session.status()["visible_desktop"], "probe")


if __name__ == "__main__":
    unittest.main()

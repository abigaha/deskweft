"""act.py: existing actions must refuse uncertain targets; invoke_pattern opens UIA.

Fake elements and patched Win32 only. Nothing here sends a real message, moves
the cursor or steals the foreground.
"""

from __future__ import annotations

import threading
import unittest
from unittest import mock

from deskweft import act, tree
from windows_mcp.uia import core
from test_tree import FakeElement, FakeRect


def detailed(*elements, **overrides):
    """A read_detailed() result built from fake elements."""
    base = {"elements": [_as_row(e) for e in elements],
            "timed_out": False, "limit_reached": False, "identity_complete": True,
            "tree_diagnostics": {"root_status": "ok", "filtered_anonymous": 0,
                                 "filtered_offscreen": 0, "warnings": [],
                                 "warnings_truncated": False}}
    base.update(overrides)
    return base


def _as_row(element):
    """The plain-data row read_detailed() emits, with the live element beside it."""
    if isinstance(element, dict):
        return element
    box = element.BoundingRectangle
    return {"control_type": element.ControlTypeName, "automation_id": element.AutomationId,
            "name": element.Name, "nth": 0, "patterns": [], "native_hwnd": None,
            "depth": 0,
            "rect": None if box is None else [box.left, box.top,
                                              box.right - box.left, box.bottom - box.top],
            "_el": element}


def el(name="", automation_id="", patterns=None, **kwargs):
    return FakeElement(name=name, automation_id=automation_id, patterns=patterns or {},
                       **kwargs)


def _control(name="one", handle=1):
    """A real Control instance with plain attributes, as the dependency exposes them."""
    from windows_mcp.uia.controls import Control
    from windows_mcp.uia.patterns import TextRange
    import unittest.mock as mock

    control = Control.__new__(Control)
    control.__dict__.update({
        "Name": name, "AutomationId": f"id{handle}", "ControlTypeName": "ListItemControl",
        "BoundingRectangle": FakeRect(), "NativeWindowHandle": handle, "_patterns": {},
        "_children": [],
    })
    return control


class ActCase(unittest.TestCase):
    def setUp(self):
        for name, value in (("title", "Window"), ("foreground", 1),
                            ("focus_window", 1), ("grab", None)):
            patch = mock.patch.object(act.win32, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        for target, value in ((act.win32.user32, "IsWindow"),):
            patch = mock.patch.object(target, value, return_value=1)
            patch.start()
            self.addCleanup(patch.stop)

    def patch_children(self, kids):
        return mock.patch.object(act.win32, "children", return_value=kids)

    def patch_read(self, result):
        return mock.patch.object(act.tree, "read_detailed", return_value=result)

    def patch_activate(self, ok=True):
        return mock.patch.object(act.win32, "activate", return_value=ok)


class TestChildResolution(ActCase):
    def test_two_exact_matches_are_ambiguous_and_send_nothing(self):
        kids = [{"hwnd": 1, "class": "Button", "text": "OK", "rect": [0, 0, 10, 10]},
                {"hwnd": 2, "class": "Button", "text": "OK", "rect": [0, 0, 10, 10]}]
        with self.patch_children(kids), \
             mock.patch.object(act.win32.user32, "PostMessageW") as post:
            result = act.act(1, "click", target="OK")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "ambiguous target")
        self.assertEqual(result["execution_state"], "not_started")
        post.assert_not_called()

    def test_empty_target_needs_exactly_one_native_candidate(self):
        kids = [{"hwnd": 1, "class": "Button", "text": "A", "rect": [0, 0, 9, 9]},
                {"hwnd": 2, "class": "Button", "text": "B", "rect": [0, 0, 9, 9]}]
        with self.patch_children(kids), self.patch_read(detailed()), \
             mock.patch.object(act.win32.user32, "PostMessageW") as post:
            result = act.act(1, "click", target="")
        self.assertEqual(result["reason"], "target required")
        post.assert_not_called()

    def test_click_never_falls_back_to_the_window_centre(self):
        with self.patch_children([]), self.patch_read(detailed()), \
             self.patch_activate(True), \
             mock.patch.object(act, "SetCursorPos") as cursor, \
             mock.patch.object(act, "Click") as click:
            result = act.act(1, "click", target="ghost", allow_foreground=True)
        self.assertEqual(result["reason"], "no such control")
        cursor.assert_not_called()
        click.assert_not_called()

    def test_incomplete_tree_refuses_before_activation(self):
        with self.patch_children([]), \
             self.patch_read(detailed(el(name="ghost"), timed_out=True)), \
             self.patch_activate(True) as activate, \
             mock.patch.object(act, "Click") as click:
            result = act.act(1, "click", target="ghost", allow_foreground=True)
        self.assertEqual(result["reason"], "tree incomplete")
        activate.assert_not_called()
        click.assert_not_called()

    def test_ambiguous_uia_target_refuses(self):
        elements = detailed(el(name="Save"), el(name="Save", automation_id="b"))
        with self.patch_children([]), self.patch_read(elements), \
             self.patch_activate(True) as activate:
            result = act.act(1, "click", target="Save", allow_foreground=True)
        self.assertEqual(result["reason"], "ambiguous target")
        activate.assert_not_called()

    def test_unique_native_click_reports_queued_not_verified(self):
        kids = [{"hwnd": 5, "class": "Button", "text": "OK", "rect": [0, 0, 9, 9]}]
        with self.patch_children(kids), \
             mock.patch.object(act.win32.user32, "PostMessageW", return_value=1) as post:
            result = act.act(1, "click", target="OK")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["delivery"], "queued")
        self.assertFalse(result["effect_verified"])
        self.assertEqual(post.call_args[0][0], 5)

    def test_rejected_post_message_is_not_success(self):
        kids = [{"hwnd": 5, "class": "Button", "text": "OK", "rect": [0, 0, 9, 9]}]
        with self.patch_children(kids), \
             mock.patch.object(act.win32.user32, "PostMessageW", return_value=0):
            result = act.act(1, "click", target="OK")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "message delivery failed")

    def test_a_provider_error_stops_the_chain_instead_of_trying_another_route(self):
        """A getter that raises is a real failure, not "this pattern is absent".

        Falling through to InvokePattern would perform a different side-effecting
        call the caller never asked for - and on Chromium that route takes the
        foreground.
        """
        invoke = mock.Mock()
        with self.patch_children([]), self.patch_read(detailed(el(name="b"))), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=[
                                   {"ok": False, "reason": "provider error",
                                    "detail": "COMError: legacy broke"},
                                   {"ok": True, "value": invoke,
                                    "canonical": "InvokePattern", "pattern_id": 10000}]):
            result = act.act(1, "click", target="b", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider error")
        self.assertIn("legacy broke", result["detail"])
        invoke.Invoke.assert_not_called()

    def test_an_absent_pattern_still_moves_to_the_next_route(self):
        invoke = mock.Mock()
        with self.patch_children([]), self.patch_read(detailed(el(name="b"))), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=[
                                   {"ok": False, "reason": "pattern unavailable",
                                    "cause_unknown": True},
                                   {"ok": True, "value": invoke,
                                    "canonical": "InvokePattern", "pattern_id": 10000}]):
            result = act.act(1, "click", target="b", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        invoke.Invoke.assert_called_once()

    def test_a_called_route_that_raises_is_not_replaced_by_another(self):
        legacy = mock.Mock()
        legacy.DoDefaultAction.side_effect = RuntimeError("provider exploded")
        invoke = mock.Mock()
        with self.patch_children([]), self.patch_read(detailed(el(name="b"))), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=[
                                   {"ok": True, "value": legacy,
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018},
                                   {"ok": True, "value": invoke,
                                    "canonical": "InvokePattern", "pattern_id": 10000}]):
            result = act.act(1, "click", target="b", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider error")
        self.assertEqual(result["execution_state"], "unknown")
        invoke.Invoke.assert_not_called()


class TestTyping(ActCase):
    def cursor_type(self, text, character_input, key_input):
        root = el(name="edit", automation_id="e")
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.win32, "window_at", return_value=1), \
             mock.patch.object(act, "_focus_settled", return_value=True), \
             mock.patch.object(act, "SetCursorPos"), \
             mock.patch.object(act, "Click"), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             mock.patch.object(core, "SendUnicodeChar", side_effect=character_input), \
             mock.patch.object(core, "keybd_event", side_effect=key_input), \
             mock.patch.object(core, "_VKtoSC", return_value=0), \
             mock.patch.object(core.time, "sleep"):
            return act.act(1, "type", target="e", text=text, allow_foreground=True)

    def test_native_type_uses_the_managed_helper_and_verifies(self):
        kids = [{"hwnd": 5, "class": "Edit", "text": "", "rect": [0, 0, 9, 9]}]
        with self.patch_children(kids), \
             mock.patch.object(act.win32, "_write_text",
                               return_value={"ok": True, "effect_verified": True,
                                             "delivery": "returned", "result": 1}):
            result = act.act(1, "type", target="", text="hello")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["route"], "win32:WM_SETTEXT")

    def test_value_none_is_unverifiable_not_a_definite_failure(self):
        root = el(name="edit", automation_id="e")
        with self.patch_children([]), \
             self.patch_read(detailed(root)), self.patch_activate(True), \
             mock.patch.object(act.win32, "window_at", return_value=1), \
             mock.patch.object(act, "_focus_settled", return_value=True), \
             mock.patch.object(act, "SetCursorPos"), \
             mock.patch.object(act, "Click"), \
             mock.patch.object(act, "SendKeys"), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}):
            result = act.act(1, "type", target="e", text="x", allow_foreground=True)
        self.assertFalse(result["effect_verified"])
        self.assertEqual(result.get("verification_reason"), "readback unavailable")

    def test_cursor_typing_keeps_braces_and_shortcut_names_literal(self):
        for text in ('safe{Alt}{F4}', '{"name": "value"}', "{} { } (text)"):
            with self.subTest(text=text):
                typed = []
                pressed = []
                try:
                    result = self.cursor_type(
                        text, lambda char, mode: typed.append(char),
                        lambda vk, *rest: pressed.append(vk))
                except ValueError as error:
                    self.fail(f"literal text was parsed as key syntax: {error}")
                self.assertTrue(result["ok"], result)
                self.assertEqual("".join(typed), text)
                self.assertNotIn(0x12, pressed, "literal text must not press Alt")
                self.assertNotIn(0x73, pressed, "literal text must not press F4")

    def test_cursor_typing_replaces_the_existing_value(self):
        for replacement in ("new-value", ""):
            with self.subTest(replacement=replacement):
                state = {"text": "old-value", "selected": False}
                held = set()

                def key_input(vk, scan, flags, extra):
                    if flags & 2:
                        held.discard(vk)
                        return
                    held.add(vk)
                    if vk == 0x41 and 0x11 in held:  # Ctrl+A selects the existing value.
                        state["selected"] = True
                    elif vk == 0x27:  # Right collapses the selection at its end.
                        state["selected"] = False
                    elif vk == 0x2E and state["selected"]:
                        state["text"] = ""
                        state["selected"] = False

                def character_input(char, mode):
                    state["text"] = char if state["selected"] else state["text"] + char
                    state["selected"] = False

                result = self.cursor_type(replacement, character_input, key_input)
                self.assertTrue(result["ok"], result)
                self.assertEqual(state["text"], replacement)

    def test_readback_mismatch_is_an_explicit_failure(self):
        root = el(name="edit", automation_id="e")
        value = mock.Mock()
        value.SetValue.return_value = True
        value.Value = "other"
        with self.patch_children([]), \
             self.patch_read(detailed(root)), self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": value,
                                             "canonical": "ValuePattern", "pattern_id": 10002}):
            result = act.act(1, "type", target="e", text="wanted", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "text readback mismatch")

    def test_cursor_readback_failures_preserve_the_completed_input_result(self):
        for values, reason in (([RuntimeError("provider lost")], "readback unavailable"),
                               (["other", RuntimeError("read twice")], "text readback mismatch")):
            with self.subTest(reason=reason):
                root = el(name="edit", automation_id="e")
                value = mock.Mock()
                type(value).Value = mock.PropertyMock(side_effect=values)
                sent = []
                with self.patch_children([]), self.patch_read(detailed(root)), \
                     self.patch_activate(True), \
                     mock.patch.object(act.win32, "window_at", return_value=1), \
                     mock.patch.object(act, "_focus_settled", return_value=True), \
                     mock.patch.object(act, "SetCursorPos"), mock.patch.object(act, "Click"), \
                     mock.patch.object(act, "SendKeys", side_effect=lambda text, **kw: sent.append(text)), \
                     mock.patch.object(act.tree, "pattern_detailed", side_effect=[
                         {"ok": False, "reason": "pattern unavailable", "cause_unknown": True},
                         {"ok": True, "value": value, "canonical": "ValuePattern",
                          "pattern_id": 10002}]):
                    result = act.act(1, "type", target="e", text="wanted", allow_foreground=True)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["execution_state"], "completed")
                self.assertFalse(result["effect_verified"])
                self.assertFalse(result["retry_safe"])
                self.assertEqual(sent, ["{Ctrl}a", "wanted"])

    def test_typing_never_reaches_the_window_centre(self):
        root = el(name="edit", automation_id="e", rect=FakeRect(0, 0, 0, 0))
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable"}), \
             mock.patch.object(act, "SendKeys") as keys:
            result = act.act(1, "type", target="e", text="x", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "control has no clickable area")
        keys.assert_not_called()


class TestScrollAndKeys(ActCase):
    def test_scroll_uses_the_documented_enum_pair(self):
        sp = mock.Mock()
        sp.VerticalScrollPercent = 0
        root = el(name="list", automation_id="l")
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": sp,
                                             "canonical": "ScrollPattern", "pattern_id": 10004}):
            act.act(1, "scroll", target="l", text="down", allow_foreground=True)
        sp.Scroll.assert_called_once_with(act.ScrollAmount.NoAmount,
                                         act.ScrollAmount.LargeIncrement)

    def test_scroll_up_uses_large_decrement(self):
        sp = mock.Mock()
        sp.VerticalScrollPercent = 50
        root = el(name="list", automation_id="l")
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": sp,
                                             "canonical": "ScrollPattern", "pattern_id": 10004}):
            act.act(1, "scroll", target="l", text="up", allow_foreground=True)
        sp.Scroll.assert_called_once_with(act.ScrollAmount.NoAmount,
                                          act.ScrollAmount.LargeDecrement)

    def test_scroll_false_is_not_success(self):
        sp = mock.Mock()
        sp.VerticalScrollPercent = 0
        sp.Scroll.return_value = False
        root = el(name="list", automation_id="l")
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": sp,
                                             "canonical": "ScrollPattern", "pattern_id": 10004}):
            result = act.act(1, "scroll", target="l", text="down", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider reported false")

    def test_scroll_with_a_missing_target_does_not_fall_back_to_the_root(self):
        root = el(name="list")
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act, "ControlFromHandle") as handle:
            result = act.act(1, "scroll", target="ghost", allow_foreground=True)
        self.assertEqual(result["reason"], "no such control")
        handle.assert_not_called()

    def test_real_keys_need_a_verified_foreground(self):
        with mock.patch.object(act.win32, "foreground", return_value=99), \
             mock.patch.object(act.launch, "is_shown", return_value=True), \
             mock.patch.object(act, "SendKeys") as keys:
            result = act.act(1, "key", text="Ctrl+s", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "target not focused")
        keys.assert_not_called()

    def test_key_notation_is_normalised(self):
        with mock.patch.object(act.win32, "foreground", return_value=1), \
             mock.patch.object(act.launch, "is_shown", return_value=True), \
             mock.patch.object(act, "ControlFromHandle", return_value=None), \
             mock.patch.object(act, "SendKeys") as keys:
            act.act(1, "key", text="Ctrl+s", allow_foreground=True)
        self.assertEqual(keys.call_args[0][0], "{Ctrl}{s}")

    def test_keys_are_not_sent_when_focus_cannot_be_placed(self):
        # The window is foreground and shown, but SetFocus fails. Keystrokes
        # would go to whatever really holds focus, so nothing may be sent.
        root = mock.Mock()
        root.SetFocus.side_effect = RuntimeError("no focus")
        with mock.patch.object(act.win32, "foreground", return_value=1), \
             mock.patch.object(act.launch, "is_shown", return_value=True), \
             mock.patch.object(act, "ControlFromHandle", return_value=root), \
             mock.patch.object(act, "SendKeys") as keys:
            result = act.act(1, "key", text="Enter", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "target not focused")
        self.assertEqual(result["execution_state"], "not_started")
        keys.assert_not_called()

    def test_foreground_permission_is_still_checked_first(self):
        with self.patch_read(detailed()) as read:
            result = act.act(1, "key", text="Enter")
        self.assertTrue(result["needs_permission"])
        read.assert_not_called()


class TestCursorReachability(ActCase):
    """A real cursor click lands on whatever window is topmost at that pixel.

    The tool addresses a window; if another window covers the point, the click
    would act on the wrong application. That must be refused before the cursor
    moves - this is the same class of rule as "never click the window centre".
    """

    def patch_owner(self, owner):
        return mock.patch.object(act.win32, "window_at", return_value=owner)

    def editable(self, *names):
        return el(name=names[0] if names else "field", automation_id="e",
                  rect=FakeRect(10, 20, 200, 40))

    def test_a_covered_point_is_refused_before_the_cursor_moves(self):
        root = self.editable()
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             self.patch_owner(999), \
             mock.patch.object(act, "SetCursorPos") as cursor, \
             mock.patch.object(act, "Click") as click:
            result = act.act(1, "type", target="e", text="x", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "target obstructed")
        self.assertEqual(result["execution_state"], "not_started")
        cursor.assert_not_called()
        click.assert_not_called()

    def test_an_uncovered_point_clicks_the_element_centre(self):
        # FakeRect is (left, top, right, bottom): [10,20,210,60] -> centre (110,40).
        root = el(name="field", automation_id="e", rect=FakeRect(10, 20, 210, 60))
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             self.patch_owner(1), \
             mock.patch.object(act, "_focus_settled", return_value=True), \
             mock.patch.object(act, "SetCursorPos") as cursor, \
             mock.patch.object(act, "Click") as click, \
             mock.patch.object(act, "SendKeys"):
            act.act(1, "type", target="e", text="x", allow_foreground=True)
        self.assertEqual(cursor.call_args[0], (110, 40))
        self.assertEqual(click.call_args[0], (110, 40))

    def test_an_owner_of_another_window_is_obstruction(self):
        """Same process is not enough: a sibling window is still the wrong target."""
        root = self.editable()
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             self.patch_owner(4242), \
             mock.patch.object(act, "SetCursorPos") as cursor:
            result = act.act(1, "type", target="e", text="x", allow_foreground=True)
        self.assertEqual(result["reason"], "target obstructed")
        cursor.assert_not_called()

    def test_click_route_also_refuses_an_obstructed_element(self):
        root = el(name="btn", automation_id="b", rect=FakeRect(0, 0, 100, 30))
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             self.patch_owner(777), \
             mock.patch.object(act, "SetCursorPos") as cursor, \
             mock.patch.object(act, "Click") as click:
            result = act.act(1, "click", target="b", allow_foreground=True)
        self.assertEqual(result["reason"], "target obstructed")
        cursor.assert_not_called()
        click.assert_not_called()


class TestClickObservation(ActCase):
    """A semantic click can report success without changing anything.

    Measured on WeChat: LegacyIAccessible.DoDefaultAction and InvokePattern.Invoke
    both returned True with execution_state=completed while the login page stayed
    exactly as it was. The tool cannot call that success, and it must not invent
    a failure either - it reports what it could observe.
    """

    def test_a_click_whose_control_state_did_not_change_says_so(self):
        target = el(name="进入微信", automation_id="")
        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "ControlFromHandle", return_value=target), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=lambda el, name: (
                                   {"ok": True, "value": mock.Mock(
                                       DoDefaultAction=mock.Mock(return_value=True)),
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018}
                                   if name == "LegacyIAccessiblePattern"
                                   else {"ok": False, "reason": "pattern unavailable",
                                         "cause_unknown": True})):
            result = act.act(1, "click", target="进入微信", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["route"], "uia:legacy-default")
        self.assertFalse(result["effect_verified"])
        self.assertEqual(result.get("observation"), "element state and tree size are unchanged")
        self.assertEqual(result.get("observation_source"), "UIA")

    def test_identical_captures_report_only_the_sampled_frames(self):
        target = el(name="联系人", automation_id="")
        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "ControlFromHandle", return_value=target), \
             mock.patch.object(act, "tree_size", side_effect=[316, 166]), \
             mock.patch.object(act.win32, "grab", return_value=(b"same", 10, 10)), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=lambda e, name: (
                                   {"ok": True, "value": mock.Mock(
                                       DoDefaultAction=mock.Mock(return_value=True)),
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018}
                                   if name == "LegacyIAccessiblePattern"
                                   else {"ok": False, "reason": "pattern unavailable",
                                         "cause_unknown": True})):
            result = act.act(1, "click", target="联系人", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["observation"], "captured frames are identical")
        self.assertEqual(result.get("observation_source"), "PrintWindow")
        self.assertEqual(result["route_effect"], "business effect unverified")
        self.assertFalse(result["effect_verified"])

    def test_different_captures_do_not_verify_the_business_effect(self):
        target = el(name="联系人", automation_id="")
        grabs = iter([(b"before", 10, 10), (b"after", 10, 10)])
        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "ControlFromHandle", return_value=target), \
             mock.patch.object(act, "tree_size", return_value=316), \
             mock.patch.object(act.win32, "grab", side_effect=lambda h: next(grabs)), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=lambda e, name: (
                                   {"ok": True, "value": mock.Mock(
                                       DoDefaultAction=mock.Mock(return_value=True)),
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018}
                                   if name == "LegacyIAccessiblePattern"
                                   else {"ok": False, "reason": "pattern unavailable",
                                         "cause_unknown": True})):
            result = act.act(1, "click", target="联系人", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result.get("observation"), "captured frames differ")
        self.assertEqual(result.get("observation_source"), "PrintWindow")
        self.assertEqual(result["route_effect"], "business effect unverified")
        self.assertFalse(result["effect_verified"])

    def test_a_cached_frame_does_not_deny_an_executed_action_or_trigger_a_retry(self):
        state = {"saves": 0}
        target = el(name="Save", automation_id="save")

        class Saving:
            def DoDefaultAction(self):
                state["saves"] += 1
                target.Name = "Saved"
                return True

        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "tree_size", return_value=1), \
             mock.patch.object(act.win32, "grab", return_value=(b"cached", 10, 10)), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": Saving(),
                                             "canonical": "LegacyIAccessiblePattern",
                                             "pattern_id": 10018}):
            result = act.act(1, "click", target="save", allow_foreground=True)
        self.assertEqual(state["saves"], 1)
        self.assertEqual(target.Name, "Saved")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result.get("observation_source"), "PrintWindow")
        self.assertEqual(result["observation"], "captured frames are identical")
        self.assertEqual(result["route_effect"], "business effect unverified")
        self.assertFalse(result["effect_verified"])

    def test_a_click_that_changed_the_control_has_no_observation(self):
        state = {"n": 0}
        target = el(name="展开", automation_id="")

        class Changing:
            def DoDefaultAction(self):
                state["n"] += 1
                target.Name = "已展开"
                return True

        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "ControlFromHandle", return_value=target), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=lambda el, name: (
                                   {"ok": True, "value": Changing(),
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018}
                                   if name == "LegacyIAccessiblePattern"
                                   else {"ok": False, "reason": "pattern unavailable",
                                         "cause_unknown": True})):
            result = act.act(1, "click", target="展开", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("observation", result)

    def test_a_click_that_changed_the_tree_is_not_called_a_no_op(self):
        """Measured on QQ: clicking a contact group changed the tree from 185 to
        256 elements while the clicked label itself was unchanged. Judging only
        the clicked control reported a false "no visible change"."""
        target = el(name="我的好友", automation_id="")
        sizes = iter([185, 256])
        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "ControlFromHandle", return_value=target), \
             mock.patch.object(act, "tree_size", side_effect=lambda hwnd: next(sizes)), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=lambda el, name: (
                                   {"ok": True, "value": mock.Mock(
                                       DoDefaultAction=mock.Mock(return_value=True)),
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018}
                                   if name == "LegacyIAccessiblePattern"
                                   else {"ok": False, "reason": "pattern unavailable",
                                         "cause_unknown": True})):
            result = act.act(1, "click", target="我的好友", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("observation", result)

    def test_an_unreadable_tree_size_does_not_prove_a_change(self):
        target = el(name="x", automation_id="")
        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "ControlFromHandle", return_value=target), \
             mock.patch.object(act, "tree_size", return_value=None), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=lambda el, name: (
                                   {"ok": True, "value": mock.Mock(
                                       DoDefaultAction=mock.Mock(return_value=True)),
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018}
                                   if name == "LegacyIAccessiblePattern"
                                   else {"ok": False, "reason": "pattern unavailable",
                                         "cause_unknown": True})):
            result = act.act(1, "click", target="x", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("observation", result,
                         "an unreadable tree must not be reported as a change")

    def test_an_unreadable_state_is_not_reported_as_unchanged(self):
        """If the control's own name cannot be read, the tool has observed
        nothing and must not claim "no change"."""
        target = el(name="x", automation_id="")
        broken = mock.Mock()
        broken.DoDefaultAction.return_value = True
        type(target).__getattribute__

        with self.patch_children([]), self.patch_read(detailed(target)), \
             mock.patch.object(act, "ControlFromHandle", return_value=target), \
             mock.patch.object(act.tree, "pattern_detailed",
                               side_effect=lambda el, name: (
                                   {"ok": True, "value": broken,
                                    "canonical": "LegacyIAccessiblePattern",
                                    "pattern_id": 10018}
                                   if name == "LegacyIAccessiblePattern"
                                   else {"ok": False, "reason": "pattern unavailable",
                                         "cause_unknown": True})), \
             mock.patch.object(act, "_state_signature", return_value=None):
            result = act.act(1, "click", target="x", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("observation", result,
                         "unknown state must not be called an unchanged one")

    def test_the_pointer_route_reports_no_observation(self):
        root = el(name="btn", automation_id="b", rect=FakeRect(0, 0, 100, 30))
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             mock.patch.object(act.win32, "window_at", return_value=1), \
             mock.patch.object(act, "SetCursorPos"), \
             mock.patch.object(act, "Click"):
            result = act.act(1, "click", target="b", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("observation", result)


class TestFocusSettling(ActCase):
    """A click is followed by keys, but focus moves a moment later.

    Measured: the first character of a typed string was lost. Fixed sleep was
    not enough, so the wait is driven by the focus actually arriving.
    """

    def setUp(self):
        super().setUp()
        self.now = 0.0

        def advance(seconds):
            self.now = round(self.now + seconds, 9)

        for patch in (
                mock.patch.object(act.time, "monotonic", side_effect=lambda: self.now),
                mock.patch.object(act.time, "sleep", side_effect=advance),
                mock.patch.object(act.win32.user32, "GetAncestor", return_value=1)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_no_keys_until_the_focus_is_reported(self):
        observed = []
        with mock.patch.object(act.win32, "focus_window",
                               side_effect=lambda: 1 if self.now >= 0.04 else 0), \
             mock.patch.object(act, "SendKeys",
                               side_effect=lambda text, **kw: observed.append(text)):
            settled = act._focus_settled(1, timeout_ms=500)
        self.assertTrue(settled)
        self.assertEqual(observed, [], "waiting must not type anything")

    def test_focus_that_never_arrives_is_a_refusal(self):
        with mock.patch.object(act.win32, "focus_window", return_value=0):
            self.assertFalse(act._focus_settled(1, timeout_ms=500))
        self.assertLessEqual(self.now, 0.5)

    def test_another_foreground_window_is_not_the_target(self):
        with mock.patch.object(act.win32, "foreground", return_value=999), \
             mock.patch.object(act.win32, "focus_window", return_value=999):
            self.assertFalse(act._focus_settled(1, timeout_ms=500))
        self.assertLessEqual(self.now, 0.5)

    def test_focus_must_belong_to_the_addressed_window(self):
        with mock.patch.object(act.win32, "focus_window", return_value=999), \
             mock.patch.object(act.win32.user32, "GetAncestor", return_value=999):
            self.assertFalse(act._focus_settled(1, timeout_ms=500))

    def test_focus_lost_during_settling_is_refused(self):
        with mock.patch.object(act.win32, "foreground",
                               side_effect=lambda: 1 if self.now < 0.05 else 999):
            self.assertFalse(act._focus_settled(1, timeout_ms=500))

    def test_focus_read_exceeding_the_budget_cannot_report_settled(self):
        def delayed_focus():
            if self.now:
                self.now += 1
            return 1

        with mock.patch.object(act.win32, "focus_window", side_effect=delayed_focus):
            self.assertFalse(act._focus_settled(1, timeout_ms=500))

    def test_typing_refuses_focus_left_on_another_control_in_the_same_window(self):
        root = el(name="disabled-field", automation_id="e")
        root.HasKeyboardFocus = False
        sent = []
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.win32, "focus_window", return_value=5), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             mock.patch.object(act.win32, "window_at", return_value=1), \
             mock.patch.object(act, "SetCursorPos"), mock.patch.object(act, "Click"), \
             mock.patch.object(act, "SendKeys", side_effect=lambda text, **kw: sent.append(text)):
            result = act.act(1, "type", target="e", text="private", allow_foreground=True)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "target not focused")
        self.assertEqual(sent, [])
        self.assertLessEqual(self.now, 0.8)

    def test_keys_recheck_foreground_after_setfocus(self):
        state = {"foreground": 1}
        root = mock.Mock()
        root.SetFocus.side_effect = lambda: state.update(foreground=999)
        sent = []
        with mock.patch.object(act.win32, "foreground", side_effect=lambda: state["foreground"]), \
             mock.patch.object(act.launch, "is_shown", return_value=True), \
             mock.patch.object(act, "ControlFromHandle", return_value=root), \
             mock.patch.object(act, "SendKeys", side_effect=lambda text, **kw: sent.append(text)):
            result = act.act(1, "key", text="Enter", allow_foreground=True)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "target not focused")
        self.assertEqual(sent, [])
        self.assertLessEqual(self.now, 0.8)

    def test_typing_stops_if_focus_moves_after_select_all(self):
        root = el(name="field", automation_id="e")
        root.HasKeyboardFocus = True
        state = {"foreground": 1}
        sent = []

        def send(text, **kwargs):
            sent.append(text)
            state["foreground"] = 999

        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.win32, "foreground", side_effect=lambda: state["foreground"]), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             mock.patch.object(act.win32, "window_at", return_value=1), \
             mock.patch.object(act, "SetCursorPos"), mock.patch.object(act, "Click"), \
             mock.patch.object(act, "SendKeys", side_effect=send):
            result = act.act(1, "type", target="e", text="private", allow_foreground=True)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "target not focused")
        self.assertEqual(sent, ["{Ctrl}a"])
        self.assertFalse(result["retry_safe"])

    def test_keys_wait_for_native_focus_to_arrive(self):
        sent_at = []
        root = mock.Mock()
        root.SetFocus.return_value = True
        with mock.patch.object(act.launch, "is_shown", return_value=True), \
             mock.patch.object(act, "ControlFromHandle", return_value=root), \
             mock.patch.object(act.win32, "focus_window",
                               side_effect=lambda: 1 if self.now >= 0.06 else 0), \
             mock.patch.object(act, "SendKeys", side_effect=lambda *args, **kw: sent_at.append(self.now)):
            result = act.act(1, "key", text="Enter", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(sent_at), 1)
        self.assertGreaterEqual(sent_at[0], 0.06)
        self.assertLessEqual(self.now, 0.8)

    def test_a_failed_focus_wait_sends_nothing(self):
        root = el(name="f", automation_id="f", rect=FakeRect(0, 0, 100, 20))
        with self.patch_children([]), self.patch_read(detailed(root)), \
             self.patch_activate(True), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "pattern unavailable",
                                             "cause_unknown": True}), \
             mock.patch.object(act.win32, "window_at", return_value=1), \
             mock.patch.object(act, "_focus_settled", return_value=False), \
             mock.patch.object(act, "SetCursorPos"), \
             mock.patch.object(act, "Click"), \
             mock.patch.object(act, "SendKeys") as keys:
            result = act.act(1, "type", target="f", text="hello", allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "target not focused")
        keys.assert_not_called()


class TestInvokePattern(ActCase):
    def setUp(self):
        super().setUp()
        self.root = el(name="root")
        self.read = mock.patch.object(act.tree, "read_detailed",
                                      return_value=detailed(self.root))
        self.handle = mock.patch.object(act, "ControlFromHandle", return_value=self.root)
        for patch in (self.read, self.handle):
            patch.start()
            self.addCleanup(patch.stop)
        self.patch_read = None

    def invoke(self, **kwargs):
        params = dict(pattern="ValuePattern", target="", method="Value", args=None)
        params.update(kwargs)
        return act.invoke_pattern(1, **params)

    def value_pattern(self, value="text", attr=True):
        pattern = mock.Mock()
        pattern.Value = value
        return pattern

    def test_empty_target_uses_the_root_window(self):
        pattern = self.value_pattern()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ValuePattern", "pattern_id": 10002}):
            result = self.invoke(method="Value", args=[])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"], "text")
        self.assertEqual(result["route"], "uia:ValuePattern")
        self.assertFalse(result["effect_verified"])
        self.assertTrue(result["call_completed"])

    def test_unknown_or_unwrapped_pattern_is_reported_as_is(self):
        for reason in ("unknown pattern", "pattern not wrapped", "provider error",
                       "pattern unavailable"):
            with mock.patch.object(act.tree, "pattern_detailed",
                                   return_value={"ok": False, "reason": reason,
                                                 "detail": "x", "pattern_id": 10034}):
                result = self.invoke()
            self.assertFalse(result["ok"], reason)
            self.assertEqual(result["reason"], reason)
            self.assertEqual(result["execution_state"], "not_started")

    def test_property_chain_reaches_a_text_range_and_projects_it(self):
        from windows_mcp.uia.patterns import TextPattern, TextRange

        text_range = TextRange.__new__(TextRange)
        text_range.GetText = lambda cap: "hello world"[:cap]
        class _FakeTextPattern(TextPattern):
            DocumentRange = property(lambda self: text_range)

        text_pattern = _FakeTextPattern()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": text_pattern,
                                             "canonical": "TextPattern", "pattern_id": 10014}):
            result = self.invoke(pattern="TextPattern", method="DocumentRange.GetText",
                                 args=[4096])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["text"], "hello world")

    def test_read_only_queries_are_allowed_in_the_background(self):
        pattern = self.value_pattern()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ValuePattern", "pattern_id": 10002}):
            result = self.invoke(method="Value", allow_foreground=False)
        self.assertTrue(result["ok"], result)

    def test_writer_members_need_permission_and_never_reach_the_provider(self):
        pattern = mock.Mock()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ValuePattern", "pattern_id": 10002}) as get:
            result = self.invoke(method="SetValue", args=["x"])
        self.assertTrue(result.get("needs_permission"), result)
        get.assert_not_called()
        pattern.SetValue.assert_not_called()

    def test_get_prefix_is_not_trusted_as_read_only(self):
        pattern = mock.Mock()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ValuePattern", "pattern_id": 10002}):
            result = self.invoke(method="SomethingElse", args=[])
        self.assertTrue(result.get("needs_permission"), result)
        pattern.SomethingElse.assert_not_called()

    def test_private_and_expression_members_are_refused(self):
        for method in ("_private", "Value.__class__", "Value[0]", "Value()", "a b"):
            with mock.patch.object(act.tree, "pattern_detailed") as get:
                result = self.invoke(method=method)
            self.assertEqual(result["reason"], "invalid arguments", method)
            get.assert_not_called()

    def test_raw_element_fields_cannot_be_used_as_a_chain(self):
        for method in ("pattern", "Element", "textRange", "pattern.CurrentValue"):
            with mock.patch.object(act.tree, "pattern_detailed") as get:
                result = self.invoke(method=method)
            self.assertIn(result["reason"], ("invalid arguments", "member unavailable"),
                          method)
            get.assert_not_called()

    def test_action_false_is_a_failure_that_completed(self):
        pattern = mock.Mock()
        pattern.Expand.return_value = False
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ExpandCollapsePattern",
                                             "pattern_id": 10005}):
            result = self.invoke(pattern="ExpandCollapsePattern", method="Expand",
                                 args=[], allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider reported false")
        self.assertTrue(result["call_completed"])
        self.assertEqual(result["execution_state"], "completed")

    def test_query_returning_false_is_a_legitimate_value(self):
        pattern = mock.Mock()
        pattern.IsSelected = False
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "SelectionItemPattern",
                                             "pattern_id": 10010}):
            result = self.invoke(pattern="SelectionItemPattern", method="IsSelected", args=[])
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"])

    def test_control_list_is_projected_without_com_leaking(self):
        import windows_mcp.uia.patterns as patterns

        # Real Control objects are what SelectionPattern returns; a fake cannot
        # stand in because _TRUSTED checks the dependency's actual classes.
        items = [act.ControlFromHandle.__self__ if False else _control("one", 1),
                 _control("two", 2)]
        pattern = patterns.SelectionPattern.__new__(patterns.SelectionPattern)
        pattern.GetSelection = lambda: items
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "SelectionPattern", "pattern_id": 10001}):
            result = self.invoke(pattern="SelectionPattern", method="GetSelection", args=[])
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["result"]), 2)
        self.assertNotIn("_el", result["result"][0])

    def test_unknown_object_is_result_unsupported_not_silent_success(self):
        import windows_mcp.uia.patterns as patterns

        pattern = patterns.ValuePattern.__new__(patterns.ValuePattern)
        # A declared public member whose value has no projection.
        pattern.Weird = object()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ValuePattern", "pattern_id": 10002}):
            result = self.invoke(method="Weird", args=[], allow_foreground=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "result unsupported")
        self.assertEqual(result["execution_state"], "completed")
        self.assertFalse(result["retry_safe"])

    def test_arguments_are_limited_to_json_scalars(self):
        # Authorization comes first: SetValue is off the read-only table, so the
        # call needs allow_foreground before its arguments are even considered.
        for args in ([{"a": 1}], [float("nan")], [float("inf")], [None], [[1]]):
            result = self.invoke(method="SetValue", args=args, allow_foreground=True)
            self.assertEqual(result["reason"], "invalid arguments", args)
        # Plain scalars are legal arguments.
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": False, "reason": "unknown pattern"}):
            self.assertNotEqual(
                self.invoke(method="SetValue", args=["x"], allow_foreground=True)["reason"],
                "invalid arguments")

    def test_args_none_means_no_arguments(self):
        pattern = self.value_pattern()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ValuePattern", "pattern_id": 10002}):
            result = self.invoke(method="Value", args=None)
        self.assertTrue(result["ok"], result)

    def test_a_property_rejects_arguments(self):
        pattern = self.value_pattern()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": pattern,
                                             "canonical": "ValuePattern", "pattern_id": 10002}):
            result = self.invoke(method="Value", args=[1])
        self.assertEqual(result["reason"], "invalid arguments")

    def test_target_resolution_is_exact_only(self):
        one = el(name="Save As")
        with mock.patch.object(act.tree, "read_detailed", return_value=detailed(one)):
            result = self.invoke(target="Save", method="Value")
        self.assertEqual(result["reason"], "no such control")

    def test_ambiguous_or_incomplete_targets_refuse(self):
        with mock.patch.object(act.tree, "read_detailed",
                               return_value=detailed(el(name="x"), el(name="x", automation_id="2"))):
            self.assertEqual(self.invoke(target="x")["reason"], "ambiguous target")
        with mock.patch.object(act.tree, "read_detailed",
                               return_value=detailed(el(name="x"), limit_reached=True)):
            self.assertEqual(self.invoke(target="x")["reason"], "tree incomplete")

    def test_timeout_and_hwnd_validation(self):
        for bad in (0, -1, True, "1"):
            result = act.invoke_pattern(bad, "ValuePattern", "", "Value", [])
            self.assertEqual(result["reason"], "invalid hwnd", bad)
        for bad in (0, 30001, True):
            result = self.invoke(timeout_ms=bad)
            self.assertEqual(result["reason"], "invalid arguments", bad)
        self.assertEqual(self.invoke(pattern="")["reason"], "invalid arguments")
        self.assertEqual(self.invoke(method="")["reason"], "invalid arguments")

    def test_gettext_cap_is_bounded(self):
        for bad in (-1, 0, 6002):
            with mock.patch.object(act.tree, "pattern_detailed") as get:
                result = self.invoke(pattern="TextPattern", method="DocumentRange.GetText",
                                     args=[bad])
            self.assertEqual(result["reason"], "invalid arguments", bad)
            get.assert_not_called()

    def test_gettext_at_the_cap_is_possibly_truncated(self):
        from windows_mcp.uia.patterns import TextPattern, TextRange

        text_range = TextRange.__new__(TextRange)
        text_range.GetText = lambda cap: "x" * min(cap, 4097)
        class _FakeTextPattern(TextPattern):
            DocumentRange = property(lambda self: text_range)

        text_pattern = _FakeTextPattern()
        with mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": text_pattern,
                                             "canonical": "TextPattern", "pattern_id": 10014}):
            result = self.invoke(pattern="TextPattern", method="DocumentRange.GetText",
                                 args=[4096])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["result"]["possibly_truncated"])


class TestProjection(ActCase):
    def test_projecticts_scalars_without_stringifying(self):
        budget = act._Budget()
        self.assertEqual(act._plain_result(True, budget), True)
        self.assertEqual(act._plain_result(7, budget), 7)
        self.assertEqual(act._plain_result(1.5, budget), 1.5)
        self.assertEqual(act._plain_result("s", budget), "s")
        self.assertIsNone(act._plain_result(None, budget))

    def test_large_lists_are_truncated_and_flagged(self):
        budget = act._Budget()
        value = list(range(500))
        result = act._plain_result(value, budget)
        self.assertEqual(len(result), 100)
        self.assertTrue(budget.truncated)

    def test_long_strings_are_bounded(self):
        budget = act._Budget()
        result = act._plain_result("x" * 20000, budget)
        self.assertLessEqual(len(result), act.MAX_TEXT)
        self.assertTrue(budget.truncated)

    def test_depth_is_bounded(self):
        budget = act._Budget()
        deep = [[[[[[1]]]]]]
        act._plain_result(deep, budget)
        self.assertTrue(budget.truncated)

    def test_non_string_keys_are_not_projected(self):
        budget = act._Budget()
        with self.assertRaises(act.Unsupported):
            act._plain_result({1: "x"}, budget)


if __name__ == "__main__":
    unittest.main()

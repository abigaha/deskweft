"""Composite targets: current unique identity from MCP through worker to UIA.

All providers, messages and input are fakes; no application is touched.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from fastmcp import Client

from deskweft import act, server, tree, uia_worker
from test_act import ActCase, detailed, el
from test_tree import FakeElement, FakeRect


class TestSelectorResolution(unittest.TestCase):
    def setUp(self):
        self.edit = el("message", control_type="EditControl")
        self.button = el("message", control_type="ButtonControl")
        self.data = detailed(self.edit, self.button)

    def test_name_and_type_disambiguate_repeated_names(self):
        found = tree.resolve(self.data, {"name": "message", "control_type": "EditControl"})
        self.assertTrue(found["ok"], found)
        self.assertIs(found["element"]["_el"], self.edit)

    def test_rectangle_and_native_handle_are_exact_additional_predicates(self):
        other = el("message", control_type="EditControl", rect=FakeRect(10, 10, 30, 30))
        data = detailed(self.edit, other)
        data["elements"][0]["native_hwnd"] = 9
        found = tree.resolve(data, {"control_type": "EditControl", "native_hwnd": 9,
                                    "rect": [0, 0, 10, 10]})
        self.assertTrue(found["ok"], found)
        self.assertIs(found["element"]["_el"], self.edit)
        found = tree.resolve(data, {"name": "message", "rect": [10, 10, 20, 20]})
        self.assertIs(found["element"]["_el"], other)

    def test_all_fields_must_match_without_substring_or_id_priority(self):
        for selector in ({"name": "mess"}, {"name": "Message"},
                         {"automation_id": "missing", "name": "message"},
                         {"name": "message", "rect": [0, 0, 11, 10]}):
            with self.subTest(selector=selector):
                result = tree.resolve(self.data, selector)
                self.assertEqual(result["reason"], "no such control", result)

    def test_ambiguous_and_incomplete_trees_still_refuse(self):
        self.assertEqual(tree.resolve(self.data, {"name": "message"})["reason"],
                         "ambiguous target")
        for flag in ("timed_out", "limit_reached", "identity_complete"):
            data = dict(self.data, **{flag: flag != "identity_complete"})
            self.assertEqual(tree.resolve(data, {"control_type": "EditControl"})["reason"],
                             "tree incomplete")

    def test_invalid_selectors_are_rejected(self):
        for target in (None, 7, True, [], {}, {"name": ""}, {"name": 7},
                       {"name": "message", "nth": 0}, {"rect": [0, 0, 10, 10]},
                       {"native_hwnd": True}, {"native_hwnd": 0},
                       {"name": "message", "rect": [0, 0, 1]},
                       {"name": "message", "rect": [0, 0, True, 10]},
                       {"name": "message", "rect": [0, 0, 0, 10]}):
            with self.subTest(target=target):
                result = tree.resolve(self.data, target)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["reason"], "invalid target", result)

    def test_unreadable_selector_field_cannot_hide_a_competitor(self):
        for attribute, selector in (
            ("ControlTypeName", {"name": "message", "control_type": "EditControl"}),
            ("BoundingRectangle", {"name": "message", "rect": [0, 0, 10, 10]}),
            ("NativeWindowHandle", {"name": "message", "native_hwnd": 9}),
        ):
            with self.subTest(attribute=attribute):
                root = FakeElement(children=[
                    FakeElement(name="message", control_type="EditControl", native=9),
                    FakeElement(name="message", fail={attribute}),
                ])
                with mock.patch.object(tree, "ControlFromHandle", return_value=root):
                    data = tree.read_detailed(1)
                self.assertEqual(tree.resolve(data, selector)["reason"], "tree incomplete")
                # Optional metadata failures must not break old string addressing.
                data["elements"][1]["name"] = "different"
                self.assertTrue(tree.resolve(data, "message")["ok"])

    def test_anonymous_controls_participate_in_selector_uniqueness(self):
        unnamed = FakeElement(automation_id="other-edit", control_type="EditControl",
                              native=10, patterns={"LegacyIAccessiblePattern": object()})
        root = FakeElement(children=[self.edit, unnamed])
        with mock.patch.object(tree, "ControlFromHandle", return_value=root):
            data = tree.read_detailed(1)
        self.assertEqual(tree.resolve(data, {"control_type": "EditControl"})["reason"],
                         "ambiguous target")
        found = tree.resolve(data, {"automation_id": "other-edit"})
        self.assertTrue(found["ok"], found)
        self.assertIs(found["element"]["_el"], unnamed)


class TestSelectorActions(ActCase):
    def setUp(self):
        super().setUp()
        self.edit = el("message", control_type="EditControl")
        self.selector = {"name": "message", "control_type": "EditControl"}
        self.data = detailed(el("message"), self.edit)

    def test_all_fixed_actions_use_the_same_resolved_element_once(self):
        for action, helper in (("click", "_click_uia"), ("type", "_type_uia"),
                               ("scroll", "_scroll")):
            with self.subTest(action=action), self.patch_children([]), \
                 self.patch_read(self.data) as read, \
                 mock.patch.object(act, helper, return_value={"ok": True}) as route:
                result = act.act(1, action, self.selector, allow_foreground=True)
                self.assertTrue(result["ok"], result)
                self.assertIn(self.edit, route.call_args.args)
                read.assert_called_once()

    def test_structured_native_target_keeps_the_background_message_route(self):
        self.data["elements"][1]["native_hwnd"] = 9
        kids = [{"hwnd": 9, "class": "Edit", "text": "native title differs"}]
        with self.patch_children(kids), self.patch_read(self.data), \
             mock.patch.object(act.win32, "_write_text", return_value={
                 "ok": True, "effect_verified": True}) as write:
            result = act.act(1, "type", self.selector, text="text")
        self.assertEqual(result["route"], "win32:WM_SETTEXT", result)
        self.assertEqual(write.call_args.args[:2], (9, "text"))

    def test_foreign_or_non_native_handle_never_bypasses_the_permission_gate(self):
        self.data["elements"][1]["native_hwnd"] = 9
        for kids in ([], [{"hwnd": 9, "class": "RenderHost", "text": "message"}],
                     [{"hwnd": 10, "class": "Edit", "text": "message"}]):
            with self.subTest(kids=kids), self.patch_children(kids), \
                 self.patch_read(self.data), mock.patch.object(act.win32, "_write_text") as write:
                result = act.act(1, "type", self.selector, text="text")
                self.assertTrue(result["needs_permission"], result)
                write.assert_not_called()

    def test_changed_or_ambiguous_target_sends_no_action(self):
        for selector in ({"name": "message"}, dict(self.selector, rect=[9, 9, 10, 10])):
            with self.subTest(selector=selector), self.patch_children([]), \
                 self.patch_read(self.data), mock.patch.object(act, "_click_uia") as route, \
                 mock.patch.object(act.win32.user32, "PostMessageW") as post:
                result = act.act(1, "click", selector, allow_foreground=True)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["execution_state"], "not_started")
                route.assert_not_called()
                post.assert_not_called()

    def test_unnamed_competitor_prevents_a_native_write_from_a_real_tree_read(self):
        root = FakeElement(children=[
            FakeElement(name="message", control_type="EditControl", native=9),
            FakeElement(automation_id="other-edit", control_type="EditControl", native=10),
        ])
        with mock.patch.object(tree, "ControlFromHandle", return_value=root), \
             mock.patch.object(act.win32, "children") as children, \
             mock.patch.object(act.win32, "_write_text") as write:
            result = act.act(1, "type", {"control_type": "EditControl"}, text="text")
        self.assertEqual(result["reason"], "ambiguous target", result)
        self.assertEqual(result["execution_state"], "not_started")
        children.assert_not_called()
        write.assert_not_called()

    def test_invalid_target_is_rejected_before_tree_or_provider(self):
        for target in ({}, {"name": "message", "nth": 0}, 9):
            with self.subTest(target=target), self.patch_read(self.data) as read:
                result = act.act(1, "scroll", target, allow_foreground=True)
                self.assertEqual(result["reason"], "invalid target", result)
                read.assert_not_called()

    def test_generic_query_resolves_the_selector_instead_of_the_root(self):
        pattern = mock.Mock(Value="actual text")
        with self.patch_read(self.data), \
             mock.patch.object(act, "ControlFromHandle") as root, \
             mock.patch.object(tree, "pattern_detailed", return_value={
                 "ok": True, "value": pattern, "canonical": "ValuePattern",
                 "pattern_id": 10002}) as getter:
            result = act.invoke_pattern(1, "ValuePattern", self.selector, "Value", [])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"], "actual text")
        getter.assert_called_once_with(self.edit, "ValuePattern")
        root.assert_not_called()


class TestSelectorMCP(unittest.TestCase):
    def call(self, name, target):
        async def run():
            async with Client(server.mcp) as client:
                arguments = {"hwnd": 1, "target": target}
                if name == "invoke_pattern":
                    arguments.update(pattern="ValuePattern", method="Value")
                return await client.call_tool(name, arguments)
        return asyncio.run(run())

    def test_every_target_tool_advertises_and_forwards_plain_selector_fields(self):
        target = {"name": "message", "control_type": "EditControl", "rect": [0, 0, 20, 10]}
        for name in ("click", "type_text", "scroll", "invoke_pattern"):
            with self.subTest(name=name), \
                 mock.patch.object(server, "_worker_call", return_value={"ok": True}) as call:
                self.call(name, target)
                self.assertEqual(call.call_args.args[1]["target"], target)

    def test_schema_rejects_unknown_fields_and_wrong_field_types_before_worker(self):
        for target in ({"name": "message", "nth": 0}, {"name": 9},
                       {"native_hwnd": True}, {"rect": [0, 0, 10]},
                       {"name": "x", "rect": [0, 0, 10, "20"]}):
            with self.subTest(target=target), mock.patch.object(server, "_worker_call") as call:
                with self.assertRaises(Exception):
                    self.call("click", target)
                call.assert_not_called()

    def test_worker_dispatch_preserves_structured_targets(self):
        selector = {"name": "message", "control_type": "EditControl"}
        with mock.patch.object(act, "act", return_value={"ok": True}) as call:
            dispatch = uia_worker._make_dispatch()
            dispatch["type_text"](hwnd=1, target=selector, text="text")
        self.assertEqual(call.call_args.kwargs["target"], selector)


if __name__ == "__main__":
    unittest.main()

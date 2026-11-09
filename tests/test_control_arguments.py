"""C1-b: let a caller pass a control reference as an argument.

The contract forbids raw COM objects and dictionary-impersonated Controls
crossing the protocol, and forbids caching references across requests. What is
allowed is a *description* a worker can re-resolve and verify in the same call.

So an argument may be `{"$control": {"hwnd": n, "name": ..., "automation_id": ...,
"control_type": ...}}`: the worker resolves it again, requires exactly one match,
and only then passes the live Control to the provider method. If it no longer
matches, the call is refused instead of acting on whatever now occupies the spot.
"""

from __future__ import annotations

import unittest
from unittest import mock

from deskweft import act, tree
from test_tree import FakeElement, FakeRect


def detailed(*elements, **overrides):
    base = {"elements": [_as_row(e) for e in elements],
            "timed_out": False, "limit_reached": False, "identity_complete": True,
            "tree_diagnostics": {"root_status": "ok", "filtered_anonymous": 0,
                                 "filtered_offscreen": 0, "warnings": [],
                                 "warnings_truncated": False}}
    base.update(overrides)
    return base


def _as_row(element):
    box = element.BoundingRectangle
    return {"control_type": element.ControlTypeName, "automation_id": element.AutomationId,
            "name": element.Name, "nth": 0, "patterns": [], "native_hwnd": None,
            "depth": 0,
            "rect": None if box is None else [box.left, box.top,
                                              box.right - box.left,
                                              box.bottom - box.top],
            "_el": element}


def el(name="", automation_id="", patterns=None, **kwargs):
    return FakeElement(name=name, automation_id=automation_id, patterns=patterns or {},
                       **kwargs)


class TestControlArguments(unittest.TestCase):
    def test_a_control_argument_is_recognised(self):
        value = {"$control": {"hwnd": 42, "name": "node", "control_type": "TreeItemControl"}}
        self.assertTrue(act._is_control_argument(value))

    def test_a_plain_dict_is_not_a_control_argument(self):
        for value in ({"a": 1}, {"hwnd": 42}, {"$control": "x"}, {},
                      {"$control": {"name": 5}}):
            self.assertFalse(act._is_control_argument(value), value)

    def test_a_control_argument_needs_at_least_one_identity_field(self):
        self.assertFalse(act._is_control_argument({"$control": {"hwnd": 42}}))
        self.assertTrue(act._is_control_argument({"$control": {"hwnd": 42, "name": "x"}}))
        self.assertTrue(act._is_control_argument(
            {"$control": {"hwnd": 42, "automation_id": "n1"}}))
        self.assertTrue(act._is_control_argument(
            {"$control": {"hwnd": 42, "control_type": "TreeItemControl"}}))

    def test_unknown_fields_inside_a_control_argument_are_refused(self):
        value = {"$control": {"hwnd": 42, "name": "x", "pattern": "raw"}}
        self.assertFalse(act._is_control_argument(value))

    def test_arguments_still_accept_ordinary_scalars(self):
        self.assertIsNone(act._argument_error([1, "a", 2.5, True]))
        self.assertIsNone(act._argument_error(
            [{"$control": {"hwnd": 42, "name": "x"}}]))
        self.assertIsNotNone(act._argument_error([{"a": 1}]))


class TestControlResolution(unittest.TestCase):
    def resolve(self, args, rows, revision=(1, 2, 3, 4)):
        element = el(name="node", automation_id="n1")
        with mock.patch.object(act, "ControlFromHandle", return_value=el(name="root")), \
             mock.patch.object(act.tree, "read_detailed", return_value=detailed(*rows)), \
             mock.patch.object(act, "_control_signature", return_value=revision):
            return act._resolve_arguments(42, args)

    def test_a_matching_reference_becomes_the_live_control(self):
        row = el(name="node", automation_id="n1")
        resolved = self.resolve([{"$control": {"hwnd": 42, "automation_id": "n1"}}], [row])
        self.assertTrue(resolved["ok"], resolved)
        self.assertIs(resolved["args"][0], row)

    def test_an_ambiguous_reference_is_refused(self):
        rows = [el(name="node", automation_id="n1"), el(name="node", automation_id="n1")]
        resolved = self.resolve([{"$control": {"hwnd": 42, "automation_id": "n1"}}], rows)
        self.assertFalse(resolved["ok"])
        self.assertEqual(resolved["reason"], "ambiguous target")

    def test_a_reference_that_no_longer_matches_is_refused(self):
        row = el(name="renamed", automation_id="n2")
        resolved = self.resolve([{"$control": {"hwnd": 42, "automation_id": "n1"}}], [row])
        self.assertFalse(resolved["ok"])
        self.assertEqual(resolved["reason"], "no such control")

    def test_an_incomplete_tree_refuses_the_reference(self):
        row = el(name="node", automation_id="n1")
        element = el(name="root")
        with mock.patch.object(act, "ControlFromHandle", return_value=element), \
             mock.patch.object(act.tree, "read_detailed",
                               return_value=detailed(row, limit_reached=True)):
            resolved = act._resolve_arguments(42, [{"$control": {"hwnd": 42,
                                                                 "automation_id": "n1"}}])
        self.assertFalse(resolved["ok"])
        self.assertEqual(resolved["reason"], "tree incomplete")

    def test_a_reference_to_another_window_is_refused(self):
        resolved = self.resolve([{"$control": {"hwnd": 99, "name": "node"}}],
                                [el(name="node")])
        self.assertFalse(resolved["ok"])
        self.assertEqual(resolved["reason"], "invalid arguments")

    def test_the_arguments_stay_finite_when_no_reference_is_used(self):
        resolved = self.resolve([1, "a"], [])
        self.assertTrue(resolved["ok"], resolved)
        self.assertEqual(resolved["args"], [1, "a"])

    def test_a_disappearing_control_is_reported_before_the_call(self):
        """The re-resolved control must still be the same element; a tree read
        that returns a different instance with the same name is not enough."""
        row = el(name="node", automation_id="n1")
        signatures = iter([(9, 9, 9, 9), (1, 2, 3, 4)])
        with mock.patch.object(act, "ControlFromHandle", return_value=el(name="root")), \
             mock.patch.object(act.tree, "read_detailed", return_value=detailed(row)), \
             mock.patch.object(act, "_control_signature",
                               side_effect=lambda e: next(signatures)):
            resolved = act._resolve_arguments(42, [{"$control": {"hwnd": 42,
                                                                 "automation_id": "n1",
                                                                 "rect": [1, 2, 3, 4]}}])
        self.assertFalse(resolved["ok"])
        self.assertEqual(resolved["reason"], "no such control")


class TestMemberKind(unittest.TestCase):
    """Whether a member takes arguments follows the wrapper's descriptor.

    SelectionPattern.GetSelection is a method; ValuePattern.Value is a property.
    Deciding by "it is on the read-only table" refused a legitimate method call.
    """

    def invoke(self, value, method, args):
        with mock.patch.object(act, "ControlFromHandle", return_value=el(name="root")), \
             mock.patch.object(act.tree, "pattern_detailed",
                               return_value={"ok": True, "value": value,
                                             "canonical": type(value).__name__,
                                             "pattern_id": 1}):
            return act.invoke_pattern(42, "Whatever", "", method, args,
                                      allow_foreground=True)

    def test_a_read_only_method_accepts_arguments(self):
        from windows_mcp.uia.controls import Control
        from windows_mcp.uia.patterns import SelectionPattern, TextRange

        picked = Control.__new__(Control)
        picked.__dict__.update({
            "Name": "picked", "AutomationId": "p1", "ControlTypeName": "ListItemControl",
            "BoundingRectangle": FakeRect(), "NativeWindowHandle": 1,
            "_patterns": {}, "_children": [],
        })
        pattern = SelectionPattern.__new__(SelectionPattern)
        pattern.GetSelection = lambda: [picked]
        result = self.invoke(pattern, "GetSelection", [])
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["result"]), 1)
        self.assertIn("control_type", result["result"][0])
        self.assertNotIn("_el", result["result"][0])

    def test_a_property_still_refuses_arguments(self):
        from windows_mcp.uia.patterns import ValuePattern

        pattern = ValuePattern.__new__(ValuePattern)
        result = self.invoke(pattern, "Value", ["x"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid arguments")


if __name__ == "__main__":
    unittest.main()

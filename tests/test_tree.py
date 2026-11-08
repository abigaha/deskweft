"""tree.py: pattern guard, diagnostics, native handles.

Fake elements only - no UIA, no provider, no window.
"""

from __future__ import annotations

import unittest
from unittest import mock

from deskweft import tree


class FakeRect:
    def __init__(self, left=0, top=0, right=10, bottom=10):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


_READABLE = {"Name", "AutomationId", "ControlTypeName", "IsOffscreen",
             "BoundingRectangle", "NativeWindowHandle"}


class FakeElement:
    """A stand-in for windows_mcp.uia.Control, down to its failure modes."""

    def __init__(self, name="", automation_id="", control_type="ButtonControl",
                 children=None, offscreen=False, patterns=None, rect=FakeRect(),
                 native=0, fail=None, pattern_errors=None, pattern_none=()):
        self.Name = name
        self.AutomationId = automation_id
        self.ControlTypeName = control_type
        self.IsOffscreen = offscreen
        self.BoundingRectangle = rect
        self.NativeWindowHandle = native
        self._children = children or []
        self._patterns = patterns or {}
        self._fail = fail or set()
        self._pattern_errors = pattern_errors or {}
        self._pattern_none = set(pattern_none)

    def __getattribute__(self, item):
        if item in _READABLE:
            fail = object.__getattribute__(self, "_fail")
            if item in fail:
                raise OSError(f"{item} unreadable")
        return object.__getattribute__(self, item)

    def GetChildren(self):
        if "children" in self._fail:
            raise RuntimeError("GetChildren exploded")
        return self._children

    def __getattr__(self, item):
        if item.startswith("Get") and item.endswith("Pattern"):
            name = item[3:]
            if name in self._pattern_errors:
                raise self._pattern_errors[name]
            if name in self._pattern_none:
                return lambda: None
            if name in self._patterns:
                return lambda: self._patterns[name]
            raise AttributeError(item)
        raise AttributeError(item)


class TestPatternGuard(unittest.TestCase):
    def el(self, **kwargs):
        return FakeElement(**kwargs)

    def test_unknown_pattern_name(self):
        result = tree.pattern_detailed(self.el(), "NoSuchPattern")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "unknown pattern")

    def test_pattern_without_a_wrapper_reports_the_id(self):
        result = tree.pattern_detailed(self.el(), "SelectionPattern2")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "pattern not wrapped")
        self.assertEqual(result["pattern_id"], 10034)

    def test_wrapper_returning_none_keeps_the_cause_unknown(self):
        result = tree.pattern_detailed(self.el(pattern_none={"InvokePattern"}), "InvokePattern")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "pattern unavailable")
        self.assertTrue(result["cause_unknown"])
        self.assertEqual(result["pattern_id"], 10000)

    def test_provider_error_is_preserved(self):
        result = tree.pattern_detailed(
            self.el(pattern_errors={"InvokePattern": ValueError("boom")}), "InvokePattern")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider error")
        self.assertIn("ValueError", result["detail"])

    def test_missing_getter_falls_back_to_the_numeric_id(self):
        el = self.el()
        sentinel = object()
        hits = []

        def get_pattern(pattern_id):
            hits.append(pattern_id)
            return sentinel

        el.GetPattern = get_pattern
        result = tree.pattern_detailed(el, "ValuePattern")
        self.assertTrue(result["ok"])
        self.assertIs(result["value"], sentinel)
        self.assertEqual(hits, [10002])

    def test_case_insensitive_name(self):
        sentinel = object()
        result = tree.pattern_detailed(
            self.el(patterns={"InvokePattern": sentinel}), "invokepattern")
        self.assertTrue(result["ok"])
        self.assertEqual(result["canonical"], "InvokePattern")

    def test_pattern_keeps_its_old_none_contract(self):
        self.assertIsNone(tree.pattern(self.el(), "NoSuchPattern"))
        sentinel = object()
        self.assertIs(tree.pattern(self.el(patterns={"InvokePattern": sentinel}),
                                   "InvokePattern"), sentinel)

    def test_patterns_summary_stays_small_and_lowercase(self):
        el = self.el(patterns={"InvokePattern": object(), "ValuePattern": object()})
        got = tree.patterns(el)
        self.assertEqual(got, ["invokepattern", "valuepattern"])


class TestReadDetailed(unittest.TestCase):
    def read(self, root, **kwargs):
        with mock.patch.object(tree, "ControlFromHandle", return_value=root):
            return tree.read_detailed(1234, **kwargs)

    def test_shape_and_fields(self):
        root = FakeElement(children=[FakeElement(name="HIT-ME", automation_id="b1", native=55)])
        got = self.read(root)
        self.assertEqual(got["tree_diagnostics"]["root_status"], "ok")
        self.assertFalse(got["timed_out"])
        self.assertFalse(got["limit_reached"])
        self.assertTrue(got["identity_complete"])
        self.assertEqual(got["elements"][0]["name"], "HIT-ME")
        self.assertEqual(got["elements"][0]["native_hwnd"], 55)

    def test_absent_root_is_reported_not_explained(self):
        with mock.patch.object(tree, "ControlFromHandle", return_value=None):
            got = tree.read_detailed(1234)
        self.assertEqual(got["tree_diagnostics"]["root_status"], "absent")
        self.assertEqual(got["elements"], [])

    def test_root_exception_is_a_provider_error(self):
        with mock.patch.object(tree, "ControlFromHandle", side_effect=OSError("nope")):
            got = tree.read_detailed(1234)
        self.assertEqual(got["tree_diagnostics"]["root_status"], "provider_error")
        self.assertFalse(got["identity_complete"])
        self.assertTrue(any("OSError" in w["message"] for w in got["tree_diagnostics"]["warnings"]))

    def test_getchildren_failure_marks_identity_incomplete(self):
        root = FakeElement(children=[FakeElement(name="a")], fail={"children"})
        got = self.read(root)
        self.assertFalse(got["identity_complete"])
        self.assertEqual(got["tree_diagnostics"]["warnings"][0]["stage"], "children")

    def test_unreadable_name_or_id_marks_identity_incomplete(self):
        kid = FakeElement(name="x", automation_id="a")
        kid._fail.add("automation_id")
        root = FakeElement(children=[kid])
        got = self.read(root)
        self.assertFalse(got["identity_complete"])
        self.assertIsNotNone(got["elements"][0]["name"] if got["elements"] else None)

    def test_anonymous_nodes_are_retained_and_offscreen_counts_are_reported(self):
        root = FakeElement(children=[
            FakeElement(name=""),                       # still addressable by type
            FakeElement(name="hidden", offscreen=True),  # filtered
            FakeElement(name="shown"),
        ])
        got = self.read(root)
        self.assertEqual(got["tree_diagnostics"]["filtered_anonymous"], 0)
        self.assertEqual(got["tree_diagnostics"]["filtered_offscreen"], 1)
        self.assertEqual([e["name"] for e in got["elements"]], ["", "shown"])

    def test_limit_reached_is_reported(self):
        kids = [FakeElement(name=f"n{i}") for i in range(10)]
        got = self.read(FakeElement(children=kids), max_elements=3)
        self.assertEqual(len(got["elements"]), 3)
        self.assertTrue(got["limit_reached"])

    def test_warning_list_is_capped(self):
        kids = [FakeElement(name="", children=[], fail={"children"}) for _ in range(80)]
        got = self.read(FakeElement(children=kids), max_elements=10000)
        self.assertLessEqual(len(got["tree_diagnostics"]["warnings"]), 50)
        self.assertTrue(got["tree_diagnostics"]["warnings_truncated"])

    def test_legacy_read_keeps_its_pair(self):
        root = FakeElement(children=[FakeElement(name="HIT-ME")])
        with mock.patch.object(tree, "ControlFromHandle", return_value=root):
            elements, timed_out = tree.read(1234)
        self.assertEqual(elements[0]["name"], "HIT-ME")
        self.assertFalse(timed_out)

    def test_native_hwnd_failure_is_a_warning_not_an_id(self):
        kid = FakeElement(name="HIT-ME", fail={"NativeWindowHandle"})
        root = FakeElement(children=[kid])
        got = self.read(root)
        self.assertIsNone(got["elements"][0]["native_hwnd"])
        self.assertIn("native", " ".join(w["stage"] for w in got["tree_diagnostics"]["warnings"]))

    def test_unreadable_name_or_id_marks_identity_incomplete(self):
        kid = FakeElement(name="x", automation_id="a", fail={"AutomationId"})
        root = FakeElement(children=[kid])
        got = self.read(root)
        self.assertFalse(got["identity_complete"])

    def test_describe_public_signature_still_works(self):
        got = tree.describe(FakeElement(name="x", automation_id="a", native=9), 2)
        self.assertEqual(got["name"], "x")
        self.assertEqual(got["nth"], 2)
        self.assertEqual(got["native_hwnd"], 9)
        self.assertIn("_el", got)


if __name__ == "__main__":
    unittest.main()

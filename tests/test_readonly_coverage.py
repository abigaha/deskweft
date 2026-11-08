"""Reviewed UIA getters work without granting permission for UI actions.

Real dependency wrappers run against plain fake COM providers. No UIA session,
desktop input, application process or real window is used.
"""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from windows_mcp.uia import patterns

from deskweft import act


# Literal wrapper/member/COM-field fixtures, checked against windows-mcp 0.8.8.
# These include zero, False and empty strings: all are successful query values.
SCALAR_READS = (
    ("AnnotationPattern", "AnnotationTypeId", "CurrentAnnotationTypeId", 0),
    ("AnnotationPattern", "AnnotationTypeName", "CurrentAnnotationTypeName", "comment"),
    ("AnnotationPattern", "Author", "CurrentAuthor", "writer"),
    ("AnnotationPattern", "DateTime", "CurrentDateTime", "2026-11-08"),
    ("DockPattern", "DockPosition", "CurrentDockPosition", 0),
    ("DragPattern", "DropEffect", "CurrentDropEffect", "move"),
    ("DragPattern", "IsGrabbed", "CurrentIsGrabbed", False),
    ("DropTargetPattern", "DropTargetEffect", "CurrentDropTargetEffect", "copy"),
    ("ExpandCollapsePattern", "ExpandCollapseState", "CurrentExpandCollapseState", 0),
    ("GridItemPattern", "Column", "CurrentColumn", 0),
    ("GridItemPattern", "ColumnSpan", "CurrentColumnSpan", 1),
    ("GridItemPattern", "Row", "CurrentRow", 0),
    ("GridItemPattern", "RowSpan", "CurrentRowSpan", 1),
    ("GridPattern", "ColumnCount", "CurrentColumnCount", 3),
    ("GridPattern", "RowCount", "CurrentRowCount", 7),
    ("LegacyIAccessiblePattern", "ChildId", "CurrentChildId", 0),
    ("LegacyIAccessiblePattern", "DefaultAction", "CurrentDefaultAction", "press"),
    ("LegacyIAccessiblePattern", "Description", "CurrentDescription", ""),
    ("LegacyIAccessiblePattern", "Help", "CurrentHelp", "help text"),
    ("LegacyIAccessiblePattern", "KeyboardShortcut", "CurrentKeyboardShortcut", "Alt+O"),
    ("LegacyIAccessiblePattern", "Name", "CurrentName", ""),
    ("LegacyIAccessiblePattern", "Role", "CurrentRole", 42),
    ("LegacyIAccessiblePattern", "State", "CurrentState", 0),
    ("LegacyIAccessiblePattern", "Value", "CurrentValue", ""),
    ("MultipleViewPattern", "CurrentView", "CurrentCurrentView", 0),
    ("SpreadsheetItemPattern", "Formula", "CurrentFormula", "=A1+1"),
    ("StylesPattern", "ExtendedProperties", "CurrentExtendedProperties", ""),
    ("StylesPattern", "FillColor", "CurrentFillColor", 0),
    ("StylesPattern", "FillPatternColor", "CurrentFillPatternColor", 0),
    ("StylesPattern", "Shape", "CurrentShape", "rectangle"),
    ("StylesPattern", "StyleId", "CurrentStyleId", 0),
    ("StylesPattern", "StyleName", "CurrentStyleName", "Normal"),
    ("TablePattern", "RowOrColumnMajor", "CurrentRowOrColumnMajor", 0),
    ("TogglePattern", "ToggleState", "CurrentToggleState", 0),
    ("TransformPattern", "CanMove", "CurrentCanMove", False),
    ("TransformPattern", "CanResize", "CurrentCanResize", False),
    ("TransformPattern", "CanRotate", "CurrentCanRotate", False),
    ("TransformPattern2", "CanZoom", "CurrentCanZoom", False),
    ("TransformPattern2", "ZoomLevel", "CurrentZoomLevel", 100.0),
    ("TransformPattern2", "ZoomMaximum", "CurrentZoomMaximum", 500.0),
    ("TransformPattern2", "ZoomMinimum", "CurrentZoomMinimum", 10.0),
    ("WindowPattern", "CanMaximize", "CurrentCanMaximize", False),
    ("WindowPattern", "CanMinimize", "CurrentCanMinimize", False),
    ("WindowPattern", "IsModal", "CurrentIsModal", False),
    ("WindowPattern", "IsTopmost", "CurrentIsTopmost", False),
    ("WindowPattern", "WindowInteractionState", "CurrentWindowInteractionState", 0),
    ("WindowPattern", "WindowVisualState", "CurrentWindowVisualState", 0),
)


class TestReadOnlyCoverage(unittest.TestCase):
    def setUp(self):
        for name, value in (("foreground", 123), ("title", "Fake window")):
            patch = mock.patch.object(act.win32, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def invoke(self, pattern_name, member, provider):
        wrapper = getattr(patterns, pattern_name)(provider)
        root = SimpleNamespace(**{"Get" + pattern_name: lambda: wrapper})
        with mock.patch.object(act, "ControlFromHandle", return_value=root):
            return act.invoke_pattern(1, pattern_name, "", member,
                                      allow_foreground=False)

    def test_verified_scalar_getters_read_without_foreground_permission(self):
        for pattern_name, member, com_field, expected in SCALAR_READS:
            with self.subTest(pattern=pattern_name, member=member):
                result = self.invoke(pattern_name, member,
                                     SimpleNamespace(**{com_field: expected}))
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["result"], expected)
                self.assertIs(type(result["result"]), type(expected))
                self.assertTrue(result["call_completed"])
                self.assertFalse(result["foreground_changed"])

    def test_legacy_selection_query_projects_an_empty_selection(self):
        provider = SimpleNamespace(GetCurrentSelection=lambda: None)
        result = self.invoke("LegacyIAccessiblePattern", "GetSelection", provider)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"], [])
        self.assertFalse(result["result_truncated"])

    def test_a_read_error_is_reported_without_retrying_the_getter(self):
        class FailingProvider:
            reads = 0

            @property
            def CurrentName(self):
                self.reads += 1
                raise OSError("read refused")

        provider = FailingProvider()
        result = self.invoke("LegacyIAccessiblePattern", "Name", provider)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider error")
        self.assertIn("OSError: read refused", result["detail"])
        self.assertEqual(result["execution_state"], "unknown")
        self.assertFalse(result["retry_safe"])
        self.assertEqual(provider.reads, 1)

    def test_writes_and_unreviewed_get_members_never_reach_the_provider(self):
        for pattern_name, member, args in (
            ("LegacyIAccessiblePattern", "SetValue", ["new value"]),
            ("LegacyIAccessiblePattern", "DoDefaultAction", []),
            ("LegacyIAccessiblePattern", "Select", [1]),
            ("WindowPattern", "Close", []),
            ("WindowPattern", "SetWindowVisualState", [2]),
            ("TogglePattern", "Toggle", []),
            ("ExpandCollapsePattern", "Expand", []),
            ("DockPattern", "SetDockPosition", [1]),
            ("MultipleViewPattern", "SetCurrentView", [1]),
            ("TransformPattern", "Move", [10, 10]),
            ("TransformPattern", "Resize", [100, 100]),
            ("TransformPattern", "Rotate", [90]),
            ("TransformPattern2", "Zoom", [120]),
            ("LegacyIAccessiblePattern", "GetIAccessible", []),
            ("LegacyIAccessiblePattern", "GetUnreviewedMember", []),
        ):
            with self.subTest(pattern=pattern_name, member=member), \
                 mock.patch.object(act, "ControlFromHandle") as root, \
                 mock.patch.object(act.tree, "pattern_detailed") as get:
                result = act.invoke_pattern(1, pattern_name, "", member, args,
                                            allow_foreground=False)
                self.assertTrue(result.get("needs_permission"), result)
                self.assertEqual(result["execution_state"], "not_started")
                root.assert_not_called()
                get.assert_not_called()

    def test_new_readonly_properties_reject_arguments_before_the_provider(self):
        with mock.patch.object(act, "ControlFromHandle") as root, \
             mock.patch.object(act.tree, "pattern_detailed") as get:
            result = act.invoke_pattern(1, "LegacyIAccessiblePattern", "", "Name", [1])
        self.assertEqual(result["reason"], "invalid arguments")
        root.assert_not_called()
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()

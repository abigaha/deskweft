"""Exercise native-only see without starting a worker or touching the desktop."""

import unittest
from unittest import mock

from deskweft import tree, uia_worker, win32


class TestNativeObservation(unittest.TestCase):
    def setUp(self):
        self.see = uia_worker._make_dispatch()["see"]
        self.is_window = self.enterContext(mock.patch.object(
            win32.user32, "IsWindow", return_value=True))
        self.title = self.enterContext(mock.patch.object(win32, "title", return_value="Title"))
        self.class_name = self.enterContext(mock.patch.object(
            win32, "class_name", return_value="Class"))
        self.grab = self.enterContext(mock.patch.object(
            win32, "grab", side_effect=AssertionError("unexpected screenshot")))
        self.read_tree = self.enterContext(mock.patch.object(
            tree, "read_detailed", side_effect=AssertionError("unexpected UIA tree read")))
        self.enum = self.enterContext(mock.patch.object(win32.user32, "EnumChildWindows"))
        self.rect = self.enterContext(mock.patch.object(win32.user32, "GetWindowRect"))

    def simulate_children(self, count):
        visited = []

        def enumerate_children(hwnd, callback, data):
            for child in range(10, 10 + count):
                visited.append(child)
                if not callback(child, data):
                    return 0
            return 1

        self.enum.side_effect = enumerate_children
        return visited

    def test_native_only_returns_only_native_metadata_and_stops_after_probe(self):
        for count, expected_visits in ((0, []), (2, [10, 11]), (6, [10, 11, 12])):
            with self.subTest(count=count):
                self.enum.reset_mock()
                visited = self.simulate_children(count)
                result = self.see(1, max_elements=2, native_only=True)
                self.assertEqual(result, {"meta": {
                    "ok": True, "hwnd": 1, "title": "Title", "class": "Class",
                    "native_only": True,
                    "native_children": [
                        {"hwnd": child, "class": "Class", "text": "Title", "rect": [0, 0, 0, 0]}
                        for child in expected_visits[:2]
                    ],
                    "native_children_truncated": count > 2,
                }, "png": None})
                self.enum.assert_called_once_with(1, mock.ANY, 0)
                self.assertEqual(visited, expected_visits)
        self.grab.assert_not_called()
        self.read_tree.assert_not_called()

    def assert_no_observation(self):
        for operation in (self.title, self.class_name, self.grab, self.read_tree,
                          self.enum, self.rect):
            operation.assert_not_called()

    def test_invalid_arguments_do_not_touch_win32_or_uia(self):
        for invalid in ({"with_tree": True}, {"native_only": 1}, {"native_only": "true"},
                        {"with_tree": 1}, {"hwnd": True}, {"hwnd": 0}, {"hwnd": -1},
                        {"hwnd": 0xFFFF}, {"hwnd": 0x10000000}, {"hwnd": "1"},
                        {"timeout_ms": 0}, {"timeout_ms": 30001}, {"timeout_ms": True},
                        {"max_elements": 0}, {"max_elements": 10001}, {"max_elements": True}):
            with self.subTest(invalid=invalid):
                result = self.see(**({"hwnd": 1, "native_only": True} | invalid))
                self.assertEqual(result["reason"], "invalid arguments")
                self.assertEqual(result["execution_state"], "not_started")
        self.is_window.assert_not_called()
        self.assert_no_observation()

    def test_gone_window_is_not_observed(self):
        self.is_window.return_value = False
        result = self.see(1, native_only=True)
        self.assertEqual(result["reason"], "no such window")
        self.assertEqual(result["execution_state"], "not_started")
        self.is_window.assert_called_once_with(1)
        self.assert_no_observation()

    def test_children_without_limit_still_enumerates_all(self):
        visited = self.simulate_children(6)
        self.assertEqual([child["hwnd"] for child in win32.children(1)], list(range(10, 16)))
        self.assertEqual(visited, list(range(10, 16)))

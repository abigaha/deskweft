"""ItemContainer adapter: real VARIANTs, fake COM, no desktop interaction."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from fastmcp import Client
from windows_mcp.uia.patterns import ItemContainerPattern

from deskweft import items, server, uia_worker


class Element:
    CurrentName = "duplicate"
    CurrentAutomationId = ""
    CurrentControlType = 50007
    CurrentIsOffscreen = True

    def __init__(self, index):
        self.index = index

    def GetRuntimeId(self):
        return [42, self.index]


class Provider:
    def __init__(self, count=3):
        self.elements = [Element(i) for i in range(count)]
        self.calls = []

    def FindItemByProperty(self, previous, property_id, value):
        self.calls.append((previous, property_id, value.vt, value.value))
        index = 0 if previous is None else previous.index + 1
        return self.elements[index] if index < len(self.elements) else None


class TestItems(unittest.TestCase):
    def setUp(self):
        for obj, name, value in ((items.act.win32, "foreground", 7),
                                 (items.act.win32, "title", "Test")):
            patch = mock.patch.object(obj, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def query(self, provider=None, **kwargs):
        self.provider = provider or Provider()
        root = SimpleNamespace(GetItemContainerPattern=lambda: ItemContainerPattern(self.provider))
        with mock.patch.object(items, "ControlFromHandle", return_value=root):
            return items.find_items(1, **kwargs)

    def test_null_first_then_real_element_references_and_explicit_end(self):
        result = self.query()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["complete"])
        self.assertTrue(result["reached_end"])
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_start_index"])
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual([v["index"] for v in result["items"]], [0, 1, 2])
        self.assertIsNone(self.provider.calls[0][0])
        self.assertIs(self.provider.calls[1][0], self.provider.elements[0])
        self.assertEqual(self.provider.calls[0][2:], (0, None))  # VT_EMPTY
        self.assertFalse(result["foreground_changed"])

    def test_page_limit_looks_ahead_and_rescan_offset_keeps_duplicate_names(self):
        first = self.query(max_items=2)
        self.assertFalse(first["complete"])
        self.assertFalse(first["reached_end"])
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_start_index"], 2)
        self.assertEqual(len(self.provider.calls), 3)
        last = self.query(start_index=2, max_items=2)
        self.assertTrue(last["reached_end"])
        self.assertFalse(last["complete"])  # a final page alone is not a full list
        self.assertEqual(last["items"][0]["index"], 2)

    def test_empty_and_exact_limit_prove_end_with_null(self):
        for count in (0, 2):
            result = self.query(Provider(count), max_items=2)
            self.assertTrue(result["complete"], result)
            self.assertEqual(len(result["items"]), count)

    def test_query_values_use_the_correct_variant_type(self):
        for value, vt in ((False, 11), (0, 3), (-5, 3), (1.5, 5), ("", 8)):
            with self.subTest(value=value):
                self.query(property_id=30005, value=value)
                self.assertEqual(self.provider.calls[0][2:], (vt, value))

    def test_invalid_inputs_never_touch_the_provider(self):
        invalid = ({"property_id": True}, {"property_id": -1},
                   {"property_id": 0, "value": "ignored"},
                   {"property_id": 30005, "value": None},
                   {"property_id": 30005, "value": {}},
                   {"property_id": 30005, "value": float("nan")},
                   {"property_id": 30005, "value": 2**40},
                   {"start_index": -1}, {"start_index": True},
                   {"max_items": 0}, {"max_items": 101},
                   {"timeout_ms": 0}, {"target": {"rect": [1, 2, 3, 4]}})
        for arguments in invalid:
            with self.subTest(arguments=arguments), mock.patch.object(items, "ControlFromHandle") as root:
                result = items.find_items(1, **arguments)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["execution_state"], "not_started")
                root.assert_not_called()

    def test_cycle_is_a_partial_failure_not_success_or_name_deduplication(self):
        provider = Provider()
        provider.elements[2] = provider.elements[0]
        result = self.query(provider)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider cycle")
        self.assertEqual(len(result["items"]), 2)
        self.assertFalse(result["complete"])

    def test_provider_error_retains_partial_items_without_retry(self):
        provider = Provider()
        original = provider.FindItemByProperty
        def fail(previous, property_id, value):
            if previous is not None:
                raise OSError("stale element")
            return original(previous, property_id, value)
        provider.FindItemByProperty = fail
        result = self.query(provider)
        self.assertEqual(result["reason"], "provider error")
        self.assertEqual(len(result["items"]), 1)
        self.assertFalse(result["retry_safe"])
        self.assertEqual(result["execution_state"], "unknown")

    def test_missing_runtime_id_then_recovered_id_still_detects_a_cycle(self):
        class ChangingIdentity(Element):
            reads = 0
            def GetRuntimeId(self):
                self.reads += 1
                if self.reads == 1:
                    raise OSError("identity temporarily unavailable")
                return super().GetRuntimeId()
        provider = Provider()
        repeated = ChangingIdentity(0)
        provider.elements = [repeated, Element(1), repeated]
        sequence = iter(provider.elements + [None])
        provider.FindItemByProperty = lambda *args: next(sequence)
        with mock.patch.object(items, "ControlsAreSame", side_effect=lambda a, b: a.Element is b.Element):
            result = self.query(provider)
        self.assertEqual(result.get("reason"), "provider cycle", result)
        self.assertEqual(len(result["items"]), 2)

    def test_runtime_id_fallback_can_complete_without_inventing_an_id(self):
        provider = Provider(2)
        for item in provider.elements:
            item.GetRuntimeId = lambda: None
        with mock.patch.object(items, "ControlsAreSame", side_effect=lambda a, b: a.Element is b.Element):
            result = self.query(provider)
        self.assertTrue(result["complete"], result)
        self.assertIsNone(result["items"][0]["runtime_id"])

    def test_failed_identity_fallback_retains_partial_without_claiming_end(self):
        provider = Provider(2)
        provider.elements[1].GetRuntimeId = lambda: None
        with mock.patch.object(items, "ControlsAreSame", side_effect=OSError("comparison failed")):
            result = self.query(provider)
        self.assertEqual(result["reason"], "provider error")
        self.assertEqual(len(result["items"]), 1)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["has_more"])

    def test_cycle_in_skipped_prefix_is_refused(self):
        provider = Provider()
        sequence = iter([provider.elements[0], provider.elements[0], None])
        provider.FindItemByProperty = lambda *args: next(sequence)
        result = self.query(provider, start_index=2)
        self.assertEqual(result["reason"], "provider cycle")
        self.assertEqual(result["items"], [])

    def test_lookahead_failure_does_not_invent_end_or_more_results(self):
        provider = Provider(1)
        original = provider.FindItemByProperty
        def fail(previous, *args):
            if previous is not None:
                raise OSError("lookahead failed")
            return original(previous, *args)
        provider.FindItemByProperty = fail
        result = self.query(provider, max_items=1)
        self.assertEqual(result["reason"], "provider error")
        self.assertEqual(len(result["items"]), 1)
        self.assertIsNone(result["has_more"])
        self.assertFalse(result["reached_end"])

    def test_soft_deadline_keeps_partial_result_without_retry(self):
        provider = Provider(2)
        clock = [0.0]
        original = provider.FindItemByProperty
        def slow(*args):
            item = original(*args)
            clock[0] = 1.0
            return item
        provider.FindItemByProperty = slow
        with mock.patch.object(items.time, "perf_counter", side_effect=lambda: clock[0]):
            result = self.query(provider, timeout_ms=100)
        self.assertEqual(result["reason"], "query budget exhausted")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(provider.calls), 1)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["has_more"])

    def test_unreadable_virtualized_metadata_is_explicit(self):
        class Virtual(Element):
            @property
            def CurrentAutomationId(self):
                raise OSError("not realized")
        provider = Provider(1)
        provider.elements = [Virtual(0)]
        result = self.query(provider)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["reached_end"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["metadata_complete"])
        self.assertIsNone(result["items"][0]["automation_id"])
        self.assertIn("automation_id", result["items"][0]["read_errors"])

    def test_text_limit_does_not_masquerade_as_a_complete_result(self):
        provider = Provider(2)
        provider.elements[0].CurrentName = "x" * 7000
        result = self.query(provider)
        self.assertTrue(result["result_truncated"])
        self.assertFalse(result["complete"])
        self.assertLessEqual(len(result["items"][0]["name"]), 6000)

    def test_ambiguous_target_and_unknown_pattern_are_not_empty_lists(self):
        with mock.patch.object(items.tree, "read_detailed", return_value={}), \
             mock.patch.object(items.tree, "resolve", return_value={
                 "ok": False, "reason": "ambiguous target", "detail": "two"}):
            result = items.find_items(1, target="list")
        self.assertEqual(result["reason"], "ambiguous target")
        with mock.patch.object(items.tree, "pattern_detailed", return_value={
            "ok": False, "reason": "pattern unavailable", "detail": "unknown", "cause_unknown": True}):
            result = self.query()
        self.assertFalse(result["ok"])
        self.assertTrue(result["cause_unknown"])

    def test_mcp_schema_and_worker_forwarding(self):
        async def call(arguments):
            async with Client(server.mcp) as client:
                return await client.call_tool("find_items", arguments)
        with mock.patch.object(server.uia_worker, "call", return_value={"ok": True}) as worker:
            asyncio.run(call({"hwnd": 1, "property_id": 30079, "value": False,
                              "start_index": 2, "max_items": 3, "timeout_ms": 4000}))
            action, parameters, timeout = worker.call_args.args
            self.assertEqual((action, timeout), ("find_items", 4000))
            self.assertIs(parameters["value"], False)
            self.assertEqual(parameters["start_index"], 2)
            for arguments in ({"hwnd": True}, {"hwnd": 1, "max_items": "2"}):
                with self.assertRaises(Exception):
                    asyncio.run(call(arguments))
        self.assertIs(uia_worker._make_dispatch()["find_items"], items.find_items)


if __name__ == "__main__":
    unittest.main()

"""server.py: 16 tools, strict schemas, every desktop call through the worker.

The MCP surface is exercised in-process; nothing opens a window or a socket.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock

from fastmcp import Client

from deskweft import server


def tool_names():
    return sorted(tool.name for tool in asyncio.run(list_tools()))


async def list_tools():
    async with Client(server.mcp) as client:
        return await client.list_tools()


class TestSurface(unittest.TestCase):
    def test_exactly_eighteen_tools(self):
        names = tool_names()
        self.assertEqual(len(names), 18, names)

    def test_the_expected_names(self):
        names = set(tool_names())
        self.assertEqual(names, {
            "open_app", "reveal", "windows", "see", "click", "type_text", "key",
            "scroll", "app_info", "invoke_pattern", "find_items", "post_message", "recall",
            "remember", "approve", "confirm_proven", "forget", "private_desktop",
        })

    def test_new_signatures_match_the_contract(self):
        tools = {tool.name: tool for tool in asyncio.run(list_tools())}
        props = tools["invoke_pattern"].inputSchema["properties"]
        self.assertEqual(list(props), ["hwnd", "pattern", "target", "method", "args",
                                       "allow_foreground", "timeout_ms"])
        props = tools["post_message"].inputSchema["properties"]
        self.assertEqual(list(props), ["hwnd", "msg", "wparam", "lparam", "allow_unsafe",
                                       "allow_foreground", "wait", "timeout_ms", "text",
                                       "max_chars"])
        props = tools["remember"].inputSchema["properties"]
        self.assertEqual(list(props), ["app", "version", "plan_id", "summary", "cost",
                                       "body", "uses_foreground", "overwrite"])
        props = tools["approve"].inputSchema["properties"]
        self.assertEqual(list(props), ["app", "version", "plan_id", "expected_revision",
                                       "reviewed"])

    def test_nullable_version_is_typed_nullable(self):
        tools = {tool.name: tool for tool in asyncio.run(list_tools())}
        schema = tools["recall"].inputSchema
        self.assertEqual(list(schema["properties"]),
                         ["query", "max_body_chars", "plan_id", "body_offset"])
        # version is explicit (so an unknown version is a decision, not an
        # omission) and accepts null, which is how an unversioned record is made.
        version = tools["remember"].inputSchema["properties"]["version"]
        self.assertIn("null", json.dumps(version))


class TestStrictArguments(unittest.TestCase):
    """Wrong JSON types must be rejected before the tool body runs."""

    def call(self, name, arguments):
        async def go():
            async with Client(server.mcp) as client:
                return await client.call_tool(name, arguments)
        return asyncio.run(go())

    def test_a_bool_is_not_an_integer(self):
        with mock.patch.object(server.win32, "title") as title:
            with self.assertRaises(Exception):
                self.call("see", {"hwnd": True})
            title.assert_not_called()

    def test_a_string_is_not_an_integer(self):
        with mock.patch.object(server.win32, "title") as title:
            with self.assertRaises(Exception):
                self.call("see", {"hwnd": "1234"})
            title.assert_not_called()

    def test_a_string_is_not_permission(self):
        with mock.patch.object(server, "_worker_call") as call:
            with self.assertRaises(Exception):
                self.call("click", {"hwnd": 1, "allow_foreground": "true"})
            call.assert_not_called()

    def test_a_number_is_not_a_string(self):
        with mock.patch.object(server, "_worker_call") as call:
            with self.assertRaises(Exception):
                self.call("recall", {"query": 5})
            call.assert_not_called()


class TestWorkerRouting(unittest.TestCase):
    """No HTTP-thread code may reach UIA directly any more."""

    def run_tool(self, name, **kwargs):
        return getattr(server, name)(**kwargs)

    def test_see_goes_through_the_worker(self):
        payload = {"ok": True, "meta": {"ok": True, "hwnd": 5, "title": "T"},
                   "png": None}
        with mock.patch.object(server, "_worker_call", return_value=payload) as call:
            result = self.run_tool("see", hwnd=5, with_tree=True)
        call.assert_called_once()
        self.assertEqual(call.call_args.args[0], "see")
        self.assertIsInstance(result, list)
        self.assertEqual(json.loads(result[0].text)["hwnd"], 5)

    def test_see_returns_text_then_image(self):
        payload = {"ok": True, "meta": {"ok": True, "hwnd": 5}, "png": b"\x89PNG"}
        with mock.patch.object(server, "_worker_call", return_value=payload):
            result = self.run_tool("see", hwnd=5)
        self.assertEqual(len(result), 2)
        self.assertTrue(type(result[1]).__name__ == "Image")

    def test_a_successful_see_still_reports_the_foreground_sample(self):
        """see is a window tool: the shared sample must reach the caller even
        when the result is content blocks rather than a plain dict."""
        payload = {"ok": True, "meta": {"ok": True, "hwnd": 5}, "png": None,
                   "foreground_before": 11, "foreground_after": 11,
                   "foreground_changed": False}
        with mock.patch.object(server, "_worker_call", return_value=payload):
            result = self.run_tool("see", hwnd=5)
        meta = json.loads(result[0].text)
        self.assertEqual(meta["foreground_before"], 11)
        self.assertIn("foreground_changed", meta)

    def test_a_failed_see_is_not_reported_as_an_image(self):
        payload = {"ok": False, "reason": "desktop call timed out",
                   "detail": "discarded", "execution_state": "unknown"}
        with mock.patch.object(server, "_worker_call", return_value=payload):
            result = self.run_tool("see", hwnd=5)
        self.assertEqual(len(result), 1)
        self.assertFalse(json.loads(result[0].text)["ok"])

    def test_click_sends_only_plain_parameters(self):
        with mock.patch.object(server, "_worker_call",
                              return_value={"ok": True}) as call:
            self.run_tool("click", hwnd=5, target="OK", allow_foreground=True)
        self.assertEqual(call.call_args.args[0], "click")
        self.assertEqual(call.call_args.args[1],
                         {"hwnd": 5, "target": "OK", "allow_foreground": True})

    def test_invoke_pattern_passes_its_own_budget(self):
        with mock.patch.object(server, "_worker_call",
                              return_value={"ok": True}) as call:
            self.run_tool("invoke_pattern", hwnd=5, pattern="ValuePattern", target="",
                          method="Value", args=None, allow_foreground=False,
                          timeout_ms=1234)
        self.assertEqual(call.call_args.args[2], 1234)

    def test_memory_tools_do_not_touch_the_worker(self):
        with mock.patch.object(server.memory, "recall", return_value={"ok": True}) as recall, \
             mock.patch.object(server, "_worker_call") as call:
            self.run_tool("recall", query="qq")
        recall.assert_called_once()
        call.assert_not_called()

    def test_app_info_and_post_message_are_direct(self):
        with mock.patch.object(server.appinfo, "app_info",
                              return_value={"ok": True}) as info:
            self.run_tool("app_info", hwnd=5)
        info.assert_called_once_with(5)
        with mock.patch.object(server.win32, "post_message",
                              return_value={"ok": True}) as post:
            self.run_tool("post_message", hwnd=5, msg=0)
        post.assert_called_once()

    def test_open_app_rejects_a_non_numeric_settle(self):
        """A string settle reaches `time.time() + settle` and raises TypeError,
        which surfaces as a server error instead of an argument error."""
        with mock.patch.object(server, "_launch") as launch:
            with self.assertRaises(Exception):
                self.call("open_app", {"command": "x.exe", "settle": "abc"})
            launch.assert_not_called()

    def test_open_app_keeps_the_foreground_sample(self):
        with mock.patch.object(server, "_launch",
                               return_value={"ok": True, "hidden_windows": []}):
            with mock.patch.object(server.win32, "foreground", return_value=7):
                result = self.run_tool("open_app", command="x.exe")
        self.assertIn("foreground_before", result)

    def test_foreground_fields_are_added_to_a_window_tool(self):
        # Mock the worker, not _worker_call: adding the foreground sample to
        # every window result is exactly what _worker_call exists to do.
        with mock.patch.object(server.uia_worker, "call",
                               return_value={"ok": False, "reason": "tree incomplete"}):
            result = self.run_tool("click", hwnd=5, target="x")
        self.assertIn("foreground_before", result)
        self.assertIn("foreground_changed", result)

    def test_worker_foreground_evidence_survives_server_wrapping(self):
        payload = {"ok": True, "foreground_before": 11, "foreground_after": 22,
                   "foreground_changed": True}
        with mock.patch.object(server.uia_worker, "call", return_value=payload), \
             mock.patch.object(server.win32, "foreground", return_value=22):
            result = server.click(5, target="OK", allow_foreground=True)
        self.assertEqual(result["foreground_before"], 11)
        self.assertEqual(result["foreground_after"], 22)
        self.assertTrue(result["foreground_changed"])

    def test_fallback_foreground_sample_spans_the_worker_call(self):
        foreground = [11]

        def worker(*args):
            foreground[0] = 22
            return {"ok": False, "reason": "desktop call timed out"}

        with mock.patch.object(server.uia_worker, "call", side_effect=worker), \
             mock.patch.object(server.win32, "foreground", side_effect=lambda: foreground[0]):
            result = server.click(5, target="OK", allow_foreground=True)
        self.assertEqual(result["foreground_before"], 11)
        self.assertEqual(result["foreground_after"], 22)
        self.assertTrue(result["foreground_changed"])


class TestLifespan(unittest.TestCase):
    def test_close_is_registered_for_shutdown(self):
        self.assertTrue(hasattr(server, "_shutdown"))
        with mock.patch.object(server.uia_worker, "close") as close:
            asyncio.run(server._shutdown())
        close.assert_called_once()


class TestInstructions(unittest.TestCase):
    def test_no_direct_advice_to_click_credential_accounts(self):
        text = server.INSTRUCTIONS
        self.assertNotIn("click them", text.lower())

    def test_no_claim_that_every_uia_call_steals_focus(self):
        text = server.INSTRUCTIONS.lower()
        self.assertNotIn("uia pattern calls do steal the foreground", text)
        self.assertNotIn("user has left", text)

    def test_no_default_background_legacy_claim(self):
        text = server.INSTRUCTIONS.lower()
        self.assertNotIn("default background legacy", text)

    def test_it_describes_the_real_gate(self):
        text = server.INSTRUCTIONS.lower()
        self.assertIn("needs_permission", text)


if __name__ == "__main__":
    unittest.main()

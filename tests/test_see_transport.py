"""see metadata must decode once regardless of screenshot availability."""

from __future__ import annotations

import base64
import json
import unittest
from unittest import mock

from fastmcp import Client

from deskweft import server


class TestSeeTransport(unittest.IsolatedAsyncioTestCase):
    async def call_see(self, payload):
        # Keep the real MCP serialization; replace only desktop execution and
        # its shutdown so these tests never start or stop a desktop worker.
        with mock.patch.object(server, "_worker_call", return_value=payload), \
             mock.patch.object(server.uia_worker, "close"):
            async with Client(server.mcp) as client:
                return await client.call_tool("see", {"hwnd": 5, "with_tree": True})

    async def test_no_image_metadata_decodes_once_to_an_object(self):
        result = await self.call_see({
            "ok": True,
            "meta": {"ok": True, "hwnd": 5, "image_unavailable": "synthetic blank frame",
                     "elements": [], "identity_complete": True},
            "png": None,
            "foreground_before": 11, "foreground_after": 22, "foreground_changed": True,
        })
        self.assertEqual([block.type for block in result.content], ["text"])
        self.assertEqual(json.loads(result.content[0].text), {
            "ok": True, "hwnd": 5, "image_unavailable": "synthetic blank frame",
            "elements": [], "identity_complete": True,
            "foreground_before": 11, "foreground_after": 22, "foreground_changed": True,
        })

    async def test_worker_error_decodes_once_and_keeps_diagnostics(self):
        result = await self.call_see({
            "ok": False, "reason": "desktop call timed out", "execution_state": "unknown",
            "effect_verified": False, "retry_safe": False,
            "foreground_before": 11, "foreground_after": 22, "foreground_changed": True,
        })
        self.assertEqual([block.type for block in result.content], ["text"])
        self.assertEqual(json.loads(result.content[0].text), {
            "ok": False, "reason": "desktop call timed out", "execution_state": "unknown",
            "effect_verified": False, "retry_safe": False,
            "foreground_before": 11, "foreground_after": 22, "foreground_changed": True,
        })

    async def test_invalid_worker_result_decodes_once_to_an_error_object(self):
        result = await self.call_see(None)
        self.assertEqual([block.type for block in result.content], ["text"])
        self.assertEqual(json.loads(result.content[0].text), {
            "ok": False, "reason": "worker result invalid",
        })

    async def test_image_follows_metadata_without_changing_its_shape(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
            "AQUBAScY42YAAAAASUVORK5CYII="
        )
        result = await self.call_see({
            "ok": True, "meta": {"ok": True, "hwnd": 5}, "png": png,
            "foreground_before": 11, "foreground_after": 11, "foreground_changed": False,
        })
        self.assertEqual([block.type for block in result.content], ["text", "image"])
        self.assertEqual(json.loads(result.content[0].text), {
            "ok": True, "hwnd": 5,
            "foreground_before": 11, "foreground_after": 11, "foreground_changed": False,
        })
        self.assertEqual(result.content[1].mime_type, "image/png")
        self.assertEqual(base64.b64decode(result.content[1].data), png)


if __name__ == "__main__":
    unittest.main()

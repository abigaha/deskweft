"""The README must describe the shipped surface, not the old one."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from deskweft import server

README = Path(__file__).resolve().parents[1] / "README.md"


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_documents_every_tool(self):
        async def names():
            async with server.mcp._lifespan_manager():  # noqa: SLF001 - tool registry only
                return [t.name for t in await server.mcp.list_tools()]

        tools = asyncio.run(names())
        missing = [name for name in tools if f"`{name}(" not in self.text
                   and f"`{name}()`" not in self.text]
        self.assertEqual(missing, [], f"README does not document: {missing}")

    def test_no_stale_claims(self):
        lowered = self.text.lower()
        self.assertNotIn("does take the foreground\n- `click", lowered)
        self.assertNotIn("capability sids\n\n`printwindow` returns `error_access_denied`",
                         lowered)

    def test_the_wrong_sid_classification_is_corrected(self):
        self.assertIn("S-1-15-3", self.text)
        self.assertIn("was wrong", self.text)

    def test_mentions_the_companion_skill(self):
        self.assertIn("skills/windows-app-automation/SKILL.md", self.text)

    def test_no_implied_automatic_authorization(self):
        lowered = self.text.lower()
        self.assertNotIn("user has left, so", lowered)
        self.assertNotIn("safe to click", lowered)


if __name__ == "__main__":
    unittest.main()

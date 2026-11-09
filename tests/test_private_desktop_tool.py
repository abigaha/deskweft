"""C6: the private desktop is reachable from MCP, and switching needs permission.

Two rules matter here:
  - showing or hiding a desktop changes what the user is looking at, so it is
    refused unless allow_foreground is set - exactly like reveal;
  - the tool never claims the screen moved: it reports the desktop that
    OpenInputDesktop answers with.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from deskweft import private_desktop, server


def tool_names():
    async def go():
        async with server.mcp._lifespan_manager():
            return [t.name for t in await server.mcp.list_tools()]
    return asyncio.run(go())


class TestDesktopTool(unittest.TestCase):
    def test_the_tool_is_registered(self):
        names = tool_names()
        self.assertIn("private_desktop", names)
        self.assertEqual(len(names), 18, names)

    def test_status_is_read_only(self):
        with mock.patch.object(server, "_desktop_session") as session:
            session.status.return_value = {"ok": True, "visible_desktop": "Default",
                                           "private_desktop": None}
            result = server.private_desktop("status")
        self.assertTrue(result["ok"], result)
        session.create.assert_not_called()
        session.show.assert_not_called()

    def test_showing_needs_permission(self):
        with mock.patch.object(server, "_desktop_session") as session:
            result = server.private_desktop("show")
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("needs_permission"))
        self.assertEqual(result["execution_state"], "not_started")
        session.show.assert_not_called()

    def test_hiding_needs_permission(self):
        with mock.patch.object(server, "_desktop_session") as session:
            result = server.private_desktop("hide")
        self.assertTrue(result.get("needs_permission"))
        session.hide.assert_not_called()

    def test_creating_does_not_switch(self):
        with mock.patch.object(server, "_desktop_session") as session:
            session.create.return_value = {"ok": True, "name": "x", "reused": False}
            session.status.return_value = {"ok": True, "visible_desktop": "Default"}
            result = server.private_desktop("create", name="x")
        self.assertTrue(result["ok"], result)
        session.create.assert_called_once_with("x")
        session.show.assert_not_called()

    def test_creating_without_a_name_generates_one(self):
        with mock.patch.object(server, "_desktop_session") as session:
            session.create.return_value = {"ok": True, "name": "gen", "reused": False}
            session.status.return_value = {"ok": True, "visible_desktop": "Default"}
            result = server.private_desktop("create")
        self.assertTrue(result["ok"], result)
        generated = session.create.call_args.args[0]
        self.assertTrue(generated.startswith("DeskWeft_"), generated)

    def test_showing_with_permission_switches_and_reports_the_real_desktop(self):
        with mock.patch.object(server, "_desktop_session") as session:
            session.show.return_value = {"ok": True, "visible_desktop": "x",
                                         "previous_desktop": "Default"}
            session.status.return_value = {"ok": True, "visible_desktop": "x"}
            result = server.private_desktop("show", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["visible_desktop"], "x")
        self.assertFalse(result["effect_verified"],
                         "switching the screen is not proof the user's work is intact")

    def test_an_unknown_action_is_refused(self):
        result = server.private_desktop("teleport")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid arguments")

    def test_closing_returns_to_the_previous_desktop(self):
        with mock.patch.object(server, "_desktop_session") as session:
            session.close.return_value = {"ok": True, "closed": True,
                                          "visible_desktop": "Default"}
            result = server.private_desktop("close", allow_foreground=True)
        self.assertTrue(result["ok"], result)
        session.close.assert_called_once()

    def test_every_result_carries_the_foreground_sample(self):
        with mock.patch.object(server, "_desktop_session") as session:
            session.status.return_value = {"ok": True, "visible_desktop": "Default"}
            result = server.private_desktop("status")
        self.assertIn("foreground_before", result)
        self.assertIn("foreground_changed", result)


if __name__ == "__main__":
    unittest.main()

"""The shipped skill: one file, self-contained, with every route the contract names."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "windows-app-automation" / "SKILL.md"


class TestSkillFile(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_frontmatter(self):
        self.assertTrue(self.text.startswith("---\n"))
        front = self.text.split("---\n")[1]
        self.assertIn("name: windows-app-automation", front)
        self.assertIn("description:", front)

    def test_covers_every_surface(self):
        for token in ("native_children", "UIA", "Electron", "UWP",
                      "自绘", "虚拟化", "API", "CLI"):
            self.assertIn(token, self.text, token)

    def test_untried_directions_survive(self):
        for token in ("--disable-gpu", "--disable-features",
                      "--force-renderer-accessibility", "未试方向"):
            self.assertIn(token, self.text, token)

    def test_untried_stays_labelled_untried(self):
        self.assertIn("未验证", self.text)
        # The three directions must not be reworded into proven fixes.
        self.assertNotIn("已验证：--disable-gpu", self.text)

    def test_the_eight_body_sections(self):
        for heading in ("目标", "环境与适用条件", "已验证步骤", "已尝试但失败",
                        "实测记录", "未解决", "未试方向", "更新记录"):
            self.assertIn(f"## {heading}", self.text, heading)

    def test_new_tool_names_are_the_real_ones(self):
        for name in ("app_info", "invoke_pattern", "post_message", "recall",
                     "remember", "approve", "confirm_proven"):
            self.assertIn(name, self.text, name)

    def test_it_warns_about_unknown_versions(self):
        self.assertIn("app@unversioned", self.text)
        self.assertIn("version=None", self.text)

    def test_it_separates_rank_from_permission(self):
        self.assertIn("reviewed/proven 不是本次业务操作授权", self.text)

    def test_it_distinguishes_completion_from_effect(self):
        self.assertIn("执行完成", self.text.replace("调用完成", "执行完成"))
        self.assertIn("effect", self.text.lower()) if "effect" in self.text.lower() else None
        self.assertIn("不自动重发", self.text)

    def test_historical_numbers_are_marked_historical(self):
        self.assertIn("不是本次测量", self.text)
        self.assertIn("132", self.text)
        self.assertIn("128", self.text)

    def test_no_duplicated_interface_contract(self):
        # The skill explains routes; signatures live in the handoff.
        self.assertNotIn("def invoke_pattern", self.text)
        self.assertNotIn("StrictInt", self.text)

    def test_it_does_not_promise_absent_tools(self):
        self.assertIn("工具尚未实现", self.text)


class TestSkillDiscovery(unittest.TestCase):
    def test_source_lives_inside_the_repository(self):
        self.assertTrue(SKILL.is_file())
        self.assertEqual(SKILL.parent.name, "windows-app-automation")

    def test_only_one_skill_file(self):
        files = list(SKILL.parent.rglob("*"))
        self.assertEqual([p for p in files if p.is_file()], [SKILL])


if __name__ == "__main__":
    unittest.main()

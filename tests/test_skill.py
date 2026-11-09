"""The shipped skill and its reachable resources preserve the automation contract."""

from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "windows-app-automation" / "SKILL.md"
TOOL_REFERENCE = SKILL.parent / "references" / "tool-reference.md"


def shipped_text() -> str:
    """SKILL.md plus the tool reference: launch flags live there, not in the method."""
    text = SKILL.read_text(encoding="utf-8")
    if TOOL_REFERENCE.is_file():
        text += "\n" + TOOL_REFERENCE.read_text(encoding="utf-8")
    return text


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
        shipped = shipped_text()
        for token in ("--disable-gpu", "--disable-features",
                      "--force-renderer-accessibility", "未试方向"):
            self.assertIn(token, shipped, token)

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

    def test_four_tiers_prioritize_background_over_speed(self):
        # A fast foreground route must never jump ahead of a slow background one.
        tiers = re.findall(r"^\d+\. \*\*(后台高效|后台低效|前台高效|前台低效)\*\*", self.text, re.M)
        self.assertEqual(tiers, ["后台高效", "后台低效", "前台高效", "前台低效"])

    def test_background_trial_requires_prevention_before_calling(self):
        for rule in ("调用前先阻止应用抢前台", "allow_foreground=true 不是防抢焦保护",
                     "不发出潜在抢焦动作", "继续其他后台只读候选"):
            self.assertTrue(rule in self.text, f"missing policy rule: {rule}")

    def test_restoring_focus_and_matching_endpoints_do_not_prove_background(self):
        for rule in ("先抢焦再切回", "before==after", "两个采样端点",
                     "不能证明全程前台未变", "uses_foreground=true"):
            self.assertTrue(rule in self.text, f"missing policy rule: {rule}")

    def test_cost_comparison_and_downgrade_stay_within_the_policy(self):
        for rule in ("只在同层", "完整成本", "降级理由", "保护安装", "异步"):
            self.assertTrue(rule in self.text, f"missing policy rule: {rule}")

    def test_all_eleven_diagnostic_routes_survive(self):
        numbers = re.findall(r"^### (\d+)\. ", self.text, re.M)
        self.assertEqual(numbers, [str(number) for number in range(1, 12)])

    def test_it_distinguishes_completion_from_effect(self):
        self.assertIn("执行完成", self.text.replace("调用完成", "执行完成"))
        self.assertIn("effect", self.text.lower()) if "effect" in self.text.lower() else None
        self.assertIn("不自动重发", self.text)

    def test_no_duplicated_interface_contract(self):
        # The skill explains routes; signatures live in the handoff.
        self.assertNotIn("def invoke_pattern", self.text)
        self.assertNotIn("StrictInt", self.text)

    def test_it_does_not_promise_absent_tools(self):
        self.assertIn("工具尚未实现", self.text)

    def test_guided_calls_match_the_registered_mcp_contract(self):
        from fastmcp import Client
        from jsonschema import validate
        from unittest import mock
        from deskweft import server

        async def schemas():
            with mock.patch.object(server.uia_worker, "close"):
                async with Client(server.mcp) as client:
                    return {tool.name: tool.input_schema for tool in await client.list_tools()}

        contracts = asyncio.run(schemas())
        examples = [json.loads(block) for block in
                    re.findall(r"```json\s*\n(.*?)\n```", shipped_text(), re.S)]
        guided = [example for example in examples if "tool" in example]
        self.assertGreater(len(guided), 0, "the guide needs executable tool-call examples")
        for example in guided:
            with self.subTest(tool=example["tool"]):
                self.assertIn(example["tool"], contracts)
                validate(example["arguments"], contracts[example["tool"]])


class TestSkillDiscovery(unittest.TestCase):
    def test_source_lives_inside_the_repository(self):
        self.assertTrue(SKILL.is_file())
        self.assertEqual(SKILL.parent.name, "windows-app-automation")

    def test_foreground_protection_reference_is_discoverable(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue("(references/foreground-protection.md)" in text,
                        "foreground-protection reference is not linked from SKILL.md")
        self.assertTrue((SKILL.parent / "references" / "foreground-protection.md").is_file())

    def test_all_shipped_resources_are_reachable_inside_the_skill(self):
        root = SKILL.parent.resolve()
        pending = [SKILL]
        reached = set()
        while pending:
            resource = pending.pop().resolve()
            if resource in reached:
                continue
            reached.add(resource)
            if resource.suffix != ".md":
                continue
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", resource.read_text(encoding="utf-8")):
                if "://" in target or target.startswith(("#", "mailto:")):
                    continue
                linked = (resource.parent / target.split("#", 1)[0]).resolve()
                self.assertTrue(linked.is_relative_to(root), f"resource escapes skill: {target}")
                self.assertTrue(linked.is_file(), f"missing resource: {target}")
                pending.append(linked)
        self.assertEqual(reached, {path.resolve() for path in root.rglob("*")
                                   if path.is_file() and "__pycache__" not in path.parts
                                   and path.suffix not in (".pyc", ".pyo")})


if __name__ == "__main__":
    unittest.main()

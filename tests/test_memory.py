"""memory.py: one record per app@version, strict schema, trust bits, continuation.

Temporary directories only - these tests never touch the real user memory root
or open a window.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import yaml

from deskweft import memory

QQ_BODY = """## 目标
读取当前窗口已暴露的命名控件
## 未解决
尚未证明能够读取虚拟化列表中未渲染的项目
"""


class MemoryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = mock.patch.object(memory, "memory_root", return_value=self.root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def write_plans(self, app="QQ", version="9.9.22", body=QQ_BODY, plan_id="B"):
        return memory.remember(
            app, version, plan_id, "summary", "cost", body, uses_foreground=False
        )


class TestKeyAndPath(MemoryCase):
    def test_make_key_casefolds_app_and_keeps_full_version(self):
        self.assertEqual(memory.make_key("QQ", "9.9.22"), "qq@9.9.22")
        self.assertEqual(memory.make_key(" qq ", None), "qq@unversioned")

    def test_record_path_is_digest_only(self):
        path = memory.record_path(self.root, "qq@9.9.22")
        self.assertEqual(path.parent, self.root / "playbooks")
        self.assertRegex(path.name, r"^[0-9a-f]{64}\.md$")
        self.assertNotIn("@", path.name)

    def test_chinese_and_traversal_names_do_not_collide_or_escape(self):
        keys = [
            memory.record_path(self.root, memory.make_key("QQ", "9.9.22")),
            memory.record_path(self.root, memory.make_key("QQ音乐", "9.9.22")),
            memory.record_path(self.root, memory.make_key("../etc", "9.9.22")),
        ]
        self.assertEqual(len(set(keys)), 3)
        for path in keys:
            self.assertEqual(path.parent, self.root / "playbooks")

    def test_root_follows_env_override(self):
        # memory_root is the unpatched function here: these tests patch the
        # module attribute, so call the closure kept at import time instead.
        real = memory._real_memory_root
        with mock.patch.dict(os.environ, {"WINMCP_MEMORY_DIR": str(self.root / "chosen"),
                                         "DESKWEFT_MEMORY_DIR": ""}):
            self.assertEqual(real(), self.root / "chosen")
        env = dict(os.environ)
        env.pop("WINMCP_MEMORY_DIR", None)
        env.pop("DESKWEFT_MEMORY_DIR", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(real(), Path(os.environ["LOCALAPPDATA"]) / "winmcp" / "memory")

    def test_new_memory_override_takes_priority_over_legacy_override(self):
        with mock.patch.dict(os.environ, {
            "DESKWEFT_MEMORY_DIR": str(self.root / "new"),
            "WINMCP_MEMORY_DIR": str(self.root / "legacy"),
        }):
            self.assertEqual(memory._real_memory_root(), self.root / "new")

    def test_bad_app_and_version_are_rejected(self):
        for app in ("", "  ", "a@b", "a/b", "a\\b", "a\x00b", "a\nb"):
            result = self.write_plans(app=app)
            self.assertFalse(result["ok"], app)
            self.assertEqual(result["reason"], "invalid app", app)
        for version in ("unversioned", "", "9.9/22", "9.9@22", "9\x01.9"):
            result = self.write_plans(version=version)
            self.assertFalse(result["ok"], version)
            self.assertEqual(result["reason"], "invalid version", version)

    def test_bad_plan_id_is_rejected(self):
        for plan_id in ("", "a" * 33, "a b", "../x", "a/b"):
            result = self.write_plans(plan_id=plan_id)
            self.assertFalse(result["ok"], plan_id)
            self.assertEqual(result["reason"], "invalid plan id", plan_id)


class TestSchema(MemoryCase):
    def read_file(self, app="QQ", version="9.9.22"):
        path = memory.record_path(self.root, memory.make_key(app, version))
        return path.read_text(encoding="utf-8")

    def test_round_trip_keeps_unicode_and_body_readable(self):
        result = self.write_plans(body="## 目标\n中文 body 🙂\n")
        self.assertTrue(result["ok"], result)
        text = self.read_file()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("中文 body 🙂", text)
        self.assertIn("qq@9.9.22", text)
        got = memory.recall("qq@9.9.22")
        self.assertEqual(got["matches"][0]["plans"][0]["body"], "## 目标\n中文 body 🙂\n")

    def test_bad_yaml_is_a_warning_on_scan_and_invalid_on_exact_read(self):
        path = memory.record_path(self.root, "qq@9.9.22")
        path.parent.mkdir(parents=True)
        path.write_text("---\nkey: [unclosed\n---\n", encoding="utf-8")
        scanned = memory.recall("qq")
        self.assertEqual(scanned["matches"], [])
        self.assertEqual(len(scanned["warnings"]), 1)
        self.assertEqual(scanned["warnings"][0]["file"], path.name)
        self.assertIn("yaml", scanned["warnings"][0]["reason"].casefold())
        exact = memory.recall("qq@9.9.22")
        self.assertFalse(exact["ok"])
        self.assertEqual(exact["reason"], "invalid record")

    def test_date_parsed_into_object_is_rejected(self):
        self.write_plans()
        # Take the real date from the record: the fixture is written with
        # today's date, so hard-coding one makes the test fail tomorrow.
        text = self.read_file()
        quoted = re.search(r"updated: '(\d{4}-\d{2}-\d{2})'", text)
        self.assertIsNotNone(quoted, text)
        plain = quoted.group(1)
        text = text.replace(f"updated: '{plain}'", f"updated: {plain}")
        self.assertIn(f"updated: {plain}", text)
        memory.record_path(self.root, "qq@9.9.22").write_text(text, encoding="utf-8")
        result = memory.recall("qq@9.9.22")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid record")

    def test_string_boolean_is_rejected(self):
        self.write_plans()
        text = self.read_file().replace("uses_foreground: false", "uses_foreground: 'false'")
        memory.record_path(self.root, "qq@9.9.22").write_text(text, encoding="utf-8")
        result = memory.recall("qq@9.9.22")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid record")

    def test_unknown_schema_is_rejected(self):
        self.write_plans()
        text = self.read_file().replace("schema: 1", "schema: 2")
        memory.record_path(self.root, "qq@9.9.22").write_text(text, encoding="utf-8")
        self.assertEqual(memory.recall("qq@9.9.22")["reason"], "invalid record")

    def test_duplicate_plan_id_is_rejected(self):
        self.write_plans(plan_id="B")
        text = self.read_file()
        data = yaml.safe_load(text.split("---\n", 2)[1])
        data["plans"].append(dict(data["plans"][0]))
        path = memory.record_path(self.root, "qq@9.9.22")
        path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n", encoding="utf-8")
        self.assertEqual(memory.recall("qq@9.9.22")["reason"], "invalid record")

    def test_content_key_must_match_path(self):
        self.write_plans()
        text = self.read_file().replace("key: qq@9.9.22", "key: qq@1.0")
        memory.record_path(self.root, "qq@9.9.22").write_text(text, encoding="utf-8")
        self.assertEqual(memory.recall("qq@9.9.22")["reason"], "invalid record")

    def test_missing_root_reads_as_empty(self):
        empty = self.root / "never-created"
        with mock.patch.object(memory, "memory_root", return_value=empty):
            result = memory.recall("")
        self.assertTrue(result["ok"])
        self.assertEqual(result["keys"], [])

    def test_remember_creates_playbooks_directory(self):
        self.write_plans()
        self.assertTrue((self.root / "playbooks").is_dir())


class TestUnversioned(MemoryCase):
    def test_unknown_version_stores_as_unversioned_and_is_recallable(self):
        result = self.write_plans(version=None)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["key"], "qq@unversioned")
        got = memory.recall("qq@unversioned")
        self.assertTrue(got["exact"])
        match = got["matches"][0]
        self.assertIsNone(match["version"])
        self.assertTrue(match["version_unknown"])
        self.assertEqual(match["plans"][0]["rank"], 0)

    def test_unversioned_never_takes_trust(self):
        self.write_plans(version=None)
        rev = memory.recall("qq@unversioned")["matches"][0]["plans"][0]["revision"]
        approved = memory.approve("QQ", None, "B", rev)
        self.assertFalse(approved["ok"])
        self.assertEqual(approved["reason"], "version unconfirmed")
        proven = memory.confirm_proven("QQ", None, "B", rev)
        self.assertEqual(proven["reason"], "version unconfirmed")
        self.assertEqual(memory.recall("qq@unversioned")["matches"][0]["plans"][0]["rank"], 0)

    def test_unversioned_record_with_true_trust_is_rejected(self):
        self.write_plans(version=None)
        path = memory.record_path(self.root, "qq@unversioned")
        text = path.read_text(encoding="utf-8").replace("reviewed: false", "reviewed: true")
        path.write_text(text, encoding="utf-8")
        self.assertEqual(memory.recall("qq@unversioned")["reason"], "invalid record")

    def test_unversioned_has_no_family_fallback(self):
        self.write_plans(version=None)
        self.write_plans(version="9.9.22")
        got = memory.recall("qq@unversioned")
        self.assertEqual([m["key"] for m in got["matches"]], ["qq@unversioned"])
        miss = memory.recall("qq@9.9.19")
        self.assertTrue(miss["ok"])
        self.assertFalse(miss["exact"])
        self.assertEqual([m["key"] for m in miss["matches"]], ["qq@9.9.22", "qq@unversioned"])
        self.assertTrue([m["version_unknown"] for m in miss["matches"] if m["key"] == "qq@unversioned"][0])

    def test_string_unversioned_is_not_a_version(self):
        self.assertFalse(self.write_plans(version="unversioned")["ok"])


class TestMatching(MemoryCase):
    def setUp(self):
        super().setUp()
        self.write_plans(app="QQ", version="9.9.22")
        self.write_plans(app="QQ", version="9.9.19")
        self.write_plans(app="QQMusic", version="1.0")
        self.write_plans(app="QQ音乐", version="1.0")

    def keys_for(self, query, **kwargs):
        result = memory.recall(query, **kwargs)
        self.assertTrue(result["ok"], result)
        return [m["key"] for m in result["matches"]]

    def test_empty_query_lists_keys_only(self):
        result = memory.recall("   ")
        self.assertEqual(result["matches"], [])
        self.assertFalse(result["exact"])
        self.assertEqual(len(result["keys"]), 4)

    def test_exact_key_hit(self):
        self.assertEqual(self.keys_for("qq@9.9.22"), ["qq@9.9.22"])
        self.assertTrue(memory.recall("qq@9.9.22")["exact"])

    def test_windows_path_and_exe_stem(self):
        self.assertEqual(self.keys_for(r"C:\Program Files\Tencent\QQ.exe"), ["qq@9.9.19", "qq@9.9.22"])
        self.assertEqual(self.keys_for("QQ.exe"), ["qq@9.9.19", "qq@9.9.22"])

    def test_family_fallback_stays_inside_the_app(self):
        self.assertEqual(self.keys_for("qq@1.0"), ["qq@9.9.19", "qq@9.9.22"])

    def test_substring_match(self):
        self.assertEqual(self.keys_for("music"), ["qqmusic@1.0"])
        self.assertIn("qq音乐@1.0", self.keys_for("qq音"))

    def test_miss_is_success(self):
        result = memory.recall("never-seen")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])
        self.assertFalse(result["exact"])

    def test_illegal_query(self):
        for query in ("@", "@9.9", "qq@"):
            result = memory.recall(query)
            self.assertFalse(result["ok"], query)
            self.assertEqual(result["reason"], "invalid query", query)

    def test_matches_sorted_by_key_and_plans_by_rank_then_id(self):
        memory.remember("QQ", "9.9.22", "A", "s", "c", "body a", uses_foreground=False)
        rev = {p["id"]: p["revision"] for p in memory.recall("qq@9.9.22")["matches"][0]["plans"]}
        memory.confirm_proven("QQ", "9.9.22", "A", rev["A"])
        plans = memory.recall("qq@9.9.22")["matches"][0]["plans"]
        self.assertEqual([p["id"] for p in plans], ["A", "B"])
        self.assertEqual([p["rank"] for p in plans], [2, 0])


class TestBudgetAndContinuation(MemoryCase):
    def test_whole_response_stays_inside_the_body_budget(self):
        long_unresolved = "## 未解决\n" + ("x" * 4000) + "\n"
        body = "## 目标\n" + ("y" * 5000) + "\n" + long_unresolved
        self.write_plans(body=body, plan_id="A")
        self.write_plans(body=body, plan_id="B")
        result = memory.recall("qq@9.9.22", max_body_chars=500)
        total = sum(len(p["body"]) for m in result["matches"] for p in m["plans"])
        total += sum(len(u["text"]) for m in result["matches"] for u in m["unresolved"])
        self.assertLessEqual(total, 500)
        self.assertTrue(result["truncated"])
        for match in result["matches"]:
            for plan in match["plans"]:
                self.assertTrue(plan["truncated"])
                self.assertIsNotNone(plan["next_body_offset"])

    def test_continuation_recovers_the_full_body(self):
        body = "".join(f"line {i}\n" for i in range(400))
        self.write_plans(body=body)
        first = memory.recall("qq@9.9.22", max_body_chars=200)["matches"][0]["plans"][0]
        pieces = [first["body"]]
        offset, revision = first["next_body_offset"], first["revision"]
        while offset is not None:
            piece = memory.recall("qq@9.9.22", plan_id="B", body_offset=offset,
                                  max_body_chars=200)["matches"][0]["plans"][0]
            self.assertEqual(piece["revision"], revision)
            pieces.append(piece["body"])
            offset = piece["next_body_offset"]
        self.assertEqual("".join(pieces), body)

    def test_continuation_requires_exact_key_and_existing_plan(self):
        self.write_plans()
        self.assertEqual(memory.recall("qq", plan_id="B")["reason"], "plan not found")
        self.assertEqual(memory.recall("qq@9.9.22", plan_id="Z")["reason"], "plan not found")

    def test_bad_offsets(self):
        self.write_plans()
        self.assertEqual(memory.recall("qq@9.9.22", body_offset=1)["reason"], "invalid offset")
        self.assertEqual(memory.recall("qq@9.9.22", plan_id="B", body_offset=-1)["reason"], "invalid offset")
        self.assertEqual(memory.recall("qq@9.9.22", plan_id="B", body_offset=True)["reason"], "invalid offset")
        total = len(QQ_BODY)
        end = memory.recall("qq@9.9.22", plan_id="B", body_offset=total)["matches"][0]["plans"][0]
        self.assertEqual(end["body"], "")
        self.assertIsNone(end["next_body_offset"])
        self.assertEqual(memory.recall("qq@9.9.22", plan_id="B", body_offset=total + 1)["reason"], "invalid offset")

    def test_offset_is_a_python_string_index_not_bytes(self):
        self.write_plans(body="中文🙂tail")
        # 中文 is 6 UTF-8 bytes but 2 characters; "🙂" is 4 bytes but 1 character.
        self.assertEqual(len("中文🙂tail".encode("utf-8")), 14)
        plan = memory.recall("qq@9.9.22", plan_id="B", body_offset=2)["matches"][0]["plans"][0]
        self.assertEqual(plan["body"], "🙂tail")
        self.assertEqual(plan["body_total_chars"], 7)

    def test_bad_budget(self):
        self.write_plans()
        for value in (0, 6001, True, "500"):
            self.assertFalse(memory.recall("qq", max_body_chars=value)["ok"], value)


class TestTrust(MemoryCase):
    def revision(self, plan_id="B", version="9.9.22"):
        plans = {p["id"]: p for p in memory.recall(f"qq@{version}")["matches"][0]["plans"]}
        return plans[plan_id]["revision"]

    def test_rank_covers_all_four_combinations(self):
        self.assertEqual((memory.rank(False, False), memory.rank(True, False),
                          memory.rank(False, True), memory.rank(True, True)), (0, 1, 2, 3))

    def test_approve_and_confirm_are_independent_and_revocable(self):
        self.write_plans()
        rev = self.revision()
        self.assertTrue(memory.approve("QQ", "9.9.22", "B", rev)["ok"])
        plan = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]
        self.assertEqual((plan["reviewed"], plan["proven"], plan["rank"]), (True, False, 1))
        self.assertTrue(memory.confirm_proven("QQ", "9.9.22", "B", plan["revision"])["ok"])
        plan = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]
        self.assertEqual((plan["reviewed"], plan["proven"], plan["rank"]), (True, True, 3))
        self.assertTrue(memory.approve("QQ", "9.9.22", "B", plan["revision"], reviewed=False)["ok"])
        plan = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]
        self.assertEqual((plan["reviewed"], plan["proven"], plan["rank"]), (False, True, 2))

    def test_body_change_clears_trust(self):
        self.write_plans()
        rev = self.revision()
        memory.approve("QQ", "9.9.22", "B", rev)
        rev = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]["revision"]
        memory.confirm_proven("QQ", "9.9.22", "B", rev)
        memory.remember("QQ", "9.9.22", "B", "summary", "cost", QQ_BODY + "more\n",
                        uses_foreground=False, overwrite=True)
        plan = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]
        self.assertEqual((plan["reviewed"], plan["proven"], plan["rank"]), (False, False, 0))

    def test_identical_overwrite_keeps_trust(self):
        self.write_plans()
        memory.approve("QQ", "9.9.22", "B", self.revision())
        memory.remember("QQ", "9.9.22", "B", "summary", "cost", QQ_BODY,
                        uses_foreground=False, overwrite=True)
        plan = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]
        self.assertTrue(plan["reviewed"])

    def test_other_plans_keep_trust_when_one_changes(self):
        self.write_plans(plan_id="A", body="body a\n")
        self.write_plans(plan_id="B")
        memory.approve("QQ", "9.9.22", "A", self.revision("A"))
        memory.remember("QQ", "9.9.22", "B", "summary", "cost", "new body b\n",
                        uses_foreground=False, overwrite=True)
        plans = {p["id"]: p for p in memory.recall("qq@9.9.22")["matches"][0]["plans"]}
        self.assertTrue(plans["A"]["reviewed"])
        self.assertFalse(plans["B"]["reviewed"])

    def test_stale_revision_cannot_approve_overwritten_content(self):
        self.write_plans()
        old = self.revision()
        memory.remember("QQ", "9.9.22", "B", "summary", "cost", "different body\n",
                        uses_foreground=False, overwrite=True)
        stale = memory.approve("QQ", "9.9.22", "B", old)
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["reason"], "stale plan")
        self.assertFalse(memory.recall("qq@9.9.22")["matches"][0]["plans"][0]["reviewed"])

    def test_missing_key_or_plan_is_an_error_not_a_creation(self):
        result = memory.approve("QQ", "9.9.22", "B", "x")
        self.assertEqual(result["reason"], "plan not found")
        self.write_plans()
        self.assertEqual(memory.approve("QQ", "9.9.22", "Z", self.revision())["reason"], "plan not found")
        self.assertEqual(memory.recall("qq@9.9.22")["matches"][0]["plans"][0]["rank"], 0)

    def test_remember_needs_overwrite_for_existing_id(self):
        self.write_plans()
        clash = self.write_plans()
        self.assertFalse(clash["ok"])
        self.assertEqual(clash["reason"], "plan exists")
        self.assertEqual(len(memory.recall("qq@9.9.22")["matches"][0]["plans"]), 1)

    def test_required_text_fields(self):
        for field in ("summary", "cost", "body"):
            kwargs = dict(app="QQ", version="9.9.22", plan_id="B", summary="s", cost="c",
                          body="b", uses_foreground=False)
            kwargs[field] = "   "
            self.assertFalse(memory.remember(**kwargs)["ok"], field)

    def test_uses_foreground_must_be_a_real_bool(self):
        for value in (1, 0, "false", None):
            result = memory.remember("QQ", "9.9.22", "B", "s", "c", "b", uses_foreground=value)
            self.assertFalse(result["ok"], value)
            self.assertEqual(result["reason"], "invalid uses_foreground")


class TestConcurrencyAndFailure(MemoryCase):
    def test_two_threads_appending_different_plans_both_survive(self):
        errors = []

        def add(plan_id):
            try:
                result = memory.remember("QQ", "9.9.22", plan_id, "s", "c", f"body {plan_id}\n",
                                         uses_foreground=False)
                if not result["ok"]:
                    errors.append(result)
            except Exception as error:  # pragma: no cover - reported below
                errors.append(error)

        threads = [threading.Thread(target=add, args=(pid,)) for pid in ("A", "B", "C")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        plans = memory.recall("qq@9.9.22")["matches"][0]["plans"]
        self.assertEqual(sorted(p["id"] for p in plans), ["A", "B", "C"])

    def test_failed_replace_keeps_the_old_record(self):
        self.write_plans()
        before = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]["body"]
        with mock.patch.object(memory.os, "replace", side_effect=OSError("disk full")):
            result = memory.remember("QQ", "9.9.22", "B", "summary", "cost", "replacement\n",
                                     uses_foreground=False, overwrite=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "write failed")
        self.assertEqual(memory.recall("qq@9.9.22")["matches"][0]["plans"][0]["body"], before)

    def test_no_temporary_files_left_behind(self):
        self.write_plans()
        leftovers = [p.name for p in (self.root / "playbooks").iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])


class TestInheritance(MemoryCase):
    def write_inherited(self, version="9.9.19", source="qq@9.9.22"):
        key = memory.make_key("QQ", version)
        path = memory.record_path(self.root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema": 1, "key": key, "app": "QQ", "version": version,
                "updated": "2026-11-08", "see": source}
        path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n",
                        encoding="utf-8")
        return path

    def test_inherited_plans_carry_no_trust(self):
        self.write_plans()
        memory.confirm_proven("QQ", "9.9.22", "B",
                             memory.recall("qq@9.9.22")["matches"][0]["plans"][0]["revision"])
        self.write_inherited()
        match = memory.recall("qq@9.9.19")["matches"][0]
        self.assertEqual(match["inherits"], "qq@9.9.22")
        self.assertEqual(match["plans"][0]["rank"], 0)
        self.assertFalse(match["plans"][0]["reviewed"])
        self.assertFalse(match["plans"][0]["proven"])
        self.assertTrue(memory.recall("qq@9.9.19")["exact"])

    def test_inheritance_follows_exactly_one_level(self):
        self.write_plans()
        self.write_inherited(version="9.9.19", source="qq@9.9.22")
        self.write_inherited(version="9.9.10", source="qq@9.9.19")
        self.assertEqual(memory.recall("qq@9.9.10")["reason"], "invalid record")
        self.assertEqual(memory.recall("qq@9.9.19", plan_id="B")["reason"], "plan not found")

    def test_self_reference_and_missing_source(self):
        self.write_inherited(version="9.9.19", source="qq@9.9.19")
        self.assertEqual(memory.recall("qq@9.9.19")["reason"], "invalid record")
        self.write_inherited(version="9.9.30", source="qq@7.7.7")
        self.assertEqual(memory.recall("qq@9.9.30")["reason"], "invalid record")

    def test_remember_refuses_inherited_record_until_materialized(self):
        self.write_plans()
        self.write_inherited()
        refused = memory.remember("QQ", "9.9.19", "B", "s", "c", "new\n", uses_foreground=False)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["reason"], "inherited record")
        materialized = memory.remember("QQ", "9.9.19", "B", "s", "c", "new\n",
                                       uses_foreground=False, overwrite=True)
        self.assertTrue(materialized["ok"], materialized)
        match = memory.recall("qq@9.9.19")["matches"][0]
        self.assertIsNone(match["inherits"])
        self.assertEqual(match["plans"][0]["body"], "new\n")

    def test_approve_cannot_touch_an_inherited_record(self):
        self.write_plans()
        self.write_inherited()
        result = memory.approve("QQ", "9.9.19", "B", "whatever")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "inherited record")


class TestUnresolved(MemoryCase):
    def test_unresolved_comes_from_the_real_body(self):
        self.write_plans()
        got = memory.unresolved()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["key"], "qq@9.9.22")
        self.assertEqual(got[0]["plan_id"], "B")
        self.assertEqual(got[0]["text"], "尚未证明能够读取虚拟化列表中未渲染的项目")

    def test_deleting_the_section_closes_the_gap(self):
        self.write_plans()
        memory.remember("QQ", "9.9.22", "B", "summary", "cost", "## 目标\nno gaps\n",
                        uses_foreground=False, overwrite=True)
        self.assertEqual(memory.unresolved(), [])

    def test_section_stops_at_the_next_heading(self):
        body = "## 未解决\nfirst\n## 更新记录\nsecond\n### deep\n"
        self.write_plans(body=body)
        self.assertEqual(memory.unresolved()[0]["text"], "first")

    def test_heading_must_not_swallow_newlines(self):
        body = "## 未解决  \nafter trailing spaces\n"
        self.write_plans(body=body)
        self.assertEqual(memory.unresolved()[0]["text"], "after trailing spaces")

    def test_recall_reports_gaps_per_match(self):
        self.write_plans()
        match = memory.recall("qq@9.9.22")["matches"][0]
        self.assertEqual(match["unresolved"][0]["plan_id"], "B")
        self.assertFalse(match["unresolved"][0]["truncated"])


class TestRevision(MemoryCase):
    def test_revision_ignores_trust_bits(self):
        self.write_plans()
        plan = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]
        rev = plan["revision"]
        memory.approve("QQ", "9.9.22", "B", rev)
        after = memory.recall("qq@9.9.22")["matches"][0]["plans"][0]
        self.assertEqual(after["revision"], rev)

    def test_revision_is_bound_to_the_key(self):
        plan = {"id": "B", "summary": "s", "cost": "c", "body": "b", "uses_foreground": False}
        self.assertNotEqual(memory.plan_revision("qq@9.9.22", plan),
                            memory.plan_revision("qq@9.9.19", plan))

    def test_revision_changes_with_content(self):
        plan = {"id": "B", "summary": "s", "cost": "c", "body": "b", "uses_foreground": False}
        other = dict(plan, body="b2")
        self.assertNotEqual(memory.plan_revision("k", plan), memory.plan_revision("k", other))


if __name__ == "__main__":
    unittest.main()

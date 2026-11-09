"""memory.forget: remove information that is now wrong or superseded.

Errors stay (they are evidence); stale facts must go, or recall hands the caller
an answer that is no longer true. So deletion is per plan, checked against the
revision the caller was shown, and removing the last plan removes the record.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deskweft import memory

BODY = "## 目标\nold\n"


class ForgetCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = mock.patch.object(memory, "memory_root", return_value=self.root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def add(self, plan_id="A", body=BODY, version="9.9.22", app="QQ"):
        return memory.remember(app, version, plan_id, "summary", "cost", body,
                               uses_foreground=False)

    def revision(self, plan_id="A", key="qq@9.9.22"):
        for match in memory.recall(key)["matches"]:
            for plan in match["plans"]:
                if plan["id"] == plan_id:
                    return plan["revision"]
        return None

    def path_for(self, key="qq@9.9.22"):
        return memory.record_path(self.root, key)


class TestForgetPlan(ForgetCase):
    def test_removing_one_plan_leaves_the_record_and_the_others(self):
        self.add("A")
        self.add("B")
        result = memory.forget("QQ", "9.9.22", "B", self.revision("B"))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["key"], "qq@9.9.22")
        self.assertEqual(result["removed"], ["B"])
        self.assertFalse(result["record_removed"])
        plans = [p["id"] for p in memory.recall("qq@9.9.22")["matches"][0]["plans"]]
        self.assertEqual(plans, ["A"])

    def test_removing_the_last_plan_removes_the_record(self):
        self.add("A")
        result = memory.forget("QQ", "9.9.22", "A", self.revision("A"))
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["record_removed"])
        self.assertFalse(self.path_for().exists(), "the file must not linger")
        self.assertEqual(memory.recall("qq@9.9.22")["matches"], [])

    def test_a_stale_revision_cannot_delete_newer_content(self):
        """The revision guard is the same one approve uses: you delete what you
        were shown, not whatever replaced it."""
        self.add("A")
        old = self.revision("A")
        memory.remember("QQ", "9.9.22", "A", "s", "c", "## 目标\nnew\n",
                        uses_foreground=False, overwrite=True)
        result = memory.forget("QQ", "9.9.22", "A", old)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "stale plan")
        plans = memory.recall("qq@9.9.22")["matches"][0]["plans"]
        self.assertEqual([p["id"] for p in plans], ["A"], "nothing may be removed")

    def test_a_missing_plan_is_an_error_not_a_silent_success(self):
        self.add("A")
        result = memory.forget("QQ", "9.9.22", "Z", "whatever")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "plan not found")
        self.assertTrue(self.path_for().exists())

    def test_a_missing_record_is_an_error(self):
        result = memory.forget("QQ", "9.9.22", "A", "whatever")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "plan not found")

    def test_the_revision_is_required(self):
        self.add("A")
        for bad in ("", None, 0):
            result = memory.forget("QQ", "9.9.22", "A", bad)
            self.assertFalse(result["ok"], bad)
            self.assertEqual(result["reason"], "invalid revision", bad)
        self.assertTrue(self.path_for().exists())


class TestForgetRecord(ForgetCase):
    def test_no_plan_id_removes_the_whole_record_with_confirmation(self):
        self.add("A")
        self.add("B")
        result = memory.forget("QQ", "9.9.22", confirm=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["record_removed"])
        self.assertEqual(sorted(result["removed"]), ["A", "B"])
        self.assertFalse(self.path_for().exists())

    def test_no_plan_id_without_confirmation_is_refused(self):
        self.add("A")
        result = memory.forget("QQ", "9.9.22")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "confirmation required")
        self.assertTrue(self.path_for().exists(), "nothing may be deleted")

    def test_confirm_must_be_a_real_bool(self):
        self.add("A")
        for bad in ("true", 1, 0):
            result = memory.forget("QQ", "9.9.22", confirm=bad)
            self.assertFalse(result["ok"], bad)
            self.assertTrue(self.path_for().exists())


class TestForgetValidation(ForgetCase):
    def test_inherited_records_are_not_deleted(self):
        self.add("A")
        key = memory.make_key("QQ", "9.9.19")
        path = memory.record_path(self.root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nschema: 1\nkey: qq@9.9.19\napp: QQ\nversion: \"9.9.19\"\n"
            "updated: '2026-11-08'\nsee: qq@9.9.22\n---\n", encoding="utf-8")
        result = memory.forget("QQ", "9.9.19", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "inherited record")
        self.assertTrue(path.exists(), "deleting the pointer must not touch the source")
        self.assertTrue(self.path_for().exists())

    def test_unversioned_records_can_be_removed(self):
        self.add("A", version=None)
        result = memory.forget("QQ", None, "A",
                               memory.recall("qq@unversioned")["matches"][0]["plans"][0]["revision"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(memory.recall("")["keys"], [])

    def test_bad_names_are_rejected(self):
        for app in ("", "a@b", "a/b"):
            self.assertEqual(memory.forget(app, "9.9.22", confirm=True)["reason"],
                             "invalid app", app)
        for version in ("unversioned", "a/b"):
            self.assertEqual(memory.forget("QQ", version, confirm=True)["reason"],
                             "invalid version", version)

    def test_other_records_are_untouched(self):
        self.add("A", app="QQ")
        self.add("A", app="Weixin", version="4.2.0.13")
        result = memory.forget("QQ", "9.9.22", confirm=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(self.path_for("weixin@4.2.0.13").exists())
        self.assertEqual(memory.recall("")["keys"], ["weixin@4.2.0.13"])


class TestForgetLeavesNoDebris(ForgetCase):
    def test_no_temporary_files_stay_behind(self):
        self.add("A")
        memory.forget("QQ", "9.9.22", confirm=True)
        folder = self.root / "playbooks"
        self.assertEqual([p.name for p in folder.iterdir() if p.suffix == ".tmp"], [])

    def test_a_failed_write_keeps_the_record(self):
        """Deleting one plan still rewrites the record, so a failed replace must
        leave the old file readable with all its plans."""
        self.add("A")
        self.add("B")
        with mock.patch.object(memory.os, "replace", side_effect=OSError("disk full")):
            result = memory.forget("QQ", "9.9.22", "B", self.revision("B"))
        self.assertFalse(result["ok"])
        self.assertTrue(self.path_for().exists(), "a failed delete must not lose data")
        plans = [p["id"] for p in memory.recall("qq@9.9.22")["matches"][0]["plans"]]
        self.assertEqual(sorted(plans), ["A", "B"])

    def test_removing_the_last_plan_does_not_need_a_rewrite(self):
        """With nothing left there is no record to write, so an unavailable
        replace must not block the deletion."""
        self.add("A")
        with mock.patch.object(memory.os, "replace", side_effect=OSError("disk full")):
            result = memory.forget("QQ", "9.9.22", "A", self.revision("A"))
        self.assertTrue(result["ok"], result)
        self.assertFalse(self.path_for().exists())

    def test_an_unreadable_record_is_reported_not_deleted(self):
        path = self.path_for()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nkey: [broken\n---\n", encoding="utf-8")
        result = memory.forget("QQ", "9.9.22", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid record")
        self.assertTrue(path.exists(), "a corrupt record must not be silently removed")


if __name__ == "__main__":
    unittest.main()

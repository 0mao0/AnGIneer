"""P1.1/P1.4 SOP 加载器状态过滤与统计回流单测。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))

from sop_core.sop_loader import SopLoader  # noqa: E402


def write_sop(sop_dir, sop_id, payload):
    os.makedirs(sop_dir, exist_ok=True)
    with open(os.path.join(sop_dir, f"{sop_id}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


class SopLoaderStatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sop_base = self._tmp.name
        self.json_dir = os.path.join(self.sop_base, "json")
        self.loader = SopLoader(self.sop_base)

    def tearDown(self):
        self._tmp.cleanup()

    def test_legacy_json_without_status_grandfathered_to_published(self):
        write_sop(self.json_dir, "legacy", {"id": "legacy", "name_zh": "旧SOP", "steps": []})
        sops = self.loader.load_all()
        self.assertEqual([s.id for s in sops], ["legacy"])
        self.assertEqual(sops[0].status, "published")

    def test_draft_excluded_by_default_and_included_when_requested(self):
        write_sop(self.json_dir, "legacy", {"id": "legacy", "name_zh": "旧SOP", "steps": []})
        write_sop(
            self.json_dir,
            "draft_sop",
            {
                "id": "draft_sop",
                "name_zh": "新SOP",
                "status": "draft",
                "steps": [
                    {
                        "id": "step_1",
                        "description": {"content": "执行", "citations": []},
                        "tool": "auto",
                    }
                ],
            },
        )

        default_sops = self.loader.load_all()
        self.assertEqual([s.id for s in default_sops], ["legacy"])

        all_sops = self.loader.load_all(include_status=("draft", "published"))
        self.assertEqual({s.id for s in all_sops}, {"legacy", "draft_sop"})

    def test_record_run_updates_stats_atomically_and_in_memory(self):
        write_sop(self.json_dir, "run_sop", {"id": "run_sop", "name_zh": "运行SOP", "steps": []})
        self.loader.load_all()

        self.loader.record_run("run_sop", "success")
        self.loader.record_run("run_sop", "failed")

        with open(os.path.join(self.json_dir, "run_sop.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["stats"], {"runs": 2, "success": 1, "last_status": "failed"})
        in_memory = next(s for s in self.loader.sops if s.id == "run_sop")
        self.assertEqual(in_memory.stats["runs"], 2)
        self.assertEqual(in_memory.stats["success"], 1)

    def test_record_run_missing_sop_is_noop(self):
        self.loader.record_run("nope", "success")  # 不应抛异常

    def test_update_status_persists_and_syncs_memory(self):
        write_sop(self.json_dir, "run_sop", {"id": "run_sop", "name_zh": "运行SOP", "steps": []})
        self.loader.load_all()

        review = {"reviewer": "tester", "note": "ok", "at": "2026-08-09T00:00:00"}
        self.assertTrue(self.loader.update_status("run_sop", "disabled", review=review))

        with open(os.path.join(self.json_dir, "run_sop.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["status"], "disabled")
        self.assertEqual(data["review"]["note"], "ok")
        in_memory = next(s for s in self.loader.sops if s.id == "run_sop")
        self.assertEqual(in_memory.status, "disabled")
        self.assertEqual(in_memory.review["reviewer"], "tester")

        self.assertFalse(self.loader.update_status("missing", "published"))


if __name__ == "__main__":
    unittest.main()

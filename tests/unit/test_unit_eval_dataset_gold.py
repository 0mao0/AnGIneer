"""题集 gold 契约回归：拒答题不得携带事实性 gold_answer（2026-09-13 核查）。

背景：v2 拒答集由 build_refusal_set.py 早期版本生成，gold_answer 直接拷了原始事实答案，
与 refusal_expected=true 自相矛盾（39/39 皆如此）。该字段从不参与判分（answer_eval 在
refusal_expected 分支短路，早于 LLM 语义判分 return），但留着只会在日后判分改动时被误用。

本测试钉死三件事：
- v3 bundle 的 39 道拒答题 gold 必须是哨兵文本，且不得残留事实答案
- 非拒答题的 gold_answer 必须原样保留（防归一化误伤）
- 哨兵常量在"生产者"（build_refusal_set）与"校验者"（build_subset_v3）两侧一致
"""
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "open_ragbench"))

V3_BUNDLE = REPO / "data" / "evals" / "datasets" / "open-ragbench-subset-v3.json"


def _load_items():
    return json.loads(V3_BUNDLE.read_text(encoding="utf-8"))["items"]


class RefusalGoldContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from build_subset_v3 import REFUSAL_GOLD_SENTINEL

        cls.sentinel = REFUSAL_GOLD_SENTINEL
        cls.items = _load_items()

    def test_question_count_and_ids_unique(self):
        self.assertEqual(len(self.items), 526)
        ids = [it["question_id"] for it in self.items]
        self.assertEqual(len(ids), len(set(ids)), "question_id 必须唯一")

    def test_refusal_items_carry_sentinel_not_facts(self):
        refusals = [it for it in self.items if it.get("question_family") == "unanswerable"]
        self.assertEqual(len(refusals), 39, "拒答题应为 39 道")
        for it in refusals:
            answer = it.get("answer") or {}
            self.assertTrue(answer.get("refusal_expected"), f"{it['question_id']} 缺 refusal_expected")
            self.assertEqual(
                answer.get("gold_answer"), self.sentinel,
                f"{it['question_id']} 的 gold_answer 不是拒答哨兵——事实性 gold 会与"
                f" refusal_expected 自相矛盾，且可能被日后判分改动误用")
            self.assertIsNone(it.get("retrieval"), "拒答题不应有检索金标（设计如此）")

    def test_non_refusal_items_keep_their_gold(self):
        others = [it for it in self.items if it.get("question_family") != "unanswerable"]
        self.assertEqual(len(others), 487)
        missing = [it["question_id"] for it in others if not (it.get("answer") or {}).get("gold_answer")]
        self.assertEqual(missing, [], "非拒答题的标准答案不得被归一化误伤")


class SentinelSingleSourceTests(unittest.TestCase):
    def test_producer_and_validator_share_one_sentinel(self):
        from build_subset_v3 import REFUSAL_GOLD_SENTINEL
        import build_refusal_set

        self.assertEqual(build_refusal_set.REFUSAL_GOLD_SENTINEL, REFUSAL_GOLD_SENTINEL,
                         "拒答哨兵必须单一真相源（build_refusal_set 从 build_subset_v3 导入）")


class ScrubHelperTests(unittest.TestCase):
    def test_scrub_only_touches_refusal_items(self):
        from build_subset_v3 import _scrub_refusal_gold_text, REFUSAL_GOLD_SENTINEL

        text, changed = _scrub_refusal_gold_text("Protostars are early-stage stars", refusal_expected=True)
        self.assertTrue(changed)
        self.assertEqual(text, REFUSAL_GOLD_SENTINEL)

        text, changed = _scrub_refusal_gold_text("正常答案", refusal_expected=False)
        self.assertFalse(changed)
        self.assertEqual(text, "正常答案")

        _, changed = _scrub_refusal_gold_text(REFUSAL_GOLD_SENTINEL, refusal_expected=True)
        self.assertFalse(changed, "已归一化的数据应幂等不再改动")


if __name__ == "__main__":
    unittest.main()

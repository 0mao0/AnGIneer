"""候选集合对账（recall_audit）单测——plan-ls-routing §5 施工主线第①项。

覆盖：target/doc/matter 三档金标路由、chunk 命名空间双路命中、多轮并集去重、
matter 双源（catalog 注入 / text_regex fallback）、no_machine_gold 不静默、
audit_error 自兜底、run 级聚合分桶。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.runner import recall_audit
from evals_core.runner.recall_audit import (
    compute_audit,
    extract_gold_units,
    summarize_audits,
)


def _item(item_id, doc_id, *, target=None, title="", text="", content=None):
    it = {
        "item_id": item_id,
        "doc_id": doc_id,
        "citation_target_id": target or item_id,
        "title": title,
        "text": text,
        "metadata": {"cite": "K1"},
    }
    if content is not None:
        it["content"] = content
    return it


class ExtractGoldUnitsTest(unittest.TestCase):
    def test_target_priority_over_doc(self):
        q = {"retrieval_gold": {"gold_target_ids": ["t1"], "gold_doc_ids": ["d1"]}}
        unit, gold = extract_gold_units(q)
        self.assertEqual(unit, "target")
        self.assertEqual(gold, ["t1"])

    def test_chunk_ids_count_as_target(self):
        q = {"retrieval_gold": {"gold_chunk_ids": ["c1", "c2"]}}
        unit, gold = extract_gold_units(q)
        self.assertEqual((unit, gold), ("target", ["c1", "c2"]))

    def test_doc_level(self):
        q = {"retrieval_gold": {"gold_doc_ids": ["d1", "d2"]}}
        unit, gold = extract_gold_units(q)
        self.assertEqual((unit, gold), ("doc", ["d1", "d2"]))

    def test_matter_from_rubric_text(self):
        q = {"rubric_gold": {"criteria": [{"text": "Matters 1234-56789 and 9876-54321 qualify."}]}}
        unit, gold = extract_gold_units(q)
        self.assertEqual((unit, gold), ("matter", ["1234-56789", "9876-54321"]))

    def test_no_machine_gold(self):
        q = {"rubric_gold": {"criteria": [{"text": "the memo must discuss privilege."}]}}
        unit, gold = extract_gold_units(q)
        self.assertIsNone(unit)
        self.assertIsNone(gold)


class ComputeAuditTest(unittest.TestCase):
    def test_target_hit_via_citation_and_item_id(self):
        # 命中双路：t1 走 citation_target_id（chunk 命名空间的 item_id 不等值）、
        # t2 走 item_id（block 路径两者同值）
        pred = {"retrieved_items": [_item("chunk-a", "d1", target="t1"), _item("t2", "d2")]}
        q = {"retrieval_gold": {"gold_target_ids": ["t1", "t2"]}}
        audit = compute_audit(pred, q)
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(audit["unit"], "target")
        self.assertEqual((audit["hit"], audit["gold_total"], audit["recall"]), (2, 2, 1.0))
        self.assertEqual(audit["missing"], [])

    def test_doc_level_gap_with_secondary(self):
        pred = {
            "retrieved_items": [_item("i1", "d1")],
            "evidences": [{"evidence_id": "i1", "doc_id": "d1", "content": "…"}],
        }
        # 上桌证据里有 d2（候选层截断差异归因的演示场景）
        q = {"retrieval_gold": {"gold_doc_ids": ["d1", "d2"]}}
        audit = compute_audit(pred, q)
        self.assertEqual((audit["hit"], audit["gold_total"]), (1, 2))
        self.assertEqual(audit["recall"], 0.5)
        self.assertEqual(audit["missing"], ["d2"])
        self.assertEqual(audit["candidates_n"], 1)

    def test_matter_catalog_source(self):
        pred = {"retrieved_items": [_item("i1", "doc-1", title="Memo"), _item("i2", "doc-2", title="Memo 2")]}
        q = {"rubric_gold": {"criteria": [{"text": "Matters 1234-56789 and 9876-54321 qualify."}]}}
        resolver = {"doc-1": "1234-56789"}.get  # doc-2 无映射且正文无号 → 正则也捞不到
        audit = compute_audit(pred, q, matter_resolver=resolver)
        self.assertEqual(audit["unit"], "matter")
        self.assertEqual((audit["hit"], audit["gold_total"]), (1, 2))
        self.assertEqual(audit["missing"], ["9876-54321"])
        self.assertEqual(audit["recall"], 0.5)
        self.assertEqual(audit["matter_source"], "catalog")

    def test_matter_regex_fallback_source(self):
        pred = {"retrieved_items": [
            _item("i1", "doc-1", title="Memo 1234-56789"),
            _item("i2", "doc-2", text="…the 9876-54321 transaction…"),
        ]}
        q = {"rubric_gold": {"criteria": [{"text": "Matters 1234-56789 and 9876-54321 qualify."}]}}
        audit = compute_audit(pred, q, matter_resolver=None)
        self.assertEqual((audit["hit"], audit["gold_total"]), (2, 2))
        self.assertEqual(audit["matter_source"], "text_regex")

    def test_matter_mixed_source(self):
        pred = {"retrieved_items": [
            _item("i1", "doc-1", title="no number here"),
            _item("i2", "doc-2", text="…9876-54321…"),
        ]}
        q = {"rubric_gold": {"criteria": [{"text": "Matters 1234-56789 and 9876-54321 qualify."}]}}
        resolver = {"doc-1": "1234-56789"}.get
        audit = compute_audit(pred, q, matter_resolver=resolver)
        self.assertEqual(audit["matter_source"], "mixed")
        self.assertEqual(audit["hit"], 2)

    def test_no_machine_gold_not_silent(self):
        q = {"rubric_gold": {"criteria": [{"text": "must discuss privilege."}]}}
        audit = compute_audit({"retrieved_items": [_item("i1", "d1")]}, q)
        self.assertEqual(audit["status"], "no_machine_gold")
        self.assertEqual(audit["candidates_n"], 1)  # 分母外仍留候选计数备查

    def test_dedup_items_across_turns(self):
        pred = {"retrieved_items": [_item("i1", "d1"), _item("i1", "d1")]}
        q = {"retrieval_gold": {"gold_doc_ids": ["d1"]}}
        audit = compute_audit(pred, q)
        self.assertEqual(audit["candidates_n"], 1)
        self.assertEqual(audit["recall"], 1.0)

    def test_empty_candidates_with_gold_is_honest_zero(self):
        # key 存在但为空 = 检索真为空，如实记 0（不与「没记录」混淆）
        q = {"retrieval_gold": {"gold_doc_ids": ["d1"]}}
        audit = compute_audit({"retrieved_items": []}, q)
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(audit["candidate_record"], "retrieved_items")
        self.assertEqual((audit["hit"], audit["recall"]), (0, 0.0))
        self.assertEqual(audit["missing"], ["d1"])

    def test_no_candidates_recorded_for_legacy_prediction(self):
        # 旧 run 连 retrieved_items key 都没有：「没记录」≠「召回 0」，单独成桶
        q = {"retrieval_gold": {"gold_doc_ids": ["d1"]}}
        audit = compute_audit({"answer": "…", "citations": []}, q)
        self.assertEqual(audit["status"], "no_candidates_recorded")
        self.assertIsNone(audit["recall"])

    def test_citations_only_fallback_for_legacy_run(self):
        # 旧 run 只有 citations：可对账但降级为下界，candidate_record 如实标注
        pred = {"citations": [
            {"target_id": "t1", "doc_id": "d1", "doc_title": "a.pdf", "marker": "K1"},
            {"target_id": "t9", "doc_id": "d9", "doc_title": "b.pdf", "marker": "K2"},
        ]}
        q = {"retrieval_gold": {"gold_doc_ids": ["d1", "d2"]}}
        audit = compute_audit(pred, q)
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(audit["candidate_record"], "citations_only")
        self.assertEqual((audit["hit"], audit["gold_total"]), (1, 2))
        self.assertEqual(audit["missing"], ["d2"])
        self.assertEqual(audit["candidates_n"], 2)

    def test_audit_error_self_contained(self):
        q = {"retrieval_gold": {"gold_doc_ids": ["d1"]}}
        with mock.patch.object(recall_audit, "_compute_audit", side_effect=RuntimeError("boom")):
            audit = compute_audit({"retrieved_items": []}, q)
        self.assertEqual(audit["status"], "audit_error")
        self.assertIn("boom", audit["error"])

    def test_secondary_evidences_recall(self):
        pred = {
            "retrieved_items": [_item("i1", "d1"), _item("i2", "d2")],
            "evidences": [{"evidence_id": "i1", "doc_id": "d1", "content": "…"}],
        }
        q = {"retrieval_gold": {"gold_doc_ids": ["d1", "d2"]}}
        audit = compute_audit(pred, q)
        # primary=候选全集 2/2；secondary=上桌子集 1/2（截断层归因）
        self.assertEqual(audit["recall"], 1.0)
        self.assertEqual(audit["secondary"], {"hit": 1, "recall": 0.5})


class SummarizeAuditsTest(unittest.TestCase):
    def test_bucket_counts(self):
        audits = [
            {"status": "ok", "gold_total": 2, "hit": 2, "recall": 1.0},
            {"status": "ok", "gold_total": 4, "hit": 1, "recall": 0.25},
            {"status": "ok", "gold_total": 1, "hit": 1, "recall": 1.0},
            {"status": "no_machine_gold"},
            {"status": "no_candidates_recorded"},
            {"status": "audit_error", "error": "x"},
            {"status": "weird_status"},
            "garbage",  # 非 dict：静默跳过（不进任何桶）
        ]
        s = summarize_audits(audits)
        self.assertEqual(s["audited"], 3)
        self.assertEqual(s["full_recall"], 2)
        self.assertEqual(s["with_gap"], 1)
        self.assertEqual(s["mean_recall"], round((1.0 + 0.25 + 1.0) / 3, 4))
        self.assertEqual(s["no_machine_gold"], 1)
        self.assertEqual(s["no_candidates_recorded"], 1)
        self.assertEqual(s["audit_error"], 1)
        self.assertEqual(s["other"], 1)

    def test_json_string_entries_parsed(self):
        """存储层未反序列化时（历史路径），字符串条目也要能出桶。"""
        import json as _json
        audits = [
            _json.dumps({"status": "ok", "gold_total": 2, "hit": 1, "recall": 0.5}),
            _json.dumps({"status": "no_machine_gold"}),
            "not-a-json",
        ]
        s = summarize_audits(audits)
        self.assertEqual(s["audited"], 1)
        self.assertEqual(s["with_gap"], 1)
        self.assertEqual(s["no_machine_gold"], 1)

    def test_empty(self):
        s = summarize_audits([])
        self.assertEqual(s["audited"], 0)
        self.assertIsNone(s["mean_recall"])


if __name__ == "__main__":
    unittest.main()

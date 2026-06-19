"""检索精度基准集与评测协议的回归测试。"""

import sys
import unittest
from pathlib import Path


EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.dataset.loader import load_bundle_from_dict
from evals_core.runner.retrieval_eval import RetrievalEvaluator
from evals_core.runner.suite_runner import _compute_summary


class RetrievalPrecisionBundleTests(unittest.TestCase):
    """验证 docs 检索基准集能保留专项字段。"""

    def test_bundle_preserves_extended_retrieval_gold_fields(self) -> None:
        """基准集导入时应保留 target 与题型相关字段。"""
        payload = {
            "dataset": {
                "dataset_id": "docs-retrieval-precision-v1",
                "title": "Docs 检索精度基准集",
                "library_id": "default",
            },
            "items": [{
                "question_id": "harbor-1-clause-001",
                "question": "4.2.3 条关于港口水位有什么要求？",
                "task_type": "definition",
                "intent_level": "L1",
                "doc_ids": ["harbor-1"],
                "retrieval": {
                    "gold_section_paths": ["第四章/4.2/4.2.3"],
                    "gold_doc_ids": ["harbor-1"],
                    "gold_target_ids": ["title:4.2.3"],
                    "gold_target_types": ["title"],
                    "question_type": "locate_clause",
                    "notes": "条款精确定位题",
                },
            }],
        }

        bundle = load_bundle_from_dict(payload)
        retrieval = bundle.items[0].retrieval

        self.assertEqual(retrieval.gold_target_ids, ["title:4.2.3"])
        self.assertEqual(retrieval.gold_target_types, ["title"])
        self.assertEqual(retrieval.question_type, "locate_clause")
        self.assertEqual(retrieval.notes, "条款精确定位题")

    def test_retrieval_evaluator_reports_hit1_and_failure_bucket(self) -> None:
        """图题未命中但正文误召回时应输出失败分桶。"""
        evaluator = RetrievalEvaluator()
        question = {
            "question_id": "harbor-2-figure-001",
            "retrieval_gold": {
                "gold_section_paths": ["第三章/图3"],
                "gold_doc_ids": ["harbor-2"],
                "gold_target_ids": ["figure:3"],
                "gold_target_types": ["figure"],
                "question_type": "locate_figure",
            },
        }
        prediction = {
            "retrieved_section_paths": ["第三章/正文说明"],
            "retrieved_doc_ids": ["harbor-2"],
            "citations": [{
                "reference": {"targetId": "content:chapter-3"},
            }],
            "retrieved_items": [{
                "item_id": "chunk-body-3",
                "doc_id": "harbor-2",
                "metadata": {
                    "section_path": "第三章/正文说明",
                    "target_type": "content",
                },
            }],
        }

        result = evaluator.evaluate(question, question["retrieval_gold"], prediction)

        self.assertEqual(result["hit@1"], 0.0)
        self.assertEqual(result["failure_bucket"], "caption_body_confusion")

    def test_suite_summary_groups_scores_by_question_type_and_failure_bucket(self) -> None:
        """评测汇总应输出题型与失败桶维度的聚合结果。"""
        summary = _compute_summary([
            {
                "status": "completed",
                "quality": "correct",
                "intent_level": "L1",
                "doc_ids": ["harbor-1"],
                "all_scores": {
                    "retrieval": {
                        "evaluated": True,
                        "hit@5": 1.0,
                        "question_type": "locate_clause",
                        "failure_bucket": "ok",
                    },
                },
            },
            {
                "status": "completed",
                "quality": "wrong",
                "intent_level": "L1",
                "doc_ids": ["harbor-2"],
                "all_scores": {
                    "retrieval": {
                        "evaluated": True,
                        "hit@5": 0.0,
                        "question_type": "locate_figure",
                        "failure_bucket": "caption_body_confusion",
                    },
                },
            },
        ])

        self.assertEqual(summary["grouped_scores"]["question_type"]["locate_clause"], 1.0)
        self.assertEqual(summary["grouped_scores"]["question_type"]["locate_figure"], 0.0)
        self.assertEqual(summary["grouped_scores"]["failure_bucket"]["caption_body_confusion"], 1)


if __name__ == "__main__":
    unittest.main()

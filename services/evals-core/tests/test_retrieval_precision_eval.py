"""检索精度基准集与评测协议的回归测试。"""

import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.dataset.loader import load_bundle_from_dict
from evals_core.dataset import manager as dataset_manager
from evals_core.dataset.manager import import_bundle
from evals_core.runner.retrieval_eval import RetrievalEvaluator, compute_failure_bucket
from evals_core.runner.suite_runner import _compute_summary, get_eval_run
from evals_core.storage import result_store


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

    def test_compute_failure_bucket_marks_hard_negative_bias(self) -> None:
        """命中 hard negative target 时应输出专用失败桶。"""
        gold = {
            "gold_section_paths": ["附录 C / C.2 混凝土本构关系"],
            "gold_target_ids": ["doc-8474a7fe:19:1"],
            "gold_target_types": ["formula"],
            "hard_negative_target_ids": ["doc-8474a7fe:19:3"],
        }
        predicted_items = [
            {
                "entity_type": "formula",
                "metadata": {
                    "target_type": "formula",
                    "citation_target_id": "doc-8474a7fe:19:3",
                },
            }
        ]
        predicted_citations = [
            {"reference": {"targetId": "doc-8474a7fe:19:3"}},
        ]

        bucket = compute_failure_bucket(
            predicted_section_paths=[],
            predicted_citations=predicted_citations,
            predicted_items=predicted_items,
            gold=gold,
        )

        self.assertEqual(bucket, "hard_negative_bias")

    def test_compute_summary_groups_retrieval_score_by_variant_type(self) -> None:
        """评测汇总应输出 family、variant 与 runtime flag 视角。"""
        details = [
            {
                "quality": "correct",
                "status": "completed",
                "doc_ids": ["海港1"],
                "question_family": "harbor-1-clause-water-level",
                "variant_type": "canonical",
                "perturbation_tags": [],
                "runtime_flags": [],
                "all_scores": {
                    "retrieval": {
                        "evaluated": True,
                        "hit@5": 1.0,
                        "question_type": "locate_clause",
                        "failure_bucket": "ok",
                    }
                },
            },
            {
                "quality": "wrong",
                "status": "completed",
                "doc_ids": ["海港1"],
                "question_family": "harbor-1-clause-water-level",
                "variant_type": "noisy_symbol",
                "perturbation_tags": ["symbol-variant"],
                "runtime_flags": ["embedding_hash_fallback"],
                "all_scores": {
                    "retrieval": {
                        "evaluated": True,
                        "hit@5": 0.0,
                        "question_type": "locate_clause",
                        "failure_bucket": "missed_exact_target",
                    }
                },
            },
        ]

        summary = _compute_summary(details)

        self.assertEqual(summary["grouped_scores"]["variant_type"]["canonical"], 1.0)
        self.assertEqual(summary["grouped_scores"]["variant_type"]["noisy_symbol"], 0.0)
        self.assertEqual(summary["grouped_scores"]["question_family"]["harbor-1-clause-water-level"], 0.5)
        self.assertEqual(summary["grouped_scores"]["runtime_flag"]["embedding_hash_fallback"], 0.0)

    def test_run_prediction_preserves_runtime_flags(self) -> None:
        """检索预测结果应保留 query engine 返回的 runtime flags。"""
        evaluator = RetrievalEvaluator()
        question = {
            "question_id": "concrete-formula-variant-001",
            "question": r"混凝土规范附录C里 \varepsilon_{t,r} 这条式子在哪？",
            "library_id": "default",
            "doc_ids": ["混凝土结构设计规范"],
        }

        with patch("evals_core.runner.retrieval_eval.run_eval_query") as mock_run_eval_query:
            mock_run_eval_query.return_value = {
                "retrieved_items": [],
                "citations": [],
                "runtime_flags": ["embedding_hash_fallback", "llm_config_missing"],
            }

            prediction = evaluator.run_prediction(question)

        self.assertEqual(
            prediction["runtime_flags"],
            ["embedding_hash_fallback", "llm_config_missing"],
        )

    def test_stage_callback_preserves_runtime_flags(self) -> None:
        """阶段回调也应透传 runtime flags，便于轮询观察中间态。"""
        emitted = []
        question = {
            "question_id": "concrete-formula-variant-001",
            "question": r"混凝土规范附录C里 \varepsilon_{t,r} 这条式子在哪？",
        }
        partial = {
            "retrieved_items": [],
            "citations": [],
            "runtime_flags": ["embedding_hash_fallback"],
            "stage": "retrieval",
        }

        RetrievalEvaluator._emit_enriched_stage(question, partial, emitted.append)

        self.assertEqual(emitted[0]["runtime_flags"], ["embedding_hash_fallback"])

    def test_import_bundle_initializes_empty_eval_store(self) -> None:
        """导入基准集时应能在空 SQLite 上自动建表。"""
        payload = {
            "dataset": {
                "dataset_id": "docs-retrieval-precision-v1",
                "title": "Docs 检索精度基准集",
                "category": "knowledge",
                "description": "检索基准样本",
                "schema_version": "eval.bundle.v2",
                "version": "1.0",
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

        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = result_store._DB_PATH
            original_local = result_store._LOCAL
            original_datasets_dir = dataset_manager._DATASETS_DIR
            try:
                result_store._DB_PATH = str(Path(temp_dir) / "evals.sqlite")
                result_store._LOCAL = None
                dataset_manager._DATASETS_DIR = str(Path(temp_dir) / "datasets")

                imported = import_bundle(payload, source_file="data/evals/datasets/docs-retrieval-precision-v1.json")

                self.assertEqual(imported["dataset_id"], "docs-retrieval-precision-v1")
                self.assertEqual(imported["question_count"], 1)
                self.assertTrue(Path(result_store._DB_PATH).exists())
                self.assertTrue(Path(dataset_manager._DATASETS_DIR, "docs-retrieval-precision-v1.json").exists())
            finally:
                local = result_store._get_thread_local()
                conn = getattr(local, "conn", None)
                if conn is not None:
                    conn.close()
                dataset_manager._DATASETS_DIR = original_datasets_dir
                result_store._LOCAL = original_local
                result_store._DB_PATH = original_db_path

    def test_get_eval_run_backfills_doc_ids_from_dataset_question(self) -> None:
        """运行详情未持久化 doc_ids 时，查询运行结果仍应回填题目文档范围。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = result_store._DB_PATH
            original_local = result_store._LOCAL
            try:
                result_store._DB_PATH = str(Path(temp_dir) / "evals.sqlite")
                result_store._LOCAL = None
                result_store.init_db()
                result_store.insert_dataset({
                    "dataset_id": "docs-retrieval-precision-v1",
                    "title": "Docs 检索精度基准集",
                    "category": "knowledge",
                    "library_id": "default",
                    "question_count": 1,
                })
                result_store.insert_question({
                    "question_id": "concrete-formula-001",
                    "dataset_id": "docs-retrieval-precision-v1",
                    "question": "混凝土结构设计规范附录 C 中 ε_t,r 的公式在哪一节？",
                    "task_type": "definition",
                    "intent_level": "L1",
                    "doc_ids": ["混凝土结构设计规范"],
                    "retrieval_gold": {
                        "gold_section_paths": ["附录 C / C.2 混凝土本构关系"],
                        "gold_doc_ids": ["混凝土结构设计规范"],
                    },
                })
                run = result_store.create_run("docs-retrieval-precision-v1", 1)
                result_store.insert_run_detail({
                    "run_id": run["run_id"],
                    "question_id": "concrete-formula-001",
                    "status": "completed",
                    "quality": "wrong",
                    "scores": {"score": 0.0},
                    "all_scores": {"retrieval": {"evaluated": False}},
                })

                current = get_eval_run(run["run_id"])

                self.assertEqual(current["details"][0]["doc_ids"], ["混凝土结构设计规范"])
            finally:
                local = result_store._get_thread_local()
                conn = getattr(local, "conn", None)
                if conn is not None:
                    conn.close()
                result_store._LOCAL = original_local
                result_store._DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()

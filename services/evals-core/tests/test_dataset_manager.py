"""题集管理器的回归测试。"""

import json
import tempfile
import sys
import unittest
from pathlib import Path


EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.dataset import manager
from evals_core.storage import result_store


class DatasetManagerRoundTripTests(unittest.TestCase):
    """验证第二轮 benchmark 元数据不会在导入导出时丢失。"""

    def test_import_bundle_round_trips_variant_metadata(self) -> None:
        """导入导出题集时应保留变体与 hard-negative 元数据。"""
        payload = {
            "dataset": {
                "dataset_id": "docs-retrieval-precision-v2-test",
                "title": "docs retrieval precision v2 test",
                "schema_version": "eval.bundle.v2",
                "version": "2.0",
                "library_id": "default",
            },
            "items": [
                {
                    "question_id": "harbor-1-clause-variant-001",
                    "question": "海港1 里 6.2.7 说的航道设计通航水位要求是什么？",
                    "task_type": "retrieval",
                    "intent_level": "L2",
                    "library_id": "default",
                    "doc_ids": ["海港1"],
                    "difficulty": "medium",
                    "tags": ["harbor1", "clause"],
                    "question_family": "harbor-1-clause-water-level",
                    "canonical_question_id": "harbor-1-clause-001",
                    "variant_type": "paraphrase",
                    "perturbation_tags": ["word-order"],
                    "retrieval": {
                        "question_type": "locate_clause",
                        "gold_section_paths": ["6.2 航道建设规模及航行标准 / 6.2.7 航道设计通航水位"],
                        "gold_target_ids": ["doc-24aa8f8a:0:5:li7"],
                        "gold_target_types": ["list_procedure"],
                        "hard_negative_target_ids": ["doc-24aa8f8a:0:5:title"],
                    },
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = result_store._DB_PATH
            original_local = result_store._LOCAL
            original_datasets_dir = manager._DATASETS_DIR
            try:
                result_store._DB_PATH = str(Path(temp_dir) / "evals.sqlite")
                result_store._LOCAL = None
                manager._DATASETS_DIR = str(Path(temp_dir) / "datasets")

                manager.delete_dataset("docs-retrieval-precision-v2-test")
                manager.import_bundle(
                    payload,
                    source_file="data/evals/datasets/docs-retrieval-precision-v2-test.json",
                )
                exported = manager.export_dataset("docs-retrieval-precision-v2-test")
                item = exported["items"][0]

                self.assertEqual(item["question_family"], "harbor-1-clause-water-level")
                self.assertEqual(item["canonical_question_id"], "harbor-1-clause-001")
                self.assertEqual(item["variant_type"], "paraphrase")
                self.assertEqual(item["perturbation_tags"], ["word-order"])
                self.assertEqual(
                    item["retrieval"]["hard_negative_target_ids"],
                    ["doc-24aa8f8a:0:5:title"],
                )
            finally:
                local = result_store._get_thread_local()
                conn = getattr(local, "conn", None)
                if conn is not None:
                    conn.close()
                manager._DATASETS_DIR = original_datasets_dir
                result_store._LOCAL = original_local
                result_store._DB_PATH = original_db_path


class DatasetManagerRound2DatasetTests(unittest.TestCase):
    """验证第二轮 benchmark 文件结构稳定。"""

    def test_docs_retrieval_precision_v2_contains_harbor_round2_items(self) -> None:
        """v2 数据集应包含海港条款、图和表的 round 2 题目。"""
        with open("data/evals/datasets/docs-retrieval-precision-v2.json", "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        item_ids = {item["question_id"] for item in payload["items"]}
        self.assertIn("harbor-1-clause-001", item_ids)
        self.assertIn("harbor-1-clause-variant-001", item_ids)
        self.assertIn("harbor-2-figure-001", item_ids)
        self.assertIn("harbor-2-table-hard-negative-001", item_ids)


if __name__ == "__main__":
    unittest.main()

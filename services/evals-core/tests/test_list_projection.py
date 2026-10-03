"""题集/明细列表投影（fields=summary / fields=status）回归测试。

背景（2026-10-03 生产实测，详见 docs/evals-first-screen-latency.md）：
单题集首屏两条链路各自下载了列表根本不渲染的字节——题目列表 1040 题原始 1978 KB 中
gold 字段占 68%；运行明细 light 1211 KB 中 scores 占 84%。投影把这两块从首屏链路摘掉，
gold 与 scores 改为展开单题时按需取回（单题详情接口行为不变，仍带 scores）。
"""

import sys
import tempfile
import unittest
from pathlib import Path


EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.dataset import manager  # noqa: E402
from evals_core.storage import result_store  # noqa: E402


PAYLOAD = {
    "dataset": {
        "dataset_id": "projection-test",
        "title": "projection test",
        "schema_version": "eval.bundle.v2",
        "version": "1.0",
        "library_id": "default",
    },
    "items": [
        {
            "question_id": "q-1",
            "question": "第一题",
            "task_type": "definition",
            "intent_level": "L1",
            "library_id": "default",
            "doc_ids": ["doc-a"],
            "difficulty": "easy",
            "tags": ["tag-a"],
            "retrieval": {"gold_target_ids": ["doc-a:0:1"]},
            "answer": {"gold_answer": "答案一", "thought_process": "推理一"},
        },
        {
            "question_id": "q-2",
            "question": "第二题",
            "task_type": "retrieval",
            "intent_level": "L2",
            "library_id": "default",
            "doc_ids": [],
            "difficulty": "medium",
            "tags": [],
            "rubric": {"criteria": ["要点一"]},
        },
    ],
}

def gold_columns() -> list:
    """按库结构取全部 gold 列（不写死清单：将来新增 *_gold 列而投影漏排除，这条会直接红）。"""
    conn = result_store._get_conn()
    return [row[1] for row in conn.execute("PRAGMA table_info(eval_question)") if row[1].endswith("_gold")]

LIST_KEYS = (
    "question_id",
    "dataset_id",
    "question",
    "task_type",
    "intent_level",
    "difficulty",
    "tags",
    "library_id",
    "doc_ids",
    "sort_order",
)


class ProjectionTestBase(unittest.TestCase):
    """每个用例独占一个临时库：result_store 的连接是线程局部单例，必须复位。"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._original_db_path = result_store._DB_PATH
        self._original_local = result_store._LOCAL
        self._original_datasets_dir = manager._DATASETS_DIR
        result_store._DB_PATH = str(Path(self._temp_dir.name) / "evals.sqlite")
        result_store._LOCAL = None
        manager._DATASETS_DIR = str(Path(self._temp_dir.name) / "datasets")
        manager.import_bundle(dict(PAYLOAD), source_file="projection-test.json")

    def tearDown(self) -> None:
        local = result_store._get_thread_local()
        conn = getattr(local, "conn", None)
        if conn is not None:
            conn.close()
        manager._DATASETS_DIR = self._original_datasets_dir
        result_store._LOCAL = self._original_local
        result_store._DB_PATH = self._original_db_path
        self._temp_dir.cleanup()


class QuestionListProjectionTests(ProjectionTestBase):
    """`fields=summary`：题目列表只回列表 UI 真正渲染的列。"""

    def test_full_list_keeps_gold(self) -> None:
        """默认（不传 fields）保持全量，导出/编辑回填等既有消费方零改动。"""
        questions = result_store.list_questions("projection-test")
        by_id = {q["question_id"]: q for q in questions}
        self.assertEqual(by_id["q-1"]["answer_gold"]["gold_answer"], "答案一")
        self.assertEqual(by_id["q-1"]["retrieval_gold"]["gold_target_ids"], ["doc-a:0:1"])
        self.assertEqual(by_id["q-2"]["rubric_gold"]["criteria"], ["要点一"])

    def test_summary_list_drops_gold_but_keeps_list_fields(self) -> None:
        """summary 投影：gold 一律为 None（键保留，形状稳定），列表字段与顺序完整。"""
        questions = result_store.list_questions("projection-test", summary=True)
        self.assertEqual([q["question_id"] for q in questions], ["q-1", "q-2"])
        columns = gold_columns()
        # 防投影清单与库结构脱节：这两个列必须真在表里，否则下面的断言是空转
        self.assertIn("answer_gold", columns)
        self.assertIn("retrieval_gold", columns)
        for question in questions:
            for key in columns:
                self.assertIn(key, question, f"投影后仍应保留 {key} 键")
                self.assertIsNone(question.get(key), f"summary 投影不得回传 {key}")
            for key in LIST_KEYS:
                self.assertIn(key, question, f"summary 投影不得丢列表字段 {key}")
        self.assertEqual(questions[0]["tags"], ["tag-a"])
        self.assertEqual(questions[0]["doc_ids"], ["doc-a"])
        self.assertEqual(questions[1]["intent_level"], "L2")

    def test_page_projection_matches_full_page_fields(self) -> None:
        """分页路径同样支持 summary，且 total 不受投影影响。"""
        page, total = result_store.list_questions_page(
            "projection-test", 0, 1, summary=True,
        )
        self.assertEqual(total, 2)
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0]["question_id"], "q-1")
        self.assertIsNone(page[0]["answer_gold"])

        full_page, full_total = result_store.list_questions_page("projection-test", 0, 1)
        self.assertEqual(full_total, 2)
        self.assertEqual(full_page[0]["answer_gold"]["gold_answer"], "答案一")

    def test_manager_passthrough_and_single_question(self) -> None:
        """manager 透传 summary；单题接口返回完整 gold（展开时按需取回的那一份）。"""
        summary = manager.list_questions("projection-test", summary=True)
        self.assertIsNone(summary[0]["answer_gold"])

        question = manager.get_question("projection-test", "q-1")
        self.assertIsNotNone(question)
        self.assertEqual(question["answer_gold"]["gold_answer"], "答案一")
        self.assertEqual(question["retrieval_gold"]["gold_target_ids"], ["doc-a:0:1"])
        self.assertIsNone(manager.get_question("projection-test", "not-exist"))


class RunDetailProjectionTests(ProjectionTestBase):
    """`fields=status`：运行明细只回状态染色需要的列（去 scores）。"""

    RUN_ID = ""

    def setUp(self) -> None:
        super().setUp()
        created = result_store.create_run("projection-test", 2, run_name="proj")
        self.RUN_ID = created["run_id"]
        result_store.insert_run_detail({
            "run_id": self.RUN_ID,
            "question_id": "q-1",
            "status": "completed",
            "quality": "correct",
            "prediction": {"answer": "模型答案" * 50},
            "scores": {"score": 1.0, "semantic_reason": "判分理由" * 50},
            "all_scores": {"answer": {"score": 1.0}},
            "all_predictions": {"retrieval": {"text": "快照" * 50}},
            "error": None,
            "latency_ms": 1234,
        })

    def test_status_projection_drops_scores_only(self) -> None:
        """status 投影：status/quality/error/latency_ms 保留，scores 不再回传。"""
        rows = result_store.list_run_details(self.RUN_ID, projection="status")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["question_id"], "q-1")
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["quality"], "correct")
        self.assertEqual(row["latency_ms"], 1234)
        self.assertNotIn("scores", row)
        self.assertNotIn("prediction", row)
        self.assertNotIn("all_scores", row)
        self.assertNotIn("all_predictions", row)

    def test_light_still_carries_scores(self) -> None:
        """既有 light 语义不变（单题详情/题集卡等消费方仍按 light 取分）。"""
        rows = result_store.list_run_details(self.RUN_ID, light=True)
        self.assertEqual(rows[0]["scores"]["score"], 1.0)
        self.assertNotIn("prediction", rows[0])

    def test_get_eval_run_passthrough_keeps_enrichment(self) -> None:
        """路由层投影：get_eval_run 仍补齐题目元信息，只是不再回传 scores。"""
        from evals_core.runner import suite_runner

        run = suite_runner.get_eval_run(self.RUN_ID, projection="status")
        self.assertEqual(run["run_id"], self.RUN_ID)
        detail = run["details"][0]
        self.assertEqual(detail["question"], "第一题")
        self.assertEqual(detail["intent_level"], "L1")
        self.assertNotIn("scores", detail)


if __name__ == "__main__":
    unittest.main()

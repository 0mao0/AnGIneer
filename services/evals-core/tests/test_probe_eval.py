"""探针题（probe 断言块）入库往返 + 评测器断言语义。

背景（2026-09-29）：clause-probe-v1 建成时 probe 块不在 bundle schema，入库即丢，
UI 点运行拿不到断言、又没有金标答案 → 无评价。现 probe 随题集入库
（eval_question.probe_gold），断言逻辑收口 evals_core.runner.probe_eval。
"""
import sys
import unittest
from pathlib import Path

import pytest

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.dataset import manager
from evals_core.runner import probe_eval
from evals_core.runner.probe_eval import ProbeEvaluator, run_probe_item
from evals_core.runner.suite_runner import _decide_quality, _determine_evaluator_names
from evals_core.storage import result_store


def _clause_item(doc_id: str, text: str) -> dict:
    return {"doc_id": doc_id, "text": text, "retrieval_policy": "clause_direct"}


def _plain_item(doc_id: str, text: str = "普通块") -> dict:
    return {"doc_id": doc_id, "text": text, "retrieval_policy": "semantic"}


# --- 断言语义（与 scripts/clause_probe.py 历史行为对齐） ---


def test_pass_all_checks_ok():
    probe = {"expect_clause_direct": True, "top_clause_docs": ["doc-a"],
             "gold_num": "6.2.7", "gold_doc_for_num": ["doc-a"], "precise_rank_max": 4}
    items = [_plain_item("doc-x"), _clause_item("doc-a", "6.2.7 航道设计通航水位…")]
    outcome = run_probe_item({"probe": probe}, items)
    assert outcome["status"] == "PASS"
    assert not outcome["failed"]
    assert outcome["checks"]["precise_rank"].startswith("ok(rank=2)")


def test_fail_direct_missing():
    probe = {"expect_clause_direct": True}
    outcome = run_probe_item({"probe": probe}, [_plain_item("doc-x")])
    assert outcome["status"] == "FAIL"
    assert outcome["failed"] == ["clause_direct"]


def test_guard_negative_expects_no_direct():
    """反例题：期望无直达，实际无直达 → PASS。"""
    outcome = run_probe_item({"probe": {"expect_clause_direct": False}}, [_plain_item("doc-x")])
    assert outcome["status"] == "PASS"


def test_xfail_gap_still_open_vs_fixed():
    probe = {"expect_clause_direct": True, "xfail": True}
    assert run_probe_item({"probe": probe}, [])["status"] == "XFAIL-OK"
    assert run_probe_item({"probe": probe}, [_clause_item("doc-a", "x")])["status"].startswith("XPASS")


# --- 评测器：quality 映射与路由 ---


def test_probe_questions_route_exclusive(monkeypatch):
    question = {"probe_gold": {"expect_clause_direct": True}, "answer_gold": {"gold_answer": "x"}}
    assert _determine_evaluator_names(question) == ["probe"]


@pytest.fixture()
def fake_retriever():
    items = [_clause_item("doc-a", "6.2.7 条文")]
    probe_eval.set_retriever(lambda **kw: {"items": items})
    yield
    probe_eval.set_retriever(None)


def test_evaluator_score_maps_to_quality(fake_retriever):
    ev = ProbeEvaluator()
    question = {"question": "6.2.7 条？", "library_id": "default",
                "probe_gold": {"expect_clause_direct": True, "top_clause_docs": ["doc-a"],
                               "gold_num": "6.2.7", "gold_doc_for_num": ["doc-a"], "precise_rank_max": 4}}
    prediction = ev.run_prediction(question)
    scores = ev.evaluate(question, question["probe_gold"], prediction)
    assert scores["evaluated"] and scores["score"] == 1.0
    assert _decide_quality("probe", {"probe": scores}) == ("completed", "correct")


def test_evaluator_fail_is_wrong(fake_retriever):
    ev = ProbeEvaluator()
    question = {"question": "x", "probe_gold": {"expect_clause_direct": True, "top_clause_docs": ["doc-z"]}}
    scores = ev.evaluate(question, question["probe_gold"], ev.run_prediction(question))
    assert scores["status"] == "FAIL" and scores["score"] < 0.8
    assert _decide_quality("probe", {"probe": scores}) == ("completed", "wrong")


def test_missing_retriever_errors_not_silent():
    probe_eval.set_retriever(None)
    prediction = ProbeEvaluator().run_prediction({"question": "x"})
    assert "error" in prediction and "set_retriever" in prediction["error"]


# --- 入库往返：probe 块不再丢 ---


class ProbeIngestRoundTrip(unittest.TestCase):

    def test_probe_block_survives_import_export(self) -> None:
        import tempfile

        payload = {
            "dataset": {"dataset_id": "probe-roundtrip-test", "title": "probe roundtrip"},
            "items": [
                {
                    "question_id": "cp-rt-001",
                    "question": "6.2.7 条要求是什么？",
                    "task_type": "retrieval",
                    "probe": {"expect_clause_direct": True, "gold_num": "6.2.7",
                              "gold_doc_for_num": ["doc-a"], "precise_rank_max": 4},
                },
                {
                    "question_id": "cp-rt-002",
                    "question": "普通题",
                    "task_type": "definition",
                    "answer": {"gold_answer": "普通答案"},
                },
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

                manager.delete_dataset("probe-roundtrip-test")
                manager.import_bundle(payload)

                questions = result_store.list_questions("probe-roundtrip-test")
                by_id = {q["question_id"]: q for q in questions}
                self.assertEqual(by_id["cp-rt-001"]["probe_gold"]["gold_num"], "6.2.7")
                self.assertIsNone(by_id["cp-rt-002"].get("probe_gold"))

                exported = manager.export_dataset("probe-roundtrip-test")
                exported_items = {i["question_id"]: i for i in exported["items"]}
                self.assertEqual(
                    exported_items["cp-rt-001"]["probe"]["precise_rank_max"], 4)
                self.assertNotIn("probe", exported_items["cp-rt-002"])

                # runner 拿到的行能路由到 probe 评测器
                self.assertEqual(_determine_evaluator_names(by_id["cp-rt-001"]), ["probe"])
                self.assertNotIn("probe", _determine_evaluator_names(by_id["cp-rt-002"]))
            finally:
                local = result_store._get_thread_local()
                conn = getattr(local, "conn", None)
                if conn is not None:
                    conn.close()
                manager._DATASETS_DIR = original_datasets_dir
                result_store._LOCAL = original_local
                result_store._DB_PATH = original_db_path

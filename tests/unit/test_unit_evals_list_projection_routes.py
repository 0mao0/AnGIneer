"""题集列表投影接口测试：GET /datasets/{id}/questions?fields=summary、
GET /datasets/{id}/questions/{qid}、GET /runs/{rid}?fields=status。

背景见 docs/evals-first-screen-latency.md：单题集首屏曾把 gold（占列表载荷 68-84%）
与 scores（占明细载荷 84%）全量下发，而列表页一处都不渲染。投影把这两块移出首屏链路，
默认行为保持不变（导出/runner/nightly 等消费方零改动）。
"""
import gc
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for rel in (
    "services/aichat-api",
    "services/evals-core/src",
    "services/angineer-core/src",
    "services/ai-inference/src",
    "services/sop-core/src",
):
    p = os.path.join(ROOT, rel)
    if p not in sys.path:
        sys.path.insert(0, p)

# chat_auth 依赖 models.user（docs-api 侧）——与 test_unit_evals_nightly_routes 同法用桩顶掉
_chat_auth_stub = types.ModuleType("chat_auth")
_chat_auth_stub.resolve_session_principal = lambda request: False
sys.modules.setdefault("chat_auth", _chat_auth_stub)

import evals_routes  # noqa: E402
from evals_core.dataset import manager  # noqa: E402
from evals_core.storage import result_store  # noqa: E402


PAYLOAD = {
    "dataset": {
        "dataset_id": "proj-routes",
        "title": "投影路由测试集",
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
            "answer": {"gold_answer": "答案一"},
            "retrieval": {"gold_target_ids": ["doc-a:0:1"]},
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
        },
    ],
}

def gold_columns() -> list:
    """按库结构取全部 gold 列（不写死清单：将来新增 *_gold 列而投影漏排除，这条会直接红）。"""
    conn = result_store._get_conn()
    return [row[1] for row in conn.execute("PRAGMA table_info(eval_question)") if row[1].endswith("_gold")]


class ListProjectionRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.eval_dir = Path(self.tmp.name) / "evals"
        self.eval_dir.mkdir()
        self.db_patch = mock.patch.object(
            evals_routes.result_store, "_DB_PATH", str(self.eval_dir / "evals.sqlite"),
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        # 连接是线程局部缓存的、不随 _DB_PATH 自动切换：不复位会把上个用例（乃至真实库）的连接带进来
        self._local_patch = mock.patch.object(evals_routes.result_store, "_LOCAL", None)
        self._local_patch.start()
        self.addCleanup(self._local_patch.stop)

        datasets_dir = mock.patch.object(manager, "_DATASETS_DIR", str(self.eval_dir / "datasets"))
        datasets_dir.start()
        self.addCleanup(datasets_dir.stop)

        manager.import_bundle(dict(PAYLOAD), source_file="proj-routes.json")
        self.run_id = result_store.create_run("proj-routes", 2, run_name="proj")["run_id"]
        result_store.insert_run_detail({
            "run_id": self.run_id,
            "question_id": "q-1",
            "status": "completed",
            "quality": "correct",
            "scores": {"score": 1.0, "semantic_reason": "判分理由"},
            "prediction": {"answer": "模型答案"},
            "latency_ms": 42,
        })

    def tearDown(self):
        conn = getattr(result_store._get_thread_local(), "conn", None)
        if conn is not None:
            conn.close()
        result_store._LOCAL = None
        # TestClient 的请求跑在 portal 线程里，那个线程的连接随线程结束释放；
        # 这里补一次 GC，避免 Windows 上临时目录删除时 "文件被占用"
        gc.collect()

    @contextmanager
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(evals_routes.evals_router, prefix="/api/evals")
        # 必须当上下文用：退出时关掉 portal 线程与其 sqlite 连接，
        # 否则 Windows 上临时目录里那个 evals.sqlite 一直被占着删不掉
        with TestClient(app, base_url="http://test") as client:
            yield client

    def test_questions_default_keeps_gold(self):
        """不传 fields 保持全量：导出、runner、nightly 等既有消费方零改动。"""
        with self._client() as client:
            r = client.get("/api/evals/datasets/proj-routes/questions")
        self.assertEqual(r.status_code, 200)
        questions = r.json()["questions"]
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["answer_gold"]["gold_answer"], "答案一")
        self.assertEqual(questions[0]["retrieval_gold"]["gold_target_ids"], ["doc-a:0:1"])

    def test_questions_summary_drops_gold(self):
        """fields=summary：gold 一律 None，列表字段完整（这是题集首屏走的那条）。"""
        with self._client() as client:
            r = client.get("/api/evals/datasets/proj-routes/questions?fields=summary")
        self.assertEqual(r.status_code, 200)
        questions = r.json()["questions"]
        self.assertEqual([q["question_id"] for q in questions], ["q-1", "q-2"])
        columns = gold_columns()
        self.assertIn("answer_gold", columns)
        self.assertIn("retrieval_gold", columns)
        for question in questions:
            for key in columns:
                self.assertIsNone(question.get(key), f"summary 投影不得回传 {key}")
            self.assertIn("intent_level", question)
            self.assertIn("doc_ids", question)
        self.assertEqual(questions[0]["tags"], ["tag-a"])

    def test_questions_summary_with_paging_and_filter(self):
        """投影与分页/筛选可叠加，total 为筛选后总数。"""
        with self._client() as client:
            r = client.get(
                "/api/evals/datasets/proj-routes/questions?fields=summary&offset=0&limit=1&level=L2"
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(len(body["questions"]), 1)
        self.assertEqual(body["questions"][0]["question_id"], "q-2")
        self.assertIsNone(body["questions"][0]["answer_gold"])

    def test_single_question_returns_gold(self):
        """展开/编辑按需取回的原文接口：gold 完整在此。"""
        with self._client() as client:
            r = client.get("/api/evals/datasets/proj-routes/questions/q-1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["question_id"], "q-1")
        self.assertEqual(body["answer_gold"]["gold_answer"], "答案一")
        self.assertEqual(body["retrieval_gold"]["gold_target_ids"], ["doc-a:0:1"])

    def test_single_question_404(self):
        with self._client() as client:
            r = client.get("/api/evals/datasets/proj-routes/questions/not-exist")
        self.assertEqual(r.status_code, 404)

    def test_run_status_projection_drops_scores(self):
        """fields=status：逐题状态在，scores 不在（题集首屏与轮询只读状态）。"""
        with self._client() as client:
            r = client.get(f"/api/evals/runs/{self.run_id}?fields=status")
        self.assertEqual(r.status_code, 200)
        detail = r.json()["details"][0]
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(detail["quality"], "correct")
        self.assertEqual(detail["question"], "第一题")
        self.assertNotIn("scores", detail)

    def test_run_light_still_carries_scores(self):
        """light 语义不变：单题详情/题集卡等仍按 light 取分。"""
        with self._client() as client:
            r = client.get(f"/api/evals/runs/{self.run_id}?light=1")
        self.assertEqual(r.status_code, 200)
        detail = r.json()["details"][0]
        self.assertEqual(detail["scores"]["score"], 1.0)


if __name__ == "__main__":
    unittest.main()

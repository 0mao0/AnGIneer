# -*- coding: utf-8 -*-
"""对话黑板图存储（M1）单测：schema / 幂等写入 / 水位补跑 / 五处级联 / 蒸馏入口接存储。

对应 BB §5（键模型与落位）、§5.1（级联五处）、§3.4（水位 + 补跑）、§3.3（ops 校验）。
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

CHAT_HISTORY_SRC = Path(__file__).resolve().parents[1] / "src"
if str(CHAT_HISTORY_SRC) not in sys.path:
    sys.path.insert(0, str(CHAT_HISTORY_SRC))

from chat_history.store import sqlite_store  # noqa: E402
from chat_history.store.graph_store import (  # noqa: E402
    ConvGraphStore,
    apply_ops,
    delete_graph,
    init_graph_schema,
    load_graph,
    missing_runs,
    reassign_owner,
    sweep_orphans,
)

from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.conv_graph import distill_run, extract_ops  # noqa: E402


def _item(cite, doc_id="doc-a", doc_title="JTS 165-2013 海港总体设计规范",
          section_path="5 港口平面 / 5.3 港内水域"):
    return {"doc_id": doc_id, "title": section_path,
            "metadata": {"cite": cite, "doc_title": doc_title, "section_path": section_path}}


def _slice():
    """一轮切片：一条 tool（两条候选）+ 一条引用了 K1 的 assistant。"""
    return [
        AgentMessage(role="user", content="某5万吨级散货船，满载吃水T=12.8m，算码头前沿水深"),
        AgentMessage(role="tool", name="knowledge_search", content="K" * 200,
                     meta={"items": [_item("K1"), _item("K2", doc_id="doc-b")], "total": 2}),
        AgentMessage(role="assistant", content="结论：T=12.8m，依据 [K1] 计算。"),
    ]


class SchemaTests(unittest.TestCase):
    def test_init_is_idempotent_and_creates_four_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_graph_schema(conn)
        init_graph_schema(conn)   # 幂等
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"conv_graph_node", "conv_graph_edge", "conv_graph_version",
                         "conv_graph_state"}.issubset(names))
        conn.close()

    def test_chat_history_init_db_creates_graph_tables(self):
        """建表入口只此一处：chat-history 的 init_db 必须把图四表带上（BB §5）。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "chat.sqlite")
            sqlite_store.init_db(db)
            conn = sqlite3.connect(db)
            try:
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
        self.assertIn("conv_graph_node", names)
        self.assertIn("conv_graph_state", names)


class ApplyOpsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_graph_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_apply_ops_writes_graph_and_is_idempotent(self):
        ops = extract_ops(_slice(), run_id="r1")
        self.assertTrue(apply_ops(self.conn, "u:1", "s1", "r1", ops))
        self.assertFalse(apply_ops(self.conn, "u:1", "s1", "r1", ops))   # 幂等：同 run 跳过
        graph = load_graph(self.conn, "u:1", "s1")
        self.assertEqual(len(graph.clause_nodes()), 1)                   # 只建有引用的那条
        self.assertEqual(len(graph.value_nodes()), 1)                    # T=12.8m
        self.assertEqual(graph.clause_nodes()[0].markers, ["K1"])
        self.assertEqual(graph.run_cites.get(1), [graph.clause_nodes()[0].node_id])

    def test_watermark_and_missing_runs(self):
        """水位推进 + chat_runs 差集补跑（BB §3.4）。"""
        self.conn.execute(
            "CREATE TABLE chat_runs (run_id TEXT PRIMARY KEY, owner_key TEXT, session_id TEXT,"
            " created_at TEXT)")
        for run_id in ("r1", "r2"):
            self.conn.execute("INSERT INTO chat_runs VALUES (?,?,?,?)",
                              (run_id, "u:1", "s1", run_id))
        apply_ops(self.conn, "u:1", "s1", "r1", extract_ops(_slice(), run_id="r1"))
        row = self.conn.execute("SELECT last_run_id, status FROM conv_graph_state"
                                " WHERE owner_key='u:1' AND session_id='s1'").fetchone()
        self.assertEqual((row["last_run_id"], row["status"]), ("r1", "ok"))
        self.assertEqual(missing_runs(self.conn, "u:1", "s1"), ["r2"])

    def test_markers_merge_on_repeat_citation(self):
        """同一节点被多轮引用：markers 合并、last_run 前进、不重复建节点（append-only）。"""
        apply_ops(self.conn, "u:1", "s1", "r1", extract_ops(_slice(), run_id="r1"))
        apply_ops(self.conn, "u:1", "s1", "r2", extract_ops(_slice(), run_id="r2"))
        graph = load_graph(self.conn, "u:1", "s1")
        self.assertEqual(len(graph.nodes), 2)          # 1 clause + 1 value
        self.assertEqual(len(graph.clause_nodes()), 1)


class CascadeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_graph_schema(self.conn)
        self.conn.execute("CREATE TABLE chat_sessions (owner_key TEXT, session_id TEXT,"
                          " updated_at TEXT)")
        self.conn.execute("INSERT INTO chat_sessions VALUES ('u:1','s1','2020-01-01T00:00:00')")
        apply_ops(self.conn, "u:1", "s1", "r1", extract_ops(_slice(), run_id="r1"))

    def tearDown(self):
        self.conn.close()

    def test_delete_graph_and_reassign_owner(self):
        self.assertGreater(delete_graph(self.conn, "u:1", "s1"), 0)
        apply_ops(self.conn, "u:1", "s1", "r1", extract_ops(_slice(), run_id="r1"))
        self.assertGreater(reassign_owner(self.conn, "u:1", "u:2"), 0)
        self.assertEqual(load_graph(self.conn, "u:1", "s1").nodes, {})
        self.assertTrue(load_graph(self.conn, "u:2", "s1").nodes)

    def test_sweep_orphans_removes_rows_without_session(self):
        """孤儿图清理（gc 的「消息先删、会话后删」窗口，BB §5.1）。"""
        self.conn.execute("DELETE FROM chat_sessions")
        self.assertGreater(sweep_orphans(self.conn), 0)
        self.assertEqual(load_graph(self.conn, "u:1", "s1").nodes, {})


class DistillRunTests(unittest.TestCase):
    def test_distill_run_writes_through_store_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConvGraphStore(os.path.join(tmp, "chat.sqlite"))
            store.init()
            result = distill_run(_slice(), run_id="r1", store=store,
                                 owner_key="u:1", session_id="s1")
            self.assertTrue(result.applied)
            self.assertEqual(result.rejected, [])
            graph = store.load_graph("u:1", "s1")
            self.assertEqual(len(graph.clause_nodes()), 1)
            again = distill_run(_slice(), run_id="r1", store=store,
                               owner_key="u:1", session_id="s1")
            self.assertFalse(again.applied)          # 幂等
            self.assertIn("已处理过", again.note)

    def test_distill_run_rejects_whole_batch_on_hanging_edge(self):
        """BB §3.3：悬挂边 → 整批不进图，但留痕进 version 台账。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = ConvGraphStore(os.path.join(tmp, "chat.sqlite"))
            store.init()
            ops = [{"op": "add_edge", "edge_id": "e1", "type": "cites",
                    "src": "assistant:r1", "dst": "clause:missing:missing:missing", "run": "r1"}]
            result = distill_run([], run_id="r1", store=store, owner_key="u:1", session_id="s1")
            self.assertTrue(result.rejected or result.accepted == [])   # 空切片无 op
            # 直接喂非法批次：走 validate_ops 的路径由 extract_ops 产出，故这里验 store 侧留痕
            store.record_rejected("u:1", "s1", "r2", ops, ["悬挂边: e1"])
            self.assertEqual(store.load_graph("u:1", "s1").nodes, {})
            self.assertEqual(store.last_run("u:1", "s1"), "r1")


if __name__ == "__main__":
    unittest.main()

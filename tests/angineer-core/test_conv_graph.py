# -*- coding: utf-8 -*-
"""对话黑板引擎内核单测：确定性蒸馏 / ops 校验 / 召回渲染 / 读路径 transformer。

纪律：开关关态必须与现状**逐字一致**（生产里「臂 1 = 现状」）；图上无节点**不许移除证据**
（BB 2026-10-04 干跑护栏）；子图段插在**本轮提问之前**（BB §2 段序）。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ANGINEER_CORE_SRC = Path(__file__).resolve().parents[1] / ".." / "angineer-core" / "src"
if str(ANGINEER_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(ANGINEER_CORE_SRC))

from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.conv_graph import (  # noqa: E402
    Graph,
    Node,
    build_graph,
    distill_run,
    extract_ops,
    make_conv_graph_transformer,
    recall,
    render,
    validate_ops,
)


def _item(cite, doc_id="doc-a", doc_title="JTS 165-2013 海港总体设计规范",
          section_path="5 港口平面 / 5.3 港内水域"):
    return {"doc_id": doc_id, "title": section_path,
            "metadata": {"cite": cite, "doc_title": doc_title, "section_path": section_path}}


def _slice(items=None, assistant="结论：T=12.8m，依据 [K1] 计算。"):
    return [
        AgentMessage(role="user", content="某5万吨级散货船，满载吃水T=12.8m，算码头前沿水深"),
        AgentMessage(role="tool", name="knowledge_search", content="K" * 200,
                     meta={"items": items if items is not None else [_item("K1"), _item("K2", doc_id="doc-b")],
                           "total": 2}),
        AgentMessage(role="assistant", content=assistant),
    ]


class ExtractOpsTests(unittest.TestCase):
    def test_only_cited_items_become_clause_nodes(self):
        ops = extract_ops(_slice(), run_id="r1")
        nodes = [op for op in ops if op["op"] == "add_node"]
        clause_nodes = [op for op in nodes if op.get("kind") == "clause"]
        self.assertEqual(len(clause_nodes), 1)                 # 只有 K1 被引用
        self.assertIn("JTS 165-2013", clause_nodes[0]["key"])
        self.assertEqual([op for op in ops if op["op"] == "add_edge"][0]["type"], "cites")

    def test_value_node_requires_unit_and_source_text(self):
        with_unit = [op for op in extract_ops(_slice(), run_id="r1")
                     if op["op"] == "add_node" and op.get("kind") == "value"]
        self.assertEqual([op["key"] for op in with_unit], ["T=12.8m"])
        no_unit = [op for op in extract_ops(_slice(assistant="结论：T=12.8，依据 [K1]。"), run_id="r1")
                   if op["op"] == "add_node" and op.get("kind") == "value"]
        self.assertEqual(no_unit, [])

    def test_derives_edge_links_value_to_cited_clause(self):
        ops = extract_ops(_slice(), run_id="r1")
        derives = [op for op in ops if op["op"] == "add_edge" and op["type"] == "derives"]
        self.assertEqual(len(derives), 1)


class ValidateOpsTests(unittest.TestCase):
    def test_hanging_edge_rejected_but_structural_src_allowed(self):
        good = extract_ops(_slice(), run_id="r1")
        accepted, rejected, notes = validate_ops(good, assistant_text="结论：T=12.8m，依据 [K1] 计算。")
        self.assertEqual(rejected, [])
        self.assertEqual(notes, [])
        self.assertTrue(any(op["op"] == "add_edge" and op["src"].startswith("assistant:")
                            for op in accepted))
        hanging = [{"op": "add_edge", "edge_id": "e1", "type": "cites",
                    "src": "assistant:r1", "dst": "clause:missing:x:y", "run": "r1"}]
        accepted2, rejected2, _notes2 = validate_ops(hanging, existing_node_ids=[])
        self.assertEqual(accepted2, [])
        self.assertTrue(rejected2)

    def test_unitless_value_and_illegal_op_rejected(self):
        ops = [
            {"op": "add_node", "node_id": "value:x:1", "kind": "value", "key": "x=1", "run": "r1"},
            {"op": "delete_everything", "node_id": "z"},
        ]
        accepted, rejected, _notes = validate_ops(ops, existing_node_ids=[], assistant_text="x=1")
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 2)

    def test_batch_cap_truncates_instead_of_rejecting(self):
        """容量超限 = 截断 + 注记，**不是**致命拒收（2026-10-05 端到端实测：真实单轮 22~60 条 op，
        按「超限即拒收」会让 7/19 轮整轮丢图）。"""
        ops = [{"op": "add_node", "node_id": f"clause:a:d{i}:s", "kind": "clause",
                "key": f"k{i}", "run": "r1"} for i in range(30)]
        accepted, rejected, notes = validate_ops(ops, existing_node_ids=[], max_ops=20)
        self.assertEqual(rejected, [])                 # 无致命错误
        self.assertEqual(len(accepted), 20)            # 截断
        self.assertTrue(any("超上限" in note for note in notes))

    def test_html_tags_stripped_and_keys_clipped(self):
        """实测 <sub> 标签会进节点 key；section_path 可能是整句——都要在节点层收口。"""
        item = _item("K1", section_path="3<sub>.</sub> 4 码头设计水位和高程" + "很长" * 40)
        ops = extract_ops([
            AgentMessage(role="tool", name="knowledge_search", content="K" * 10,
                         meta={"items": [item], "total": 1}),
            AgentMessage(role="assistant", content="见 [K1]。"),
        ], run_id="r1")
        node = [op for op in ops if op["op"] == "add_node"][0]
        self.assertNotIn("<sub>", node["key"])
        self.assertNotIn("<sub>", node["locator"])
        self.assertLessEqual(len(node["locator"]), 40)
        self.assertTrue(node["locator"].endswith("…"))


class DistillEntryTests(unittest.TestCase):
    def test_without_store_returns_ops_only(self):
        result = distill_run(_slice(), run_id="r1")
        self.assertFalse(result.applied)
        self.assertTrue(result.accepted)
        self.assertIn("仅返回 ops", result.note)


class FakeStore:
    def __init__(self, graph):
        self._graph = graph
        self.applied = []

    def load_graph(self, owner_key, session_id):
        return self._graph

    def apply_ops(self, owner_key, session_id, run_id, ops, *, scope_hash="", library_ids=None):
        self.applied.append((run_id, list(ops)))
        return True

    def record_rejected(self, *args, **kwargs):
        return None


def _graph_with_one_clause():
    graph = Graph()
    node = Node(node_id="clause:-:doc-a:5.3 港内水域", kind="clause",
                key="JTS 165-2013 海港总体设计规范/5.3 港内水域",
                doc_id="doc-a", locator="5.3 港内水域",
                doc_title="JTS 165-2013 海港总体设计规范", first_run=1, last_run=1,
                markers=["K1"])
    graph.nodes[node.node_id] = node
    graph.runs = [1]
    graph.run_cites = {1: [node.node_id]}
    return graph


class TransformerTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            AgentMessage(role="user", content="第一问"),
            AgentMessage(role="tool", name="knowledge_search", content="T" * 4000, meta={"items": []}),
            AgentMessage(role="assistant", content="答：见 [K1]。"),
            AgentMessage(role="user", content="刚才第二条提到的规范，具体说了什么？"),
        ]

    def test_disabled_state_is_untouched(self):
        store = FakeStore(_graph_with_one_clause())
        with mock.patch.dict(os.environ, {"ANGINEER_CONV_GRAPH": "0"}):
            out = make_conv_graph_transformer(store, owner_key="u:1", session_id="s1")(self.messages)
        self.assertEqual([m.content for m in out], [m.content for m in self.messages])

    def test_enabled_drops_history_tool_and_injects_segment_before_question(self):
        store = FakeStore(_graph_with_one_clause())
        with mock.patch.dict(os.environ, {"ANGINEER_CONV_GRAPH": "1"}):
            out = make_conv_graph_transformer(store, owner_key="u:1", session_id="s1")(self.messages)
        contents = [m.content for m in out]
        self.assertNotIn("T" * 4000, contents)                     # 历史 tool 原文移出
        segment_index = next(i for i, c in enumerate(contents)
                             if c.startswith("【会话记忆·相关子图】"))
        self.assertEqual(segment_index, contents.index(self.messages[-1].content) - 1)
        self.assertNotIn("[K1]", contents[segment_index])           # 自描述，不带标记

    def test_enabled_keeps_evidence_when_graph_empty(self):
        store = FakeStore(Graph())
        with mock.patch.dict(os.environ, {"ANGINEER_CONV_GRAPH": "1"}):
            out = make_conv_graph_transformer(store, owner_key="u:1", session_id="s1")(self.messages)
        self.assertIn("T" * 4000, [m.content for m in out])         # 护栏：空图不移除证据


class RecallRenderTests(unittest.TestCase):
    def test_render_includes_issue_and_respects_cap(self):
        graph = _graph_with_one_clause()
        graph.nodes["issue:z4"] = Node(node_id="issue:z4", kind="issue", key="备淤深度 Z4 待确认",
                                       last_run=2, status="open")
        text = render(recall(graph, "刚才第二条提到的规范"), max_chars=400)
        self.assertIn("条款｜", text)
        self.assertIn("未决｜", text)
        self.assertLessEqual(len(text), 400)

    def test_build_graph_from_messages_matches_ops_path(self):
        graph = build_graph(_slice())
        self.assertEqual(len(graph.clause_nodes()), 1)
        self.assertEqual(graph.clause_nodes()[0].markers, ["K1"])
        self.assertEqual(len(graph.value_nodes()), 1)


if __name__ == "__main__":
    unittest.main()

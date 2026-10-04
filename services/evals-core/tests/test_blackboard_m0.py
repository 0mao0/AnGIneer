# -*- coding: utf-8 -*-
"""对话黑板 M0 离线壳单测：题集保真 / 三臂组装 / 离线图 / 闸门度量。

纪律：题集必须与 chat.sqlite **逐字**一致（arms §3 复现口径）；臂 1 必须等于生产压缩器的
关态输出（「臂 1 = 现状」的机器化保证）；臂 3 必须真的把历史 tool 原文移出并自带子图段。
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

EVALS_CORE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(EVALS_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(EVALS_CORE_SRC))

from evals_core.blackboard.arms import (  # noqa: E402
    ALL_ARMS,
    ARM_A_MIN,
    ARM_GRAPH,
    ARM_POINTER,
    compose,
    compose_all,
    estimate,
)
from evals_core.blackboard.cases import CASES, cases_by_kind  # noqa: E402
from evals_core.blackboard.graph import build_graph, recall, render  # noqa: E402
from evals_core.blackboard.runner import case_fidelity, resolve_chat_db, run_dry  # noqa: E402

from angineer_core.agent_configs import make_budget_transformer  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402

DB_PATH = resolve_chat_db()
DB_AVAILABLE = os.path.exists(DB_PATH)


def _tool_message(items_json=None, content="K" * 5000, name="knowledge_search"):
    raw = items_json if items_json is not None else {"items": [], "total": 0}
    return AgentMessage(role="tool", name=name, content=content,
                        meta=dict(raw, name=name, tool_call_id="call-1"))


def _item(cite, doc_id="doc-a", doc_title="JTS 165-2013 海港总体设计规范",
          section_path="5 港口平面 / 5.3 港内水域"):
    return {"doc_id": doc_id, "title": section_path,
            "metadata": {"cite": cite, "doc_title": doc_title, "section_path": section_path}}


class CaseListTests(unittest.TestCase):
    def test_case_list_shape(self):
        """主集 22 题、四类齐全、D5 合成题不入主集。"""
        self.assertEqual(len(CASES), 22)
        self.assertEqual(len(cases_by_kind("A")), 7)
        self.assertEqual(len(cases_by_kind("B")), 5)
        self.assertEqual(len(cases_by_kind("C")), 6)
        self.assertEqual(len(cases_by_kind("D")), 4)
        self.assertNotIn("D5", [case.case_id for case in CASES])

    @unittest.skipUnless(DB_AVAILABLE, "需要本地 chat.sqlite")
    def test_case_questions_match_db_verbatim(self):
        """每条题面必须与库内 (session_id, seq) 的 user 消息逐字一致（预注册的可复核性）。"""
        import sqlite3

        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            bad = [check for check in (case_fidelity(conn, case) for case in CASES)
                   if not check["match"]]
        finally:
            conn.close()
        self.assertEqual(bad, [], f"题面与库不一致: {bad}")


class ArmCompositionTests(unittest.TestCase):
    def setUp(self):
        self.items = {"items": [_item("K1"),
                                _item("K2", doc_id="doc-b",
                                      section_path="7 斜坡式护岸设计 / 7.1 一般规定")],
                      "total": 2}
        self.history = [
            AgentMessage(role="user", content="什么是乘潮水位？"),
            _tool_message(self.items),
            AgentMessage(role="assistant", content="乘潮水位是……见 [K1][K2]。"),
            AgentMessage(role="user", content="刚才第二条提到的规范，具体说了什么？"),
        ]

    def test_arm1_equals_production_compressor_off(self):
        """臂 1 关态必须与生产压缩器输出**逐字一致**——这是「臂 1 = 现状」的机器化保证。"""
        with mock.patch.dict(os.environ, {"ANGINEER_POINTER_SKELETON": "0"}):
            expected = make_budget_transformer(max_tokens_est=200, protect_current_run=True)(
                list(self.history))
        result = compose("X", self.history[-1].content, self.history, ARM_A_MIN, budget_est=200)
        self.assertEqual([m.content for m in result.messages], [m.content for m in expected])
        self.assertEqual(result.metrics["pointer_lines"], 0)

    def test_arm2_adds_pointers_only_when_switch_on(self):
        """臂 2 的唯一差别是指针：开态出现「候选指针」，且仍在「检索到 N 条候选」之后。"""
        arm1 = compose("X", self.history[-1].content, self.history, ARM_A_MIN, budget_est=200)
        arm2 = compose("X", self.history[-1].content, self.history, ARM_POINTER, budget_est=200)
        self.assertEqual(arm1.metrics["pointer_lines"], 0)
        self.assertGreaterEqual(arm2.metrics["pointer_lines"], 1)
        compressed = [m.content for m in arm2.messages if m.role == "tool"]
        self.assertTrue(any("候选指针" in c and "检索到 2 条候选" in c for c in compressed))

    def test_arm3_drops_historical_tool_and_injects_segment_before_question(self):
        """臂 3：历史 tool 原文移出 prompt；子图段插在**本轮提问之前**；段自描述。"""
        arm3 = compose("X", self.history[-1].content, self.history, ARM_GRAPH, budget_est=200)
        contents = [m.content for m in arm3.messages]
        self.assertNotIn("K" * 5000, contents)                       # 历史 tool 原文已移出
        self.assertEqual(arm3.metrics["dropped_tool_messages"], 1)
        self.assertGreater(arm3.metrics["subgraph_est"], 0)
        segment_index = next(i for i, c in enumerate(contents)
                             if c.startswith("【会话记忆·相关子图】"))
        question_index = contents.index(self.history[-1].content)
        self.assertEqual(segment_index, question_index - 1)           # 段序：段在本轮提问之前
        self.assertIn("条款｜", contents[segment_index])
        self.assertNotIn("[K1]", contents[segment_index])              # 自描述，不带跨 run 会撞号的标记

    def test_arm3_keeps_evidence_when_graph_is_empty(self):
        """护栏：图上没有可用节点时**不许移除证据**（否则臂 3 = 丢了又没补，实测 D4 命中此坑）。"""
        history = [
            AgentMessage(role="user", content="第一问"),
            _tool_message({"items": [], "total": 0}, content="T" * 5000),
            AgentMessage(role="assistant", content="答：见第 3 章。"),   # 无引用标记 → 无节点
            AgentMessage(role="user", content="那再算一遍"),
        ]
        arm3 = compose("Y", history[-1].content, history, ARM_GRAPH, budget_est=200)
        self.assertEqual(arm3.metrics["dropped_tool_messages"], 0)
        self.assertIn("T" * 5000, [m.content for m in arm3.messages])     # 证据仍在
        self.assertEqual(arm3.metrics["subgraph_est"], 0)

    def test_compose_all_shares_one_graph(self):
        """三臂共用同一张图 → 臂间可比（否则召回差异会被图差异污染）。"""
        results = compose_all("X", self.history[-1].content, self.history, budget_est=200)
        self.assertEqual(set(results), set(ALL_ARMS))
        self.assertTrue(all(r.case_id == "X" for r in results.values()))

    def test_metrics_estimate_consistent(self):
        """分段 est 之和必须等于总 est（度量的自洽性）。"""
        arm2 = compose("X", self.history[-1].content, self.history, ARM_POINTER, budget_est=200)
        m = arm2.metrics
        self.assertEqual(m["total_est"], m["semantic_est"] + m["tool_line_est"] + m["subgraph_est"])
        self.assertEqual(m["total_est"], estimate(arm2.messages))


class OfflineGraphTests(unittest.TestCase):
    def _messages(self, assistant_text="结论：T=12.8m，见 [K1]。"):
        return [
            AgentMessage(role="user", content="某5万吨级散货船，满载吃水T=12.8m，算码头前沿水深"),
            _tool_message({"items": [_item("K1"), _item("K2", doc_id="doc-b",
                                                 section_path="7 斜坡式护岸设计 / 7.1 一般规定")],
                           "total": 2}),
            AgentMessage(role="assistant", content=assistant_text),
        ]

    def test_cites_edges_from_markers(self):
        """cites 边 = assistant 的 [K1] 标记 × 本轮 items 的 cite（BB §3.2 同一口径）。"""
        graph = build_graph(self._messages())
        self.assertEqual(len(graph.clause_nodes()), 1)          # 只建被引用的那条
        self.assertEqual(len([e for e in graph.edges if e.kind == "cites"]), 1)
        node = graph.clause_nodes()[0]
        self.assertEqual(node.markers, ["K1"])
        self.assertIn("JTS 165-2013", node.key)

    def test_value_node_requires_unit(self):
        """BB §3.3：无单位不建 value 节点。"""
        with_unit = build_graph(self._messages())
        self.assertEqual([n.key for n in with_unit.value_nodes()], ["T=12.8m"])
        without_unit = build_graph(self._messages(assistant_text="结论：T=12.8，见 [K1]。"))
        self.assertEqual(without_unit.value_nodes(), [])

    def test_recall_ordinal_picks_nth_of_last_run(self):
        """「刚才第二条」→ 上一轮引用序列的第 2 条（序数消解，BB §4）。"""
        messages = [
            AgentMessage(role="user", content="第一问"),
            _tool_message({"items": [_item("K1"), _item("K2", doc_id="doc-b")], "total": 2}),
            AgentMessage(role="assistant", content="答：见 [K1][K2]。"),
        ]
        graph = build_graph(messages)
        nodes = recall(graph, "刚才第二条提到的规范，具体说了什么？")
        self.assertEqual(len(nodes), 1)
        self.assertNotIn("[K1]", nodes[0].markers)

    def test_recall_demonstrative_takes_whole_last_run(self):
        """「那抗倾稳定呢？」（无序号）→ 取上一轮全部被引用节点。"""
        messages = [
            AgentMessage(role="user", content="第一问"),
            _tool_message({"items": [_item("K1"), _item("K2", doc_id="doc-b")], "total": 2}),
            AgentMessage(role="assistant", content="答：见 [K1][K2]。"),
        ]
        graph = build_graph(messages)
        nodes = recall(graph, "那抗倾稳定呢？")
        self.assertEqual(len(nodes), 2)

    def test_render_is_bounded_and_self_describing(self):
        """渲染有界（闸 B）+ 自描述（带「第 N 轮」、不带标记）。"""
        messages = self._messages()
        graph = build_graph(messages)
        text = render(recall(graph, "T=12.8m 是哪来的"), max_chars=200)
        self.assertLessEqual(len(text), 200)
        self.assertIn("【会话记忆·相关子图】", text)
        self.assertIn("第", text)
        self.assertNotIn("[K1]", text)


class DryRunReportTests(unittest.TestCase):
    @unittest.skipUnless(DB_AVAILABLE, "需要本地 chat.sqlite")
    def test_dry_run_report_shape(self):
        """干跑报告：题面保真无失败 + 三臂读数齐 + 闸 A/闸 B 字段在（只跑前 3 例省时）。"""
        report = run_dry(CASES[:3], budget_est=16_000)
        self.assertEqual(report["fidelity_failures"], [])
        self.assertEqual(set(report["summary"]["arms"]), set(ALL_ARMS))
        self.assertIn("gate_a", report["summary"])
        self.assertIn("subgraph_cap_violations", report["summary"])
        for entry in report["per_case"]:
            self.assertIn("history_est_per_turn", entry[ARM_A_MIN])

    @unittest.skipUnless(DB_AVAILABLE, "需要本地 chat.sqlite")
    def test_arm3_never_exceeds_arm1_history_segment(self):
        """闸 A 的差分口径：臂 3 的历史段 est/轮不得高于臂 1（tool 段已移出）。"""
        report = run_dry(CASES[:3], budget_est=16_000)
        base = report["summary"]["arms"][ARM_A_MIN]["history_est_per_turn_median"]
        graph = report["summary"]["arms"][ARM_GRAPH]["history_est_per_turn_median"]
        self.assertLessEqual(graph, base)


if __name__ == "__main__":
    unittest.main()

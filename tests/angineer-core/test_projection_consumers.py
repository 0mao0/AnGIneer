"""投影形态消费方回归（2026-10-16「引用圆圈消失」事故专用）。

背景：LLM 投影（agent_loop._project_items）把 metadata.cite 提升到条目顶层后，
读旧形态的三处消费方全部静默失效——守卫 _valid_markers 恒空（正文引用标记被全量
剥除，内联圆圈消失）、agent_policy._has_evidence 恒 False（L2 档次次回退 L1）、
_item_pointer_keys 整条为空（回看指针失效）。生产实况：2026-10-06 起 11 条回答、
102 个标记被误剥（对照 09-29 只有 3 条真编造被剥）。

本组用例一律用**投影后的 content**（生产真实形态）喂消费方，锁住双形态读法；
同时保留反向用例（无工具消息时编造标记仍须剥除），防止修成「守卫失效」。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_configs import _item_pointer_keys, _valid_markers, make_final_answer_guard  # noqa: E402
from angineer_core.agent_loop import AgentLoopConfig, run_agent_loop  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.agent_policy import _has_evidence  # noqa: E402
from angineer_core.agent_tools import AgentTool  # noqa: E402

from agent_test_utils import MockLLM, text_events, tool_block  # noqa: E402


def _raw_items():
    return [
        {
            "item_id": "i1", "entity_type": "chunk", "doc_id": "d1",
            "title": "公路水泥规范", "text": "混凝土保护层厚度 30mm。", "score": 0.9,
            "rerank_score": 0.72, "citation_target_id": "ct1",
            "metadata": {
                "cite": "K1", "doc_title": "公路水泥规范.pdf", "page_idx": 3,
                "page_label": "12", "section_path": "4 材料 / 4.1 水泥",
                "library_id": "std-highway", "source_kind": "mineru",
            },
        },
        {
            "item_id": "i2", "entity_type": "chunk", "doc_id": "d2",
            "title": "内河通航标准", "text": "航道尺度按等级确定。", "score": 0.8,
            "rerank_score": 0.61,
            "metadata": {"cite": "K2", "doc_title": "内河通航标准.pdf", "page_idx": 5},
        },
    ]


def _projected_content() -> str:
    """生产真实形态：经 _llm_content_payload 投影后的 tool content。"""
    from angineer_core.agent_loop import _llm_content_payload

    return json.dumps(_llm_content_payload({"items": _raw_items(), "total": 2}), ensure_ascii=False)


def _legacy_content() -> str:
    """投影关闭（ANGINEER_LLM_SHELL_STRIP=0）与历史落库的旧形态。"""
    return json.dumps({"items": _raw_items(), "total": 2}, ensure_ascii=False)


def _tool_msg(content: str) -> AgentMessage:
    return AgentMessage(role="tool", content=content, name="knowledge_search")


class ProjectedShapeConsumerTests(unittest.TestCase):
    """消费方必须同时认两种形态：顶层 cite（投影后）与 metadata.cite（投影前）。"""

    def test_valid_markers_reads_projected_top_level_cite(self):
        markers = _valid_markers([_tool_msg(_projected_content())])
        self.assertEqual(markers, {"K1", "K2"})

    def test_valid_markers_reads_legacy_metadata_cite(self):
        markers = _valid_markers([_tool_msg(_legacy_content())])
        self.assertEqual(markers, {"K1", "K2"})

    def test_guard_keeps_projected_markers(self):
        """守卫不得剥证据内标记（事故本体：投影形态下 10/11 个标记被误剥）。"""
        added = [
            _tool_msg(_projected_content()),
            AgentMessage(role="assistant", content="混凝土保护层厚度为 30mm [K1]，另见 [K2]。"),
        ]
        result = make_final_answer_guard(enforce_evidence=True)(added)
        self.assertIsNone(result)  # 无边界问题、不改写

    def test_guard_still_strips_invented_markers(self):
        """反向锁：证据里没有的标记（K9）仍须剥除，别把守卫修成橡皮章。"""
        added = [
            _tool_msg(_projected_content()),
            AgentMessage(role="assistant", content="混凝土保护层厚度为 30mm [K1]，另见 [K9]。"),
        ]
        result = make_final_answer_guard(enforce_evidence=True)(added)
        self.assertIsNotNone(result)
        self.assertEqual(result[2], "markers_cleaned")
        self.assertIn("[K1]", result[0])
        self.assertNotIn("[K9]", result[0])

    def test_guard_strips_all_markers_without_tool_messages(self):
        """无工具消息时所有标记视为编造（2026-10-04 定版行为，投影修复不得回退它）。"""
        result = make_final_answer_guard(enforce_evidence=True)([
            AgentMessage(role="assistant", content="混凝土保护层厚度为 30mm [K1]。"),
        ])
        self.assertIsNotNone(result)
        self.assertEqual(result[2], "markers_cleaned")
        self.assertNotIn("[K1]", result[0])

    def test_has_evidence_reads_projected_shape(self):
        self.assertTrue(_has_evidence([_tool_msg(_projected_content())]))

    def test_has_evidence_reads_legacy_shape(self):
        self.assertTrue(_has_evidence([_tool_msg(_legacy_content())]))

    def test_has_evidence_false_without_cite(self):
        """无 cite 的 items（表格式返回）不算证据，防「恒 True」修法。"""
        content = json.dumps({"items": [{"item_id": "t1", "text": "表头", "metadata": {}}]})
        self.assertFalse(_has_evidence([_tool_msg(content)]))

    def test_pointer_keys_reads_projected_shape(self):
        """回看指针（提示词 v17 规则 15）依赖 doc_id + cite，投影形态下不得整条为空。"""
        text = _item_pointer_keys(json.loads(_projected_content())["items"])
        self.assertIn("K1·公路水泥规范[doc_id=d1]", text)
        self.assertIn("K2·内河通航标准[doc_id=d2]", text)

    def test_pointer_keys_reads_legacy_shape(self):
        text = _item_pointer_keys(json.loads(_legacy_content())["items"])
        self.assertIn("K1·公路水泥规范[doc_id=d1]", text)


class ProjectionEndToEndTests(unittest.TestCase):
    """端到端（真实 run_agent_loop + 真实投影落 content）：最终答案里的标记必须活下来。

    事故链完整走一遍：工具返回 → _run_tool_inner 投影落 content → 守卫校验标记 →
    正文（run_end 下发前端画圆圈的那份）保留 [K1]。
    """

    def _tool(self):
        def handler(query=None, **_kw):
            return {
                "items": [
                    {
                        "item_id": "i1", "entity_type": "chunk", "doc_id": "d1",
                        "title": "公路水泥规范", "text": "混凝土保护层厚度 30mm。",
                        "score": 0.9, "rerank_score": 0.72, "citation_target_id": "ct1",
                        "metadata": {
                            "cite": "K1", "doc_title": "公路水泥规范.pdf",
                            "page_idx": 3, "page_label": "12",
                            "section_path": "4 材料 / 4.1 水泥", "library_id": "std-highway",
                        },
                    }
                ],
                "total": 1,
                "citations": [{"marker": "K1", "doc_id": "d1", "snippet": "混凝土保护层厚度 30mm。"}],
            }

        return AgentTool(
            name="knowledge_search",
            description="检索",
            parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=handler,
        )

    def test_final_answer_keeps_markers_end_to_end(self):
        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "knowledge_search", "arguments": {"query": "保护层厚度"}}]))
            else:
                yield from text_events("混凝土保护层厚度为 30mm [K1]。")

        llm = MockLLM(handler)
        messages: list = []
        events: list = []
        run_agent_loop(
            messages,
            AgentLoopConfig(llm=llm, tools=[self._tool()], max_turns=3, system_prompt="你是助手"),
            emit=events.append,
        )
        tool_msg = next(m for m in messages if m.role == "tool")
        projected = json.loads(tool_msg.content)["items"][0]
        # 投影后仍是消费方能读的形态（顶层 id/引用/位置 + 遥测已剥）
        self.assertEqual(projected["cite"], "K1")
        self.assertEqual(projected["item_id"], "i1")
        self.assertEqual(projected["doc_id"], "d1")
        self.assertNotIn("metadata", projected)
        self.assertNotIn("_admission", json.loads(tool_msg.content))
        # 最终答案（run_end 下发前端的那份）标记保留
        final_answer = next(m.content for m in reversed(messages) if m.role == "assistant" and not m.tool_calls)
        self.assertIn("[K1]", final_answer)
        notes = [n["detail"] for n in events[-1].payload.get("notes", [])]
        self.assertFalse(any("无效引用标记" in note for note in notes))


if __name__ == "__main__":
    unittest.main()

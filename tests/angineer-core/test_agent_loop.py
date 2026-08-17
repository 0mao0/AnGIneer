"""P2 run_agent_loop 核心语义单测（mock LLM）。"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_events import AgentEvent  # noqa: E402
from angineer_core.agent_loop import AgentLoopConfig, AttemptConfig, run_agent_loop  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.agent_tools import AgentTool, ToolResult  # noqa: E402
from angineer_core.tool_codec import TextToolCallCodec  # noqa: E402

from agent_test_utils import MockLLM, collect_events, text_events, tool_block  # noqa: E402


def make_tool(name, handler, schema=None, **overrides):
    return AgentTool(
        name=name,
        description=f"{name} 工具",
        parameters_schema=schema or {"type": "object", "properties": {}},
        handler=handler,
        **overrides,
    )


def make_config(llm, tools, **overrides):
    defaults = {"max_turns": 3, "system_prompt": "你是助手"}
    defaults.update(overrides)
    return AgentLoopConfig(llm=llm, tools=tools, **defaults)


class AgentLoopTests(unittest.TestCase):
    def test_natural_stop_single_turn(self):
        llm = MockLLM(lambda messages, kwargs: text_events("直接答案"))
        events = []
        messages: list = []
        added = run_agent_loop(messages, make_config(llm, []), emit=events.append)

        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(added[-1].content, "直接答案")
        self.assertEqual(added[-1].role, "assistant")
        run_end = events[-1]
        self.assertEqual(run_end.type, "run_end")
        self.assertEqual(run_end.payload["reason"], "completed")
        self.assertEqual(run_end.payload["turns"], 1)

    def test_route_note_appears_as_first_note(self):
        llm = MockLLM(lambda messages, kwargs: text_events("直接答案"))
        events: list = []
        run_agent_loop(
            [],
            make_config(
                llm,
                [],
                route_note="意图判断：正文问答（L1）→ 策略 semantic_retrieval",
            ),
            emit=events.append,
        )

        types = collect_events(events)
        self.assertEqual(types[0], "run_start")
        self.assertEqual(types[1], "note")
        run_end = events[-1]
        self.assertEqual(run_end.type, "run_end")
        self.assertTrue(any(n["detail"].startswith("意图判断") for n in run_end.payload["notes"]))

    def test_two_turn_retrieval(self):
        search_calls = []

        def search(q):
            search_calls.append(q)
            return {"results": [q]}

        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "港口吞吐量"}}]))
            else:
                yield from text_events("答案是港口吞吐量")

        llm = MockLLM(handler)
        events = []
        messages: list = []
        added = run_agent_loop(
            messages,
            make_config(llm, [make_tool("search", search, {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]})]),
            emit=events.append,
        )

        self.assertEqual(search_calls, ["港口吞吐量"])
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(added[-1].content, "答案是港口吞吐量")
        tool_msgs = [m for m in added if m.role == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertFalse(tool_msgs[0].is_error)
        self.assertIn("港口吞吐量", tool_msgs[0].content)

    def test_tool_exception_becomes_error_result(self):
        def boom():
            raise RuntimeError("boom")

        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {}}]))
            else:
                yield from text_events("已处理")

        llm = MockLLM(handler)
        messages: list = []
        run_agent_loop(messages, make_config(llm, [make_tool("search", boom)]))

        tool_msgs = [m for m in messages if m.role == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertTrue(tool_msgs[0].is_error)
        self.assertIn("工具执行失败: boom", tool_msgs[0].content)
        self.assertEqual(messages[-1].content, "已处理")

    def test_parameter_validation_failure_skips_handler(self):
        calls = []
        schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}

        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": 123}}]))
            else:
                yield from text_events("参数错了，我重来")

        llm = MockLLM(handler)
        messages: list = []
        run_agent_loop(messages, make_config(llm, [make_tool("search", lambda q: calls.append(q), schema)]))

        self.assertEqual(calls, [])
        tool_msgs = [m for m in messages if m.role == "tool"]
        self.assertTrue(tool_msgs[0].is_error)
        self.assertIn("参数校验失败", tool_msgs[0].content)

    def test_truncation_guard_voids_tool_calls(self):
        calls = []

        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(
                    tool_block([{"name": "search", "arguments": {"q": "x"}}]),
                    finish_reason="length",
                )
            else:
                yield from text_events("重试后的答案")

        llm = MockLLM(handler)
        messages: list = []
        run_agent_loop(messages, make_config(llm, [make_tool("search", lambda q: calls.append(q))]))

        self.assertEqual(calls, [])
        self.assertTrue(any(m.role == "tool" and m.is_error and "输出被长度截断" in m.content for m in messages))
        self.assertEqual(messages[-1].content, "重试后的答案")

    def test_terminate_requires_all_votes(self):
        def make_handler(calls):
            def handler(messages, kwargs):
                if len(llm.calls) == 1:
                    yield from text_events(
                        tool_block([
                            {"name": "tool_a", "arguments": {}},
                            {"name": "tool_b", "arguments": {}},
                        ])
                    )
                else:
                    yield from text_events("继续完成")
            return handler

        # 一面旗帜：继续
        llm = MockLLM(make_handler([]))
        tools = [
            make_tool("tool_a", lambda: {"terminate": True}),
            make_tool("tool_b", lambda: {"value": 1}),
        ]
        events = []
        run_agent_loop([], make_config(llm, tools), emit=events.append)
        self.assertEqual(events[-1].payload["reason"], "completed")
        self.assertEqual(len(llm.calls), 2)

        # 全票：停止
        llm = MockLLM(make_handler([]))
        tools = [
            make_tool("tool_a", lambda: {"terminate": True}),
            make_tool("tool_b", lambda: {"terminate": True}),
        ]
        events = []
        run_agent_loop([], make_config(llm, tools), emit=events.append)
        self.assertEqual(events[-1].payload["reason"], "terminated")
        self.assertEqual(len(llm.calls), 1)

    def test_max_turns_final_no_tool_turn(self):
        def handler(messages, kwargs):
            if len(llm.calls) < 3:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            else:
                yield from text_events("最终答案")

        llm = MockLLM(handler)
        events = []
        messages: list = []
        run_agent_loop(
            messages,
            make_config(
                llm,
                [make_tool("search", lambda q: {"ok": True})],
                max_turns=2,
            ),
            emit=events.append,
        )

        self.assertEqual(len(llm.calls), 3)
        final_call = llm.calls[-1]
        system_content = final_call["messages"][0]["content"]
        self.assertIn("轮次预算已用完", final_call["messages"][-1]["content"])
        self.assertIn("工具调用已被禁用", system_content)
        run_end = events[-1]
        self.assertEqual(run_end.payload["reason"], "max_turns")
        self.assertEqual(run_end.payload["turns"], 3)

    def test_cancel_completes_turn_then_stops(self):
        cancel = threading.Event()

        def slow_handler():
            cancel.set()
            time.sleep(0.05)
            return {"ok": True}

        def handler(messages, kwargs):
            yield from text_events(tool_block([{"name": "search", "arguments": {}}]))

        llm = MockLLM(handler)
        events = []
        run_agent_loop(
            [],
            make_config(llm, [make_tool("search", slow_handler)]),
            emit=events.append,
            cancel=cancel,
        )

        types = collect_events(events)
        self.assertEqual(types[-1], "run_end")
        self.assertEqual(events[-1].payload["reason"], "cancelled")
        self.assertEqual(types[-2], "note")
        self.assertIn("tool_end", types)

    def test_cancel_before_execution_still_traces_pending_tool(self):
        cancel = threading.Event()

        def before(tool, args):
            cancel.set()
            return None

        def handler(messages, kwargs):
            yield from text_events(tool_block([{"name": "search", "arguments": {}}]))

        llm = MockLLM(handler)
        events: list = []
        messages: list = []
        run_agent_loop(
            messages,
            make_config(
                llm,
                [make_tool("search", lambda: {"ok": 1})],
                before_tool_call=before,
            ),
            emit=events.append,
            cancel=cancel,
        )

        types = collect_events(events)
        self.assertEqual(types.count("tool_start"), types.count("tool_end"))
        self.assertIn("tool_end", types)
        tool_msgs = [m for m in messages if m.role == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertTrue(tool_msgs[0].is_error)
        self.assertIn("取消", tool_msgs[0].content)

    def test_before_after_hooks(self):
        calls = []

        def before(tool, args):
            if tool.name == "search":
                return "此工具被拦截"
            return None

        def after(result: ToolResult) -> ToolResult:
            result.content += "[已补丁]"
            return result

        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {}}]))
            else:
                yield from text_events("完成")

        llm = MockLLM(handler)
        messages: list = []
        run_agent_loop(
            messages,
            make_config(
                llm,
                [make_tool("search", lambda: calls.append(1))],
                before_tool_call=before,
                after_tool_call=after,
            ),
        )

        self.assertEqual(calls, [])
        tool_msgs = [m for m in messages if m.role == "tool"]
        self.assertTrue(tool_msgs[0].is_error)
        self.assertIn("拦截", tool_msgs[0].content)
        self.assertIn("[已补丁]", tool_msgs[0].content)

    def test_max_turns_emits_boundary_note(self):
        def handler(messages, kwargs):
            if len(llm.calls) < 3:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            else:
                yield from text_events("最终答案")

        llm = MockLLM(handler)
        events: list = []
        run_agent_loop(
            [],
            make_config(
                llm,
                [make_tool("search", lambda q: {"ok": True})],
                max_turns=2,
            ),
            emit=events.append,
        )

        types = collect_events(events)
        self.assertIn("note", types)
        run_end = events[-1]
        self.assertEqual(run_end.type, "run_end")
        self.assertTrue(any("轮次预算已用完" in n["detail"] for n in run_end.payload["notes"]))

    def test_final_answer_guard_replaces_answer_and_emits_answer_event(self):
        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            else:
                yield from text_events("随便给的答案")

        def guard(added_messages):
            return ("没有检索到足够证据支持最终结论。", "边界规则：未检索到有效证据，拒绝给出最终结论")

        llm = MockLLM(handler)
        events: list = []
        messages: list = []
        run_agent_loop(
            messages,
            make_config(
                llm,
                [make_tool("search", lambda q: {"items": [], "total": 0})],
                final_answer_guard=guard,
            ),
            emit=events.append,
        )

        self.assertEqual(messages[-1].content, "没有检索到足够证据支持最终结论。")
        types = collect_events(events)
        self.assertIn("answer", types)
        self.assertIn("note", types)
        run_end = events[-1]
        self.assertEqual(run_end.type, "run_end")
        self.assertTrue(any(n["detail"].startswith("边界规则") for n in run_end.payload["notes"]))
        self.assertEqual(run_end.payload["messages"][-1]["content"], "没有检索到足够证据支持最终结论。")

    def test_final_answer_guard_runs_without_tool_results_for_marker_cleanup(self):
        def guard(added_messages):
            return ("清理后的回答", "清理说明")

        llm = MockLLM(lambda messages, kwargs: text_events("闲聊直接回答 [K9]"))
        events: list = []
        messages: list = []
        run_agent_loop(
            messages,
            make_config(llm, [], final_answer_guard=guard),
            emit=events.append,
        )

        self.assertEqual(messages[-1].content, "清理后的回答")
        types = collect_events(events)
        self.assertIn("answer", types)
        self.assertTrue(any(n["detail"] == "清理说明" for n in events[-1].payload["notes"]))

    def test_event_order_and_nesting(self):
        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {}}]))
            else:
                yield from text_events("最终")

        llm = MockLLM(handler)
        events: list = []
        run_agent_loop([], make_config(llm, [make_tool("search", lambda: {"ok": 1})]), emit=events.append)

        types = collect_events(events)
        self.assertEqual(types[0], "run_start")
        self.assertEqual(types[-1], "run_end")
        self.assertEqual(types.count("turn_start"), types.count("turn_end"))
        self.assertEqual(types.count("tool_start"), types.count("tool_end"))
        # 工具事件必须夹在 turn 事件之间
        first_turn_start = types.index("turn_start")
        first_tool_start = types.index("tool_start")
        first_turn_end = types.index("turn_end")
        self.assertTrue(first_turn_start < first_tool_start < first_turn_end)
        # message_delta 只出现在打开的 message_start/message_end 之间
        open_message = 0
        for i, t in enumerate(types):
            if t == "message_delta":
                self.assertGreater(open_message, 0)
            elif t == "message_start":
                open_message += 1
            elif t == "message_end":
                open_message -= 1
        self.assertEqual(open_message, 0)
        # 所有事件带 run_id
        self.assertTrue(all(isinstance(e, AgentEvent) and e.run_id for e in events))

    def test_two_attempt_fallback_chain(self):
        def make_attempt_llm(text):
            return MockLLM(lambda messages, kwargs: text_events(text))

        events: list = []
        messages: list = []

        def attempt_factory(name, text):
            def factory():
                return AgentLoopConfig(
                    llm=make_attempt_llm(text),
                    tools=[],
                    system_prompt=f"prompt-{name}",
                    max_turns=1,
                )
            return factory

        def success_false(added):
            return False

        config = AgentLoopConfig(
            llm=MockLLM(lambda messages, kwargs: text_events("unused")),
            tools=[],
            system_prompt="outer",
            max_turns=1,
            attempts=[
                AttemptConfig(name="L2条款定位", config_factory=attempt_factory("l2", "L2答案"), success_check=success_false, fallback_note="L2未命中→回退L1"),
                AttemptConfig(name="L1语义检索", config_factory=attempt_factory("l1", "L1答案")),
            ],
        )
        run_agent_loop(messages, config, emit=events.append)

        types = collect_events(events)
        self.assertIn("note", types)
        self.assertEqual(messages[-1].content, "L1答案")
        run_end = events[-1]
        self.assertEqual(run_end.payload["reason"], "completed")
        self.assertTrue(any("回退" in n["detail"] for n in run_end.payload["notes"]))

    def test_no_premature_fallback_after_tool_turn(self):
        """段内先调工具、后给答案：工具轮结束不得触发回退。"""
        events: list = []
        messages: list = []

        def handler(messages, kwargs):
            if len(llm.calls) == 1:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            else:
                yield from text_events("最终答案")

        llm = MockLLM(handler)
        attempt = AttemptConfig(
            name="L1",
            config_factory=lambda: AgentLoopConfig(
                llm=llm,
                tools=[make_tool("search", lambda q: {"items": [q]})],
                system_prompt="p",
                max_turns=3,
            ),
            success_check=lambda added: any(
                m.role == "assistant" and not m.tool_calls and m.content for m in added
            ),
        )
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="outer", max_turns=3, attempts=[attempt])
        run_agent_loop(messages, config, emit=events.append)

        self.assertEqual(len(llm.calls), 2)  # 工具轮 + 答案轮，没有第三段
        run_end = events[-1]
        self.assertEqual(run_end.payload["reason"], "completed")
        self.assertFalse(any("回退" in n["detail"] for n in run_end.payload["notes"]))

    def test_terminal_refusal_answer_completes(self):
        """终段产出了答案（含拒答）即正常完成，不再暴露 attempts_exhausted。"""
        events: list = []
        llm = MockLLM(lambda messages, kwargs: text_events("没有检索到足够证据支持最终结论。"))
        config = AgentLoopConfig(
            llm=llm,
            tools=[],
            system_prompt="outer",
            max_turns=1,
            attempts=[
                AttemptConfig(name="L1", config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1), success_check=lambda added: False),
            ],
        )
        added = run_agent_loop([], config, emit=events.append)
        self.assertEqual(events[-1].payload["reason"], "completed")
        self.assertEqual(added[-1].content, "没有检索到足够证据支持最终结论。")

    def test_empty_final_answer_gets_refusal_fallback(self):
        """终段输出为空时，引擎补一条拒答并以 completed 收尾，前端不会无结果。"""
        events: list = []
        llm = MockLLM(lambda messages, kwargs: text_events(""))
        config = AgentLoopConfig(
            llm=llm,
            tools=[],
            system_prompt="outer",
            max_turns=1,
            attempts=[
                AttemptConfig(name="L1", config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1), success_check=lambda added: False),
            ],
        )
        added = run_agent_loop([], config, emit=events.append)
        self.assertEqual(events[-1].payload["reason"], "completed")
        self.assertTrue(added[-1].content.startswith("没有检索到足够证据支持最终结论"))
        self.assertTrue(any("拒答" in n["detail"] for n in events[-1].payload["notes"]))

    def test_direct_answer_markers_stripped_without_tools(self):
        """模型没调工具却输出 [Kx]：guard 仍执行标记清理，reason 保持 completed。"""
        from angineer_core.agent_configs import make_final_answer_guard

        events: list = []
        llm = MockLLM(lambda messages, kwargs: text_events("航道水深由吃水加富裕深度确定 [K12]。"))
        config = AgentLoopConfig(
            llm=llm,
            tools=[],
            system_prompt="outer",
            max_turns=1,
            final_answer_guard=make_final_answer_guard(enforce_evidence=True),
        )
        added = run_agent_loop([], config, emit=events.append)
        run_end = events[-1]
        self.assertEqual(run_end.payload["reason"], "completed")
        self.assertNotIn("[K12]", added[-1].content)
        self.assertTrue(any("无效引用标记" in n["detail"] for n in run_end.payload["notes"]))

    def test_requires_tools_forces_retry_then_tool_round(self):
        """requires_tools 段：模型先直接回答 → 强制补一轮带工具的重试 → 完成后正常结束。"""
        events: list = []
        messages: list = []

        def handler(messages, kwargs):
            if len(llm.calls) == 2:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            elif len(llm.calls) == 3:
                yield from text_events("基于证据的最终答案")
            else:
                yield from text_events("没查库直接答")

        llm = MockLLM(handler)
        attempt = AttemptConfig(
            name="L1",
            config_factory=lambda: AgentLoopConfig(
                llm=llm,
                tools=[make_tool("search", lambda q: {"items": [q]})],
                system_prompt="p",
                max_turns=2,
            ),
            success_check=lambda added: True,
            requires_tools=True,
        )
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="outer", max_turns=2, attempts=[attempt])
        run_agent_loop(messages, config, emit=events.append)

        self.assertEqual(len(llm.calls), 3)  # 直接答 → 强制重试(工具轮) → 最终答案
        self.assertTrue(any(m.role == "tool" for m in messages))
        self.assertEqual(events[-1].payload["reason"], "completed")
        self.assertTrue(any("未调用检索工具" in n["detail"] for n in events[-1].payload["notes"]))

    def test_requires_tools_keeps_nonempty_answer_if_model_never_calls_tools(self):
        """requires_tools 段：重试一次后仍不调工具 → 保留非空答案，不再无条件覆盖为拒答。"""
        events: list = []
        llm = MockLLM(lambda messages, kwargs: text_events("我就是不查库"))
        attempt = AttemptConfig(
            name="L1",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1),
            success_check=lambda added: True,
            requires_tools=True,
        )
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="outer", max_turns=1, attempts=[attempt])
        added = run_agent_loop([], config, emit=events.append)

        self.assertEqual(len(llm.calls), 2)  # 直接答 + 一次强制重试
        self.assertEqual(events[-1].payload["reason"], "completed")
        self.assertEqual(added[-1].content, "我就是不查库")
        self.assertTrue(any("未调用检索工具" in n["detail"] for n in events[-1].payload["notes"]))
        self.assertFalse(any("拒答" in n["detail"] for n in events[-1].payload["notes"]))

    def test_requires_tools_empty_answer_after_retry_still_refused(self):
        """requires_tools 段：重试后仍输出空内容 → 引擎补拒答收尾。"""
        events: list = []
        llm = MockLLM(lambda messages, kwargs: text_events(""))
        attempt = AttemptConfig(
            name="L1",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1),
            success_check=lambda added: True,
            requires_tools=True,
        )
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="outer", max_turns=1, attempts=[attempt])
        added = run_agent_loop([], config, emit=events.append)

        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(events[-1].payload["reason"], "completed")
        self.assertTrue(added[-1].content.startswith("没有检索到足够证据支持最终结论"))
        self.assertTrue(any("拒答" in n["detail"] for n in events[-1].payload["notes"]))

    def test_requires_tools_retries_current_attempt_before_fallback_and_resets_per_attempt(self):
        """requires_tools：L2 先强制重试（不直接回退），L1 回退后重新拥有自己的工具轮。"""
        events: list = []
        messages: list = []

        def handler(messages, kwargs):
            call = len(llm.calls)
            if call == 1:
                yield from text_events("L2 直接答")
            elif call == 2:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            elif call == 3:
                yield from text_events("没有检索到足够证据支持最终结论。")
            elif call == 4:
                yield from text_events("L1 直接答")
            elif call == 5:
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            else:
                yield from text_events("L1 基于证据的答案")

        llm = MockLLM(handler)
        tool = make_tool("search", lambda q: {"items": [{"metadata": {"cite": "K1"}, "text": "证据"}]})

        def has_evidence(added):
            return any(m.role == "tool" and not m.is_error and '"cite"' in m.content for m in added)

        def usable(added):
            for m in reversed(added):
                if m.role == "assistant" and not m.tool_calls and (m.content or "").strip():
                    return m.content != "没有检索到足够证据支持最终结论。"
            return False

        def l2_factory():
            return AgentLoopConfig(llm=llm, tools=[tool], system_prompt="p", max_turns=2)

        def l1_factory():
            return AgentLoopConfig(llm=llm, tools=[tool], system_prompt="p", max_turns=2)

        attempts = [
            AttemptConfig(
                name="L2",
                config_factory=l2_factory,
                success_check=lambda added: has_evidence(added) and usable(added),
                fallback_note="L2 未命中，回退 L1",
                requires_tools=True,
            ),
            AttemptConfig(
                name="L1",
                config_factory=l1_factory,
                success_check=usable,
                requires_tools=True,
            ),
        ]
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="outer", max_turns=1, attempts=attempts)
        run_agent_loop(messages, config, emit=events.append)

        self.assertEqual(len(llm.calls), 6)
        self.assertEqual(messages[-1].content, "L1 基于证据的答案")
        notes = [n["detail"] for n in events[-1].payload["notes"]]
        self.assertIn("L2 未命中，回退 L1", notes)
        self.assertEqual(notes.count("未调用检索工具，已要求重新检索后回答"), 2)

    def test_attempt_budget_resets_on_fallback(self):
        """回退后新段重新计轮，能完整执行自己的 max_turns。"""
        events: list = []
        messages: list = []
        calls: list = []

        def handler(messages, kwargs):
            calls.append(len(calls) + 1)
            if len(calls) in (1, 3):
                yield from text_events(tool_block([{"name": "search", "arguments": {"q": "x"}}]))
            elif len(calls) == 2:
                yield from text_events("L2 未命中")
            else:
                yield from text_events("L1 答案")

        llm = MockLLM(handler)
        first = AttemptConfig(
            name="L2",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[make_tool("search", lambda q: {"items": [q]})], system_prompt="p", max_turns=1),
            success_check=lambda added: False,
            fallback_note="回退 L1",
        )
        second = AttemptConfig(
            name="L1",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[make_tool("search", lambda q: {"items": [q]})], system_prompt="p", max_turns=2),
        )
        config = AgentLoopConfig(llm=llm, tools=[], system_prompt="outer", max_turns=1, attempts=[first, second])
        run_agent_loop(messages, config, emit=events.append)

        self.assertEqual(len(calls), 4)  # L2: 工具+收尾；L1: 工具+答案（预算独立）
        self.assertEqual(events[-1].payload["reason"], "completed")


class FollowupRefusalTests(unittest.TestCase):
    def _run_exhausted(self, followup_question: bool):
        llm = MockLLM(lambda messages, kwargs: text_events(""))
        attempt = AttemptConfig(
            name="L1",
            config_factory=lambda: AgentLoopConfig(
                llm=llm, tools=[], system_prompt="p", max_turns=1,
                followup_question=followup_question,
            ),
            success_check=lambda added: False,
        )
        messages = [AgentMessage(role="user", content="测试问题")]
        run_agent_loop(messages, AgentLoopConfig(llm=llm, attempts=[attempt]))
        return messages

    def test_exhausted_refusal_appends_followup_question_when_enabled(self):
        from angineer_core.agent_messages import REFUSAL_FOLLOWUP_QUESTION

        messages = self._run_exhausted(followup_question=True)
        self.assertEqual(messages[-1].role, "assistant")
        self.assertTrue(messages[-1].content.endswith(REFUSAL_FOLLOWUP_QUESTION))

    def test_exhausted_refusal_plain_when_disabled(self):
        from angineer_core.agent_messages import REFUSAL_ANSWER_TEXT

        messages = self._run_exhausted(followup_question=False)
        self.assertEqual(messages[-1].content, REFUSAL_ANSWER_TEXT)


if __name__ == "__main__":
    unittest.main()

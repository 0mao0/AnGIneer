"""幻觉工具名熔断（2026-10-25 FinanceBench 实锤）。

现场形态：模型自造工具名（「销量」/空名），“工具未注册”错误结果喂回后
仍原样重试同一错名，连烧 6 轮预算、一题未答。
熔断：连续 2 轮「本轮调用全部未注册」→ 复用预算耗尽的无工具收尾轮
（allow_tools=False）直接基于已有证据作答；轮内混入真实工具则计数清零。
跑法：unittest discover（仓库惯例）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from angineer_core.agent_loop import AgentLoopConfig, run_agent_loop
from angineer_core.agent_messages import AgentMessage
from angineer_core.agent_tools import AgentTool
from angineer_core.tool_codec import TextToolCallCodec


class _ScriptLLM:
    """mock LLMProvider：按脚本回放回复；空队列后回退纯文本「兜底回答」（永不自然停）。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.captured = []

    def chat_stream_events(self, messages, **kwargs):
        self.captured.append(messages)
        text = self.replies.pop(0) if self.replies else "兜底回答"
        for ch in text:
            yield {"type": "delta", "text": ch}
        yield {"type": "done", "finish_reason": "stop", "usage": {"prompt_tokens": 1}}


def _fence(calls):
    return "```tool_calls\n" + json.dumps(calls, ensure_ascii=False) + "\n```"


def _bad_call(name="销量"):
    return _fence([{"name": name, "arguments": {"query": "x"}}])


def _real_tool():
    return AgentTool(
        name="knowledge_search",
        description="检索知识库正文",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=lambda query=None, **kw: {"content": f"真实证据：{query}"},
        read_only=True,
    )


def _run(llm, tools):
    events = []
    messages = [AgentMessage(role="user", content="该船型的销量是多少？")]
    config = AgentLoopConfig(
        llm=llm,
        system_prompt="test",
        tools=tools,
        codec=TextToolCallCodec(),
        max_turns=8,
        followup_question=False,
    )
    result = run_agent_loop(messages, config, emit=events.append, run_id="t-breaker")
    run_end = [e for e in events if e.type == "run_end"][-1]
    return result, run_end.payload


def test_two_hallucination_turns_lock_tools_and_answer_directly():
    """连续两轮未注册工具名 → 第三次调用即无工具收尾轮；预算（8 轮）未烧满。"""
    llm = _ScriptLLM([_bad_call("销量"), _bad_call("产品销量表"), "基于已有证据：结论是 A。"])
    result, payload = _run(llm, tools=[])
    assert len(llm.captured) == 3, f"应恰好 3 次 LLM 调用（2 幻觉 + 1 直答），实际 {len(llm.captured)}"
    assert payload["reason"] == "tool_hallucination_breaker"
    assert "tool_hallucination_breaker" in payload["path_trace"]
    assert payload["turns"] <= 3, f"轮次应远小于 max_turns=8，实际 {payload['turns']}"
    final = [m for m in result if m.role == "assistant" and not m.tool_calls][-1]
    assert "结论是 A" in final.content
    # 收尾轮的系统提示词不再带工具清单（allow_tools=False 的可观测面）
    assert "未注册" in json.dumps(
        [m for m in result if m.role == "tool" and m.is_error], default=lambda o: str(o), ensure_ascii=False
    )


def test_real_tool_between_hallucinations_resets_counter():
    """幻觉-真调用-幻觉-幻觉：真调用把计数清零 → 真工具确实执行、熔断在第 5 轮才落。"""
    llm = _ScriptLLM([
        _bad_call("销量"),
        _fence([{"name": "knowledge_search", "arguments": {"query": "泵房参数"}}]),
        _bad_call("销量"),
        _bad_call("销量"),
        "基于检索结果：结论是 B。",
    ])
    result, payload = _run(llm, tools=[_real_tool()])
    assert payload["reason"] == "tool_hallucination_breaker"
    assert len(llm.captured) == 5, f"计数清零后熔断应在第 5 轮，实际 LLM 调用 {len(llm.captured)} 次"
    executed = [m for m in result if m.role == "tool" and m.name == "knowledge_search"]
    assert executed and "真实证据" in executed[0].content, "混入的真实工具必须照常执行"


def test_single_hallucination_then_answer_not_broken():
    """防误伤锁：单轮幻觉 + 模型次轮纯文本 → 正常 completed，不触熔断。

    注：空名/解析不了的围栏另有泄漏守卫接（伪造工具错误喂回），不走本计数。
    """
    llm = _ScriptLLM([_bad_call("销量"), "回答一", "回答二"])
    _, payload = _run(llm, tools=[])
    # 第 2 轮纯文本 → 模型自然给最终答案，正常 completed，不触熔断也不触预算
    assert payload["reason"] == "completed"
    assert len(llm.captured) == 2

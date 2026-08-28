"""无状态 agent 循环原语（P2，§6.4 / P2.2）。

边界：本模块只允许依赖 agent_messages / agent_events / agent_tools /
tool_codec / contracts，禁止反向依赖 dispatcher / classifier / memory。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from angineer_core.agent_events import AgentEvent
from angineer_core.agent_messages import (
    AgentMessage,
    REFUSAL_ANSWER_TEXT,
    REFUSAL_FOLLOWUP_QUESTION,
    ToolCall,
    agent_message_to_dict,
    is_refusal_text,
    to_llm_messages,
)
from angineer_core.agent_tools import AgentTool, ToolResult
from angineer_core.tool_codec import NativeToolCallCodec, TextToolCallCodec

logger = logging.getLogger(__name__)


@dataclass
class TurnContext:
    """turn 边界决策上下文。"""

    turn: int
    messages: List[AgentMessage]
    tool_results: List[ToolResult]
    usage: Dict[str, Any]


@dataclass
class AttemptConfig:
    """引擎内的一段执行：工具集/提示词/轮数由 config_factory 提供。"""

    name: str
    config_factory: Callable[[], AgentLoopConfig]
    success_check: Optional[Callable[[List[AgentMessage]], bool]] = None
    fallback_note: str = ""
    requires_tools: bool = False  # True 时禁止“不调工具直接作答”，强制至少一轮工具调用


@dataclass
class AgentLoopConfig:
    # —— 模型出口（循环只认 LLMProvider Protocol，不认厂商）——
    llm: Any  # 满足 contracts.LLMProvider
    model: Optional[str] = None
    config_name: Optional[str] = None
    mode: str = "instruct"
    max_tokens: Optional[int] = None
    # —— 行为 ——
    tools: List[AgentTool] = field(default_factory=list)
    system_prompt: str = ""
    codec: Any = None  # ToolCallCodec，默认 TextToolCallCodec
    max_turns: int = 3
    # —— 分段（attempt）执行 ——
    attempts: List[AttemptConfig] = field(default_factory=list)
    # —— 闸门与决策点（全部可选回调）——
    transform_context: Optional[Callable[[List[AgentMessage]], List[AgentMessage]]] = None
    should_stop_after_turn: Optional[Callable[[TurnContext], bool]] = None
    before_tool_call: Optional[Callable[[AgentTool, Dict], Optional[str]]] = None
    after_tool_call: Optional[Callable[[ToolResult], ToolResult]] = None
    final_answer_guard: Optional[
        Callable[[List[AgentMessage]], Optional[Tuple[Optional[str], Optional[str]]]]
    ] = None
    route_note: Optional[str] = None
    tool_timeout_s: int = 120
    followup_question: Optional[bool] = None
    pending_messages_provider: Optional[Callable[[], List[AgentMessage]]] = None


def _safe_emit(emit: Optional[Callable[[AgentEvent], None]], event: AgentEvent) -> None:
    """事件出口绝不因回调异常炸掉循环。"""
    if emit is None:
        return
    try:
        emit(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning("emit 回调异常（已忽略）: %s", exc)


def _run_callback(callback, default, *args):
    """回调异常一律 fail-open（视为未设置/不拦截）并记 warning。"""
    if callback is None:
        return default
    try:
        return callback(*args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent 回调异常，按未设置处理: %s", exc)
        return default


def _tool_evidence_present(messages: List[AgentMessage]) -> bool:
    """工具返回中是否存在非空证据文本（items[].text）。"""
    for message in messages:
        if message.role != "tool" or message.is_error:
            continue
        try:
            raw = json.loads(message.content or "{}")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(raw, dict):
            continue
        for item in raw.get("items") or []:
            if isinstance(item, dict) and str(item.get("text") or "").strip():
                return True
    return False


def _last_answer_is_refusal(messages: List[AgentMessage]) -> bool:
    """最近一条无工具调用的 assistant 消息是否为拒答话术。"""
    for message in reversed(messages):
        if message.role == "assistant" and not message.tool_calls:
            return is_refusal_text(message.content or "")
    return False


# 系统注入的指令前缀（用于与真实用户提问区分）
_INJECTED_USER_PREFIXES = (
    "请先调用检索工具",
    "请针对用户当前问题",
    "上一段未命中",
    "轮次预算已用完",
    "已代为执行知识检索",
    "已检索到有效证据",
)


def _current_user_question(messages: List[AgentMessage], start_idx: int) -> str:
    """本轮的真实用户问题。

    优先取 run 起点前一条 user 消息（AgentSession 追加的当前提问）；
    兜底逆序找最后一条非系统注入的 user 消息，避免把历史话题/注入指令误当当前问题。
    """
    if 0 < start_idx <= len(messages):
        candidate = messages[start_idx - 1]
        if candidate.role == "user" and (candidate.content or "").strip():
            return candidate.content
    for message in reversed(messages):
        if message.role != "user":
            continue
        content = (message.content or "").strip()
        if content and not content.startswith(_INJECTED_USER_PREFIXES):
            return content
    return ""


def _force_retrieve_tool(
    messages: List[AgentMessage],
    machine: "_AttemptMachine",
    emit: Optional[Callable[[AgentEvent], None]],
    run_id: str,
    cancel: threading.Event,
) -> Optional[str]:
    """代检索保险：模型拒答且未调用检索工具时，系统替它执行 knowledge_search。

    绕开模型输出工具调用格式不稳定的问题，直接把检索结果注入对话。
    query 锁定本轮真实用户问题（而非会话最旧消息），避免历史话题污染。
    返回工具结果文本；失败或工具不存在时返回 None（保持原收尾逻辑）。
    """
    query = _current_user_question(messages, machine.start_idx)
    if not query:
        return None
    tool = machine.tools_by_name.get("knowledge_search")
    if tool is None:
        return None
    call = ToolCall(id="forced_knowledge_search", name="knowledge_search", arguments={"query": query})
    try:
        results = _execute_tools_batch(
            [call], machine.tools_by_name, machine.active_config, cancel, emit, run_id,
            machine.current_turn or 0,
        )
        return results[0].content if results else None
    except Exception:  # noqa: BLE001
        logger.warning("代检索保险执行失败，按原逻辑收尾", exc_info=True)
        return None


def _validate_arguments(schema: Dict[str, Any], arguments: Dict[str, Any]) -> Optional[str]:
    try:
        import jsonschema

        jsonschema.validate(instance=arguments, schema=schema or {"type": "object", "properties": {}})
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def _json_content(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _run_tool_inner(call, tool: AgentTool) -> ToolResult:
    try:
        raw = tool.handler(**call.arguments)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raw = {"result": raw}
        raw = dict(raw)
        terminate = bool(raw.pop("terminate", False))
        return ToolResult(
            call_id=call.id,
            name=tool.name,
            content=_json_content(raw),
            is_error=bool(raw.get("error")),
            terminate=terminate,
            raw=raw,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            call_id=call.id,
            name=tool.name,
            content=f"工具执行失败: {exc}",
            is_error=True,
        )


def _timeout_result(call, tool: AgentTool, timeout: int) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=tool.name,
        content=f"工具 {tool.name} 执行超时（{timeout}s）；线程未杀死（如实记录限制）",
        is_error=True,
    )


def _execute_tools_batch(
    calls: List,
    tools_by_name: Dict[str, AgentTool],
    config: AgentLoopConfig,
    cancel: threading.Event,
    emit: Optional[Callable[[AgentEvent], None]],
    run_id: str,
    turn: int,
) -> List[ToolResult]:
    """工具三阶段：prepare（查找/schema 校验/before 钩子）→ execute → finalize。"""
    results: List[ToolResult] = []
    pending: List[Tuple] = []

    def fail(call, message: str) -> ToolResult:
        _safe_emit(
            emit,
            AgentEvent(type="tool_start", run_id=run_id, turn=turn, payload={"call_id": call.id, "name": call.name, "args": call.arguments}),
        )
        result = ToolResult(call_id=call.id, name=call.name, content=message, is_error=True)
        _safe_emit(
            emit,
            AgentEvent(type="tool_end", run_id=run_id, turn=turn, payload={"call_id": call.id, "name": call.name, "is_error": True, "duration_ms": 0, "result": message[:300]}),
        )
        return result

    for call in calls:
        tool = tools_by_name.get(call.name)
        if tool is None:
            results.append(fail(call, f"工具未注册: {call.name}"))
            continue
        validation_error = _validate_arguments(tool.parameters_schema, call.arguments)
        if validation_error:
            results.append(fail(call, f"参数校验失败: {validation_error}"))
            continue
        block_reason = _run_callback(config.before_tool_call, None, tool, call.arguments)
        if block_reason:
            results.append(fail(call, f"工具调用被拦截: {block_reason}"))
            continue
        pending.append((call, tool))

    if cancel.is_set():
        # 取消发生在执行前：仍然补发 tool_start/tool_end 和错误结果，
        # 保证思考过程能看到"已取消（未执行）"这一步。
        for call, _tool in pending:
            results.append(fail(call, "工具调用已取消（未执行）"))
        return [_run_callback(config.after_tool_call, result, result) for result in results]
    if not pending:
        return [_run_callback(config.after_tool_call, result, result) for result in results]

    timeout = max(1, config.tool_timeout_s or 120)
    sequential = any(tool.execution_mode == "sequential" for _, tool in pending)
    executor = ThreadPoolExecutor(max_workers=1 if sequential else min(len(pending), 8))
    try:
        for call, tool in pending:
            _safe_emit(
                emit,
                AgentEvent(type="tool_start", run_id=run_id, turn=turn, payload={"call_id": call.id, "name": tool.name, "args": call.arguments}),
            )

        if sequential:
            for call, tool in pending:
                if cancel.is_set():
                    break
                started = time.monotonic()
                future = executor.submit(_run_tool_inner, call, tool)
                try:
                    result = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    result = _timeout_result(call, tool, timeout)
                results.append(result)
                _safe_emit(
                    emit,
                    AgentEvent(type="tool_end", run_id=run_id, turn=turn, payload={"call_id": call.id, "name": tool.name, "is_error": result.is_error, "duration_ms": int((time.monotonic() - started) * 1000), "result": result.content[:300]}),
                )
        else:
            futures = {executor.submit(_run_tool_inner, call, tool): (call, tool) for call, tool in pending}
            for future, (call, tool) in futures.items():
                started = time.monotonic()
                try:
                    result = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    result = _timeout_result(call, tool, timeout)
                    # 超时后立即放弃等待；剩余 future 由 shutdown(cancel_futures=True) 取消/泄漏
                results.append(result)
                _safe_emit(
                    emit,
                    AgentEvent(type="tool_end", run_id=run_id, turn=turn, payload={"call_id": call.id, "name": tool.name, "is_error": result.is_error, "duration_ms": int((time.monotonic() - started) * 1000), "result": result.content[:300]}),
                )
    finally:
        # 关键：禁止 with ThreadPoolExecutor（默认 shutdown(wait=True) 会阻塞到线程跑完）
        executor.shutdown(wait=False, cancel_futures=True)

    # finalize：after_tool_call 补丁（异常 fail-open）
    return [_run_callback(config.after_tool_call, result, result) for result in results]


_TOOL_FENCE = "```tool_calls"


def _split_delta_flush(pending: str, suppress: bool) -> Tuple[str, str, bool]:
    """流式上屏过滤：扣住/抑制 tool_calls 围栏标记，其余文本原样放行。

    返回 (本次可发射文本, 剩余待判定 pending, 是否处于工具块抑制中)。
    流结束时残留的 pending 必为半截工具标记，直接丢弃（不上屏）；
    唯一的例外是裸 "```"（多为正常代码块闭合围栏），由调用方在流末放行。
    从左到右逐围栏扫描：完整工具块在一个 chunk 内也能正确识别。
    """
    out: List[str] = []
    while pending:
        if suppress:
            end = pending.find("```")
            if end < 0:
                return "".join(out), "", True
            pending = pending[end + 3:]
            suppress = False
            continue
        idx = pending.find("```")
        if idx < 0:
            out.append(pending)
            pending = ""
            break
        tail = pending[idx:]
        tail_lower = tail.lower()
        if _TOOL_FENCE.startswith(tail_lower):
            # tail 是 ```tool_calls 的真前缀（含 "```" 本身）：扣住等后续 delta 判定
            out.append(pending[:idx])
            pending = tail
            break
        if tail_lower.startswith(_TOOL_FENCE):
            # 完整工具块标记：之前文本放行，进入抑制直到闭合围栏
            out.append(pending[:idx])
            pending = tail[len(_TOOL_FENCE):]
            suppress = True
            continue
        # 普通代码围栏：放行到该围栏为止，继续向右扫描
        out.append(pending[: idx + 3])
        pending = pending[idx + 3:]
    return "".join(out), pending, suppress


def _run_llm_turn(
    messages: List[AgentMessage],
    new_prompt_messages: List[AgentMessage],
    config: AgentLoopConfig,
    codec,
    tools_by_name: Dict[str, AgentTool],
    emit: Optional[Callable[[AgentEvent], None]],
    run_id: str,
    cancel: threading.Event,
    turn: int,
    allow_tools: bool,
) -> Tuple[AgentMessage, List, List[ToolResult], Dict[str, Any]]:
    """执行一轮 LLM 调用。

    返回 (assistant 消息, 待执行工具调用, 直接结果（截断守卫产物）, usage)。
    """
    for message in new_prompt_messages:
        _safe_emit(emit, AgentEvent(type="message_start", run_id=run_id, turn=turn, payload={}))
        _safe_emit(emit, AgentEvent(type="message_end", run_id=run_id, turn=turn, payload={}))

    # 闸门一：transform_context（异常视为未设置）
    transformed = _run_callback(config.transform_context, messages, messages)
    if not isinstance(transformed, list):
        transformed = messages

    tool_style = "native" if isinstance(codec, NativeToolCallCodec) else "text"
    llm_messages = [
        {"role": "system", "content": codec.augment_system_prompt(config.system_prompt, config.tools if allow_tools else [])}
    ]
    llm_messages.extend(to_llm_messages(transformed, tool_style=tool_style))

    _safe_emit(emit, AgentEvent(type="message_start", run_id=run_id, turn=turn, payload={}))
    full_text = ""
    finish_reason = None
    usage: Dict[str, Any] = {}
    pending_delta = ""
    suppress_tool_block = False
    try:
        for event in config.llm.chat_stream_events(
            llm_messages,
            model=config.model,
            mode=config.mode,
            config_name=config.config_name,
            max_tokens=config.max_tokens,
        ):
            if cancel.is_set():
                break
            if event.get("type") == "delta":
                delta = event.get("text") or ""
                full_text += delta
                pending_delta += delta
                emit_text, pending_delta, suppress_tool_block = _split_delta_flush(pending_delta, suppress_tool_block)
                if emit_text:
                    _safe_emit(emit, AgentEvent(type="message_delta", run_id=run_id, turn=turn, payload={"delta": emit_text}))
            elif event.get("type") == "done":
                finish_reason = event.get("finish_reason")
                if event.get("usage"):
                    usage = dict(event["usage"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 流式调用异常: %s", exc)
        finish_reason = finish_reason or "error"

    # 流末遗留：裸 "```" 多为正常代码块的闭合围栏，放行；
    # 更长的半截 tool_calls 标记（如 ```tool_c）属于工具垃圾，直接丢弃不上屏。
    if pending_delta == "```":
        _safe_emit(emit, AgentEvent(type="message_delta", run_id=run_id, turn=turn, payload={"delta": pending_delta}))

    # 解析工具调用（解析失败 fail-open 到纯文本答案）
    calls: List = []
    try:
        _, calls = codec.parse_assistant(full_text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("codec 解析失败，按纯文本答案处理: %s", exc)
        calls = []

    has_tool_calls = bool(calls)
    _safe_emit(
        emit,
        AgentEvent(type="message_end", run_id=run_id, turn=turn, payload={"finish_reason": finish_reason, "has_tool_calls": has_tool_calls}),
    )

    assistant = AgentMessage(role="assistant", content=full_text, tool_calls=calls)
    direct_results: List[ToolResult] = []

    # 截断守卫（P5）：finish_reason == "length" 时本轮 tool_calls 全部作废
    if finish_reason == "length":
        if calls:
            for call in calls:
                direct_results.append(
                    ToolResult(
                        call_id=call.id,
                        name=call.name,
                        content="输出被长度截断，参数可能不完整，请重新发起调用",
                        is_error=True,
                    )
                )
        else:
            direct_results.append(
                ToolResult(
                    call_id=f"call_{turn}_truncated",
                    name="",
                    content="输出被长度截断，请基于已有内容直接给出最终答案",
                    is_error=True,
                )
            )
        return assistant, [], direct_results, usage

    return assistant, calls, [], usage


class _AttemptMachine:
    """attempt 分段状态机：应用段配置、判定段结果、fallback/retry/拒答收尾。

    状态全部显式持有（替代原先的 nonlocal 共享），事件出口通过注入的 add_note。
    """

    def __init__(
        self,
        config: AgentLoopConfig,
        messages: List[AgentMessage],
        start_idx: int,
        add_note: Callable[[str], None],
        clear_answer: Optional[Callable[[], None]] = None,
    ) -> None:
        self.base_config = config
        self.attempts = list(config.attempts or [])
        self.messages = messages
        self.start_idx = start_idx
        self.attempt_start_idx = start_idx
        self.add_note = add_note
        self._clear_answer_cb = clear_answer
        self.active_config = config
        self.active_attempt_idx = -1
        self.attempt_turn = 0
        self.retry_used = False
        self.refusal_retry_used = False
        self.current_turn = 0
        self.force_retrieve: Optional[Callable[[], Optional[str]]] = None
        self._forced_retrieve_used = False
        self.codec = config.codec or TextToolCallCodec()
        self.tools_by_name = {tool.name: tool for tool in config.tools}

    def start(self) -> None:
        if self.attempts:
            self.apply(0)
            self.add_note("执行计划：" + " → ".join(a.name for a in self.attempts))

    def apply(self, index: int) -> None:
        """应用第 index 段的完整可覆盖字段；codec 随段刷新。"""
        self.active_attempt_idx = index
        self.attempt_start_idx = len(self.messages)
        self.retry_used = False
        self.refusal_retry_used = False
        self._forced_retrieve_used = False
        nested = self.attempts[index].config_factory()
        active = replace(
            self.base_config,
            llm=nested.llm,
            model=nested.model,
            config_name=nested.config_name,
            mode=nested.mode,
            max_tokens=nested.max_tokens,
            tools=nested.tools,
            system_prompt=nested.system_prompt,
            max_turns=nested.max_turns,
            codec=nested.codec or self.base_config.codec,
            final_answer_guard=nested.final_answer_guard,
            transform_context=nested.transform_context,
            should_stop_after_turn=nested.should_stop_after_turn,
            tool_timeout_s=nested.tool_timeout_s,
            followup_question=nested.followup_question,
            pending_messages_provider=nested.pending_messages_provider or self.base_config.pending_messages_provider,
        )
        self.codec = active.codec or TextToolCallCodec()
        self.active_config = active
        self.tools_by_name = {tool.name: tool for tool in active.tools}

    def _refusal_text(self) -> str:
        if getattr(self.active_config, "followup_question", False):
            return REFUSAL_ANSWER_TEXT + REFUSAL_FOLLOWUP_QUESTION
        return REFUSAL_ANSWER_TEXT

    def _clear_answer(self) -> None:
        """重试前清空前端正文气泡：避免多轮 delta 缝合成怪文本。"""
        _run_callback(self._clear_answer_cb, None)

    def advance(self) -> str:
        """当前段成功→"completed"；失败且有下一段→切换并返回 "next"；
        需要工具但未调用→返回 "retry"（最多一次）；有证据却拒答→终段定向重试（最多一次）；
        否则 "exhausted"。"""
        added = self.messages[self.start_idx:]
        attempt = self.attempts[self.active_attempt_idx]
        check = attempt.success_check
        used_tools = any(m.role == "tool" for m in self.messages[self.attempt_start_idx:])
        ok = check is None or bool(_run_callback(check, True, added))
        if ok:
            if not (attempt.requires_tools and not used_tools):
                return "completed"
        if attempt.requires_tools and not used_tools:
            if not self.retry_used:
                self.retry_used = True
                # 腾出一轮带工具的预算：这次“直接作答”不计入轮次预算
                self.attempt_turn = max(0, self.attempt_turn - 1)
                question = _current_user_question(self.messages, self.start_idx) or "（未识别到当前问题）"
                self.messages.append(AgentMessage(
                    role="user",
                    content=(
                        f"请针对用户当前问题「{question}」调用检索工具获取证据后再回答；"
                        "检索 query 必须围绕该问题，不得使用历史对话中的其他主题。"
                    ),
                ))
                self.add_note("未调用检索工具，已要求重新检索后回答")
                self._clear_answer()
                return "retry"
            # 代检索保险：仍不调工具且最终答案是拒答时，替模型执行 knowledge_search 再答一轮
            if (
                self.force_retrieve is not None
                and not self._forced_retrieve_used
            ):
                result_content = self.force_retrieve()
                if result_content:
                    self._forced_retrieve_used = True
                    self.attempt_turn = max(0, self.attempt_turn - 1)
                    self.messages.append(
                        AgentMessage(
                            role="tool",
                            content=result_content,
                            tool_call_id="forced_knowledge_search",
                            name="knowledge_search",
                        )
                    )
                    self.messages.append(
                        AgentMessage(
                            role="user",
                            content="已代为执行知识检索，请基于检索到的证据给出最终答案；"
                            "若证据只覆盖部分内容，请回答已支持的部分并说明缺失项，不要整体拒答。",
                        )
                    )
                    self.add_note("最终回答为拒答且未调用检索工具，已代为执行 knowledge_search 并要求基于证据重答")
                    self._clear_answer()
                    return "retry"
            return self._finalize_no_tool_answer(added)
        if (
            not ok
            and used_tools
            and self.active_attempt_idx + 1 >= len(self.attempts)
            and not self.refusal_retry_used
            and _tool_evidence_present(self.messages[self.attempt_start_idx:])
            and _last_answer_is_refusal(self.messages[self.attempt_start_idx:])
        ):
            self.refusal_retry_used = True
            # 定向重试不占本轮预算
            self.attempt_turn = max(0, self.attempt_turn - 1)
            self.messages.append(AgentMessage(
                role="user",
                content="已检索到有效证据，请基于证据作答；若证据只覆盖部分内容，请回答已支持的部分并明确说明缺失项，不要整体拒答。",
            ))
            self.add_note("有有效证据但回答为拒答，已要求基于证据重答")
            self._clear_answer()
            return "retry"
        if self.active_attempt_idx + 1 < len(self.attempts):
            nxt = self.attempts[self.active_attempt_idx + 1]
            self.add_note(attempt.fallback_note or f"本段未命中，进入下一段：{nxt.name}")
            self.messages.append(AgentMessage(role="user", content=f"上一段未命中，进入下一段：{nxt.name}"))
            self.apply(self.active_attempt_idx + 1)
            self.attempt_turn = 0
            return "next"
        return self._finalize_no_tool_answer(added)

    def _finalize_no_tool_answer(self, added: List[AgentMessage]) -> str:
        """requires_tools 重试后仍不调工具：保留非空最终答案，空答案才补拒答。"""
        final_answer = next(
            (
                m for m in reversed(added)
                if m.role == "assistant" and not m.tool_calls and (m.content or "").strip()
            ),
            None,
        )
        if final_answer is not None:
            return "completed"
        return "exhausted"

    def finalize_refusal(self) -> str:
        """终段没有产出任何答案时，补一条拒答并以 completed 收尾，避免前端无结果。"""
        self.messages.append(AgentMessage(role="assistant", content=self._refusal_text()))
        self.add_note("未产生可用答案，已按拒答收尾")
        return "completed"


def _apply_final_guard(
    config: AgentLoopConfig,
    messages: List[AgentMessage],
    start_idx: int,
    emit: Optional[Callable[[AgentEvent], None]],
    run_id: str,
    turn: int,
    add_note: Callable[[str], None],
) -> None:
    """最终答案边界（P6c）：guard 自行区分检索过/未检索。"""
    added_messages = messages[start_idx:]
    final_assistant = next(
        (m for m in reversed(added_messages) if m.role == "assistant" and not m.tool_calls),
        None,
    )
    if final_assistant is None:
        return
    guard_result = _run_callback(config.final_answer_guard, None, added_messages)
    if not guard_result:
        return
    new_content, guard_note = guard_result
    if guard_note:
        add_note(guard_note)
    if new_content is not None and new_content != final_assistant.content:
        final_assistant.content = new_content
        _safe_emit(
            emit,
            AgentEvent(
                type="answer",
                run_id=run_id,
                turn=turn,
                payload={"content": new_content},
            ),
        )


def run_agent_loop(
    messages: List[AgentMessage],
    config: AgentLoopConfig,
    emit: Optional[Callable[[AgentEvent], None]] = None,
    cancel: Optional[threading.Event] = None,
    run_id: Optional[str] = None,
    pending_messages_provider: Optional[Callable[[], List[AgentMessage]]] = None,
) -> List[AgentMessage]:
    """执行 agent 循环，就地追加消息，返回本 run 新增的消息。"""
    run_id = run_id or uuid.uuid4().hex[:12]
    cancel_event = cancel if cancel is not None else threading.Event()
    provider = pending_messages_provider if pending_messages_provider is not None else config.pending_messages_provider
    start_idx = len(messages)
    turn = 0
    total_usage: Dict[str, Any] = {}
    reason = "completed"
    trace_notes: List[Dict[str, Any]] = []

    def _add_note(detail: str) -> None:
        """记录一条可见的边界/过程说明，实时事件与 run_end 都会带上。"""
        trace_notes.append({"detail": detail})
        _safe_emit(
            emit,
            AgentEvent(type="note", run_id=run_id, turn=turn, payload={"detail": detail}),
        )

    _safe_emit(emit, AgentEvent(type="run_start", run_id=run_id, turn=0, payload={}))
    if config.route_note:
        _add_note(config.route_note)

    def _clear_answer() -> None:
        """重试边界通知前端清空正文气泡（delta 晚绑定读取当前 turn）。"""
        _safe_emit(
            emit,
            AgentEvent(type="answer", run_id=run_id, turn=turn, payload={"content": ""}),
        )

    # —— 分段（attempt）初始化 ——
    machine = _AttemptMachine(config, messages, start_idx, _add_note, clear_answer=_clear_answer)
    machine.force_retrieve = lambda: _force_retrieve_tool(messages, machine, emit, run_id, cancel_event)
    machine.start()

    try:
        if cancel_event.is_set():
            reason = "cancelled"
            _add_note("用户取消，停止生成")
        else:
            prev_len = start_idx
            while True:
                # 决策点：steer 注入 / should_stop / cancel / max_turns
                if provider is not None:
                    pending = _run_callback(provider, [])
                    if pending:
                        messages.extend(pending)

                if turn > 0:
                    turn_context = TurnContext(turn=turn, messages=messages, tool_results=[], usage=total_usage)
                    if _run_callback(machine.active_config.should_stop_after_turn, False, turn_context):
                        reason = "should_stop"
                        _add_note("上下文预算超阈值，停止继续调用工具（should_stop）")
                        break
                    if cancel_event.is_set():
                        reason = "cancelled"
                        _add_note("用户取消，停止生成")
                        break
                    budget = machine.active_config.max_turns if machine.attempts else config.max_turns
                    if machine.attempt_turn >= budget:
                        # 段预算耗尽：不硬断，追加预算提示后给最后一次无工具收尾 turn
                        _add_note(
                            f"轮次预算已用完（max_turns={budget}），进入无工具收尾回答"
                        )
                        messages.append(
                            AgentMessage(role="user", content="轮次预算已用完，请基于已有证据直接给出最终答案")
                        )
                        new_prompt = messages[prev_len:]
                        prev_len = len(messages)
                        turn += 1
                        machine.attempt_turn += 1
                        machine.current_turn = turn
                        _safe_emit(emit, AgentEvent(type="turn_start", run_id=run_id, turn=turn, payload={"turn": turn}))
                        assistant, _, direct_results, usage = _run_llm_turn(
                            messages, new_prompt, machine.active_config, machine.codec, machine.tools_by_name,
                            emit, run_id, cancel_event, turn, allow_tools=False,
                        )
                        messages.append(assistant)
                        if usage:
                            total_usage.update(usage)
                        for result in direct_results:
                            messages.append(
                                AgentMessage(role="tool", content=result.content, tool_call_id=result.call_id, name=result.name, is_error=result.is_error)
                            )
                        _safe_emit(emit, AgentEvent(type="turn_end", run_id=run_id, turn=turn, payload={"turn": turn, "tool_results": []}))
                        if machine.attempts:
                            status = machine.advance()
                            if status == "next":
                                continue
                            if status in ("exhausted", "retry"):
                                reason = machine.finalize_refusal()
                            break  # completed / exhausted 均已收尾，reason 已维护
                        reason = "max_turns"
                        break

                turn += 1
                machine.attempt_turn += 1
                machine.current_turn = turn
                _safe_emit(emit, AgentEvent(type="turn_start", run_id=run_id, turn=turn, payload={"turn": turn}))
                new_prompt = messages[prev_len:]
                prev_len = len(messages)

                assistant, calls, direct_results, usage = _run_llm_turn(
                    messages, new_prompt, machine.active_config, machine.codec, machine.tools_by_name,
                    emit, run_id, cancel_event, turn, allow_tools=True,
                )
                messages.append(assistant)
                if usage:
                    total_usage.update(usage)

                if direct_results:
                    # 截断守卫产物：直接作为工具结果喂回，不执行任何工具
                    _add_note("输出被长度截断（finish_reason=length），本轮工具调用已作废")
                    for result in direct_results:
                        messages.append(
                            AgentMessage(role="tool", content=result.content, tool_call_id=result.call_id, name=result.name, is_error=result.is_error)
                        )
                    _safe_emit(
                        emit,
                        AgentEvent(type="turn_end", run_id=run_id, turn=turn, payload={"turn": turn, "tool_results": [_tool_summary(r) for r in direct_results]}),
                    )
                    continue

                if calls:
                    tool_results = _execute_tools_batch(
                        calls, machine.tools_by_name, machine.active_config, cancel_event, emit, run_id, turn,
                    )
                    for result in tool_results:
                        messages.append(
                            AgentMessage(role="tool", content=result.content, tool_call_id=result.call_id, name=result.name, is_error=result.is_error, meta=result.raw)
                        )
                    _safe_emit(
                        emit,
                        AgentEvent(type="turn_end", run_id=run_id, turn=turn, payload={"turn": turn, "tool_results": [_tool_summary(r) for r in tool_results]}),
                    )
                    if tool_results and all(result.terminate for result in tool_results):
                        reason = "terminated"
                        _add_note("工具返回终止信号，提前结束（terminate）")
                        break
                    continue

                # 无工具调用：模型主动给出最终答案，正常停
                _safe_emit(emit, AgentEvent(type="turn_end", run_id=run_id, turn=turn, payload={"turn": turn, "tool_results": []}))
                if machine.attempts:
                    status = machine.advance()
                    if status == "next":
                        continue
                    if status == "retry":
                        continue  # 已追加“请先调用检索工具”的用户消息，下一轮带工具重试
                    if status == "exhausted":
                        reason = machine.finalize_refusal()
                        break
                reason = "completed"
                break
    except Exception as exc:  # noqa: BLE001
        reason = "error"
        logger.exception("agent 循环致命错误")
        _safe_emit(
            emit,
            AgentEvent(type="error", run_id=run_id, turn=turn, payload={"message": str(exc), "stage": "run_agent_loop"}),
        )

    # 最终答案边界（P6c）：guard 自行区分检索过/未检索。
    # 有工具结果时做证据拒答 + 标记校验；没有工具结果时仍执行标记清理
    # （模型未调工具却输出 [Kx] 视为编造）。L0 闲聊档不装 guard，不受影响。
    if reason not in ("error", "cancelled"):
        _apply_final_guard(machine.active_config, messages, start_idx, emit, run_id, turn, _add_note)

    _safe_emit(
        emit,
        AgentEvent(
            type="run_end",
            run_id=run_id,
            turn=turn,
            payload={
                "reason": reason,
                "turns": turn,
                "messages": [agent_message_to_dict(m) for m in messages[start_idx:]],
                "usage": total_usage,
                "notes": trace_notes,
            },
        ),
    )
    return messages[start_idx:]


def _tool_summary(result: ToolResult) -> Dict[str, Any]:
    return {
        "call_id": result.call_id,
        "name": result.name,
        "is_error": result.is_error,
        "terminate": result.terminate,
    }

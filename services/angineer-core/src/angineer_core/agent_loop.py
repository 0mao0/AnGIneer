"""无状态 agent 循环原语（P2，§6.4 / P2.2）。

边界：本模块只允许依赖 agent_messages / agent_events / agent_tools /
tool_codec / contracts，禁止反向依赖 dispatcher / classifier / memory。
"""
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from angineer_core.agent_events import AgentEvent
from angineer_core.agent_messages import (
    AgentMessage,
    agent_message_to_dict,
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
    # —— 闸门与决策点（全部可选回调）——
    transform_context: Optional[Callable[[List[AgentMessage]], List[AgentMessage]]] = None
    should_stop_after_turn: Optional[Callable[[TurnContext], bool]] = None
    before_tool_call: Optional[Callable[[AgentTool, Dict], Optional[str]]] = None
    after_tool_call: Optional[Callable[[ToolResult], ToolResult]] = None
    tool_timeout_s: int = 120
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

    if not pending or cancel.is_set():
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
                _safe_emit(emit, AgentEvent(type="message_delta", run_id=run_id, turn=turn, payload={"delta": delta}))
            elif event.get("type") == "done":
                finish_reason = event.get("finish_reason")
                if event.get("usage"):
                    usage = dict(event["usage"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 流式调用异常: %s", exc)
        finish_reason = finish_reason or "error"

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
    codec = config.codec or TextToolCallCodec()
    tools_by_name = {tool.name: tool for tool in config.tools}
    start_idx = len(messages)
    turn = 0
    total_usage: Dict[str, Any] = {}
    reason = "completed"

    _safe_emit(emit, AgentEvent(type="run_start", run_id=run_id, turn=0, payload={}))

    try:
        if cancel_event.is_set():
            reason = "cancelled"
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
                    if _run_callback(config.should_stop_after_turn, False, turn_context):
                        reason = "should_stop"
                        break
                    if cancel_event.is_set():
                        reason = "cancelled"
                        break
                    if turn >= config.max_turns:
                        # max_turns：不硬断，追加预算提示后给最后一次无工具收尾 turn
                        messages.append(
                            AgentMessage(role="user", content="轮次预算已用完，请基于已有证据直接给出最终答案")
                        )
                        new_prompt = messages[prev_len:]
                        prev_len = len(messages)
                        turn += 1
                        _safe_emit(emit, AgentEvent(type="turn_start", run_id=run_id, turn=turn, payload={"turn": turn}))
                        assistant, _, direct_results, usage = _run_llm_turn(
                            messages, new_prompt, config, codec, tools_by_name,
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
                        reason = "max_turns"
                        break

                turn += 1
                _safe_emit(emit, AgentEvent(type="turn_start", run_id=run_id, turn=turn, payload={"turn": turn}))
                new_prompt = messages[prev_len:]
                prev_len = len(messages)

                assistant, calls, direct_results, usage = _run_llm_turn(
                    messages, new_prompt, config, codec, tools_by_name,
                    emit, run_id, cancel_event, turn, allow_tools=True,
                )
                messages.append(assistant)
                if usage:
                    total_usage.update(usage)

                if direct_results:
                    # 截断守卫产物：直接作为工具结果喂回，不执行任何工具
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
                        calls, tools_by_name, config, cancel_event, emit, run_id, turn,
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
                        break
                    continue

                # 无工具调用：模型主动给出最终答案，正常停
                _safe_emit(emit, AgentEvent(type="turn_end", run_id=run_id, turn=turn, payload={"turn": turn, "tool_results": []}))
                reason = "completed"
                break
    except Exception as exc:  # noqa: BLE001
        reason = "error"
        logger.exception("agent 循环致命错误")
        _safe_emit(
            emit,
            AgentEvent(type="error", run_id=run_id, turn=turn, payload={"message": str(exc), "stage": "run_agent_loop"}),
        )

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

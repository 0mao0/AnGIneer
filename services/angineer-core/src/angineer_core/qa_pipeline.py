"""答题流水线（P6c 从 dispatcher.py 下沉）。

承载检索后的证据组织、system prompt 构建、两阶段抽取/判定（失败回退单次
调用）与拒答校验；legacy L1 路径与 agentic 路径共用本模块。
"""
import os
import re
import time
from typing import Any, Dict, Tuple

from angineer_core.prompts.dispatcher import (
    EXTRACT_SYSTEM_PROMPT,
    EXTRACT_USER_CHOICE,
    EXTRACT_USER_GENERAL,
    JUDGE_USER_CHOICE,
    JUDGE_USER_CHOICE_EXPLICIT,
    JUDGE_USER_GENERAL,
    JUDGE_USER_GENERAL_EXPLICIT,
    SYSTEM_PROMPT_BASE,
    SYSTEM_PROMPT_CHOICE_RULES,
    SYSTEM_PROMPT_GAP_ANALYSIS,
    SYSTEM_PROMPT_RULES_CONTENT_QA,
    SYSTEM_PROMPT_RULES_DEFINITION_QA,
    SYSTEM_PROMPT_RULES_LOCATE_QA,
)

MULTI_CHOICE_PATTERN = re.compile(r"[(（][A-E][)）]")

REFUSAL_ANSWER_TEXT = (
    "没有检索到足够证据支持最终结论。"
    "当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案，请继续补充可核对的规范依据。"
)


def is_choice_query(query: str) -> bool:
    """判断问题是否包含选择题选项标记。"""
    return bool(query) and bool(MULTI_CHOICE_PATTERN.search(query))


def build_system_prompt(retriever_task_type: str, query: str = "") -> str:
    """根据检索任务类型构建对应的 system prompt。"""
    gap_analysis_enabled = os.environ.get("ANGINEER_GAP_ANALYSIS_ENABLED", "true").lower() == "true"

    base_prompt = SYSTEM_PROMPT_BASE
    is_choice = is_choice_query(query)

    if retriever_task_type == "definition_qa":
        prompt = base_prompt + SYSTEM_PROMPT_RULES_DEFINITION_QA
    elif retriever_task_type == "locate_qa":
        prompt = base_prompt + SYSTEM_PROMPT_RULES_LOCATE_QA
    else:
        prompt = base_prompt + SYSTEM_PROMPT_RULES_CONTENT_QA

    if is_choice:
        prompt += SYSTEM_PROMPT_CHOICE_RULES

    # 知识盲区分析指令（可通过环境变量关闭）
    if gap_analysis_enabled and not is_choice:
        prompt += SYSTEM_PROMPT_GAP_ANALYSIS

    return prompt


def build_answer_context(fused, top_n: int = 10) -> str:
    """从检索结果构建上下文文本（与 dispatcher 原实现一致）。"""
    context_parts = []
    for item in fused[:top_n]:
        if not item.text:
            continue
        section = str(item.metadata.get("section_path") or "")
        title = str(item.title or "")
        prefix = (
            f"[{section}]"
            if section
            else (f"[{title}]" if title else "")
        )
        context_parts.append(
            f"{prefix}\n{item.text}" if prefix else item.text
        )
    return "\n---\n".join(context_parts)


def build_user_prompt(query: str, context_text: str, explicit_evidence_text: str) -> str:
    """构建单次调用/兜底调用的用户消息。"""
    return (
        f"问题: {query}\n\n显式引用证据:\n{explicit_evidence_text}\n\n检索结果:\n{context_text}"
        if explicit_evidence_text
        else f"问题: {query}\n\n检索结果:\n{context_text}"
    )


def build_evidence_text(explicit_evidence_text: str, context_text: str) -> str:
    """合并显式引用与检索上下文为拒答校验语料。"""
    return f"{explicit_evidence_text}\n{context_text}".strip()


def _run_single_stage_answer(
    llm: Any, *, query: str, system_prompt: str, context_text: str, explicit_evidence_text: str
) -> Tuple[str, Dict[str, float]]:
    started = time.time()
    user_prompt_content = build_user_prompt(query, context_text, explicit_evidence_text)
    answer = llm.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_content},
        ],
        mode="instruct",
    )
    return answer, {"llm": round(time.time() - started, 2)}


def run_two_stage_answer(
    llm: Any,
    *,
    query: str,
    system_prompt: str,
    context_text: str,
    explicit_evidence_text: str,
) -> Tuple[str, Dict[str, float]]:
    """两阶段答题：LLM 先预过滤证据，再基于过滤结果回答；失败回退单次调用。"""
    if not context_text.strip():
        return _run_single_stage_answer(
            llm,
            query=query,
            system_prompt=system_prompt,
            context_text=context_text,
            explicit_evidence_text=explicit_evidence_text,
        )

    is_choice = is_choice_query(query)
    extract_system = EXTRACT_SYSTEM_PROMPT
    if is_choice:
        extract_user = EXTRACT_USER_CHOICE.format(context_text=context_text)
    else:
        extract_user = EXTRACT_USER_GENERAL.format(
            query=query, context_text=context_text
        )

    _t2 = time.time()
    try:
        filtered_evidence = llm.chat(
            [
                {"role": "system", "content": extract_system},
                {"role": "user", "content": extract_user},
            ],
            mode="instruct",
        )
        timings: Dict[str, float] = {"llm_extract": round(time.time() - _t2, 2)}

        _t3 = time.time()
        if is_choice:
            judge_user = JUDGE_USER_CHOICE.format(
                query=query, filtered_evidence=filtered_evidence
            )
            if explicit_evidence_text:
                judge_user = JUDGE_USER_CHOICE_EXPLICIT.format(
                    query=query,
                    explicit_evidence_text=explicit_evidence_text,
                    filtered_evidence=filtered_evidence,
                )
        else:
            judge_user = JUDGE_USER_GENERAL.format(
                query=query, filtered_evidence=filtered_evidence
            )
            if explicit_evidence_text:
                judge_user = JUDGE_USER_GENERAL_EXPLICIT.format(
                    query=query,
                    explicit_evidence_text=explicit_evidence_text,
                    filtered_evidence=filtered_evidence,
                )
        answer = llm.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": judge_user},
            ],
            mode="instruct",
        )
        timings["llm_judge"] = round(time.time() - _t3, 2)
        timings["llm"] = timings.get("llm_extract", 0) + timings.get("llm_judge", 0)
        return answer, timings
    except Exception:
        # 两阶段失败时回退单次调用
        answer, fallback_timings = _run_single_stage_answer(
            llm,
            query=query,
            system_prompt=system_prompt,
            context_text=context_text,
            explicit_evidence_text=explicit_evidence_text,
        )
        fallback_timings["llm"] = round(time.time() - _t2, 2)
        return answer, fallback_timings


def refusal_check(answer: str, evidence_text: str) -> str:
    """拒答校验：答案引用未在证据中的规范编号/真题背景 → 替换为固定拒答话术。"""
    from angineer_core.retrieval_pipeline import has_unsupported_reference

    if has_unsupported_reference(answer, evidence_text):
        return REFUSAL_ANSWER_TEXT
    return answer

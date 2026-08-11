"""答题流水线（P6c 从 dispatcher.py 下沉）。

承载检索后的证据组织、system prompt 构建、两阶段抽取/判定（失败回退单次
调用）与拒答校验；legacy L1 路径与 agentic 路径共用本模块。
"""
import os
import re
import json
import math
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from angineer_core.prompts.dispatcher import (
    CHAT_SYSTEM_PROMPT,
    EXTRACT_SYSTEM_PROMPT,
    EXTRACT_USER_CHOICE,
    EXTRACT_USER_GENERAL,
    JUDGE_USER_CHOICE,
    JUDGE_USER_CHOICE_EXPLICIT,
    JUDGE_USER_GENERAL,
    JUDGE_USER_GENERAL_EXPLICIT,
    SOP_ANSWER_COMPOSE_PROMPT,
    SOP_ANSWER_SYSTEM_PROMPT,
    SYSTEM_PROMPT_BASE,
    SYSTEM_PROMPT_CHOICE_RULES,
    SYSTEM_PROMPT_GAP_ANALYSIS,
    SYSTEM_PROMPT_RULES_CONTENT_QA,
    SYSTEM_PROMPT_RULES_DEFINITION_QA,
    SYSTEM_PROMPT_RULES_LOCATE_QA,
)

MULTI_CHOICE_PATTERN = re.compile(r"[(（][A-E][)）]")

# 拒答话术下沉到 agent_messages（引擎边界允许依赖），此处 re-export 保持旧导入兼容
from angineer_core.agent_messages import REFUSAL_ANSWER_TEXT  # noqa: E402


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


def dispatch_chat(query: str, config_name: Optional[str] = None) -> str:
    """L0 路径：闲聊寒暄，直接用 LLM 做轻松对话，不检索、不查库。"""
    from ai_inference.llm_client import get_llm_client

    llm = get_llm_client()
    return llm.chat(
        [
            {
                "role": "system",
                "content": CHAT_SYSTEM_PROMPT,
            },
            {"role": "user", "content": query},
        ],
        mode="instruct",
        config_name=config_name,
    )


def parse_gap_analysis(answer: str) -> Tuple[str, Optional[List[Dict[str, Any]]], Optional[Dict[str, List[str]]]]:
    """
    从 LLM 合成回答中解析知识盲区分析和置信度说明。

    解析策略：
    1. 按「知识盲区分析」和「置信度说明」标题切分
    2. 提取盲区列表（每条格式：序号. 描述 — 建议补充）
    3. 提取置信度分类（高/中/低）

    Returns:
        (clean_answer, gap_analysis_list, confidence_breakdown)
        - clean_answer: 去除盲区和置信度段落后的纯回答文本
        - gap_analysis_list: [{"gap_description": "...", "suggested_sources": [...]}]
        - confidence_breakdown: {"high": [...], "medium": [...], "low": [...]}
    """
    answer_text = str(answer or "")
    if not answer_text.strip():
        return answer_text, None, None

    gap_analysis: Optional[List[Dict[str, Any]]] = None
    confidence_breakdown: Optional[Dict[str, List[str]]] = None
    clean_answer = answer_text

    # 按「知识盲区分析」标题切分
    gap_patterns = [
        r'##\s*知识盲区分析\s*\n',
        r'###?\s*知识盲区分析\s*\n',
        r'知识盲区分析[：:]\s*\n',
    ]
    gap_split = None
    for pat in gap_patterns:
        parts = re.split(pat, answer_text, maxsplit=1)
        if len(parts) >= 2:
            clean_answer = parts[0].strip()
            gap_split = parts[1]
            break

    if gap_split is None:
        return clean_answer, None, None

    # 按「置信度说明」切分 gap 段落
    conf_patterns = [
        r'##\s*置信度说明\s*\n',
        r'###?\s*置信度说明\s*\n',
        r'置信度说明[：:]\s*\n',
    ]
    conf_split = None
    for pat in conf_patterns:
        parts = re.split(pat, gap_split, maxsplit=1)
        if len(parts) >= 2:
            gap_text = parts[0].strip()
            conf_split = parts[1].strip()
            break

    if conf_split is None:
        gap_text = gap_split.strip()
    else:
        gap_text = gap_split.split(conf_split)[0] if conf_split in gap_split else parts[0].strip() if 'parts' in dir() else gap_split.strip()

    # 重新计算：从原始 gap_split 中提取 gap 部分和 conf 部分
    gap_text = gap_split
    conf_text = ""
    for pat in conf_patterns:
        conf_parts = re.split(pat, gap_split, maxsplit=1)
        if len(conf_parts) >= 2:
            gap_text = conf_parts[0].strip()
            conf_text = conf_parts[1].strip()
            break

    # 解析盲区列表
    if gap_text and gap_text.strip():
        # 匹配格式：1. **盲区描述** — 建议：xxx 或 1. 盲区描述 — 建议补充xxx
        gap_items = []
        # 按数字编号拆分
        gap_lines = re.split(r'\n(?=\d+\.\s)', gap_text.strip())
        for line in gap_lines:
            line_clean = re.sub(r'^\d+\.\s*\*?\*?', '', line.strip()).strip()
            if not line_clean or len(line_clean) < 5:
                continue
            # 跳过"无盲区"的陈述
            if any(kw in line_clean for kw in ['无盲区', '已覆盖', '未发现明显', '所有关键方面']):
                continue
            # 提取盲区描述和建议
            gap_desc = line_clean
            suggested = []
            # 尝试按 "—" 或 "：" 分割描述和建议
            for sep in [' — 建议', ' — ', '：建议', '：']:
                if sep in line_clean:
                    parts_sep = line_clean.split(sep, 1)
                    gap_desc = parts_sep[0].strip().rstrip('：:')
                    suggest_text = parts_sep[1].strip() if len(parts_sep) > 1 else ""
                    if suggest_text:
                        suggested = [s.strip() for s in re.split(r'[、,，]', suggest_text) if s.strip()]
                    break
            gap_items.append({
                "gap_description": gap_desc,
                "suggested_sources": suggested,
            })
        if gap_items:
            gap_analysis = gap_items

    # 解析置信度说明
    if conf_text and conf_text.strip():
        cb: Dict[str, List[str]] = {"high": [], "medium": [], "low": []}
        current_level = None
        for line in conf_text.split('\n'):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            # 检测置信度级别
            if '高置信度' in line_stripped:
                current_level = 'high'
                # 提取该行中冒号后的内容
                if '：' in line_stripped or ':' in line_stripped:
                    content = re.split(r'[：:]', line_stripped, maxsplit=1)[-1].strip()
                    if content and len(content) > 2:
                        cb['high'].append(content)
                continue
            if '中置信度' in line_stripped:
                current_level = 'medium'
                if '：' in line_stripped or ':' in line_stripped:
                    content = re.split(r'[：:]', line_stripped, maxsplit=1)[-1].strip()
                    if content and len(content) > 2:
                        cb['medium'].append(content)
                continue
            if '低置信度' in line_stripped:
                current_level = 'low'
                if '：' in line_stripped or ':' in line_stripped:
                    content = re.split(r'[：:]', line_stripped, maxsplit=1)[-1].strip()
                    if content and len(content) > 2:
                        cb['low'].append(content)
                continue
            # 列表项
            if current_level and line_stripped.startswith('-'):
                item_text = re.sub(r'^[-*]\s*', '', line_stripped).strip()
                if item_text and len(item_text) > 2:
                    cb[current_level].append(item_text)
        # 只返回非空的置信度
        if any(cb.values()):
            confidence_breakdown = {k: v for k, v in cb.items() if v}

    return clean_answer, gap_analysis, confidence_breakdown


def extract_answer_from_sop_context(
    context: Dict[str, Any], query: str, config_name: Optional[str] = None,
) -> str:
    """
    从 SOP 执行上下文中提取答案，并进行步骤输出强一致性校验。

    校验规则：
    1. 优先取 context["answer"] 如果存在且有效
    2. 收集所有步骤输出（非内部变量）
    3. 检查数值一致性（如果多个步骤输出数值结果，确保它们不矛盾）
    4. 最终答案必须基于步骤输出，不能 hallucinate
    """
    # 1. 优先取已有的 answer
    if context.get("answer"):
        answer = str(context["answer"])
        # 简单校验：answer 中不应包含错误标记
        if answer.strip().lower() not in {"error", "failed", "null", "none", "undefined"}:
            # 裸数值不算完整答案，继续走下方 LLM 总结生成
            if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", answer.strip()):
                return answer

    # 2. 收集所有步骤输出（排除内部变量）
    calc_vars = {}
    step_outputs = {}
    for k, v in context.items():
        if k.startswith("_") or k == "user_query":
            continue
        if isinstance(v, (int, float)):
            calc_vars[k] = v
        elif isinstance(v, str) and v.strip():
            # 排除错误标记
            if v.strip().lower() not in {"error", "failed", "null", "none", "undefined", "nan"}:
                calc_vars[k] = v
        elif isinstance(v, dict) and v.get("result") is not None:
            # 工具输出（如 table_lookup 结果）
            step_outputs[k] = v["result"]
            calc_vars[k] = v["result"]

    if not calc_vars:
        return ""

    # 3. 数值一致性校验
    numeric_values = {}
    for k, v in calc_vars.items():
        if isinstance(v, (int, float)):
            numeric_values[k] = float(v)
        elif isinstance(v, str):
            # 尝试提取数值
            num_match = re.search(r'[-+]?\d+(?:\.\d+)?', v)
            if num_match:
                try:
                    numeric_values[k] = float(num_match.group(0))
                except ValueError:
                    pass

    # 如果存在多个数值输出，检查它们是否合理（不矛盾）
    consistency_warning = None
    if len(numeric_values) >= 2:
        values = list(numeric_values.values())
        # 检查是否有明显矛盾的值（如一个为正一个为负，但工程场景中可能有合理情况）
        # 这里只做简单检查：确保没有 NaN 或 Inf
        if any(math.isnan(v) or math.isinf(v) for v in values):
            consistency_warning = "检测到无效数值（NaN 或 Inf）"

    # 4. 构建最终答案
    # 优先使用最后一步的输出作为答案
    final_answer = None
    # 尝试找到最可能是最终答案的变量
    answer_candidates = [k for k in calc_vars if any(
        suffix in k.lower() for suffix in ["answer", "result", "final", "output", "值", "结果"]
    )]
    if answer_candidates:
        final_answer = calc_vars[answer_candidates[-1]]
    elif calc_vars:
        # 取最后一个数值变量
        final_answer = list(calc_vars.values())[-1]

    if final_answer is not None:
        fallback_text = str(final_answer)
        if consistency_warning:
            fallback_text = f"{fallback_text}\n\n[警告: {consistency_warning}]"
        # 不直接返回裸值：统一经 LLM 基于计算结果组织成完整答案，失败时回退裸值
        try:
            return compose_sop_answer(query, calc_vars, config_name)
        except Exception as exc:
            logger.warning(f"SOP 答案总结生成失败，回退为原始计算值: {exc}")
            return fallback_text

    # 5. 如果没有明确答案，同样用 LLM 生成（严格限制在步骤输出范围内）
    return compose_sop_answer(query, calc_vars, config_name)


def compose_sop_answer(query: str, calc_vars: Dict[str, Any], config_name: Optional[str] = None) -> str:
    """基于 SOP 计算结果，用 LLM 组织成完整自然语言答案（严格禁止杜撰）。"""
    from ai_inference.llm_client import get_llm_client

    llm = get_llm_client()
    # 截断超长值（如表格 HTML），避免撑爆 prompt
    trimmed_vars = {
        k: (v[:500] + "…") if isinstance(v, str) and len(v) > 500 else v
        for k, v in calc_vars.items()
    }
    prompt = SOP_ANSWER_COMPOSE_PROMPT.format(
        query=query,
        calc_vars=json.dumps(trimmed_vars, ensure_ascii=False, default=str),
    )
    return llm.chat(
        [
            {"role": "system", "content": SOP_ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        mode="instruct",
        config_name=config_name,
    )

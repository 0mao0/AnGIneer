"""回答拼装器。"""
import re
import logging
from typing import List, Optional, Tuple

from docs_core.answering.citation_builder import build_snippet
from docs_core.query.contracts import KnowledgeCitation, RetrievedItem
from docs_core.retrieval.dense_retriever import score_text
from docs_core.retrieval.query_normalizer import (
    build_query_phrases,
    contains_clause_ref,
    extract_clause_refs,
    normalize_match_text,
    tokenize_query,
)

logger = logging.getLogger(__name__)


def _get_llm_client():
    """延迟导入全局 LLM 客户端，避免循环依赖。"""
    try:
        from angineer_core.infra.llm_client import llm_client
        return llm_client
    except Exception:
        return None


# 构建让 LLM 基于证据回答问题的系统提示。
_RAG_SYSTEM_PROMPT = (
    "你是一个专业的知识库问答助手。请严格根据提供的参考证据回答用户问题。"
    "回答应直接回应问题，语言简洁准确，不要重复证据原文，而是提取关键信息组织成自然语言回答。"
    "如果证据不足以回答问题，请明确说明。"
)


# 将检索证据拼装为 LLM 的用户消息。
def _build_rag_user_message(query: str, evidence: str, doc_title: str) -> str:
    return (
        f"参考证据（来自《{doc_title}》）：\n{evidence}\n\n"
        f"问题：{query}\n\n"
        f"请根据以上证据回答问题。"
    )


# 调用 LLM 基于证据生成回答，失败时返回空字符串。
def _generate_llm_answer(query: str, evidence: str, doc_title: str) -> str:
    client = _get_llm_client()
    if client is None:
        return ""
    try:
        user_message = _build_rag_user_message(query, evidence, doc_title)
        messages = [
            {"role": "system", "content": _RAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        result = client.chat(messages, temperature=0.3, mode="instruct")
        return result.strip() if result else ""
    except Exception as exc:
        logger.warning("LLM 生成回答失败，回退到模板回答: %s", exc)
        return ""


# 将长证据拆成较短句段，便于从相邻条文中抽取最相关答案。
def split_text_passages(text: str) -> List[str]:
    compact = re.sub(r"\r\n?", "\n", text or "").strip()
    if not compact:
        return []
    parts = re.split(r"\n+|(?<=[。！？；])\s*", compact)
    passages: List[str] = []
    for part in parts:
        normalized = " ".join(part.split()).strip()
        if normalized:
            passages.append(normalized)
    return passages


# 判断问题是否在询问“如何计算/按什么公式计算”。
def is_calculation_query(query: str) -> bool:
    markers = ("怎么计算", "如何计算", "计算方法", "按什么计算", "按何计算", "公式")
    return any(marker in (query or "") for marker in markers)


# 从长文本中抽取与编号最匹配的条款片段。
def extract_clause_passage(text: str, clause_ref: str) -> str:
    passages = split_text_passages(text)
    if not passages:
        return ""
    target_index = next(
        (index for index, passage in enumerate(passages) if contains_clause_ref(passage, clause_ref)),
        -1,
    )
    if target_index < 0:
        return ""
    selected = [passages[target_index]]
    for next_index in range(target_index + 1, min(len(passages), target_index + 3)):
        next_passage = passages[next_index]
        if re.match(r"^\d+(?:\.\d+){1,4}", next_passage):
            break
        selected.append(next_passage)
    return " ".join(part for part in selected if part).strip()


# 切分表格行文本，提取类似“列名: 值”的单元格表达。
def split_table_cells(text: str) -> List[str]:
    cells: List[str] = []
    for part in (text or "").split("|"):
        normalized = " ".join(part.split()).strip()
        if normalized:
            cells.append(normalized)
    return cells


# 判断问题是否在询问表格中的具体取值。
def is_lookup_query(query: str) -> bool:
    lookup_markers = ("多少", "取多少", "什么值", "数值", "多大", "取值")
    return any(marker in (query or "") for marker in lookup_markers)


# 判断问题是否在询问公式、条款或编号对应内容。
def is_reference_query(query: str) -> bool:
    reference_markers = ("公式", "式", "条", "编号", "是什么", "含义", "定义", "解释")
    if any(marker in (query or "") for marker in reference_markers):
        return True
    return bool(extract_clause_refs(query))


# 判断候选是否来自公式/计算专用检索链。
def is_formula_candidate(item: RetrievedItem) -> bool:
    return str(item.metadata.get("source_kind") or "") in {"formula_block", "formula_context", "formula_clause"}


# 判断问题是否偏向公式或计算说明。
def is_formula_or_calc_query(query: str) -> bool:
    markers = ("公式", "按式", "式中", "怎么算", "怎么计算", "如何计算", "计算方法", "按什么计算")
    return any(marker in (query or "") for marker in markers)


# 为计算类问题从公式上下文中抽取多句联合片段。
def build_formula_calculation_snippet(query: str, item: RetrievedItem) -> str:
    passages = split_text_passages(item.text) or [item.text]
    query_tokens = tokenize_query(query)
    clause_refs = extract_clause_refs(query)
    scored_passages: List[tuple[int, float, str]] = []
    for index, passage in enumerate(passages):
        score = score_text(query_tokens, item.title, passage)
        if clause_refs and any(contains_clause_ref(passage, ref) for ref in clause_refs):
            score += 6.0
        if any(marker in passage for marker in ("按式", "式中", "统计", "频率", "计算", "确定")):
            score += 5.0
        if any(marker in passage for marker in ("K_t", "t_s", "t_1", "t_2", "t_3")):
            score += 4.0
        if score > 0:
            scored_passages.append((index, score, passage))
    if not scored_passages:
        return build_snippet(item.text, limit=260)
    top_passages = sorted(scored_passages, key=lambda row: row[1], reverse=True)[:3]
    ordered = [passage for _, _, passage in sorted(top_passages, key=lambda row: row[0])]
    return build_snippet(" ".join(ordered), limit=260)


# 为公式/计算问答优先挑选公式上下文与计算说明。
def select_formula_answer_passage(query: str, candidates: List[RetrievedItem]) -> Tuple[RetrievedItem | None, str]:
    if not candidates:
        return None, ""
    query_tokens = tokenize_query(query)
    clause_refs = extract_clause_refs(query)
    calc_query = any(marker in (query or "") for marker in ("怎么算", "怎么计算", "如何计算", "计算方法", "按什么计算"))
    best_item: RetrievedItem | None = None
    best_passage = ""
    best_score = float("-inf")
    for rank, item in enumerate(candidates[:6]):
        if not is_formula_candidate(item):
            continue
        if calc_query and item.entity_type == "formula_context":
            candidate_score = score_text(query_tokens, item.title, item.text) + 8.0 + max(0.0, 1.0 - rank * 0.1)
            if candidate_score > best_score:
                best_score = candidate_score
                best_item = item
                best_passage = build_formula_calculation_snippet(query, item)
        passages = split_text_passages(item.text) or [item.text]
        candidate_passage = ""
        candidate_score = float("-inf")
        for passage in passages:
            score = score_text(query_tokens, item.title, passage)
            if clause_refs and any(contains_clause_ref(passage, ref) for ref in clause_refs):
                score += 8.0
            if calc_query and any(marker in passage for marker in ("按式", "式中", "统计", "频率", "计算", "确定")):
                score += 4.0
            if item.entity_type == "formula_context":
                score += 2.5
            elif item.entity_type == "formula_clause":
                score += 1.5
            elif item.entity_type == "formula":
                score += 1.0
            score += max(0.0, 1.0 - rank * 0.1)
            if score <= candidate_score:
                continue
            candidate_score = score
            candidate_passage = passage
        if candidate_score <= best_score:
            continue
        best_score = candidate_score
        best_item = item
        best_passage = candidate_passage or build_snippet(item.text)
    if best_item is None:
        return None, ""
    return best_item, build_snippet(best_passage or best_item.text, limit=260)


# 判断单元格是否符合“列名: 值”的结构。
def is_named_value_cell(cell: str) -> bool:
    normalized = " ".join((cell or "").split()).strip()
    if not normalized:
        return False
    if not re.match(r"^[^:：|]{1,40}[:：]\s*.+$", normalized):
        return False
    label = re.split(r"[:：]", normalized, maxsplit=1)[0].strip()
    if re.fullmatch(r"\d+\s*[:：]\s*\d+", normalized):
        return False
    if not label or len(label) > 20:
        return False
    return not re.fullmatch(r"\d+(?:\.\d+)*", label)


# 为表格问答挑选更贴近取值结果的证据行。
def select_table_answer_passage(query: str, candidates: List[RetrievedItem]) -> Tuple[RetrievedItem | None, str]:
    if not candidates:
        return None, ""
    query_tokens = tokenize_query(query)
    normalized_query = normalize_match_text(query)
    best_item: RetrievedItem | None = None
    best_score = float("-inf")
    for rank, item in enumerate(candidates[:5]):
        chunk_type = str(item.metadata.get("chunk_type") or item.entity_type or "")
        if not chunk_type.startswith("table_"):
            continue
        item_text = item.text or ""
        row_score = score_text(query_tokens, item.title, item_text)
        if is_lookup_query(query) and re.search(r"\d+(?:\.\d+)?\s*[A-Za-z%]+", item_text):
            row_score += 2.0
        row_score += max(0.0, 1.0 - rank * 0.1)
        if row_score <= best_score:
            continue
        best_score = row_score
        best_item = item
    if best_item is None:
        return None, ""

    cells = split_table_cells(best_item.text)
    metric_cell = next(
        (
            cell for cell in cells
            if is_named_value_cell(cell) and "项目" in cell and (
                ("c" in normalized_query and re.search(r"c(?:\(m\))?", cell, flags=re.IGNORECASE))
                or score_text(query_tokens, "", cell) > 0
            )
        ),
        "",
    )
    value_cells = [cell for cell in cells if "项目" not in cell and is_named_value_cell(cell)]
    best_value_cell = ""
    best_value_score = float("-inf")
    for cell in value_cells:
        cell_score = score_text(query_tokens, "", cell)
        if is_lookup_query(query) and re.search(r"\d+(?:\.\d+)?\s*[A-Za-z%]+", cell):
            cell_score += 3.0
        if cell_score <= best_value_score:
            continue
        best_value_score = cell_score
        best_value_cell = cell
    snippet_parts = [part for part in [metric_cell, best_value_cell] if part]
    if snippet_parts:
        return best_item, "；".join(snippet_parts)
    return best_item, build_snippet(best_item.text)


# 从候选证据中选出最贴近问题的句段。
def select_answer_passage(
    query: str,
    candidates: List[RetrievedItem],
    task_type: str = "content_qa",
) -> Tuple[RetrievedItem | None, str]:
    if not candidates:
        return None, ""
    if task_type == "table_qa":
        table_item, table_snippet = select_table_answer_passage(query, candidates)
        if table_item is not None and table_snippet:
            return table_item, table_snippet
    if is_formula_or_calc_query(query):
        formula_item, formula_snippet = select_formula_answer_passage(query, candidates)
        if formula_item is not None and formula_snippet:
            return formula_item, formula_snippet
    query_tokens = tokenize_query(query)
    query_phrases = build_query_phrases(query, min_n=4, max_n=10)
    clause_refs = extract_clause_refs(query)
    best_item: RetrievedItem | None = None
    best_passage = ""
    best_score = float("-inf")
    for rank, item in enumerate(candidates[:5]):
        if clause_refs:
            exact_clause_passage = ""
            for clause_ref in clause_refs:
                exact_clause_passage = extract_clause_passage(item.text, clause_ref)
                if exact_clause_passage:
                    break
            if exact_clause_passage:
                clause_score = score_text(query_tokens, item.title, exact_clause_passage) + 10.0
                if is_calculation_query(query) and any(marker in exact_clause_passage for marker in ("按式", "公式", "计算", "式中")):
                    clause_score += 4.0
                clause_score += max(0.0, 1.0 - rank * 0.1)
                if clause_score > best_score:
                    best_score = clause_score
                    best_item = item
                    best_passage = exact_clause_passage
        passages = split_text_passages(item.text) or [item.text]
        for passage in passages:
            passage_score = score_text(query_tokens, item.title, passage)
            if clause_refs and any(contains_clause_ref(passage, ref) for ref in clause_refs):
                passage_score += 6.0
            if is_calculation_query(query) and any(marker in passage for marker in ("按式", "公式", "计算", "式中")):
                passage_score += 3.0
            if any(phrase in normalize_match_text(passage) for phrase in query_phrases):
                passage_score += 3.0
            if len(passage) <= 120:
                passage_score += 0.5
            passage_score += max(0.0, 1.0 - rank * 0.1)
            if passage_score <= best_score:
                continue
            best_score = passage_score
            best_item = item
            best_passage = passage
    if best_item is None:
        return candidates[0], build_snippet(candidates[0].text)
    return best_item, build_snippet(best_passage)


# 用候选证据拼装回答文本。
def assemble_answer(
    query: str,
    task_type: str,
    citations: List[KnowledgeCitation],
    candidates: List[RetrievedItem],
) -> Tuple[str, float]:
    if not citations:
        return "当前知识库中没有检索到足够证据，建议缩小文档范围或换一种问法。", 0.15
    selected_item, focused_snippet = select_answer_passage(query, candidates, task_type=task_type)
    lead = citations[0]
    if selected_item is not None:
        selected_item_id = selected_item.item_id
        matched_citation = next((citation for citation in citations if citation.target_id == selected_item_id), None)
        if matched_citation is not None:
            lead = matched_citation
    snippet = focused_snippet or lead.snippet
    evidence_text = lead.content or snippet
    if task_type == "locate_qa":
        template_answer = f"相关内容优先命中在《{lead.doc_title}》第 {lead.page_idx or 0} 页，片段为：{snippet}"
    elif task_type == "table_qa":
        template_answer = f"已命中与表格相关的证据，优先参考《{lead.doc_title}》中的以下片段：{snippet}"
    elif is_formula_or_calc_query(query):
        template_answer = f"已命中与公式或计算相关的证据，优先参考《{lead.doc_title}》中的以下片段：{snippet}"
    elif task_type == "schema_qa":
        template_answer = f"当前先返回最相关的字段说明证据：{snippet}"
    elif task_type == "definition_qa" and is_reference_query(query):
        template_answer = f"已命中编号或定义相关证据，优先参考《{lead.doc_title}》中的以下片段：{snippet}"
    elif task_type == "analytic_sql":
        template_answer = "该问题更适合走 Text-to-SQL 链路；当前已返回最相关证据，后续会补充 SQL 生成与执行能力。"
    else:
        template_answer = f"根据当前检索到的证据，优先答案片段为：{snippet}"
    llm_answer = _generate_llm_answer(query, evidence_text, lead.doc_title)
    answer = llm_answer if llm_answer else template_answer
    confidence = min(0.95, 0.35 + lead.score / 10.0)
    return answer, confidence

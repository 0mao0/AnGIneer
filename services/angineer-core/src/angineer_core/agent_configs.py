"""P3.1 知识问答档 agent 循环配置装配。"""
from typing import Any, Dict, List, Optional

from angineer_core.agent_loop import AgentLoopConfig
from angineer_core.agent_tools import AgentTool, RetrieverAdapter
from angineer_core.tool_codec import TextToolCallCodec


QA_AGENT_SYSTEM_PROMPT = (
    "你是一个工程规范领域的专业助手。"
    "你只能依据工具返回的检索证据回答，可以基于证据中的规范条款进行合理推导和计算。"
    "不要编造证据中未出现的规范编号、年份或考试背景。\n\n"
    "规则：\n"
    "1. 需要证据时先调用检索工具，一次可以调用多个工具。\n"
    "2. 每个关键结论后都要指出对应证据来源（文档名、章节号），格式如【根据第X章...】。\n"
    "3. 证据不足时直接回答：没有检索到足够证据支持最终结论，不要自行补全。\n"
    "4. 当问题包含选项 A/B/C/D 时，逐项给出符合/不符合/证据不足的判断，再给出最终答案。"
)


def _build_inline_citation_context(inline_citations: List[Dict[str, Any]]) -> str:
    """把前端显式确认的引用对象转成高优先级证据文本（与 dispatcher 同款）。"""
    evidence_blocks: List[str] = []
    for item in inline_citations[:5]:
        reference = item.get("reference") if isinstance(item, dict) else {}
        if not isinstance(reference, dict):
            reference = {}
        label = str(item.get("label") or reference.get("label") or "").strip()
        doc_title = str(reference.get("docTitle") or reference.get("doc_title") or "").strip()
        section_path = str(reference.get("sectionPath") or reference.get("section_path") or "").strip()
        page_idx = reference.get("pageIdx", reference.get("page_idx", ""))
        content = str(reference.get("content") or reference.get("snippet") or "").strip()
        meta_parts = [
            part
            for part in (
                f"标签: {label}" if label else "",
                f"文档: {doc_title}" if doc_title else "",
                f"页码: {page_idx}" if page_idx else "",
                f"位置: {section_path}" if section_path else "",
            )
            if part
        ]
        block_parts: List[str] = []
        if meta_parts:
            block_parts.append("\n".join(meta_parts))
        if content:
            block_parts.append(f"证据内容:\n{content}")
        if block_parts:
            evidence_blocks.append("\n".join(block_parts))
    return "\n---\n".join(evidence_blocks)


def build_qa_config(
    *,
    llm: Any,
    doc_nodes: Optional[List[Any]] = None,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    filters: Any = None,
    task_type: str = "content_qa",
    max_turns: int = 3,
    inline_citations: Optional[List[Dict[str, Any]]] = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    tools: Optional[List[AgentTool]] = None,
    rerank: bool = True,
) -> AgentLoopConfig:
    """装配 QA 档 agent 循环：三个只读检索工具 + 内联 QA prompt（P5 前）。"""
    effective_tools = tools
    if effective_tools is None:
        effective_tools = [
            RetrieverAdapter.knowledge_search(
                library_id=library_id,
                doc_ids=doc_ids,
                doc_nodes=doc_nodes,
                top_k=20,
                task_type=task_type,
                filters=filters,
                rerank=rerank,
            ),
            RetrieverAdapter.table_search(
                library_id=library_id,
                doc_ids=doc_ids,
                doc_nodes=doc_nodes,
                top_k=20,
                filters=filters,
                rerank=rerank,
            ),
            RetrieverAdapter.entity_search(),
        ]

    system_prompt = QA_AGENT_SYSTEM_PROMPT
    explicit = _build_inline_citation_context(inline_citations or [])
    if explicit:
        system_prompt += "\n\n显式引用证据（用户已确认，优先级最高）：\n" + explicit

    return AgentLoopConfig(
        llm=llm,
        config_name=config_name,
        mode=mode,
        tools=effective_tools,
        system_prompt=system_prompt,
        max_turns=max_turns,
        codec=TextToolCallCodec(),
    )

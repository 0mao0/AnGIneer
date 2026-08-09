"""L1/L2回退/L3回退语义检索调度（P6d 从 dispatcher.py 下沉）。

检索任务映射 → 多路检索融合重排 → 证据组织 → 两阶段判定 → 拒答校验。
"""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def dispatch_semantic(
    dispatcher,
    query: str,
    doc_nodes: list,
    library_id: str,
    doc_ids: List[str],
    intent_result,
    inline_citations: Optional[List[Dict[str, Any]]] = None,
    filters=None,
    enforce_evidence: bool = False,
) -> Tuple[str, list, list, str, str, Dict, Dict[str, float], Dict[str, Any]]:
    """L1/L2回退/L3回退：语义检索路径。

    enforce_evidence=True 时，若检索无结果则直接返回空，不调用 LLM 自由生成。
    """
    from ai_inference.llm_client import get_llm_client
    from angineer_core.retrieval_pipeline import (
        build_citations_from_retrieved,
        build_inline_citation_context,
        resolve_semantic_retriever_task,
        run_semantic_retrieval,
    )
    from angineer_core.qa_pipeline import (
        build_answer_context,
        build_evidence_text,
        build_system_prompt,
        refusal_check,
        run_two_stage_answer,
    )

    answer = ""
    citations = []
    retrieved_items = []
    strategy_desc = ""
    system_prompt = ""
    retrieval_debug = {}
    runtime_flags: List[str] = []
    timings: Dict[str, float] = {}
    fused = []

    try:
        retriever_task_type = resolve_semantic_retriever_task(query, intent_result)
        strategy_desc = (
            "Dense(正文+公式) + Sparse(全文+图表+公式) + Table(表格) → Hybrid融合（证据受约束）"
        )

        fused, retrieval_debug, runtime_flags, ret_timings = run_semantic_retrieval(
            query=query,
            doc_nodes=doc_nodes,
            library_id=library_id,
            doc_ids=doc_ids,
            task_type=retriever_task_type,
            filters=filters,
        )
        timings.update(ret_timings)
        retrieved_items = [
            item.model_dump(mode="json") for item in fused
        ]
        citations = build_citations_from_retrieved(fused, doc_nodes)

        if not answer and fused:
            context_text = build_answer_context(fused)
            # enforce_evidence 模式下，若无有效上下文则拒绝生成
            if enforce_evidence and not context_text.strip():
                logger.info("语义检索：enforce_evidence=True，未检索到有效证据，拒绝 LLM 自由生成")
                return "", citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, timings, runtime_flags
            explicit_evidence_text = build_inline_citation_context(inline_citations or [])
            evidence_text = build_evidence_text(explicit_evidence_text, context_text)

            _t_prompt = time.time()
            system_prompt = build_system_prompt(retriever_task_type, query)
            timings["prompt"] = round(time.time() - _t_prompt, 2)

            llm = get_llm_client()
            answer, llm_timings = run_two_stage_answer(
                llm,
                query=query,
                system_prompt=system_prompt,
                context_text=context_text,
                explicit_evidence_text=explicit_evidence_text,
            )
            timings.update(llm_timings)
            if answer:
                answer = refusal_check(answer, evidence_text)
    except Exception as e:
        logger.error(f"语义检索失败: {e}")
        if not answer:
            answer = "抱歉，检索服务暂时不可用，请稍后重试。"

    return answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, timings, runtime_flags

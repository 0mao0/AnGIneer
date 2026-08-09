"""L2 SQL 结构化检索流水线（P6d 从 dispatcher.py 下沉）。

schema 链接 → 指标分支（标准查档 / 条件查表 / 通用查表）→ SQL 校验执行 →
LLM 组织回答；空命中时桥接条文/公式级证据。
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from angineer_core.prompts.dispatcher import (
    SQL_DOC_QA_SYSTEM_PROMPT,
    SQL_STRUCTURED_QA_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def bridge_l2_evidence(
    dispatcher,
    *,
    query: str,
    library_id: str,
    doc_ids: List[str],
    doc_nodes: list,
) -> Tuple[list, list]:
    """当 SQL 命中为空时，补充条文/公式级证据，作为 L2 的可承接依据。"""
    from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest
    from docs_core.step09_query.retrieval.formula_retriever import formula_retriever, is_calculation_query

    if not doc_nodes:
        return [], []
    clause_like = bool(re.search(r"\d+(?:\.\d+){1,4}\s*(?:条|款|式)?", query or ""))
    if not clause_like and not is_calculation_query(query or "") and "计算" not in (query or ""):
        return [], []
    request = KnowledgeQueryRequest(
        query=query,
        library_id=library_id,
        doc_ids=list(doc_ids or []),
        top_k=5,
    )
    bridge_items = formula_retriever.retrieve(request, doc_nodes)
    if not bridge_items:
        return [], []
    from angineer_core.retrieval_pipeline import build_citations_from_retrieved

    bridge_citations = build_citations_from_retrieved(bridge_items, doc_nodes)
    return bridge_items, bridge_citations


def dispatch_sql(
    dispatcher,
    query: str,
    doc_nodes: list,
    library_id: str,
    doc_ids: List[str],
) -> Tuple[str, list, list, Optional[Dict], bool]:
    """L2 路径：SQL 结构化检索。"""
    from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest
    from docs_core.step09_query.text2sql.schema_linker import link_schema
    from docs_core.step09_query.text2sql.sql_validator import validate_sql
    from docs_core.step09_query.text2sql.sql_executor import execute_sql
    from ai_inference.llm_client import get_llm_client

    answer = ""
    citations = []
    retrieved_items = []
    sql_payload = None
    fallback_used = False

    try:
        schema_result = link_schema(
            query,
            KnowledgeQueryRequest(
                query=query, library_id=library_id, doc_ids=doc_ids,
            ),
            doc_nodes,
        )
        if schema_result.get("supported"):
            metric = schema_result.get("metric", "")
            table_name = schema_result["table_name"]
            business_filters = schema_result.get("business_filters", {})
            sql_payload = {
                "supported": True,
                "metric": metric,
                "table_name": table_name,
                "business_filters": business_filters,
                "execution_status": "empty",
                "row_count": 0,
                "bridge_hits": 0,
            }

            if metric == "standard_lookup":
                standard_code = business_filters.get("standard_code", "")
                sql = (
                    "SELECT doc_id, title, source_file_name "
                    "FROM canonical_documents "
                    "WHERE title LIKE ? OR source_file_name LIKE ?"
                )
                like_pattern = f"%{standard_code}%"
                params = [like_pattern, like_pattern]
                is_valid, reason = validate_sql(sql)
                if is_valid:
                    sql_result = execute_sql(sql, params)
                    if sql_result and sql_result.get("row_count", 0) > 0:
                        sql_payload["execution_status"] = "success"
                        sql_payload["row_count"] = int(sql_result.get("row_count", 0) or 0)
                        matched_doc_ids = [
                            row.get("doc_id", "")
                            for row in sql_result["rows"]
                        ]
                        doc_titles = {
                            row.get("doc_id", ""): row.get("title", "")
                            for row in sql_result["rows"]
                        }
                        chunk_sql = (
                            "SELECT chunk_id, text, section_path, clause_id "
                            "FROM canonical_chunks "
                            f"WHERE doc_id IN ({','.join(['?' for _ in matched_doc_ids])}) "
                            "AND chunk_type = 'content' "
                            "ORDER BY page_idx ASC, chunk_idx ASC LIMIT 3"
                        )
                        chunk_params = list(matched_doc_ids)
                        is_valid2, reason2 = validate_sql(chunk_sql)
                        if is_valid2:
                            chunk_result = execute_sql(chunk_sql, chunk_params)
                            if chunk_result and chunk_result.get("row_count", 0) > 0:
                                context_parts = []
                                for row in chunk_result["rows"][:3]:
                                    section = row.get("section_path", "")
                                    text = row.get("text", "")
                                    prefix = f"[{section}]" if section else ""
                                    context_parts.append(
                                        f"{prefix}: {text}" if prefix else text
                                    )
                                doc_title_list = [
                                    doc_titles.get(did, "")
                                    for did in matched_doc_ids
                                    if doc_titles.get(did)
                                ]
                                llm = get_llm_client()
                                answer = llm.chat(
                                    [
                                        {
                                            "role": "system",
                                            "content": SQL_DOC_QA_SYSTEM_PROMPT,
                                        },
                                        {
                                            "role": "user",
                                            "content": (
                                                f"问题: {query}\n\n"
                                                f"匹配到的文档: {', '.join(doc_title_list)}\n\n"
                                                f"文档内容:\n" + "\n---\n".join(context_parts)
                                            ),
                                        },
                                    ],
                                    mode="instruct",
                                    config_name=dispatcher.config_name,
                                )
                                retrieved_items = chunk_result["rows"]
                                citations = [
                                    {"doc_id": did, "title": doc_titles.get(did, "")}
                                    for did in matched_doc_ids
                                ]
                    else:
                        sql_payload["execution_status"] = "empty"
                else:
                    sql_payload["execution_status"] = "invalid_sql"
                    sql_payload["reason"] = reason

            elif metric == "conditional_lookup":
                sql = (
                    f"SELECT chunk_id, text, section_path, clause_id, "
                    f"entity_tags_json, exam_tags_json, conditions_json "
                    f"FROM {table_name} "
                    f"WHERE doc_id IN ({','.join(['?' for _ in doc_nodes])})"
                )
                params = [node.id for node in doc_nodes]
                if "clause_id" in business_filters:
                    clause_id_val = business_filters["clause_id"]
                    check_sql = (
                        f"SELECT 1 FROM {table_name} "
                        f"WHERE clause_id = ? "
                        f"AND doc_id IN ({','.join(['?' for _ in doc_nodes])}) "
                        f"LIMIT 1"
                    )
                    check_params = [clause_id_val] + [node.id for node in doc_nodes]
                    is_check_valid, _ = validate_sql(check_sql)
                    if is_check_valid:
                        check_result = execute_sql(check_sql, check_params)
                        if check_result and check_result.get("row_count", 0) > 0:
                            sql += " AND clause_id = ?"
                            params.append(clause_id_val)
                for tag_field, json_key in [
                    ("entity_tags", "entity_tags"),
                    ("exam_tags", "exam_tags"),
                    ("conditions", "conditions"),
                ]:
                    if json_key in business_filters:
                        for tag in business_filters[json_key]:
                            sql += f" AND {json_key}_json LIKE ?"
                            params.append(f"%{tag}%")
                sql += " LIMIT 10"
                is_valid, reason = validate_sql(sql)
                if is_valid:
                    sql_result = execute_sql(sql, params)
                    if sql_result and sql_result.get("row_count", 0) > 0:
                        sql_payload["execution_status"] = "success"
                        sql_payload["row_count"] = int(sql_result.get("row_count", 0) or 0)
                        context_parts = []
                        for row in sql_result["rows"][:5]:
                            section = row.get("section_path", "")
                            text = row.get("text", "")
                            clause = row.get("clause_id", "")
                            prefix = f"[{section}]" if section else ""
                            if clause:
                                prefix += f" 第{clause}条"
                            context_parts.append(
                                f"{prefix}: {text}" if prefix else text
                            )
                        llm = get_llm_client()
                        answer = llm.chat(
                            [
                                {
                                    "role": "system",
                                    "content": SQL_STRUCTURED_QA_SYSTEM_PROMPT,
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        f"问题: {query}\n\n结构化检索结果:\n"
                                        + "\n---\n".join(context_parts)
                                    ),
                                },
                            ],
                            mode="instruct",
                        )
                        retrieved_items = sql_result["rows"]
                        citations = [
                            {
                                "doc_id": str(row.get("doc_id") or ""),
                                "section_path": str(row.get("section_path") or ""),
                                "snippet": str(row.get("text") or "")[:200],
                                "clause_id": str(row.get("clause_id") or ""),
                            }
                            for row in sql_result["rows"][:5]
                        ]
                    else:
                        sql_payload["execution_status"] = "empty"
                else:
                    sql_payload["execution_status"] = "invalid_sql"
                    sql_payload["reason"] = reason
            else:
                sql = (
                    f"SELECT * FROM {table_name} "
                    f"WHERE doc_id IN ({','.join(['?' for _ in doc_nodes])})"
                )
                params = [node.id for node in doc_nodes]
                if "clause_id" in business_filters:
                    sql += " AND clause_id = ?"
                    params.append(business_filters["clause_id"])
                is_valid, reason = validate_sql(sql)
                if is_valid:
                    sql_result = execute_sql(sql, params)
                    if sql_result:
                        sql_payload["execution_status"] = "success"
                        sql_payload["row_count"] = int(sql_result.get("row_count", 0) or 0)
                        answer = str(sql_result)
                else:
                    sql_payload["execution_status"] = "invalid_sql"
                    sql_payload["reason"] = reason
            if not answer and not citations:
                bridge_items, bridge_citations = bridge_l2_evidence(
                    dispatcher,
                    query=query,
                    library_id=library_id,
                    doc_ids=doc_ids,
                    doc_nodes=doc_nodes,
                )
                if bridge_items:
                    retrieved_items = bridge_items
                    citations = bridge_citations
                    sql_payload["execution_status"] = "bridged"
                    sql_payload["bridge_hits"] = len(bridge_items)
        else:
            sql_payload = {
                "supported": False,
                "execution_status": "unsupported",
            }
    except Exception as e:
        logger.warning(f"SQL 检索失败，回退语义检索: {e}")
        fallback_used = True
        sql_payload = {
            "supported": False,
            "execution_status": "error",
            "reason": str(e),
        }

    return answer, citations, retrieved_items, sql_payload, fallback_used

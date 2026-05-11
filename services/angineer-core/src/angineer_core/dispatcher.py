"""
执行调度核心模块，负责 L1~L4 分级调度与 SOP 步骤编排。

Dispatcher 是 angineer-core 的大脑入口：
- dispatch(): 顶层分级调度入口，根据意图分类结果选择 L1/L2/L3/L4 路径
- run(): SOP 步骤执行引擎，被 dispatch() 在 L3 路径中调用

依赖关系：
- angineer-core → docs-core（检索/SQL）
- angineer-core → sop-core（SOP 加载）
- angineer-core → ai-inference（LLM 调用）
"""
import time
import json
import uuid
import os
from typing import Dict, Any, Tuple, List, Optional, TYPE_CHECKING
from angineer_core.base_contracts import SOP, Step, IntentResult
from angineer_core.memory import Memory, StepRecord
from angineer_core.base_logger import get_logger
from angineer_core.base_utils import is_fatal_exception

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ai_inference.llm_client import LLMClient

try:
    from engtools.BaseTool import ToolRegistry
except ImportError:
    ToolRegistry = None

from ai_inference.llm_client import get_llm_client


class Dispatcher:
    def __init__(
        self,
        config_name: str = None,
        mode: str = "instruct",
        result_md_path: str = None,
        memory: Optional[Memory] = None,
        llm_client: Optional["LLMClient"] = None,
        knowledge_provider: Optional[Any] = None,
        sop_provider: Optional[Any] = None,
    ):
        """
        初始化执行器上下文与模型配置。
        
        Args:
            config_name: LLM 配置名称
            mode: 执行模式
            result_md_path: Markdown 日志文件路径
            memory: 可选的 Memory 实例（依赖注入）
            llm_client: 可选的 LLMClient 实例（依赖注入）
            knowledge_provider: 可选的知识库服务提供者（依赖注入，替代内部 from docs_core import）
            sop_provider: 可选的 SOP 服务提供者（依赖注入，替代内部 from sop_core import）
        """
        self.memory = memory or Memory()
        self.config_name = config_name
        self.mode = mode or "instruct"
        self.result_md_path = result_md_path
        self._llm_client = llm_client or get_llm_client()
        self._knowledge_provider = knowledge_provider
        self._sop_provider = sop_provider
        self.variable_metadata = {}
        self.start_time = None
        self.step_durations = {}
        self.summary_durations = {}
        self.tool_durations = {}
        
        if self.result_md_path:
            with open(self.result_md_path, "w", encoding="utf-8") as f:
                f.write("# SOP 执行日志 (LLM 风格小结版)\n\n")
                f.write("> **说明**: 本日志展示了每一步的执行小结与 Blackboard 状态快照。更新的内容已高亮显示。\n\n")

    def dispatch(
        self,
        query: str,
        library_id: str = "default",
        doc_ids: Optional[List[str]] = None,
        sop_loader=None,
    ) -> Dict[str, Any]:
        """
        顶层分级调度入口：意图分类 → L1/L2/L3/L4 路径选择 → 返回结果。

        纯同步函数，不依赖 HTTP / FastAPI / asyncio。
        可在任意线程中直接调用（包括评测器的 daemon 线程）。

        Args:
            query: 用户查询文本
            library_id: 知识库 ID
            doc_ids: 限定文档 ID 列表
            sop_loader: SOP 加载器实例（由调用方注入）

        Returns:
            包含 answer、citations、intent 等字段的字典
        """
        from angineer_core.classifier import IntentClassifier

        started_at = time.time()
        query_id = f"q-{uuid.uuid4().hex[:12]}"
        stage_timings: Dict[str, float] = {}
        doc_ids = doc_ids or []

        # --- 1. 意图分类 ---
        intent_result = IntentResult(
            intent_level="L1", service_mode="semantic_retrieval"
        )
        _t0 = time.time()
        try:
            if sop_loader is not None:
                sops = sop_loader.load_all()
                classifier = IntentClassifier(sops)
                intent_result = classifier.classify_intent(
                    query, config_name=self.config_name, mode=self.mode
                )
        except Exception as e:
            if is_fatal_exception(e):
                raise
            logger.warning(f"意图分类失败，降级为L1: {e}")
        stage_timings["intent"] = round(time.time() - _t0, 2)

        # --- 2. 获取知识库节点 ---
        try:
            kp = self._knowledge_provider
            if kp is None:
                from docs_core.knowledge_service import get_knowledge_service
                kp = get_knowledge_service()
            library_nodes = kp.list_nodes(library_id)
            doc_nodes = [node for node in library_nodes if node.type == "document"]
            if doc_ids:
                requested = set(doc_ids)
                doc_nodes = [node for node in doc_nodes if node.id in requested]
        except Exception as e:
            if is_fatal_exception(e):
                raise
            logger.error(f"知识库节点查询失败: {e}")
            return {
                "query_id": query_id,
                "session_key": "",
                "intent": intent_result.model_dump(mode="json"),
                "answer": "抱歉，知识库服务暂时不可用，请稍后重试。",
                "citations": [],
                "retrieved_items": [],
                "sql": None,
                "fallback_used": False,
                "latency_ms": int((time.time() - started_at) * 1000),
            }

        answer = ""
        citations = []
        retrieved_items = []
        sql_payload = None
        fallback_used = False
        strategy_desc = ""
        system_prompt = ""
        retrieval_debug = {}

        # --- 3. 分级调度 ---
        try:
            # --- 3a. L0: 闲聊 ---
            if intent_result.service_mode == "casual_chat":
                answer = self._dispatch_chat(query)
                strategy_desc = "L0 闲聊"

            # --- 3b. L2: SQL 检索 ---
            if intent_result.service_mode == "sql_first":
                answer, citations, retrieved_items, sql_payload, fallback_used = (
                    self._dispatch_sql(query, doc_nodes, library_id, doc_ids)
                )

            # --- 3c. L3: SOP 执行 ---
            sop_trace: list = []
            if intent_result.service_mode == "standard_sop" and not fallback_used:
                answer, citations, strategy_desc, fallback_used, sop_timing, sop_trace = (
                    self._dispatch_sop(query, sop_loader, intent_result)
                )
                if sop_timing is not None:
                    stage_timings["sop_route"] = sop_timing

            # --- 3d. L1/L2/L3回退: 语义检索 ---
            if (
                intent_result.service_mode == "semantic_retrieval"
                or fallback_used
                or not answer
            ):
                answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, ret_timings = (
                    self._dispatch_semantic(query, doc_nodes, library_id, doc_ids, intent_result)
                )
                stage_timings.update(ret_timings)

        except Exception as e:
            if is_fatal_exception(e):
                raise
            logger.error(f"查询处理异常: {e}", exc_info=True)
            if not answer:
                answer = "抱歉，查询处理出现异常，请稍后重试。"

        latency_ms = int((time.time() - started_at) * 1000)

        return {
            "query_id": query_id,
            "session_key": "",
            "intent": intent_result.model_dump(mode="json"),
            "answer": answer or "",
            "citations": citations,
            "retrieved_items": retrieved_items,
            "sql": sql_payload,
            "fallback_used": fallback_used,
            "latency_ms": latency_ms,
            "strategy": strategy_desc,
            "system_prompt": system_prompt,
            "retrieval_debug": retrieval_debug,
            "stage_timings": stage_timings,
            "sop_trace": sop_trace,
        }

    def _dispatch_chat(self, query: str) -> str:
        """L0 路径：闲聊寒暄，直接用 LLM 做轻松对话，不检索、不查库。"""
        from ai_inference.llm_client import get_llm_client

        llm = get_llm_client()
        return llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 AnGIneer，一个工程规范领域的智能助手。"
                        "当前用户在和你闲聊，请友好、简洁地回应。"
                        "如果用户问你能做什么，简要介绍你是工程规范领域的专业助手，"
                        "可以回答工程规范问题、做标准计算、查询条款等。"
                    ),
                },
                {"role": "user", "content": query},
            ],
            mode="instruct",
            config_name=self.config_name,
        )

    def _dispatch_sql(
        self,
        query: str,
        doc_nodes: list,
        library_id: str,
        doc_ids: List[str],
    ) -> Tuple[str, list, list, Optional[Dict], bool]:
        """L2 路径：SQL 结构化检索。"""
        from docs_core.query_protocols.contracts import KnowledgeQueryRequest
        from docs_core.text2sql.schema_linker import link_schema
        from docs_core.text2sql.sql_validator import validate_sql
        from docs_core.text2sql.sql_executor import execute_sql
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
                                                "content": (
                                                    "你是一个工程规范领域的专业助手。"
                                                    "用户正在查找某条规范，请根据检索结果给出该规范的核心信息。\n\n规则：\n"
                                                    "1. 明确告知该规范的名称和编号\n"
                                                    "2. 简要概述该规范的主要内容\n"
                                                    "3. 只基于检索结果回答，不要引用检索结果中未提及的版本号\n"
                                                    "4. 如果检索结果中同时包含新旧版本信息，优先介绍最新版本"
                                                ),
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
                                        config_name=self.config_name,
                                    )
                                    retrieved_items = chunk_result["rows"]
                                    citations = [
                                        {"doc_id": did, "title": doc_titles.get(did, "")}
                                        for did in matched_doc_ids
                                    ]

                elif metric == "conditional_lookup":
                    sql = (
                        f"SELECT chunk_id, text, section_path, clause_id, "
                        f"entity_tags_json, exam_tags_json, conditions_json "
                        f"FROM {table_name} "
                        f"WHERE doc_id IN ({','.join(['?' for _ in doc_nodes])})"
                    )
                    params = [node.id for node in doc_nodes]
                    if "clause_id" in business_filters:
                        sql += " AND clause_id = ?"
                        params.append(business_filters["clause_id"])
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
                                        "content": (
                                            "你是一个工程规范领域的专业助手。"
                                            "请根据以下结构化检索结果回答用户问题。\n\n规则：\n"
                                            "1. 优先直接回答用户问题\n"
                                            "2. 引用具体来源（章节号、条款号等）\n"
                                            "3. 如果检索结果中包含与问题相关的内容，请基于相关内容给出回答\n"
                                            "4. 如果检索结果完全不相关，才说明无法回答"
                                        ),
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
                            answer = str(sql_result)
        except Exception as e:
            logger.warning(f"SQL 检索失败，回退语义检索: {e}")
            fallback_used = True

        return answer, citations, retrieved_items, sql_payload, fallback_used

    def _dispatch_sop(
        self,
        query: str,
        sop_loader,
        intent_result: IntentResult,
    ) -> Tuple[str, list, str, bool, Optional[float], list]:
        """L3 路径：SOP 匹配与执行。"""
        from angineer_core.classifier import IntentClassifier

        answer = ""
        citations = []
        strategy_desc = ""
        fallback_used = False
        sop_timing = None
        sop_trace: list = []

        try:
            _t_sop = time.time()
            if sop_loader is not None:
                sops = sop_loader.load_all()
                classifier = IntentClassifier(sops)
            else:
                classifier = None

            if classifier is not None:
                route_result = classifier.route(
                    query, config_name=self.config_name, mode=self.mode
                )

                if route_result.sop and route_result.confidence >= 0.6:
                    sop_full = sop_loader.analyze_sop(
                        route_result.sop.id, prefer_llm=False
                    )

                    sop_dispatcher = Dispatcher(
                        config_name=self.config_name, mode=self.mode
                    )
                    initial_context = {"user_query": query}
                    initial_context.update(route_result.args)
                    final_context = sop_dispatcher.run_sop(sop_full, initial_context)

                    answer = self._extract_answer_from_sop_context(
                        final_context, query
                    )
                    citations = self._build_citations_from_sop_trace(sop_dispatcher)
                    sop_trace = self._build_sop_trace(sop_dispatcher, sop_full)
                    strategy_desc = (
                        f"SOP 执行 ({route_result.sop.id}, "
                        f"confidence={route_result.confidence:.2f})"
                    )
                    sop_timing = round(time.time() - _t_sop, 2)
                else:
                    logger.info(
                        f"SOP 未匹配或置信度不足: {route_result.reason}"
                    )
                    fallback_used = True
            else:
                fallback_used = True
        except Exception as e:
            logger.warning(f"SOP 执行失败，回退语义检索: {e}")
            fallback_used = True

        return answer, citations, strategy_desc, fallback_used, sop_timing, sop_trace

    def _dispatch_semantic(
        self,
        query: str,
        doc_nodes: list,
        library_id: str,
        doc_ids: List[str],
        intent_result: IntentResult,
    ) -> Tuple[str, list, list, str, str, Dict, Dict[str, float]]:
        """L1/L2回退/L3回退：语义检索路径。"""
        from docs_core.query_protocols.contracts import KnowledgeQueryRequest
        from docs_core.retrieval.dense_retriever import dense_retriever
        from docs_core.retrieval.sparse_retriever import sparse_retriever
        from docs_core.retrieval.table_retriever import table_retriever
        from docs_core.retrieval.hybrid_retriever import fuse_candidates
        from ai_inference.llm_client import get_llm_client

        answer = ""
        citations = []
        retrieved_items = []
        strategy_desc = ""
        system_prompt = ""
        retrieval_debug = {}
        timings: Dict[str, float] = {}

        try:
            _t1 = time.time()
            retriever_task_type = self._map_intent_to_retriever_task(intent_result)
            strategy_desc = (
                "Dense(正文+公式) + Sparse(全文+图表+公式) + Table(表格) → Hybrid融合"
            )

            kq_request = KnowledgeQueryRequest(
                query=query,
                library_id=library_id,
                doc_ids=doc_ids,
                top_k=5,
            )
            dense_hits = dense_retriever.retrieve(
                kq_request, doc_nodes, retriever_task_type
            )
            sparse_hits = sparse_retriever.retrieve(
                kq_request, doc_nodes, retriever_task_type
            )
            table_hits = table_retriever.retrieve(kq_request, doc_nodes)
            source_candidates = {
                "canonical_dense": dense_hits,
                "canonical_sparse": sparse_hits,
            }
            for item in table_hits:
                source_kind = str(
                    item.metadata.get("source_kind") or "table_aware"
                )
                source_candidates.setdefault(source_kind, []).append(item)
            fused, retrieval_debug = fuse_candidates(
                source_candidates,
                task_type=retriever_task_type,
                top_k=5,
            )
            timings["retrieval"] = round(time.time() - _t1, 2)
            retrieved_items = [
                item.model_dump(mode="json") for item in fused
            ]

            if not answer and fused:
                context_parts = []
                for item in fused[:5]:
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
                context_text = "\n---\n".join(context_parts)

                _t_prompt = time.time()
                system_prompt = self._build_system_prompt(retriever_task_type)
                full_prompt = (
                    f"{system_prompt}\n问题: {query}\n\n检索结果:\n{context_text}"
                )
                timings["prompt_tokens"] = len(full_prompt) // 2
                timings["prompt"] = round(time.time() - _t_prompt, 2)

                _t2 = time.time()
                llm = get_llm_client()
                answer = llm.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": (
                                f"问题: {query}\n\n检索结果:\n{context_text}"
                            ),
                        },
                    ],
                    mode="instruct",
                )
                timings["llm"] = round(time.time() - _t2, 2)

            citations = self._build_citations_from_retrieved(fused, doc_nodes)
        except Exception as e:
            logger.error(f"语义检索失败: {e}")
            if not answer:
                answer = "抱歉，检索服务暂时不可用，请稍后重试。"

        return answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, timings

    @staticmethod
    def _map_intent_to_retriever_task(intent_result: IntentResult) -> str:
        """根据意图结果映射到检索任务类型。"""
        intent_level = str(getattr(intent_result, "intent_level", "") or "")
        intent_type = str(getattr(intent_result, "intent_type", "") or "")

        if intent_level == "L1":
            if "locate" in intent_type.lower():
                return "locate_qa"
            return "definition_qa"

        if intent_level == "L2":
            if "table" in intent_type.lower():
                return "table_qa"
            return "content_qa"

        return "content_qa"

    @staticmethod
    def _build_system_prompt(retriever_task_type: str) -> str:
        """根据检索任务类型构建对应的 system prompt。"""
        base_prompt = "你是一个工程规范领域的专业助手。请根据以下检索结果回答用户问题。"

        if retriever_task_type == "definition_qa":
            return base_prompt + (
                "\n\n规则：\n"
                "1. 直接、完整地回答用户问题，给出定义或组成\n"
                "2. 如果检索结果中包含与问题相关的内容，请基于相关内容给出准确回答\n"
                '3. 引用具体来源（章节号），格式如"根据第X章..."\n'
                "4. 如果检索结果完全不相关，才说明无法回答"
            )

        if retriever_task_type == "locate_qa":
            return base_prompt + (
                "\n\n规则：\n"
                "1. 直接回答位置/设置要求，明确指出具体地点或条件\n"
                '2. 引用具体来源（章节号），格式如"根据第X章..."\n'
                "3. 如果检索结果中包含与问题相关的内容，请基于相关内容给出准确回答\n"
                "4. 如果检索结果完全不相关，才说明无法回答"
            )

        return base_prompt + (
            "\n\n规则：\n"
            "1. 优先直接回答用户问题\n"
            "2. 如果检索结果中包含与问题相关的内容，请基于相关内容给出回答\n"
            "3. 如果检索结果完全不相关，才说明无法回答\n"
            "4. 引用具体来源（文档名、章节号等）"
        )

    @staticmethod
    def _extract_answer_from_sop_context(
        context: Dict[str, Any], query: str, config_name: str = None,
    ) -> str:
        """从 SOP 执行上下文中提取答案，优先取已有 answer，否则用 LLM 生成。"""
        if context.get("answer"):
            return str(context["answer"])

        calc_vars = {
            k: v for k, v in context.items()
            if isinstance(v, (int, float, str)) and not k.startswith("_") and k != "user_query"
        }
        if not calc_vars:
            return ""

        from ai_inference.llm_client import get_llm_client
        llm = get_llm_client()
        return llm.chat(
            [
                {"role": "system", "content": "你是工程规范领域的专业助手。请根据以下计算结果回答用户问题，列出关键计算步骤和最终结果。"},
                {"role": "user", "content": f"问题: {query}\n\n计算结果: {json.dumps(calc_vars, ensure_ascii=False, default=str)}"},
            ],
            mode="instruct",
            config_name=config_name,
        )

    @staticmethod
    def _build_citations_from_sop_trace(dispatcher) -> list:
        """从 SOP 执行追踪中构建 citations。"""
        citations = []
        history = getattr(dispatcher.memory, "history", [])
        for record in history:
            tool_name = getattr(record, "tool_name", "") or ""
            step_id = getattr(record, "step_id", "") or ""
            outputs = getattr(record, "outputs", None) or {}
            if tool_name in ("table_lookup", "knowledge_search"):
                citations.append({
                    "source": tool_name,
                    "step_id": step_id,
                    "snippet": str(outputs)[:200],
                })
        return citations

    @staticmethod
    def _build_citations_from_retrieved(fused, doc_nodes) -> list:
        """从检索结果构建 citations 数组。"""
        doc_title_map = {node.id: node.title for node in doc_nodes}
        citations = []
        for item in fused[:5]:
            if not item.text:
                continue
            doc_id = str(item.doc_id or "")
            fusion_sources = item.metadata.get("fusion_sources", [])
            if not fusion_sources:
                source_kind = str(item.metadata.get("source_kind") or "")
                fusion_sources = [source_kind] if source_kind else []
            citations.append({
                "target_id": str(item.item_id or ""),
                "doc_id": doc_id,
                "doc_title": doc_title_map.get(doc_id, ""),
                "page_idx": int(item.metadata.get("page_idx", 0) or 0),
                "section_path": str(item.metadata.get("section_path") or ""),
                "snippet": str(item.text or "")[:200],
                "score": float(item.rerank_score or item.score or 0.0),
                "fusion_sources": fusion_sources,
            })
        return citations

    @staticmethod
    def _build_sop_trace(dispatcher, sop: "SOP") -> list:
        """从 SOP 执行追踪中构建步骤明细列表。"""
        step_durations = getattr(dispatcher, "step_durations", {}) or {}
        history = getattr(dispatcher.memory, "history", [])
        trace = []
        for idx, step in enumerate(sop.steps):
            record = None
            for r in history:
                if r.step_id == step.id:
                    record = r
                    break
            trace.append({
                "step_id": step.id,
                "step_name": step.name or step.name_zh or step.id,
                "step_index": idx + 1,
                "tool": step.tool or "auto",
                "description": step.description or step.description_zh or "",
                "inputs": (record.inputs if record else step.inputs) or {},
                "outputs": (record.outputs if record else None),
                "duration": step_durations.get(step.id, 0.0),
                "status": (record.status if record else "pending"),
                "error": (record.error if record else None),
            })
        return trace

    @property
    def llm_client(self):
        """获取 LLM 客户端。"""
        return self._llm_client
    
    def _extract_json_from_response(self, response: str) -> Dict[str, Any]:
        """
        从 LLM 响应中提取 JSON 数据。
        
        支持以下格式:
        - ```json {...} ```
        - ``` {...} ```
        - 纯 JSON 字符串
        
        Args:
            response: LLM 的原始响应字符串
            
        Returns:
            解析后的 JSON 字典
            
        Raises:
            json.JSONDecodeError: 当无法解析 JSON 时
        """
        cleaned = response.strip()
        
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0]
        
        return json.loads(cleaned.strip())
    
    def log_pre_execution(self, logs: List[Dict[str, Any]]):
        """
        记录前置过程日志到 Markdown。
        logs: list of dict, each containing:
            - event: 事件名称 (e.g. "用户需求")
            - method: 获得方式 (e.g. "User Input")
            - time: 发生时间 (e.g. "2023-10-27 10:00:00")
            - duration: 耗时 (e.g. "0.5s")
            - details: 详细内容
        """
        if not self.result_md_path:
            return
            
        with open(self.result_md_path, "a", encoding="utf-8") as f:
            f.write("## 0. 前置过程概览\n\n")
            f.write("| 事件 | 获得方式 | 时间 | 耗时 | 详情 |\n")
            f.write("| --- | --- | --- | --- | --- |\n")
            
            for log in logs:
                event = log.get("event", "-")
                method = log.get("method", "-")
                time_str = log.get("time", "-")
                duration = log.get("duration", "-")
                details = str(log.get("details", "-")).replace("\n", "<br>")
                if len(details) > 100:
                    details = details[:97] + "..."
                    
                f.write(f"| {event} | {method} | {time_str} | {duration} | {details} |\n")
            
            f.write("\n---\n\n")

    def run_sop(self, sop: SOP, initial_context: Dict[str, Any], pre_logs: List[Dict[str, Any]] = None):
        """
        Execute the SOP with the given initial context.
        """
        self.start_time = time.time()
        logger.info(f"[{sop.id}] Starting execution: {sop.description}")
        
        # Log pre-execution events if provided
        if pre_logs:
            self.log_pre_execution(pre_logs)
            
        self.memory.update_context(initial_context)
        
        # Simple linear execution for now
        # In a real FSM, we would follow next_step_id
        for step in sop.steps:
            self._execute_step(step)
            
        logger.info(f"[{sop.id}] Execution finished.")
        
        # Log total time
        total_duration = time.time() - self.start_time
        
        # Calculate breakdowns
        total_tool_time = sum(self.tool_durations.values())
        total_summary_time = sum(self.summary_durations.values())
        total_step_overhead = sum(self.step_durations.values()) - total_tool_time - total_summary_time
        
        if self.result_md_path:
            with open(self.result_md_path, "a", encoding="utf-8") as f:
                f.write(f"## 执行总结\n\n")
                f.write(f"| 项目 | 耗时 | 占比 |\n")
                f.write(f"| --- | --- | --- |\n")
                f.write(f"| **总耗时** | **{total_duration:.2f}s** | 100% |\n")
                f.write(f"| 工具执行 | {total_tool_time:.2f}s | {(total_tool_time/total_duration)*100:.1f}% |\n")
                f.write(f"| LLM 总结 | {total_summary_time:.2f}s | {(total_summary_time/total_duration)*100:.1f}% |\n")
                f.write(f"| 调度开销 | {total_step_overhead:.2f}s | {(total_step_overhead/total_duration)*100:.1f}% |\n")
                f.write(f"\n> 注: '调度开销' 包含 Python 代码执行、文件 I/O 及其他逻辑处理时间。\n")
        
        return self.memory.blackboard
        
    def _execute_step(self, step: Step):
        step_start = time.time()
        logger.info(f"Executing Step: {step.name or step.id} ({step.tool})")
        
        # [Hybrid Architecture Check]
        # If this step was generated by LLM analysis (Scenario A)
        if getattr(step, "analysis_status", None) == "analyzed":
            self._execute_analyzed_step(step)
        else:
            # [Classic Logic] (Scenario B)
            # 1. Resolve Inputs
            tool_inputs = {}
            for key, value in step.inputs.items():
                resolved_value = self.memory.resolve_value(value)
                tool_inputs[key] = resolved_value
                
            # 2. Determine Tool (Static or Auto)
            target_tool_name = step.tool
            if target_tool_name == "auto":
                logger.debug("Detecting tool via LLM...")
                detected_tool, detected_inputs = self._smart_select_tool(step, tool_inputs)
                if detected_tool:
                    logger.info(f"Auto selected tool: {detected_tool}")
                    target_tool_name = detected_tool
                    tool_inputs.update(detected_inputs)
                else:
                    logger.warning("Auto tool selection failed")
                    self._record_step(step, tool_inputs, None, error="Auto-selection failed")
                    return
    
            # 3. Execute Tool
            self._execute_tool_safe(target_tool_name, tool_inputs, step)
            
        # Record duration
        duration = time.time() - step_start
        self.step_durations[step.id] = duration
        
        # If markdown log was written inside _execute_tool_safe, we need to inject duration there?
        # Actually _execute_tool_safe calls _write_markdown_log.
        # But at that point we don't have the full duration (summary generation takes time too).
        # We might need to pass start time to _write_markdown_log or update it later.
        # Simpler approach: Calculate tool execution time inside _execute_tool_safe and pass it.

    def _execute_analyzed_step(self, step: Step):
        """
        Execute a step that was analyzed by LLM (Hybrid Mode).
        Logic:
        1. Resolve all inputs from context.
        2. Check if any resolved input indicates missing data (e.g. explicit None or unresolved vars).
        3. Check if 'notes' exist.
        4. If (Missing Inputs OR Notes OR Tool='auto'), wake up LLM.
        5. Else, execute directly.
        """
        context = self.memory.blackboard
        # Check if step outputs already exist in context
        if self._should_skip_step(step, context):
            self._record_step(step, {}, {"skipped": True, "reason": "value exists in context"})
            return
            
        missing_params = []
        ready_inputs = {}
        
        # 1. Resolve Inputs
        for param_name, value_expr in step.inputs.items():
            resolved_value = self.memory.resolve_value(value_expr)
            ready_inputs[param_name] = resolved_value
            
            # Simple check: if resolved value looks like an unresolved template or None
            if resolved_value is None:
                 missing_params.append(f"{param_name} (value is None)")
            elif isinstance(resolved_value, str) and "${" in resolved_value:
                 # Check if it's an unresolved reference
                 # This is a heuristic, but often useful
                 missing_params.append(f"{param_name} (unresolved: {resolved_value})")

        # 2. Decision Logic
        needs_llm = False
        reason = ""
        
        if missing_params:
            needs_llm = True
            reason = f"Missing parameters: {missing_params}"
        elif step.notes:
            needs_llm = True
            reason = f"Notes present: {step.notes}"
        elif step.tool == "auto":
            needs_llm = True
            reason = "Tool is 'auto'"
            
        if needs_llm:
            logger.debug(f"Hybrid mode: waking up LLM - {reason}")
            self._smart_step_execution(step, reason, missing_params)
        else:
            logger.debug("Hybrid mode: rule-based execution (all params ready)")
            # Execute directly
            self._execute_tool_safe(step.tool, ready_inputs, step)

    def _should_skip_step(self, step: Step, context: Dict[str, Any]) -> bool:
        """Check if step outputs are already present in context."""
        if not step.outputs:
            return False
        # If outputs is "*" we can't easily check, so don't skip
        if step.outputs == "*":
            return False
            
        output_keys = list(step.outputs.keys())
        if not output_keys:
            return False
            
        # Check if all output keys exist and are not None
        # Exception: if the value in context is explicitly "None" string or something? No.
        return all(key in context and context.get(key) is not None for key in output_keys)

    # 执行元 SOP 内置工具（llm_generate）
    def _execute_meta_sop_tool(self, tool_name: str, inputs: Dict[str, Any], step: Step) -> Any:
        if tool_name == "llm_generate":
            messages = []
            query = inputs.get("query", "")
            context = inputs.get("context", "")
            if context:
                messages.append({"role": "system", "content": f"请根据以下上下文回答用户问题：\n{context}"})
            messages.append({"role": "user", "content": query})
            response_text = self._llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            return {"answer": response_text or ""}

        return None

    def _execute_tool_safe(self, tool_name: str, inputs: Dict[str, Any], step: Step):
        """Helper to execute tool and record history"""
        meta_sop_tools = {"llm_generate"}
        if tool_name in meta_sop_tools:
            try:
                tool_start = time.time()
                result = self._execute_meta_sop_tool(tool_name, inputs, step)
                tool_duration = time.time() - tool_start
                self.tool_durations[step.id] = tool_duration
                updates = self._process_outputs(step, result)
                self._record_step(step, inputs, result)
                if self.result_md_path:
                    self._write_markdown_log(step, inputs, result, updates, duration=tool_duration)
            except Exception as e:
                logger.error(f"元 SOP 工具执行错误: {e}")
                self.tool_durations[step.id] = 0.0
                self._record_step(step, inputs, None, error=str(e))
                if self.result_md_path:
                    self._write_markdown_log(step, inputs, {"error": str(e)}, {}, duration=0.0)
            return

        if ToolRegistry is None:
            error_msg = "ToolRegistry not available (engtools not installed)"
            logger.error(error_msg)
            self._record_step(step, inputs, None, error=error_msg)
            raise RuntimeError(error_msg)
            
        tool = ToolRegistry.get_tool(tool_name)
        if not tool:
            error_msg = f"Tool not found: {tool_name}"
            logger.error(error_msg)
            self._record_step(step, inputs, None, error=error_msg)
            raise RuntimeError(error_msg)
            
        try:
            run_kwargs = dict(inputs)
            if self.config_name:
                run_kwargs["config_name"] = self.config_name
            if self.mode:
                run_kwargs["mode"] = self.mode
                
            tool_start = time.time()
            result = tool.run(**run_kwargs)
            tool_duration = time.time() - tool_start
            
            # Record tool duration
            self.tool_durations[step.id] = tool_duration
            
            logger.debug(f"Tool result: {result}")
            
            # Process outputs using the standard method
            updates = self._process_outputs(step, result)
            
            # Record history
            self._record_step(step, inputs, result)
            
            # Write log
            if self.result_md_path:
                self._write_markdown_log(step, inputs, result, updates, duration=tool_duration)
                
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            self.tool_durations[step.id] = 0.0
            self._record_step(step, inputs, None, error=str(e))
            if self.result_md_path:
                 self._write_markdown_log(step, inputs, {"error": str(e)}, {}, duration=0.0)

    def _handle_action_return_value(self, step: Step, action_data: Dict[str, Any]):
        """处理 return_value Action：直接返回值。"""
        value = action_data.get("value")
        logger.info(f"Returning value: {value}")
        updates = self._process_outputs(step, value)
        self._record_step(step, {}, value)
        if self.result_md_path:
            self._write_markdown_log(step, {}, value, updates)

    def _handle_action_ask_user(self, step: Step, action_data: Dict[str, Any]):
        """处理 ask_user Action：向用户询问输入。"""
        question = action_data.get("question")
        variable = action_data.get("variable")
        logger.info(f"Asking user: {question}")
        inputs = {"question": question}
        if variable:
            inputs["variable"] = variable
        self._execute_tool_safe("user_input", inputs, step)

    def _handle_action_execute_tool(self, step: Step, action_data: Dict[str, Any]):
        """处理 execute_tool Action：执行指定工具。"""
        tool_name = action_data.get("tool")
        inputs = action_data.get("inputs", {})
        self._execute_tool_safe(tool_name, inputs, step)

    def _handle_action_table_lookup(self, step: Step, action_data: Dict[str, Any]):
        """处理 table_lookup Action：查表操作，映射到 table_lookup 工具。"""
        table_name = action_data.get("table_name", "")
        conditions = action_data.get("conditions", {})
        target_column = action_data.get("target_column", "")
        file_name = action_data.get("file_name", "")
        inputs = {
            "table_name": table_name,
            "query_conditions": conditions if isinstance(conditions, dict) else {},
            "target_column": target_column,
        }
        if file_name:
            inputs["file_name"] = file_name
        self._execute_tool_safe("table_lookup", inputs, step)

    def _handle_action_search_knowledge(self, step: Step, action_data: Dict[str, Any]):
        """处理 search_knowledge Action：知识检索，映射到语义检索工具。"""
        query = action_data.get("query", "")
        inputs = {"query": query}
        self._execute_tool_safe("knowledge_search", inputs, step)

    def _handle_action_skip(self, step: Step, action_data: Dict[str, Any]):
        """处理 skip Action：跳过步骤。"""
        skip_reason = action_data.get('reason', 'No reason provided')
        logger.info(f"Skipping step: {skip_reason}")
        self._record_step(step, {}, {"skipped": True, "reason": skip_reason})
        if self.result_md_path:
            self._write_markdown_log(step, {}, {"skipped": True, "reason": skip_reason}, {})

    def _handle_action_unknown(self, step: Step, action: str):
        """处理未知的 Action 类型。"""
        error_msg = f"Unknown action: {action}"
        logger.error(error_msg)
        self._record_step(step, {}, None, error=error_msg)

    def _smart_step_execution(self, step: Step, reason: str, missing_params: List[str]):
        """
        LLM 智能执行步骤。

        通过 LLM 分析当前步骤状态，决定执行何种操作来完成步骤。
        支持的操作包括：询问用户、执行工具、返回值、跳过。
        注意：具体的工具执行由 LLM 返回 execute_tool action，通过 tool 字段指定工具名。
        
        Args:
            step: 当前执行的步骤
            reason: 需要 LLM 介入的原因
            missing_params: 缺失的参数列表
        """
        # 构建上下文字符串
        context_str = json.dumps(self.memory.get_context_snapshot(), default=str, ensure_ascii=False)
        if len(context_str) > 3000:
            context_str = context_str[:3000] + "..."
        
        # 构建 Prompt 并调用 LLM
        system_prompt = self._build_smart_execution_prompt(step, reason, context_str)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请完成步骤: {step.name or step.id}"},
        ]
        
        try:
            response = self.llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            action_data = self._extract_json_from_response(response)
            action = action_data.get("action")
            
            logger.debug(f"AI decision: {action}")
            
            # 使用策略模式分发到对应的处理方法
            action_handlers = {
                "return_value": self._handle_action_return_value,
                "ask_user": self._handle_action_ask_user,
                "execute_tool": self._handle_action_execute_tool,
                "table_lookup": self._handle_action_table_lookup,
                "search_knowledge": self._handle_action_search_knowledge,
                "skip": self._handle_action_skip,
            }
            
            handler = action_handlers.get(action)
            if handler:
                handler(step, action_data)
            else:
                self._handle_action_unknown(step, action)
                
        except Exception as e:
            error_msg = f"Smart execution error: {e}"
            logger.error(error_msg)
            self._record_step(step, {}, None, error=error_msg)

    def _write_markdown_log(self, step: Step, inputs: Any, result: Any, updates: Dict[str, Any], duration: float = 0.0):
        """Write step execution details to Markdown file"""
        if not self.result_md_path:
            return
            
        blackboard_values = self.memory.blackboard
        step_id = step.id
        step_name = step.name or step_id
        tool_name = step.tool
        description = step.description or ""
        
        # Determine current step note based on tool
        current_step_note = f"工具: {tool_name}"
        if tool_name == "table_lookup":
             table_name = inputs.get('table_name', '') if isinstance(inputs, dict) else ''
             current_step_note = f"查表: {table_name}"
        elif tool_name == "calculator":
             expr = inputs.get('expression', '') if isinstance(inputs, dict) else ''
             if len(expr) > 25:
                 expr = expr[:22] + "..."
             current_step_note = f"公式: {expr}" if expr else "公式计算"
        elif tool_name == "user_input":
             current_step_note = "用户输入"
        elif tool_name == "auto":
             current_step_note = "自动生成"
             
        # Update metadata for new variables
        for key in updates:
            self.variable_metadata[key] = {
                "source_step": step_id,
                "note": current_step_note,
                "duration": duration
            }
        
        with open(self.result_md_path, "a", encoding="utf-8") as f:
            f.write(f"## {step_id}: {step_name}\n\n")
            
            # 1. 写入 LLM 小结
            summary_start = time.time()
            llm_summary = self._generate_step_summary(step_name, tool_name, inputs, result, updates)
            summary_duration = time.time() - summary_start
            self.summary_durations[step.id] = summary_duration
            
            f.write(f"**LLM 小结** (耗时: {summary_duration:.2f}s): {llm_summary}\n\n")
            
            # 2. 写入 Blackboard 更新表格
            f.write(f"**Blackboard 状态**:\n\n")
            f.write("| 序号 | 参数 | 类型 | 取值 | 状态 | 耗时 | 备注 |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
            
            # 固定顺序：按字母序排序
            all_keys = sorted(blackboard_values.keys())
            
            for idx, key in enumerate(all_keys, 1):
                val = blackboard_values.get(key)
                
                # Default values
                status = "⚪ 已知量"
                note = "-"
                time_str = "-"
                
                if key in updates:
                    status = f"🟢 {step_id} 结果"
                    note = current_step_note
                    time_str = f"{duration:.2f}s"
                elif key in self.variable_metadata:
                    meta = self.variable_metadata[key]
                    source = meta.get("source_step", "Unknown")
                    status = f"🟡 {source} 求解"
                    note = meta.get("note", "-")
                    prev_duration = meta.get("duration", 0.0)
                    time_str = f"{prev_duration:.2f}s" if prev_duration > 0 else "-"
                else:
                    status = "⚪ 已知量"
                    note = "初始参数"
                    time_str = "-"

                # Type Inference (Simple)
                val_type = type(val).__name__
                if isinstance(val, (int, float)):
                    val_type = "数值"
                elif isinstance(val, str):
                    val_type = "字符串"
                
                # Format Value (Truncate if too long)
                val_str = str(val)
                # Escape pipe characters to avoid breaking the table
                val_str = val_str.replace("|", "\\|").replace("\n", " ")
                if len(val_str) > 50:
                    val_str = val_str[:47] + "..."

                f.write(f"| {idx} | {key} | {val_type} | {val_str} | {status} | {time_str} | {note} |\n")
                
            f.write("\n")
            
            # 3. 详细工具日志（折叠）
            f.write("<details>\n<summary>点击查看工具调用详情</summary>\n\n")
            f.write(f"**说明**: {description}\n\n")
            f.write(f"**工具**: `{tool_name}`\n\n")
            f.write(f"**耗时**: {duration:.4f}s\n\n")
            f.write("**输入**:\n")
            f.write(f"```json\n{json.dumps(inputs, ensure_ascii=False, indent=2)}\n```\n\n")
            f.write("**输出**:\n")
            f.write(f"```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n\n")
            f.write("</details>\n\n")
            f.write("---\n\n")

    def _process_outputs(self, step: Step, result: Any) -> Dict[str, Any]:
        # Update global context based on output mapping
        updates = {}
        if not step.outputs:
            return updates
            
        # If outputs is "*" map everything (if result is dict)
        if step.outputs == "*":
            if isinstance(result, dict):
                updates = result
                self.memory.update_context(result)
            else:
                updates = {"last_result": result}
                self.memory.update_context(updates)
            return updates
            
        for context_key, result_path in step.outputs.items():
            # Simple extraction
            # If result_path is empty string or ".", use the whole result
            if not result_path or result_path == ".":
                val = result
            # If result_path is "result", extract the 'result' field from dict
            elif result_path == "result":
                if isinstance(result, dict) and "result" in result:
                    val = result["result"]
                elif isinstance(result, dict) and context_key in result:
                    val = result[context_key]
                else:
                    val = result
            elif isinstance(result, dict) and result_path in result:
                val = result[result_path]
            else:
                # Try to treat result_path as a literal constant (e.g. "0.15", "-1", "True")
                try:
                    # Check for boolean first
                    if result_path.lower() == "true":
                         val = True
                    elif result_path.lower() == "false":
                         val = False
                    else:
                         # Try float/int
                         # Remove whitespace
                         rp = result_path.strip()
                         val = float(rp)
                         # Convert to int if it's an integer value and original string didn't look like a float (optional)
                         if val.is_integer() and '.' not in rp:
                             val = int(val)
                except:
                     val = None
                
            if val is not None:
                updates[context_key] = val
                self.memory.update_context({context_key: val})
        
        return updates
                
    def _record_step(self, step: Step, inputs: Any, outputs: Any, error: str = None):
        record = StepRecord(
            step_id=step.id,
            tool_name=step.tool,
            inputs=inputs,
            outputs=outputs,
            status="failed" if error else "success",
            error=error
        )
        self.memory.add_step_io({
            "step_id": step.id,
            "tool_name": step.tool,
            "inputs": inputs,
            "outputs": outputs,
            "status": "failed" if error else "success",
            "error": error
        })
        self.memory.add_history(record)



    def _smart_select_tool(self, step: Step, current_inputs: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Use LLM to select the best tool and formulate inputs when step.tool is 'auto'.
        """
        if ToolRegistry is None:
            return None, {}
            
        tools_desc = ToolRegistry.list_tools()
        tools_str = "\n".join([f"- {name}: {desc}" for name, desc in tools_desc.items()])
        
        # Prepare context snapshot (truncated to avoid huge prompt)
        context_str = json.dumps(self.memory.get_context_snapshot(), default=str, ensure_ascii=False)
        if len(context_str) > 2000:
            context_str = context_str[:2000] + "...(truncated)"
            
        system_prompt = f"""
You are an intelligent agent dispatcher. Your task is to select the most appropriate tool to execute the current step.

Available Tools:
{tools_str}

Current Step Information:
- ID: {step.id}
- Description: {step.description_zh or step.description}
- Pre-resolved Inputs: {json.dumps(current_inputs, default=str, ensure_ascii=False)}

Global Context:
{context_str}

Instructions:
1. Analyze the step description and context.
2. Select the best tool from the available list to accomplish the step goal.
3. Extract or formulate the necessary arguments for the tool based on context and inputs.
4. Return a JSON object with "tool" and "inputs".

Example Output:
{{
  "tool": "calculator",
  "inputs": {{ "expression": "12 * 50" }}
}}
"""
        messages = [{"role": "system", "content": system_prompt}]
        try:
            response = self.llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            data = self._extract_json_from_response(response)
            return data.get("tool"), data.get("inputs", {})
        except Exception as e:
            logger.error(f"Smart selection failed: {e}")
            return None, {}

            
    def _build_smart_execution_prompt(self, step: Step, reason: str, context_str: str) -> str:
        """
        构建智能执行步骤的 System Prompt。
        
        Args:
            step: 当前执行的步骤
            reason: 需要 LLM 介入的原因
            context_str: 上下文变量字符串
            
        Returns:
            构建好的 system prompt
        """
        return f"""You are the Step Executor of an expert system. You are facing a step that requires your attention.

Current Step:
- Name: {step.name}
- Description: {step.description}
- Notes/Warnings: {step.notes}
- Required Inputs: {step.inputs}

Context Variables:
{context_str}

Situation: {reason}

Your Goal: Complete this step or make progress towards it.

Available Actions (Output JSON):
1. ASK_USER: If parameters are missing and you cannot deduce them.
   {{ "action": "ask_user", "question": "...", "variable": "变量名" }}
   
2. SEARCH_KNOWLEDGE: If you need to check textual regulations.
    {{ "action": "search_knowledge", "query": "..." }}
    
 3. TABLE_LOOKUP: If you need to find a value in a standard table (e.g. Dimensions of 10000 DWT ship).
    {{ "action": "table_lookup", "table_name": "...", "conditions": "...", "target_column": "..." }}

 4. EXECUTE_TOOL: If you have enough info to run the tool (calculator, etc).
    {{ "action": "execute_tool", "tool": "{step.tool if step.tool != 'auto' else 'appropriate_tool'}", "inputs": {{ ... }} }}
    
 5. RETURN_VALUE: If the step is just setting a value or you know the answer directly.
    {{ "action": "return_value", "value": 0.15 }}

 6. SKIP: If this step is already done or irrelevant.
    {{ "action": "skip", "reason": "..." }}

Output ONLY the JSON."""

    def _generate_step_summary(self, step_name: str, tool_name: str, resolved_inputs: Any, result: Any, updates: Dict[str, Any]) -> str:
        """Use LLM to generate a natural language summary of the step execution."""
        try:
            # Prepare data for prompt, truncating large structures
            inputs_str = json.dumps(resolved_inputs, default=str, ensure_ascii=False)
            if len(inputs_str) > 500: inputs_str = inputs_str[:500] + "..."
            
            result_str = json.dumps(result, default=str, ensure_ascii=False)
            if len(result_str) > 500: result_str = result_str[:500] + "..."
            
            updates_str = json.dumps(updates, default=str, ensure_ascii=False)
            
            system_prompt = f"""
你是一个专家系统的执行记录员。请根据以下信息生成一段简洁、客观的中文执行小结。

【上下文信息】
- 步骤名称: {step_name}
- 工具: {tool_name}
- 输入: {inputs_str}
- 输出: {result_str}
- 状态更新: {updates_str}

【撰写要求】
1. **极其简洁**：字数控制在 80 字以内。
2. **客观陈述**：直接陈述事实，不要使用“我”、“系统”、“执行了”等主语。
3. **重点突出**：核心关注“根据什么输入（如条件、公式），得到了什么结果（关键数值）”。
4. **错误处理**：如果输出包含 error，必须明确指出错误原因。
5. **格式示例**：
   - 查表（表A），在条件 x=1 下获取到 y=2。
   - 根据公式 a+b 计算得到 c=3。
   - 用户输入变量 d，值为 4。
"""
            messages = [{"role": "system", "content": system_prompt.strip()}]
            
            response = self.llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            return response.strip()
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return f"执行工具 {tool_name} 完成。更新变量: {list(updates.keys())}"

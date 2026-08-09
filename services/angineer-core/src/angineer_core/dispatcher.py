"""
执行调度核心模块，负责 L1~L4 分级调度与 SOP 步骤编排。

Dispatcher 是 angineer-core 的大脑入口：
- dispatch(): 顶层分级调度入口，根据意图分类结果选择 L1/L2/L3/L4 路径
- run_sop(): SOP 步骤执行引擎，被 dispatch() 在 L3 路径中调用

依赖关系：
- angineer-core → docs-core（检索/SQL）
- angineer-core → sop-core（SOP 加载）
- angineer-core → ai-inference（LLM 调用）
"""
import time
import json
import uuid
import os
import re
import math
from typing import Dict, Any, Tuple, List, Optional, TYPE_CHECKING
from angineer_core.base_contracts import SOP, Step, IntentResult, AttemptedPathResult, GapAnalysis
from angineer_core.memory import Memory
from angineer_core.base_logger import get_logger
from angineer_core.base_utils import is_fatal_exception

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ai_inference.llm_client import LLMClient

from ai_inference.llm_client import get_llm_client
from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD
from angineer_core.prompts.dispatcher import (
    SQL_DOC_QA_SYSTEM_PROMPT,
    SQL_STRUCTURED_QA_SYSTEM_PROMPT,
    SOP_ANSWER_COMPOSE_PROMPT,
    SOP_ANSWER_SYSTEM_PROMPT,
)
from angineer_core.prompts import versions as _prompt_versions
from angineer_core.sop_runner import SopRunner


class Dispatcher(SopRunner):
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
        super().__init__(
            config_name=config_name,
            mode=mode,
            result_md_path=result_md_path,
            memory=memory,
            llm_client=llm_client,
        )
        self._knowledge_provider = knowledge_provider
        self._sop_provider = sop_provider

    def dispatch(
        self,
        query: str,
        library_id: str = "default",
        doc_ids: Optional[List[str]] = None,
        inline_citations: Optional[List[Dict[str, Any]]] = None,
        filters=None,
        sop_loader=None,
        stage_callback=None,
        step_callback=None,
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
            stage_callback: 主阶段更新回调
            step_callback: SOP 执行时每个步骤完成后的回调函数
        """
        from angineer_core.classifier import IntentClassifier

        started_at = time.time()
        query_id = f"q-{uuid.uuid4().hex[:12]}"
        stage_timings: Dict[str, float] = {}
        doc_ids = doc_ids or []
        inline_citations = inline_citations or []
        sop_trace: list = []

        # --- 1. 意图分类 ---
        intent_result = IntentResult(
            intent_level="L1",
            primary_level="L1",
            service_mode="semantic_retrieval",
            execution_plan=["semantic_retrieval"],
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
        self._emit_stage_callback(
            stage_callback,
            stage="intent",
            intent_result=intent_result,
            answer="",
            citations=[],
            retrieved_items=[],
            sql_payload=None,
            route_debug={},
            flow_debug={},
            stage_timings=stage_timings,
            sop_trace=[],
            fallback_used=False,
        )

        # --- 2. 获取知识库节点 ---
        try:
            kp = self._knowledge_provider
            if kp is None:
                from docs_core.docs_service import get_docs_service
                kp = get_docs_service()
            library_nodes = kp.list_nodes(library_id)
            doc_nodes = [node for node in library_nodes if node.type == "document"]
            if doc_ids:
                requested = self._resolve_requested_doc_ids(doc_nodes, doc_ids)
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
        runtime_flags: List[str] = []
        attempted_paths: List[Dict[str, Any]] = []
        route_debug: Dict[str, Any] = {
            "route_kind": "",
            "matched_sop_id": "",
            "matched_sop_name": "",
            "confidence": None,
            "candidates": [],
            "args": {},
            "missing_args": [],
            "reason": intent_result.reason or "",
            "primary_level": intent_result.primary_level or intent_result.intent_level,
            "execution_plan": list(intent_result.execution_plan or [intent_result.service_mode]),
            "attempted_paths": [],
            "final_path": None,
            "fallback_reason": "",
        }
        flow_debug: Dict[str, Any] = {
            "flow_type": "",
            "sop_id": "",
            "sop_name": "",
            "generated_sop": None,
            "final_context": {},
            "summary": "",
        }

        # --- 3. 分级调度 ---
        try:
            execution_plan = self._resolve_execution_plan(intent_result)
            route_debug["primary_level"] = intent_result.primary_level or intent_result.intent_level
            route_debug["execution_plan"] = list(execution_plan)

            for index, path in enumerate(execution_plan):
                if path == "casual_chat":
                    _t_path = time.time()
                    answer = self._dispatch_chat(query)
                    stage_timings[path] = round(time.time() - _t_path, 2)
                    strategy_desc = "L0 闲聊"
                    route_debug.update({
                        "route_kind": "none",
                        "reason": intent_result.reason or "命中 L0 闲聊直答路径。",
                    })
                    self._append_attempted_path(attempted_paths, path, "success", route_debug["reason"], stage_timings[path])
                    break

                if path == "sql_first":
                    _t_path = time.time()
                    answer, citations, retrieved_items, sql_payload, _sql_fallback = (
                        self._dispatch_sql(query, doc_nodes, library_id, doc_ids)
                    )
                    stage_timings[path] = round(time.time() - _t_path, 2)
                    route_debug.update({
                        "route_kind": "sql",
                        "reason": intent_result.reason or "命中 L2 SQL/条款定位路径。",
                    })
                    if answer:
                        strategy_desc = "L2 SQL/条款定位"
                        self._append_attempted_path(attempted_paths, path, "success", route_debug["reason"], stage_timings[path])
                        self._emit_stage_callback(
                            stage_callback,
                            stage="answer_generated",
                            intent_result=intent_result,
                            answer=answer,
                            citations=citations,
                            retrieved_items=retrieved_items,
                            sql_payload=sql_payload,
                            route_debug=route_debug,
                            flow_debug=flow_debug,
                            stage_timings=stage_timings,
                            sop_trace=sop_trace,
                            attempted_paths=attempted_paths,
                            fallback_used=fallback_used,
                            system_prompt=system_prompt,
                            retrieval_debug=retrieval_debug,
                            strategy_desc=strategy_desc,
                        )
                        break
                    fallback_used = fallback_used or index < len(execution_plan) - 1 or _sql_fallback
                    sql_status, sql_reason = self._summarize_sql_attempt(
                        citations=citations,
                        retrieved_items=retrieved_items,
                        sql_payload=sql_payload,
                        fallback_used=_sql_fallback,
                    )
                    self._append_attempted_path(attempted_paths, path, sql_status, sql_reason, stage_timings[path])
                    route_debug["reason"] = sql_reason
                    self._emit_stage_callback(
                        stage_callback,
                        stage="sop_executing",
                        intent_result=intent_result,
                        answer="",
                        citations=citations,
                        retrieved_items=retrieved_items,
                        sql_payload=sql_payload,
                        route_debug=route_debug,
                        flow_debug=flow_debug,
                        stage_timings=stage_timings,
                        sop_trace=sop_trace,
                        attempted_paths=attempted_paths,
                        fallback_used=fallback_used,
                        system_prompt=system_prompt,
                        retrieval_debug=retrieval_debug,
                        strategy_desc=strategy_desc,
                    )
                    continue

                if path == "standard_sop":
                    _t_path = time.time()
                    answer, citations, strategy_desc, sop_fallback_used, sop_timing, sop_trace, sop_route_debug, sop_flow_debug = (
                        self._dispatch_sop(query, sop_loader, intent_result, step_callback=step_callback)
                    )
                    stage_timings[path] = round(time.time() - _t_path, 2)
                    route_debug.update(sop_route_debug)
                    flow_debug.update(sop_flow_debug)
                    if sop_timing is not None:
                        stage_timings["sop_route"] = sop_timing
                    sop_status, sop_reason = self._summarize_sop_attempt(
                        answer=answer,
                        fallback_used=sop_fallback_used,
                        route_debug=sop_route_debug,
                        flow_debug=sop_flow_debug,
                    )
                    self._append_attempted_path(attempted_paths, path, sop_status, sop_reason, stage_timings[path])
                    if sop_status == "success":
                        self._emit_stage_callback(
                            stage_callback,
                            stage="answer_generated",
                            intent_result=intent_result,
                            answer=answer,
                            citations=citations,
                            retrieved_items=retrieved_items,
                            sql_payload=sql_payload,
                            route_debug=route_debug,
                            flow_debug=flow_debug,
                            stage_timings=stage_timings,
                            sop_trace=sop_trace,
                            attempted_paths=attempted_paths,
                            fallback_used=fallback_used,
                            system_prompt=system_prompt,
                            retrieval_debug=retrieval_debug,
                            strategy_desc=strategy_desc,
                        )
                        break
                    fallback_used = fallback_used or index < len(execution_plan) - 1 or sop_fallback_used
                    self._emit_stage_callback(
                        stage_callback,
                        stage="sop_executing",
                        intent_result=intent_result,
                        answer="",
                        citations=citations,
                        retrieved_items=retrieved_items,
                        sql_payload=sql_payload,
                        route_debug=route_debug,
                        flow_debug=flow_debug,
                        stage_timings=stage_timings,
                        sop_trace=sop_trace,
                        attempted_paths=attempted_paths,
                        fallback_used=fallback_used,
                        system_prompt=system_prompt,
                        retrieval_debug=retrieval_debug,
                        strategy_desc=strategy_desc,
                    )
                    continue

                if path in {"semantic_retrieval", "dynamic_orchestration"}:
                    _t_path = time.time()
                    _enforce = (path == "semantic_retrieval")
                    _agentic_tried = False
                    if path == "dynamic_orchestration" and os.environ.get("ANGINEER_AGENT_L4", "false").lower() == "true":
                        try:
                            from angineer_core.dispatcher_agentic import dispatch_complex_agentic

                            answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, ret_timings, runtime_flags = (
                                dispatch_complex_agentic(
                                    query=query,
                                    doc_nodes=doc_nodes,
                                    library_id=library_id,
                                    doc_ids=doc_ids,
                                    inline_citations=inline_citations,
                                    filters=filters,
                                    max_turns=8,
                                    config_name=self.config_name,
                                    mode=self.mode,
                                    sop_loader=sop_loader,
                                    memory=self.memory,
                                )
                            )
                            _agentic_tried = True
                        except Exception:
                            logger.exception("agentic L4 failed, falling back to legacy")
                    if path == "semantic_retrieval" and os.environ.get("ANGINEER_AGENT_L1", "false").lower() == "true":
                        try:
                            from angineer_core.dispatcher_agentic import dispatch_semantic_agentic

                            from angineer_core.retrieval_pipeline import resolve_semantic_retriever_task

                            _retriever_task = resolve_semantic_retriever_task(query, intent_result)
                            answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, ret_timings, runtime_flags = (
                                dispatch_semantic_agentic(
                                    query=query,
                                    doc_nodes=doc_nodes,
                                    library_id=library_id,
                                    doc_ids=doc_ids,
                                    inline_citations=inline_citations,
                                    filters=filters,
                                    enforce_evidence=_enforce,
                                    task_type=_retriever_task,
                                    max_turns=3,
                                    config_name=self.config_name,
                                    mode=self.mode,
                                )
                            )
                            _agentic_tried = True
                        except Exception:
                            logger.exception("agentic L1 failed, falling back to legacy")
                    if not _agentic_tried:
                        answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, ret_timings, runtime_flags = (
                            self._dispatch_semantic(query, doc_nodes, library_id, doc_ids, intent_result, inline_citations, filters=filters, enforce_evidence=_enforce)
                        )
                    stage_timings[path] = round(time.time() - _t_path, 2)
                    route_kind = "retrieval"
                    if path == "dynamic_orchestration":
                        if _agentic_tried:
                            route_kind = "agentic_complex"
                            flow_debug.update({
                                "flow_type": "agentic_complex",
                                "summary": "L4 agentic 编排路径完成。",
                            })
                        else:
                            route_kind = "semantic_fallback"
                            flow_debug.update({
                                "flow_type": "semantic_fallback",
                                "summary": "当前路径进入证据受约束的语义兜底回答。",
                            })
                    if not route_debug.get("route_kind") or path == "dynamic_orchestration":
                        route_debug.update({
                            "route_kind": route_kind,
                            "reason": intent_result.reason or strategy_desc,
                        })
                    stage_timings.update(ret_timings)
                    status = "success" if answer else "failed"
                    reason = strategy_desc or route_debug.get("reason") or "语义检索未产出可用答案。"
                    self._append_attempted_path(attempted_paths, path, status, reason, stage_timings[path])
                    if answer:
                        self._emit_stage_callback(
                            stage_callback,
                            stage="answer_generated",
                            intent_result=intent_result,
                            answer=answer,
                            citations=citations,
                            retrieved_items=retrieved_items,
                            sql_payload=sql_payload,
                            route_debug=route_debug,
                            flow_debug=flow_debug,
                            stage_timings=stage_timings,
                            sop_trace=sop_trace,
                            attempted_paths=attempted_paths,
                            fallback_used=fallback_used,
                            system_prompt=system_prompt,
                            retrieval_debug=retrieval_debug,
                            runtime_flags=runtime_flags,
                            strategy_desc=strategy_desc,
                        )
                        break
                    self._emit_stage_callback(
                        stage_callback,
                        stage="sop_executing",
                        intent_result=intent_result,
                        answer="",
                        citations=citations,
                        retrieved_items=retrieved_items,
                        sql_payload=sql_payload,
                        route_debug=route_debug,
                        flow_debug=flow_debug,
                        stage_timings=stage_timings,
                        sop_trace=sop_trace,
                        attempted_paths=attempted_paths,
                        fallback_used=fallback_used,
                        system_prompt=system_prompt,
                        retrieval_debug=retrieval_debug,
                        runtime_flags=runtime_flags,
                        strategy_desc=strategy_desc,
                    )

            if not answer and (not attempted_paths or attempted_paths[-1]["path"] != "semantic_retrieval"):
                fallback_used = True
                _t_path = time.time()
                answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, ret_timings, runtime_flags = (
                    self._dispatch_semantic(query, doc_nodes, library_id, doc_ids, intent_result, inline_citations, filters=filters, enforce_evidence=False)
                )
                stage_timings["semantic_retrieval"] = round(time.time() - _t_path, 2)
                stage_timings.update(ret_timings)
                route_debug.update({
                    "route_kind": route_debug.get("route_kind") or "retrieval",
                    "reason": route_debug.get("reason") or strategy_desc or "主执行链未收敛，回退到语义检索。",
                })
                self._append_attempted_path(
                    attempted_paths,
                    "semantic_retrieval",
                    "success" if answer else "failed",
                    strategy_desc or "主执行链未收敛，回退到语义检索。",
                    stage_timings["semantic_retrieval"],
                )
                self._emit_stage_callback(
                    stage_callback,
                    stage="answer_generated" if answer else "sop_executing",
                    intent_result=intent_result,
                    answer=answer,
                    citations=citations,
                    retrieved_items=retrieved_items,
                    sql_payload=sql_payload,
                    route_debug=route_debug,
                    flow_debug=flow_debug,
                    stage_timings=stage_timings,
                    sop_trace=sop_trace,
                    attempted_paths=attempted_paths,
                    fallback_used=fallback_used,
                    system_prompt=system_prompt,
                    retrieval_debug=retrieval_debug,
                    runtime_flags=runtime_flags,
                    strategy_desc=strategy_desc,
                )

        except Exception as e:
            if is_fatal_exception(e):
                raise
            logger.error(f"查询处理异常: {e}", exc_info=True)
            if not answer:
                answer = "抱歉，查询处理出现异常，请稍后重试。"

        final_path, fallback_reason = self._finalize_attempts(
            intent_result=intent_result,
            attempted_paths=attempted_paths,
        )
        route_debug.update({
            "attempted_paths": attempted_paths,
            "final_path": final_path,
            "fallback_reason": fallback_reason,
        })

        # P1.4 执行反馈回流：记录本次 SOP 运行统计（含成功率，供审核界面标黄）
        matched_sop_id = route_debug.get("matched_sop_id")
        if sop_loader is not None and matched_sop_id:
            sop_attempt_status = "failed"
            for item in attempted_paths:
                if item.get("path") == "standard_sop":
                    sop_attempt_status = str(item.get("status") or "failed")
                    break
            try:
                sop_loader.record_run(str(matched_sop_id), sop_attempt_status)
            except Exception as e:
                logger.warning(f"SOP 运行统计写入失败 ({matched_sop_id}): {e}")

        # 解析知识盲区分析（从 LLM 合成回答中提取）
        gap_analysis = None
        confidence_breakdown = None
        if answer and os.environ.get("ANGINEER_GAP_ANALYSIS_ENABLED", "true").lower() == "true":
            try:
                answer, gap_analysis, confidence_breakdown = self._parse_gap_analysis(answer)
            except Exception as e:
                logger.warning(f"知识盲区解析失败: {e}")

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
            "runtime_flags": list(runtime_flags or []),
            "route_debug": route_debug,
            "flow_debug": flow_debug,
            "stage_timings": stage_timings,
            "prompt_versions": dict(_prompt_versions()),
            "inline_citation_count": len(inline_citations),
            "sop_trace": sop_trace,
            "gap_analysis": gap_analysis,
            "confidence_breakdown": confidence_breakdown,
        }

    @staticmethod
    def _resolve_execution_plan(intent_result: IntentResult) -> List[str]:
        """返回当前请求的执行计划，兼容旧版仅靠 service_mode 的分发方式。"""
        plan = list(intent_result.execution_plan or [])
        if not plan:
            plan = [intent_result.service_mode]
        return plan

    @staticmethod
    def _normalize_doc_alias(value: Any) -> str:
        """归一化文档别名，兼容标题、文件名与去扩展名的匹配。"""
        normalized = str(value or "").strip().lower()
        if not normalized:
            return ""
        normalized = normalized.replace("\\", "/").split("/")[-1]
        normalized = re.sub(r"\.(pdf|docx?|md|txt)$", "", normalized)
        normalized = re.sub(r"[\s_.\-]+", "", normalized)
        return normalized

    @classmethod
    def _resolve_requested_doc_ids(cls, doc_nodes: List[Any], requested_doc_ids: List[str]) -> set[str]:
        """把逻辑文档别名映射为当前知识库中的真实运行时 doc_id。"""
        requested = {
            str(doc_id or "").strip()
            for doc_id in (requested_doc_ids or [])
            if str(doc_id or "").strip()
        }
        if not requested:
            return set()
        alias_to_doc_id: Dict[str, str] = {}
        for node in doc_nodes:
            node_id = str(getattr(node, "id", "") or "").strip()
            if not node_id:
                continue
            for candidate in (
                node_id,
                getattr(node, "title", ""),
                os.path.basename(str(getattr(node, "file_path", "") or "")),
                os.path.splitext(os.path.basename(str(getattr(node, "file_path", "") or "")))[0],
            ):
                normalized = cls._normalize_doc_alias(candidate)
                if normalized and normalized not in alias_to_doc_id:
                    alias_to_doc_id[normalized] = node_id
        resolved = set()
        for doc_id in requested:
            resolved.add(alias_to_doc_id.get(cls._normalize_doc_alias(doc_id), doc_id))
        return resolved

    @staticmethod
    def _append_attempted_path(
        attempted_paths: List[Dict[str, Any]],
        path: str,
        status: str,
        reason: str,
        duration: Optional[float] = None,
    ) -> None:
        """向尝试链追加一条执行记录。"""
        attempted_paths.append({
            "path": path,
            "status": status,
            "reason": reason,
            "duration": duration,
        })

    @staticmethod
    def _summarize_sql_attempt(
        *,
        citations: List[Dict[str, Any]],
        retrieved_items: List[Dict[str, Any]],
        sql_payload: Optional[Dict[str, Any]],
        fallback_used: bool,
    ) -> Tuple[str, str]:
        """根据 SQL 检索结果给出更准确的尝试状态与说明。"""
        """根据 SQL 检索结果给出更准确的尝试状态与说明。"""
        row_count = 0
        execution_status = ""
        if isinstance(sql_payload, dict):
            row_count = int(sql_payload.get("row_count") or 0)
            execution_status = str(sql_payload.get("execution_status") or "")
        evidence_count = max(len(citations), len(retrieved_items), row_count)
        if fallback_used:
            return "failed", "SQL/条款定位执行异常，已转入下一级尝试。"
        if execution_status == "bridged" and evidence_count > 0:
            return "insufficient", "L2 已命中可复用的条文/公式证据，但还需要后续计算链继续收敛最终答案。"
        if evidence_count > 0:
            return "insufficient", "SQL/条款定位已命中部分结构化依据，但这些依据还不足以直接完成最终作答。"
        return "no_match", "SQL/条款定位未找到可直接使用的结构化依据，已转入下一级尝试。"

    @staticmethod
    def _summarize_sop_attempt(
        *,
        answer: str,
        fallback_used: bool,
        route_debug: Dict[str, Any],
        flow_debug: Dict[str, Any],
    ) -> Tuple[str, str]:
        """根据 SOP 路由与执行结果归纳当前尝试状态。"""
        if answer and not fallback_used:
            return "success", str(flow_debug.get("summary") or route_debug.get("reason") or "SOP 执行成功。")
        if not route_debug.get("matched_sop_id"):
            return "no_match", str(route_debug.get("reason") or "未命中标准 SOP。")
        if fallback_used:
            return "failed", str(flow_debug.get("summary") or route_debug.get("reason") or "SOP 执行失败。")
        return "insufficient", str(flow_debug.get("summary") or route_debug.get("reason") or "SOP 执行后仍未得到最终答案。")

    @staticmethod
    def _finalize_attempts(
        *,
        intent_result: IntentResult,
        attempted_paths: List[Dict[str, Any]],
    ) -> Tuple[Optional[str], str]:
        """根据尝试链回填最终落点与回退原因。"""
        final_path = None
        fallback_reason = ""
        for item in attempted_paths:
            if item.get("status") == "success":
                final_path = str(item.get("path") or "")
                break
        if not final_path and attempted_paths:
            final_path = str(attempted_paths[-1].get("path") or "")
        if len(attempted_paths) > 1:
            for item in attempted_paths[:-1]:
                if item.get("status") != "success":
                    fallback_reason = str(item.get("reason") or "")
                    break
        intent_result.attempted_paths = [
            AttemptedPathResult(
                path=str(item.get("path") or ""),
                status=str(item.get("status") or "skipped"),
                reason=str(item.get("reason") or "") or None,
            )
            for item in attempted_paths
        ]
        intent_result.final_path = final_path  # type: ignore[assignment]
        intent_result.fallback_reason = fallback_reason
        return final_path, fallback_reason

    def _emit_stage_callback(
        self,
        callback,
        *,
        stage: str,
        intent_result: IntentResult,
        answer: str,
        citations: List[Dict[str, Any]],
        retrieved_items: List[Dict[str, Any]],
        sql_payload: Optional[Dict[str, Any]],
        route_debug: Dict[str, Any],
        flow_debug: Dict[str, Any],
        stage_timings: Dict[str, float],
        sop_trace: List[Dict[str, Any]],
        attempted_paths: Optional[List[Dict[str, Any]]] = None,
        fallback_used: bool = False,
        system_prompt: str = "",
        retrieval_debug: Optional[Dict[str, Any]] = None,
        runtime_flags: Optional[List[str]] = None,
        strategy_desc: str = "",
    ) -> None:
        """向评测层发送主阶段的中间态，支撑逐步展示。"""
        if callback is None:
            return
        safe_route_debug = dict(route_debug or {})
        if attempted_paths is not None:
            safe_route_debug["attempted_paths"] = list(attempted_paths)
        safe_route_debug.setdefault(
            "execution_plan",
            list(intent_result.execution_plan or [intent_result.service_mode]),
        )
        safe_route_debug.setdefault("primary_level", intent_result.primary_level or intent_result.intent_level)
        try:
            callback({
                "stage": stage,
                "answer": answer,
                "citations": list(citations or []),
                "retrieved_items": list(retrieved_items or []),
                "sql": sql_payload,
                "intent": intent_result.model_dump(mode="json"),
                "route_debug": safe_route_debug,
                "flow_debug": dict(flow_debug or {}),
                "stage_timings": dict(stage_timings or {}),
                "sop_trace": list(sop_trace or []),
                "fallback_used": fallback_used,
                "system_prompt": system_prompt,
                "retrieval_debug": dict(retrieval_debug or {}),
                "runtime_flags": list(runtime_flags or []),
                "strategy": strategy_desc,
            })
        except Exception as exc:
            logger.warning(f"阶段回调失败: {exc}")

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
                                        config_name=self.config_name,
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
                    bridge_items, bridge_citations = self._bridge_l2_evidence(
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

    def _bridge_l2_evidence(
        self,
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
        bridge_citations = self._build_citations_from_retrieved(bridge_items, doc_nodes)
        return bridge_items, bridge_citations

    def _dispatch_sop(
        self,
        query: str,
        sop_loader,
        intent_result: IntentResult,
        step_callback=None,
    ) -> Tuple[str, list, str, bool, Optional[float], list, Dict[str, Any], Dict[str, Any]]:
        """L3 路径：SOP 匹配与执行。"""
        from angineer_core.classifier import IntentClassifier

        answer = ""
        citations = []
        strategy_desc = ""
        fallback_used = False
        sop_timing = None
        stage_timings: Dict[str, Any] = {}
        sop_trace: list = []
        route_debug: Dict[str, Any] = {
            "route_kind": "standard_sop",
            "matched_sop_id": "",
            "matched_sop_name": "",
            "confidence": None,
            "candidates": [],
            "args": {},
            "missing_args": [],
            "reason": intent_result.reason or "",
        }
        flow_debug: Dict[str, Any] = {
            "flow_type": "standard_sop",
            "sop_id": "",
            "sop_name": "",
            "generated_sop": None,
            "final_context": {},
            "summary": "",
        }

        try:
            _t_sop = time.time()
            if sop_loader is not None:
                sops = sop_loader.load_all()
                classifier = IntentClassifier(sops)
            else:
                classifier = None

            if classifier is not None:
                _t_route = time.time()
                route_result = classifier.route(
                    query, config_name=self.config_name, mode=self.mode
                )
                route_timing = round(time.time() - _t_route, 2)
                matched_sop = route_result.sop
                route_debug.update({
                    "matched_sop_id": matched_sop.id if matched_sop else "",
                    "matched_sop_name": (
                        matched_sop.name_zh
                        or matched_sop.name_en
                        or matched_sop.id
                    ) if matched_sop else "",
                    "confidence": route_result.confidence,
                    "candidates": route_result.candidates or [],
                    "args": route_result.args or {},
                    "reason": route_result.reason or "",
                })

                if route_result.sop and route_result.confidence >= SOP_ROUTE_CONFIDENCE_THRESHOLD:
                    sop_full = sop_loader.analyze_sop(
                        route_result.sop.id, prefer_llm=False
                    )
                    required_args = list(((sop_full.blackboard or {}).get("required") or []))
                    route_debug["missing_args"] = [
                        key for key in required_args if key not in (route_result.args or {})
                    ]

                    sop_dispatcher = Dispatcher(
                        config_name=self.config_name, mode=self.mode
                    )
                    initial_context = {"user_query": query}
                    initial_context.update(route_result.args)

                    if step_callback:
                        try:
                            step_callback({
                                "event": "route_completed",
                                "route_debug": {
                                    "route_kind": "standard_sop",
                                    "matched_sop_id": sop_full.id,
                                    "matched_sop_name": sop_full.name_zh or sop_full.name_en or sop_full.id,
                                    "confidence": route_result.confidence,
                                    "candidates": route_result.candidates or [],
                                    "args": route_result.args or {},
                                    "missing_args": route_debug.get("missing_args", []),
                                    "reason": route_result.reason or "",
                                },
                                "intent": {"intent_level": "L3", "service_mode": "standard_sop"},
                            })
                        except Exception as e:
                            logger.warning(f"路由完成回调失败: {e}")

                    _t_execute = time.time()
                    final_context = sop_dispatcher.run_sop(sop_full, initial_context, step_callback=step_callback)
                    execute_timing = round(time.time() - _t_execute, 2)

                    _t_answer = time.time()
                    answer = self._extract_answer_from_sop_context(
                        final_context, query
                    )
                    stage_timings["llm"] = round(time.time() - _t_answer, 2)
                    citations = self._build_citations_from_sop_trace(sop_dispatcher)
                    sop_trace = self._build_sop_trace(sop_dispatcher, sop_full)
                    strategy_desc = (
                        f"SOP 执行 ({route_result.sop.id}, "
                        f"confidence={route_result.confidence:.2f})"
                    )
                    flow_debug.update({
                        "sop_id": sop_full.id,
                        "sop_name": sop_full.name_zh or sop_full.name_en or sop_full.id,
                        "final_context": final_context or {},
                        "summary": (
                            f"命中 SOP `{sop_full.id}`，执行 {len(sop_full.steps)} 个步骤。"
                        ),
                    })
                    sop_timing = route_timing
                    stage_timings["sop_execute"] = execute_timing
                else:
                    logger.info(
                        f"SOP 未匹配或置信度不足: {route_result.reason}"
                    )
                    flow_debug["summary"] = route_result.reason or "SOP 未匹配或置信度不足。"
                    fallback_used = True
            else:
                route_debug["reason"] = "SOP Loader 不可用，无法执行标准 SOP 路径。"
                flow_debug["summary"] = route_debug["reason"]
                fallback_used = True
        except Exception as e:
            logger.warning(f"SOP 执行失败，回退语义检索: {e}")
            route_debug["reason"] = str(e)
            flow_debug["summary"] = f"SOP 执行失败: {e}"
            fallback_used = True

        return answer, citations, strategy_desc, fallback_used, sop_timing, sop_trace, route_debug, flow_debug

    def _dispatch_semantic(
        self,
        query: str,
        doc_nodes: list,
        library_id: str,
        doc_ids: List[str],
        intent_result: IntentResult,
        inline_citations: Optional[List[Dict[str, Any]]] = None,
        filters=None,
        enforce_evidence: bool = False,
    ) -> Tuple[str, list, list, str, str, Dict, Dict[str, float], Dict[str, Any]]:
        """L1/L2回退/L3回退：语义检索路径。

        enforce_evidence=True 时，若检索无结果则直接返回空，不调用 LLM 自由生成。
        """
        from ai_inference.llm_client import get_llm_client
        from angineer_core.retrieval_pipeline import (
            resolve_semantic_retriever_task,
            run_semantic_retrieval,
        )
        from angineer_core.qa_pipeline import (
            build_answer_context,
            build_evidence_text,
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
            citations = self._build_citations_from_retrieved(fused, doc_nodes)

            if not answer and fused:
                context_text = build_answer_context(fused)
                # enforce_evidence 模式下，若无有效上下文则拒绝生成
                if enforce_evidence and not context_text.strip():
                    logger.info("语义检索：enforce_evidence=True，未检索到有效证据，拒绝 LLM 自由生成")
                    return "", citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, timings, runtime_flags
                explicit_evidence_text = self._build_inline_citation_context(inline_citations or [])
                evidence_text = build_evidence_text(explicit_evidence_text, context_text)

                _t_prompt = time.time()
                system_prompt = self._build_system_prompt(retriever_task_type, query)
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

    @staticmethod
    def _build_inline_citation_context(inline_citations: List[Dict[str, Any]]) -> str:
        """把前端显式确认的引用对象转成高优先级证据文本（P6b 归位 retrieval_pipeline）。"""
        from angineer_core.retrieval_pipeline import build_inline_citation_context

        return build_inline_citation_context(inline_citations)

    @staticmethod
    def _build_system_prompt(retriever_task_type: str, query: str = "") -> str:
        """根据检索任务类型构建对应的 system prompt（P6c 归位 qa_pipeline）。"""
        from angineer_core.qa_pipeline import build_system_prompt

        return build_system_prompt(retriever_task_type, query)

    @staticmethod
    def _parse_gap_analysis(answer: str) -> Tuple[str, Optional[List[Dict[str, Any]]], Optional[Dict[str, List[str]]]]:
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

    @staticmethod
    def _extract_answer_from_sop_context(
        context: Dict[str, Any], query: str, config_name: str = None,
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
                return Dispatcher._compose_sop_answer(query, calc_vars, config_name)
            except Exception as exc:
                logger.warning(f"SOP 答案总结生成失败，回退为原始计算值: {exc}")
                return fallback_text

        # 5. 如果没有明确答案，同样用 LLM 生成（严格限制在步骤输出范围内）
        return Dispatcher._compose_sop_answer(query, calc_vars, config_name)

    @staticmethod
    def _compose_sop_answer(query: str, calc_vars: Dict[str, Any], config_name: str = None) -> str:
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

    @staticmethod
    def _build_citations_from_retrieved(fused, doc_nodes) -> list:
        """从检索结果构建 citations 数组。"""
        from angineer_core.retrieval_pipeline import build_citations_from_retrieved

        return build_citations_from_retrieved(fused, doc_nodes)


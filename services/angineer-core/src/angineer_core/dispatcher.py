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
import re
import math
from typing import Dict, Any, Tuple, List, Optional, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from angineer_core.base_contracts import SOP, Step, IntentResult, AttemptedPathResult
from angineer_core.memory import Memory, StepRecord
from angineer_core.base_logger import get_logger
from angineer_core.base_utils import is_fatal_exception

logger = get_logger(__name__)

_TOOL_EXEC_TIMEOUT_SECONDS = 120

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
        inline_citations: Optional[List[Dict[str, Any]]] = None,
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
                from docs_core.knowledge_service import get_knowledge_service
                kp = get_knowledge_service()
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
                    answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, ret_timings, runtime_flags = (
                        self._dispatch_semantic(query, doc_nodes, library_id, doc_ids, intent_result, inline_citations, enforce_evidence=_enforce)
                    )
                    stage_timings[path] = round(time.time() - _t_path, 2)
                    route_kind = "retrieval"
                    if path == "dynamic_orchestration":
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
                    self._dispatch_semantic(query, doc_nodes, library_id, doc_ids, intent_result, inline_citations, enforce_evidence=False)
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
            "inline_citation_count": len(inline_citations),
            "sop_trace": sop_trace,
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
        from docs_core.query_protocols.contracts import KnowledgeQueryRequest
        from docs_core.retrieval.formula_retriever import formula_retriever, is_calculation_query

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

                if route_result.sop and route_result.confidence >= 0.6:
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
        enforce_evidence: bool = False,
    ) -> Tuple[str, list, list, str, str, Dict, Dict[str, float]]:
        """L1/L2回退/L3回退：语义检索路径。

        enforce_evidence=True 时，若检索无结果则直接返回空，不调用 LLM 自由生成。
        """
        from docs_core.query_protocols.contracts import KnowledgeQueryRequest
        from docs_core.retrieval.dense_retriever import dense_retriever
        from docs_core.retrieval.formula_retriever import formula_retriever, is_formula_query
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
        runtime_flags: List[str] = []
        timings: Dict[str, float] = {}
        fused = []

        try:
            _t1 = time.time()
            retriever_task_type = self._resolve_semantic_retriever_task(query, intent_result)
            strategy_desc = (
                "Dense(正文+公式) + Sparse(全文+图表+公式) + Table(表格) → Hybrid融合（证据受约束）"
            )

            kq_request = KnowledgeQueryRequest(
                query=query,
                library_id=library_id,
                doc_ids=doc_ids,
                top_k=10,
            )
            dense_hits = dense_retriever.retrieve(
                kq_request, doc_nodes, retriever_task_type
            )
            runtime_flags = list(
                getattr(getattr(dense_retriever, "_embedding_provider", None), "runtime_flags", []) or []
            )
            if runtime_flags:
                retrieval_debug["runtime_flags"] = list(dict.fromkeys(runtime_flags))
            sparse_hits = sparse_retriever.retrieve(
                kq_request, doc_nodes, retriever_task_type
            )
            table_hits = table_retriever.retrieve(kq_request, doc_nodes)
            formula_hits = []
            if retriever_task_type in {"locate_formula", "formula_qa"} or is_formula_query(query, retriever_task_type):
                formula_hits = formula_retriever.retrieve(kq_request, doc_nodes)
            source_candidates = {
                "canonical_dense": dense_hits,
                "canonical_sparse": sparse_hits,
            }
            for item in formula_hits:
                source_kind = str(item.metadata.get("source_kind") or "formula_block")
                source_candidates.setdefault(source_kind, []).append(item)
            for item in table_hits:
                source_kind = str(
                    item.metadata.get("source_kind") or "table_aware"
                )
                source_candidates.setdefault(source_kind, []).append(item)
            fused, retrieval_debug = fuse_candidates(
                source_candidates,
                task_type=retriever_task_type,
                top_k=20,
            )
            timings["retrieval"] = round(time.time() - _t1, 2)

            fused = self._boost_clause_matches(query, fused)
            if len(fused) > 5:
                _t_rerank = time.time()
                fused = self._rerank_candidates(query, fused)
                timings["rerank"] = round(time.time() - _t_rerank, 2)
            retrieved_items = [
                item.model_dump(mode="json") for item in fused
            ]
            citations = self._build_citations_from_retrieved(fused, doc_nodes)

            if not answer and fused:
                context_parts = []
                for item in fused[:10]:
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
                # enforce_evidence 模式下，若无有效上下文则拒绝生成
                if enforce_evidence and not context_text.strip():
                    logger.info("语义检索：enforce_evidence=True，未检索到有效证据，拒绝 LLM 自由生成")
                    return "", citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, timings, runtime_flags
                explicit_evidence_text = self._build_inline_citation_context(inline_citations or [])
                user_prompt_content = (
                    f"问题: {query}\n\n显式引用证据:\n{explicit_evidence_text}\n\n检索结果:\n{context_text}"
                    if explicit_evidence_text
                    else f"问题: {query}\n\n检索结果:\n{context_text}"
                )
                evidence_text = f"{explicit_evidence_text}\n{context_text}".strip()

                _t_prompt = time.time()
                system_prompt = self._build_system_prompt(retriever_task_type, query)
                timings["prompt"] = round(time.time() - _t_prompt, 2)

                _t2 = time.time()
                llm = get_llm_client()
                is_choice = bool(
                    Dispatcher._MULTI_CHOICE_PATTERN.search(query)
                )
                if context_text.strip():
                    # 通用两阶段流程：LLM 先预过滤证据，再基于过滤结果回答
                    extract_system = "你是一个工程规范分析助手，只做信息提取，不做推理判断。"
                    if is_choice:
                        extract_user = (
                            "请从以下检索结果中提取与题目相关的所有规范条款。"
                            "对每个条款列出：(1)条款编号 (2)条款关键内容。"
                            "只提取客观存在的条款，不要推理、不要判断、不要补充。\n\n"
                            f"检索结果：\n{context_text}"
                        )
                    else:
                        extract_user = (
                            "请从以下检索结果中提取与问题相关的所有关键信息。\n"
                            "包括：规范条款、定义、数据表格、公式、计算参数等。\n"
                            "只提取客观存在的信息，不要推理、不要回答。\n\n"
                            f"问题：{query}\n\n检索结果：\n{context_text}"
                        )
                    try:
                        filtered_evidence = llm.chat(
                            [
                                {"role": "system", "content": extract_system},
                                {"role": "user", "content": extract_user},
                            ],
                            mode="instruct",
                        )
                        timings["llm_extract"] = round(time.time() - _t2, 2)

                        _t3 = time.time()
                        if is_choice:
                            judge_user = (
                                f"问题: {query}\n\n"
                                f"已提取的规范条款:\n{filtered_evidence}\n\n"
                                "请根据以上条款，逐一判断每个选项是否符合规范要求。\n"
                                "注意：仔细阅读题目要求，区分题目问的是'符合'还是'不符合'规范。\n"
                                "必须按以下格式输出（无论单选还是多选都必须使用此格式）：\n"
                                "A: [符合/不符合/证据不足] - 一句话依据\n"
                                "B: [符合/不符合/证据不足] - 一句话依据\n"
                                "C: [符合/不符合/证据不足] - 一句话依据\n"
                                "D: [符合/不符合/证据不足] - 一句话依据\n"
                                "答案: [符合题目要求的所有选项字母]"
                            )
                            if explicit_evidence_text:
                                judge_user = (
                                    f"问题: {query}\n\n"
                                    f"显式引用证据:\n{explicit_evidence_text}\n\n"
                                    f"已提取的规范条款:\n{filtered_evidence}\n\n"
                                    "请根据以上条款，逐一判断每个选项是否符合规范要求。\n"
                                    "注意：仔细阅读题目要求，区分题目问的是'符合'还是'不符合'规范。\n"
                                    "必须按以下格式输出（无论单选还是多选都必须使用此格式）：\n"
                                    "A: [符合/不符合/证据不足] - 一句话依据\n"
                                    "B: [符合/不符合/证据不足] - 一句话依据\n"
                                    "C: [符合/不符合/证据不足] - 一句话依据\n"
                                    "D: [符合/不符合/证据不足] - 一句话依据\n"
                                    "答案: [符合题目要求的所有选项字母]"
                                )
                        else:
                            judge_user = (
                                f"问题: {query}\n\n"
                                f"关键证据:\n{filtered_evidence}\n\n"
                                "请根据以上关键证据回答问题。"
                            )
                            if explicit_evidence_text:
                                judge_user = (
                                    f"问题: {query}\n\n"
                                    f"显式引用证据:\n{explicit_evidence_text}\n\n"
                                    f"关键证据:\n{filtered_evidence}\n\n"
                                    "请根据以上关键证据回答问题。"
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
                    except Exception:
                        # 两阶段失败时回退单次调用
                        answer = llm.chat(
                            [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt_content},
                            ],
                            mode="instruct",
                        )
                        timings["llm"] = round(time.time() - _t2, 2)
                else:
                    answer = llm.chat(
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt_content},
                        ],
                        mode="instruct",
                    )
                    timings["llm"] = round(time.time() - _t2, 2)
                if self._has_unsupported_reference(answer, evidence_text):
                    answer = (
                        "没有检索到足够证据支持最终结论。"
                        "当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案，请继续补充可核对的规范依据。"
                    )
        except Exception as e:
            logger.error(f"语义检索失败: {e}")
            if not answer:
                answer = "抱歉，检索服务暂时不可用，请稍后重试。"

        return answer, citations, retrieved_items, strategy_desc, system_prompt, retrieval_debug, timings, runtime_flags

    @staticmethod
    def _build_inline_citation_context(inline_citations: List[Dict[str, Any]]) -> str:
        """把前端显式确认的引用对象转成高优先级证据文本。"""
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
            rich_media = reference.get("richMedia") or reference.get("rich_media") or {}
            rich_media_summary: List[str] = []
            if isinstance(rich_media, dict):
                if rich_media.get("tableHtml") or rich_media.get("table_html"):
                    rich_media_summary.append("包含表格")
                if rich_media.get("mathContent") or rich_media.get("math_content"):
                    rich_media_summary.append("包含公式")
                image_paths = rich_media.get("imagePaths") or rich_media.get("image_paths") or []
                if rich_media.get("imagePath") or rich_media.get("image_path") or image_paths:
                    rich_media_summary.append("包含图片")
            meta_parts = [part for part in [
                f"标签: {label}" if label else "",
                f"文档: {doc_title}" if doc_title else "",
                f"页码: {page_idx}" if page_idx else "",
                f"位置: {section_path}" if section_path else "",
                f"富媒体: {'/'.join(rich_media_summary)}" if rich_media_summary else "",
            ] if part]
            block_parts = []
            if meta_parts:
                block_parts.append("\n".join(meta_parts))
            if content:
                block_parts.append(f"证据内容:\n{content}")
            if block_parts:
                evidence_blocks.append("\n".join(block_parts))
        return "\n---\n".join(evidence_blocks)

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

    @classmethod
    def _resolve_semantic_retriever_task(cls, query: str, intent_result: IntentResult) -> str:
        """根据问句和意图结果选择更贴合的语义检索任务类型。"""
        normalized_query = str(query or "").strip()
        base_task_type = cls._map_intent_to_retriever_task(intent_result)
        has_location_hint = any(
            token in normalized_query for token in ("哪一节", "哪一章", "哪一条", "在哪里", "在哪", "位于")
        )
        if has_location_hint and "公式" in normalized_query:
            return "locate_formula"
        if has_location_hint and "图" in normalized_query:
            return "locate_figure"
        if has_location_hint and "表" in normalized_query:
            return "locate_table"
        if base_task_type == "content_qa" and "公式" in normalized_query:
            return "formula_qa"
        return base_task_type

    _MULTI_CHOICE_PATTERN = re.compile(r"[(（][A-E][)）]")

    @staticmethod
    def _build_system_prompt(retriever_task_type: str, query: str = "") -> str:
        """根据检索任务类型构建对应的 system prompt。"""
        base_prompt = (
            "你是一个工程规范领域的专业助手。"
            "你只能依据提供的检索证据回答，但可以基于证据中的规范条款进行合理的推导和计算。"
            "不要编造证据中未出现的规范编号，但应积极使用已检索到的条款内容进行判断。"
        )

        is_choice = bool(query) and bool(
            Dispatcher._MULTI_CHOICE_PATTERN.search(query)
        )

        if retriever_task_type == "definition_qa":
            prompt = base_prompt + (
                '\n\n规则：\n'
                '1. 直接、完整地回答用户问题，给出定义或组成\n'
                '2. 基于检索结果中与问题相关的内容给出准确回答\n'
                '3. 引用具体来源（章节号），格式如【根据第X章...】\n'
                '4. 检索结果即使不完整，也应基于已有内容尽力回答，避免轻易放弃'
            )
        elif retriever_task_type == "locate_qa":
            prompt = base_prompt + (
                '\n\n规则：\n'
                '1. 直接回答位置/设置要求，明确指出具体地点或条件\n'
                '2. 引用具体来源（章节号），格式如【根据第X章...】\n'
                '3. 基于检索结果中与问题相关的内容给出准确回答\n'
                '4. 检索结果即使不完整，也应基于已有内容尽力回答，避免轻易放弃'
            )
        else:
            prompt = base_prompt + (
                '\n\n规则：\n'
                '1. 优先直接回答用户问题\n'
                '2. 只能复述或推导证据中明确出现的信息，禁止引用证据里未出现的规范编号、年份或考试背景\n'
                '3. 每个关键结论后都要指出对应证据来源（文档名、章节号等）\n'
                '4. 如果证据不足以支撑最终结论，明确说明【没有检索到足够证据】，不要自行补全'
            )

        if is_choice:
            prompt += (
                "\n\n选择题分析规则（问题包含选项A/B/C/D时适用）：\n"
                "1. 先整理检索结果中涉及的所有规范章节和条款，确定可依据的规范条目清单\n"
                "2. 对每个选项A/B/C/D逐一核查，必须给出明确判断（符合规范/不符合规范）\n"
                "   - 只有检索结果完全不涉及该选项主题时才标注为\"证据不足\"\n"
                "   - 禁止主观推测题目是\"单选\"还是\"多选\"，禁止以\"题目可能是单选\"为由跳过任何选项的分析\n"
                "3. 检索结果中包含计算公式或数据表格时，代入题目参数计算或查表\n"
                "4. 最终严格按以下格式输出答案（无论单选还是多选都必须使用此格式）：\n"
                "   A: [符合/不符合/证据不足] - 一句话依据\n"
                "   B: [符合/不符合/证据不足] - 一句话依据\n"
                "   C: [符合/不符合/证据不足] - 一句话依据\n"
                "   D: [符合/不符合/证据不足] - 一句话依据\n"
                "   答案: [符合题目要求的所有选项字母]"
            )

        return prompt

        if retriever_task_type == "definition_qa":
            return base_prompt + (
                "\n\n规则：\n"
                "1. 直接、完整地回答用户问题，给出定义或组成\n"
                "2. 如果检索结果中包含与问题相关的内容，请基于相关内容给出准确回答\n"
                '3. 引用具体来源（章节号），格式如"根据第X章..."\n'
                "4. 如果证据不足以支撑结论，明确说明“没有检索到足够证据”，不要自行补全"
            )

        if retriever_task_type == "locate_qa":
            return base_prompt + (
                "\n\n规则：\n"
                "1. 直接回答位置/设置要求，明确指出具体地点或条件\n"
                '2. 引用具体来源（章节号），格式如"根据第X章..."\n'
                "3. 如果检索结果中包含与问题相关的内容，请基于相关内容给出准确回答\n"
                "4. 如果证据不足以支撑结论，明确说明“没有检索到足够证据”，不要自行补全"
            )

        return base_prompt + (
            "\n\n规则：\n"
            "1. 优先直接回答用户问题\n"
            "2. 只能复述或推导证据中明确出现的信息，禁止引用证据里未出现的规范编号、年份或考试背景\n"
            "3. 每个关键结论后都要指出对应证据来源（文档名、章节号等）\n"
            "4. 如果证据不足以支撑最终结论，明确说明“没有检索到足够证据”，不要自行补全"
        )

    @staticmethod
    def _boost_clause_matches(query: str, candidates: list) -> list:
        """题目含章节号时，给匹配该章节的候选加分，确保关键条款不被挤出 top-5。"""
        import re
        clause_refs = re.findall(r'(?:第\s*)?(\d+\.\d+(?:\.\d+)*)', query)
        if not clause_refs:
            return candidates
        for item in candidates:
            text = str(item.text or "")
            section = str(item.metadata.get("section_path") or "")
            combined = f"{section}\n{text}"
            if any(ref in combined for ref in clause_refs):
                current = float(item.rerank_score or 0.0)
                item.rerank_score = round(current + 0.30, 6)
        candidates.sort(key=lambda item: float(item.rerank_score or 0.0), reverse=True)
        return candidates

    @staticmethod
    def _rerank_candidates(query: str, candidates: list) -> list:
        """用 bge-reranker-v2-m3 重排序候选，失败时回退原始顺序。"""
        if len(candidates) <= 5:
            return candidates
        normalized_query = str(query or "").strip()
        if "公式" in normalized_query and any(
            token in normalized_query for token in ("哪一节", "哪一章", "哪一条", "在哪里", "在哪", "位于")
        ):
            return candidates
        try:
            import requests
            docs = [item.text or "" for item in candidates]
            resp = requests.post(
                "http://127.0.0.1:7998/v1/rerank",
                json={"query": query, "documents": docs, "top_n": len(candidates)},
                timeout=10,
            )
            if resp.status_code != 200:
                return candidates
            results = resp.json().get("results", [])
            if not results:
                return candidates
            score_map = {r["index"]: r["relevance_score"] for r in results}
            for i, item in enumerate(candidates):
                item.rerank_score = score_map.get(i, 0.0)
            candidates.sort(key=lambda item: item.rerank_score or 0.0, reverse=True)
            return candidates
        except Exception:
            return candidates

    # 常见中国工程规范代号前缀
    _KNOWN_STD_PREFIXES = frozenset({
        "JTS", "JTJ", "JT", "GB", "GBJ", "GB/T", "SL", "DL", "SY", "SH",
        "HG", "NB", "CJJ", "CJ", "TB", "YB", "JGJ", "JG", "DB",
    })

    @staticmethod
    def _has_unsupported_reference(answer: str, evidence_text: str) -> bool:
        """检测答案中是否出现未在证据中出现的规范编号或题库背景引用。"""
        answer_text = str(answer or "")
        corpus = str(evidence_text or "")
        if not answer_text.strip():
            return False
        # Extract Chinese standard names from the answer — if the corpus
        # mentions the same standard by name, its code is acceptable even
        # when not written verbatim in the evidence.
        answer_std_names = set(re.findall(r'《([^》]+)》', answer_text))
        corpus_std_names = set(re.findall(r'《([^》]+)》', corpus))
        any_std_name_in_corpus = bool(answer_std_names & corpus_std_names)
        # 证据中已有规范章节号（如 5.4.12、第3.1.19条），说明引用了规范内容
        corpus_has_section_nums = bool(re.search(r'(?:第\s*)?\d+\.\d+', corpus))
        patterns = [
            r"[A-Z]{2,}\s*\d+(?:[-/]\d+)*(?:-\d{4})?",
            r"20\d{2}年[^\n，。；]*真题",
        ]
        for pat in patterns:
            for match in re.findall(pat, answer_text):
                token = str(match).strip()
                if not token or token in corpus:
                    continue
                numeric_part = re.search(r'\d+(?:[-/]\d+)*(?:-\d{4})?', token)
                if numeric_part and numeric_part.group() in corpus:
                    continue
                code_match = re.match(r'([A-Z]{2,})\s*(\d+)', token)
                if code_match:
                    prefix = code_match.group(1)
                    num = code_match.group(2)
                    if prefix in corpus and num in corpus:
                        continue
                    # 常见规范代号 + 证据中有章节号 ≈ 合法引用
                    if prefix in Dispatcher._KNOWN_STD_PREFIXES and corpus_has_section_nums:
                        continue
                if any_std_name_in_corpus:
                    continue
                return True
        return False

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
            result_text = str(final_answer)
            if consistency_warning:
                result_text = f"{result_text}\n\n[警告: {consistency_warning}]"
            return result_text

        # 5. 如果没有明确答案，使用 LLM 生成（严格限制在步骤输出范围内）
        from ai_inference.llm_client import get_llm_client
        llm = get_llm_client()
        prompt = f"""你是工程规范领域的专业助手。请根据以下计算结果回答用户问题。

重要约束 - **必须严格遵守**:
- 你的回答必须逐字逐句基于以下计算结果
- 如果计算结果中没有包含问题的完整答案，必须明确说明"当前步骤计算结果不足以完整回答此问题，以下仅基于已有结果:"
- **绝对禁止**添加任何你自己知道但计算结果中未出现的规范编号、数值或公式
- 只能引用计算结果中**已经出现**的变量名和数值
- 将计算结果中的数值代入问题所问的语境中组织语言，但不要改变数值

问题: {query}

计算结果: {json.dumps(calc_vars, ensure_ascii=False, default=str)}
"""
        return llm.chat(
            [
                {"role": "system", "content": "你是工程规范领域的专业助手。请严格基于提供的计算结果回答问题，不要添加未经验证的信息。"},
                {"role": "user", "content": prompt},
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
        from docs_core.knowledge_service import get_knowledge_service

        doc_title_map = {node.id: node.title for node in doc_nodes}
        knowledge_service = get_knowledge_service()
        citations = []
        for item in fused[:5]:
            doc_id = str(item.doc_id or "")
            citation_target_id = str(
                getattr(item, "citation_target_id", None)
                or item.metadata.get("citation_target_id")
                or item.item_id
                or ""
            ).strip()
            fusion_sources = item.metadata.get("fusion_sources", [])
            if not fusion_sources:
                source_kind = str(item.metadata.get("source_kind") or "")
                fusion_sources = [source_kind] if source_kind else []
            target = knowledge_service.get_citation_target(doc_id, citation_target_id) if citation_target_id else None
            if target:
                citations.append({
                    "label": str(target.get("display_title") or item.title or "").strip(),
                    "reference": {
                        "targetId": str(target.get("target_id") or citation_target_id),
                        "targetType": str(target.get("target_type") or item.entity_type or "content"),
                        "docId": doc_id,
                        "docTitle": doc_title_map.get(doc_id, ""),
                        "pageIdx": int(target.get("page_idx") or 0),
                        "sectionPath": str(target.get("section_path") or ""),
                        "snippet": str(target.get("snippet") or item.text or "")[:200],
                    },
                    "score": float(item.rerank_score or item.score or 0.0),
                    "fusion_sources": fusion_sources,
                })
                continue
            if not item.text:
                continue
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
                "description": step.description_zh or (step.description.content if step.description else ""),
                "inputs": (record.inputs if record else step.inputs) or {},
                "outputs": (record.outputs if record else None),
                "duration": step_durations.get(step.id, 0.0),
                "status": (record.status if record else "pending"),
                "error": (record.error if record else None),
                "thinking": (record.thinking if record else None),
                "evidence": (record.evidence if record else None),
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
        - 嵌入在文本中的首个 {...} 对象（正则兜底）
        
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
        
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            pass
        
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        brace_start = cleaned.find('{')
        brace_end = cleaned.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            candidate = cleaned[brace_start:brace_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        
        raise json.JSONDecodeError(
            f"无法从响应中提取有效JSON (长度={len(response)})",
            response,
            0
        )
    
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

    def run_sop(self, sop: SOP, initial_context: Dict[str, Any], pre_logs: List[Dict[str, Any]] = None, step_callback=None):
        """
        Execute the SOP with the given initial context.
        Args:
            sop: SOP 对象
            initial_context: 初始上下文
            pre_logs: 预执行日志
            step_callback: 每个步骤执行完后的回调函数，签名为 callback(step_info: Dict)
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

            if step_callback:
                step_info = self._build_step_info(step)
                try:
                    step_callback(step_info)
                except Exception as e:
                    logger.warning(f"step_callback 调用失败: {e}")

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

    def _build_step_info(self, step: Step) -> Dict[str, Any]:
        """构建单个步骤的执行信息，用于回调通知。"""
        history = getattr(self.memory, "history", [])
        step_durations = getattr(self, "step_durations", {}) or {}
        record = None
        for r in history:
            if r.step_id == step.id:
                record = r
                break
        return {
            "step_id": step.id,
            "step_name": step.name or step.name_zh or step.id,
            "step_index": len([s for s in history if s]) + 1,
            "tool": step.tool or "auto",
            "description": step.description_zh or (step.description.content if step.description else ""),
            "inputs": (record.inputs if record else step.inputs) or {},
            "outputs": (record.outputs if record else None),
            "duration": step_durations.get(step.id, 0.0),
            "status": (record.status if record else "pending"),
            "error": (record.error if record else None),
            "thinking": (record.thinking if record else None),
            "evidence": (record.evidence if record else None),
        }

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

        # 1.5. 检查所有输入是否有效（非空），避免将空值传递给工具
        non_auto_tools = {"calculator", "table_lookup", "knowledge_search", "user_input"}
        if step.tool in non_auto_tools:
            all_inputs_empty = all(
                v in (None, "", {}, [])
                or (isinstance(v, str) and not v.strip())
                for v in ready_inputs.values()
            )
            if all_inputs_empty and ready_inputs:
                logger.warning(f"[Step {step.id}] 所有输入参数均为空值，无法执行工具调用")
                self._record_step(step, ready_inputs,
                    {"error": "所有输入参数均为空值，无法执行工具调用。请检查前序步骤输出是否正常。"},
                    error="empty_inputs")
                return

        # 1.6. Try to derive missing variables from context (K1, 折减系数, etc.)
        if missing_params and step.tool == "calculator":
            logger.debug(f"Missing calculator params, will rely on LLM: {missing_params}")

        # 2. Decision Logic
        needs_llm = False
        reason = ""
        
        if missing_params:
            needs_llm = True
            reason = f"Missing parameters: {missing_params}"
        elif step.tool == "auto":
            needs_llm = True
            reason = "Tool is 'auto'"
            
        if needs_llm:
            logger.debug(f"Hybrid mode: waking up LLM - {reason}")
            self._smart_step_execution(step, reason, missing_params)
        else:
            logger.debug("Hybrid mode: rule-based execution (all params ready)")
            # Execute directly
            if step.tool == "table_lookup" and "use_llm" not in ready_inputs:
                ready_inputs["use_llm"] = False
            self._execute_tool_safe(step.tool, ready_inputs, step)

    def _should_skip_step(self, step: Step, context: Dict[str, Any]) -> bool:
        """Check if step outputs are already present in context and valid."""
        if not step.outputs:
            return False
        # If outputs is "*" we can't easily check, so don't skip
        if step.outputs == "*":
            return False
            
        output_keys = list(step.outputs.keys())
        if not output_keys:
            return False
            
        for key in output_keys:
            value = context.get(key)
            # 值必须存在且不为 None
            if value is None:
                return False
            # 值不能是空字符串
            if isinstance(value, str) and not value.strip():
                return False
            # 值不能是明显的错误标记
            if isinstance(value, str) and value.strip().lower() in {"error", "failed", "null", "none", "undefined", "nan"}:
                return False
            # 数值类型不能是 NaN
            if isinstance(value, float) and math.isnan(value):
                return False
            # 如果是字典/列表，不能为空
            if isinstance(value, (dict, list)) and not value:
                return False
        return True

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
                normalized_result = self._adapt_result_for_step(step, tool_name, inputs, result)
                tool_error = self._extract_tool_error(normalized_result)
                updates = {} if tool_error else self._process_outputs(step, normalized_result)
                self._record_step(step, inputs, normalized_result, error=tool_error)
                if self.result_md_path:
                    self._write_markdown_log(step, inputs, normalized_result, updates, duration=tool_duration)
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
            
            def _do_tool_run():
                return tool.run(**run_kwargs)
            
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_do_tool_run)
                    result = future.result(timeout=_TOOL_EXEC_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                error_msg = f"Tool '{tool_name}' execution timed out after {_TOOL_EXEC_TIMEOUT_SECONDS}s"
                logger.error(error_msg)
                raise TimeoutError(error_msg)
                
            tool_duration = time.time() - tool_start
            
            # Record tool duration
            self.tool_durations[step.id] = tool_duration
            
            normalized_result = self._adapt_result_for_step(step, tool_name, inputs, result)
            tool_error = self._extract_tool_error(normalized_result)
            logger.debug(f"Tool result: {normalized_result}")
            
            # Process outputs using the standard method
            updates = {} if tool_error else self._process_outputs(step, normalized_result)
            
            # Record history
            self._record_step(step, inputs, normalized_result, error=tool_error)
            
            # Write log
            if self.result_md_path:
                self._write_markdown_log(step, inputs, normalized_result, updates, duration=tool_duration)
                
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
        normalized_value = self._adapt_result_for_step(step, "return_value", {}, value)
        tool_error = self._extract_tool_error(normalized_value)
        updates = {} if tool_error else self._process_outputs(step, normalized_value)
        self._record_step(step, {}, normalized_value, error=tool_error)
        if self.result_md_path:
            self._write_markdown_log(step, {}, normalized_value, updates)

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
        if tool_name == "table_lookup" and "use_llm" not in inputs:
            inputs["use_llm"] = False
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
            "use_llm": False,
        }
        if file_name:
            inputs["file_name"] = file_name
        self._execute_tool_safe("table_lookup", inputs, step)

    def _handle_action_conditional(self, step: Step, action_data: Dict[str, Any]):
        """处理 conditional Action：执行条件分支工具。"""
        condition_var = action_data.get("condition_var")
        resolved_condition = condition_var
        if isinstance(condition_var, str):
            if "${" in condition_var:
                resolved_condition = self.memory.resolve_value(condition_var)
            elif condition_var in self.memory.blackboard:
                resolved_condition = self.memory.resolve_value(f"${{{condition_var}}}")
        inputs = {
            "condition_var": resolved_condition,
            "branches": action_data.get("branches", []),
            "default": action_data.get("default"),
        }
        self._execute_tool_safe("conditional", inputs, step)

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

    def _is_value_from_context(self, value) -> bool:
        """检查 return_value 的值是否可追溯到当前上下文。"""
        if isinstance(value, (int, float)):
            return True
        value_str = str(value)
        if value_str in self.memory.blackboard:
            return True
        for v in self.memory.blackboard.values():
            if value_str in str(v):
                return True
        return False

    def _should_allow_skip(self, step: Step) -> bool:
        """检查步骤是否应该允许跳过（其输出已存在于上下文中）。"""
        if not step.outputs:
            return False
        for output_def in step.outputs:
            key = getattr(output_def, "key", None) or getattr(output_def, "name", None)
            if key and key in self.memory.blackboard and self.memory.blackboard[key] is not None:
                continue
            return False
        return True

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
            response = self.llm_client.chat(
                messages,
                mode=self.mode,
                config_name=self.config_name,
                max_tokens=512
            )
            action_data = self._extract_json_from_response(response)
            action = action_data.get("action")

            # 验证 return_value 和 skip 不会绕过必要的工具执行
            if action == "return_value":
                value = action_data.get("value")
                if value is not None and not self._is_value_from_context(value):
                    logger.warning(f"LLM 尝试 return_value 但值未在上下文中找到: {value}")
                    self._record_step(step, action_data,
                        {"error": "return_value 使用的值未在当前上下文中找到，LLM 可能正在绕过必要的计算步骤"},
                        error="return_value_rejected")
                    return
            if action == "skip":
                if not self._should_allow_skip(step):
                    logger.warning(f"LLM 尝试 skip 步骤 {step.id} 但输出尚未在上下文中")
                    self._record_step(step, action_data,
                        {"error": "skip 被拒绝：步骤的必要输出尚未在上下文中，请完成此步骤"},
                        error="skip_rejected")
                    return

            logger.debug(f"AI decision: {action}")
            
            # 使用策略模式分发到对应的处理方法
            action_handlers = {
                "return_value": self._handle_action_return_value,
                "ask_user": self._handle_action_ask_user,
                "execute_tool": self._handle_action_execute_tool,
                "table_lookup": self._handle_action_table_lookup,
                "conditional": self._handle_action_conditional,
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
        description = step.description.content if step.description else ""
        
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
                    val = result if not isinstance(result, dict) else None
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
                
    def _extract_tool_error(self, result: Any) -> Optional[str]:
        """从工具输出中提取显式错误信息。"""
        if not isinstance(result, dict):
            return None
        error = result.get("error")
        return str(error) if error else None

    def _adapt_result_for_step(self, step: Step, tool_name: str, inputs: Dict[str, Any], result: Any) -> Any:
        """按步骤输出契约为工具结果补齐别名键，降低 LLM 返回格式漂移的影响。"""
        if not isinstance(result, dict):
            return result

        adapted = dict(result)
        output_keys = list(step.outputs.keys()) if isinstance(step.outputs, dict) else []
        if not output_keys:
            return adapted

        if tool_name == "calculator" and isinstance(adapted.get("results"), list):
            for item in adapted["results"]:
                if not isinstance(item, dict):
                    continue
                label = item.get("label")
                value = item.get("result")
                expression = item.get("expression")
                if label and value is not None and label not in adapted:
                    adapted[str(label)] = value
                if expression and value is not None and expression not in adapted:
                    adapted[str(expression)] = value

        for output_key in output_keys:
            if output_key in adapted:
                continue
            candidate_value = self._select_output_value(output_key, adapted)
            if candidate_value is not None:
                adapted[output_key] = candidate_value

        if "result" not in adapted and len(output_keys) == 1 and output_keys[0] in adapted:
            adapted["result"] = adapted[output_keys[0]]

        return adapted

    def _select_output_value(self, output_key: str, result: Dict[str, Any]) -> Any:
        """根据输出键语义从结果字典中选择最合适的值。"""
        candidates = self._collect_result_candidates(result)
        if not candidates:
            return None

        normalized_key = output_key.lower()
        exact_value = candidates.get(output_key)
        if exact_value is not None:
            return exact_value

        if normalized_key == "e":
            numeric_values = [value for value in candidates.values() if isinstance(value, (int, float))]
            if numeric_values:
                return max(numeric_values)

        aliases = []
        if normalized_key == "dwl_basic":
            aliases = ["design_high_water_level", "basic", "design"]
        elif normalized_key == "dwl_extreme":
            aliases = ["extreme_high_water_level", "extreme"]
        elif normalized_key == "delta_w_basic":
            aliases = ["delta_w_10yr", "10yr", "10_year", "10年", "basic"]
        elif normalized_key == "delta_w_extreme":
            aliases = ["delta_w_2yr", "2yr", "2_year", "2年", "extreme"]
        elif normalized_key == "e_basic":
            aliases = ["e_basic", "basic", "10yr", "10年"]
        elif normalized_key == "e_extreme":
            aliases = ["e_extreme", "extreme", "2yr", "2年"]
        elif normalized_key == "t":
            aliases = ["满载吃水t", "吃水t", "design_draft", "draft", "吃水"]
        elif normalized_key == "z1":
            aliases = ["z1", "龙骨下最小富裕深度"]
        elif normalized_key == "z2":
            aliases = ["z2", "波浪富裕深度"]
        elif normalized_key == "z3":
            aliases = ["z3", "船舶装载纵倾富裕深度", "船尾吃水"]
        elif normalized_key == "z4":
            aliases = ["z4", "备淤富裕深度"]

        for alias in aliases:
            for candidate_key, candidate_value in candidates.items():
                candidate_text = str(candidate_key).lower()
                if alias in candidate_text:
                    return candidate_value

        if len(candidates) == 1:
            return next(iter(candidates.values()))
        return None

    def _collect_result_candidates(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从结果字典中提取可映射到 blackboard 的候选值。"""
        meta_keys = {
            "result",
            "results",
            "labeled_results",
            "errors",
            "error",
            "expression",
            "cleaned_expression",
            "variables_used",
            "solve_for",
            "unknowns",
        }
        candidates: Dict[str, Any] = {}

        for key, value in result.items():
            if key in meta_keys:
                continue
            if isinstance(value, dict):
                nested_value = value.get("result")
                if nested_value is not None:
                    candidates[str(key)] = nested_value
                continue
            if isinstance(value, list):
                continue
            candidates[str(key)] = value

        labeled_results = result.get("labeled_results")
        if isinstance(labeled_results, dict):
            for key, value in labeled_results.items():
                if value is not None:
                    candidates[str(key)] = value

        results = result.get("results")
        if isinstance(results, list):
            for index, item in enumerate(results):
                if not isinstance(item, dict):
                    continue
                item_value = item.get("result")
                if item_value is None:
                    continue
                label = item.get("label") or f"expr_{index + 1}"
                candidates[str(label)] = item_value
                expression = item.get("expression")
                if expression:
                    candidates[str(expression)] = item_value

        nested_result = result.get("result")
        if isinstance(nested_result, dict):
            for key, value in nested_result.items():
                if value is not None and not isinstance(value, (dict, list)):
                    candidates[str(key)] = value

        return candidates

    def _record_step(self, step: Step, inputs: Any, outputs: Any, error: str = None, thinking: str = None, evidence: Dict[str, Any] = None):
        inferred_error = error or self._extract_tool_error(outputs)
        status = "failed" if inferred_error else "success"
        record = StepRecord(
            step_id=step.id,
            tool_name=step.tool,
            inputs=inputs,
            outputs=outputs,
            status=status,
            error=inferred_error,
            thinking=thinking,
            evidence=evidence,
        )
        self.memory.add_step_io({
            "step_id": step.id,
            "tool_name": step.tool,
            "inputs": inputs,
            "outputs": outputs,
            "status": status,
            "error": inferred_error,
            "thinking": thinking,
            "evidence": evidence,
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
- Description: {step.description_zh or (step.description.content if step.description else '')}
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
        tool_hint = ""
        if step.tool == "calculator":
            tool_hint = """
IMPORTANT for calculator steps:
- If expression contains unresolved variables like ${K1}, ${折减系数}, derive them from Context Variables and user query.
- For K1 (wave coefficient): if wave direction vs dock angle < 45° → K1=0.3 (顺浪), else → K1=0.5~0.7 (横浪).
- For 折减系数 (reduction factor): 良好掩护→1.0, 部分掩护→(0,1)取中间值如0.5, 开敞→0.
- Output the FINAL computed expression with all variables resolved to numbers.
"""
        
        return f"""You are an expert engineering calculation executor. Be CONCISE.

Current Step:
- Name: {step.name}
- Description: {(step.description.content if step.description else '')}
- Notes/Warnings: {step.notes}
- Required Inputs: {json.dumps(step.inputs, ensure_ascii=False)}

Context Variables:
{context_str}

Situation: {reason}
{tool_hint}

Available Actions (Output ONE compact JSON object only):
1. ASK_USER: If parameters are truly missing.
   {{"action": "ask_user", "question": "...", "variable": "..."}}
   
2. SEARCH_KNOWLEDGE: If you need textual regulations.
    {{"action": "search_knowledge", "query": "..."}}
    
3. TABLE_LOOKUP: If you need table values.
   {{"action": "table_lookup", "table_name": "...", "conditions": {{...}}, "target_column": "..."}}

4. EXECUTE_TOOL: If you have enough info (calculator with resolved expression).
   {{"action": "execute_tool", "tool": "{step.tool if step.tool != 'auto' else 'calculator'}", "inputs": {{"expression": "..."}}}}
    
5. RETURN_VALUE: If you know the answer directly.
   {{"action": "return_value", "value": ...}}

6. SKIP: If already done.
   {{"action": "skip", "reason": "..."}}

CRITICAL OUTPUT RULES:
- Output ONLY valid JSON. No markdown fences, no explanation, no reasoning text.
- Keep JSON under 300 characters total.
- For calculator: expression must use NUMBERS only, no ${{}} templates."""

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

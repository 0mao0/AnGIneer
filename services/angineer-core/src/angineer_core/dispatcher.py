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
import uuid
import os
from typing import Dict, Any, Tuple, List, Optional, TYPE_CHECKING
from angineer_core.base_contracts import IntentResult
from angineer_core.memory import Memory
from angineer_core.base_logger import get_logger
from angineer_core.base_utils import is_fatal_exception

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ai_inference.llm_client import LLMClient

from ai_inference.llm_client import get_llm_client
from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD  # noqa: F401  # 模块属性兼容（B3 单阈值）
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
        from angineer_core.dispatch_utils import append_attempted_path

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
                    append_attempted_path(attempted_paths, path, "success", route_debug["reason"], stage_timings[path])
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
                        append_attempted_path(attempted_paths, path, "success", route_debug["reason"], stage_timings[path])
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
                    append_attempted_path(attempted_paths, path, sql_status, sql_reason, stage_timings[path])
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
                    append_attempted_path(attempted_paths, path, sop_status, sop_reason, stage_timings[path])
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
                    append_attempted_path(attempted_paths, path, status, reason, stage_timings[path])
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
                append_attempted_path(
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
        """????????P6d ?? dispatch_utils??"""
        from angineer_core.dispatch_utils import normalize_doc_alias

        return normalize_doc_alias(value)

    @classmethod
    def _resolve_requested_doc_ids(cls, doc_nodes: List[Any], requested_doc_ids: List[str]) -> set[str]:
        """???????????? doc_id?P6d ?? dispatch_utils??"""
        from angineer_core.dispatch_utils import resolve_requested_doc_ids

        return resolve_requested_doc_ids(doc_nodes, requested_doc_ids)

    @staticmethod
    def _summarize_sql_attempt(
        *,
        citations: List[Dict[str, Any]],
        retrieved_items: List[Dict[str, Any]],
        sql_payload: Optional[Dict[str, Any]],
        fallback_used: bool,
    ) -> Tuple[str, str]:
        """SQL ???????P6d ?? dispatch_utils??"""
        from angineer_core.dispatch_utils import summarize_sql_attempt

        return summarize_sql_attempt(
            citations=citations,
            retrieved_items=retrieved_items,
            sql_payload=sql_payload,
            fallback_used=fallback_used,
        )

    @staticmethod
    def _summarize_sop_attempt(
        *,
        answer: str,
        fallback_used: bool,
        route_debug: Dict[str, Any],
        flow_debug: Dict[str, Any],
    ) -> Tuple[str, str]:
        """SOP ???????P6d ?? dispatch_utils??"""
        from angineer_core.dispatch_utils import summarize_sop_attempt

        return summarize_sop_attempt(
            answer=answer,
            fallback_used=fallback_used,
            route_debug=route_debug,
            flow_debug=flow_debug,
        )

    @staticmethod
    def _finalize_attempts(
        *,
        intent_result: IntentResult,
        attempted_paths: List[Dict[str, Any]],
    ) -> Tuple[Optional[str], str]:
        """??????????P6d ?? dispatch_utils??"""
        from angineer_core.dispatch_utils import finalize_attempts

        return finalize_attempts(intent_result=intent_result, attempted_paths=attempted_paths)


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
        """L0 ????????P6d ?? qa_pipeline??"""
        from angineer_core.qa_pipeline import dispatch_chat

        return dispatch_chat(query, config_name=self.config_name)

    def _dispatch_sql(
        self,
        query: str,
        doc_nodes: list,
        library_id: str,
        doc_ids: List[str],
    ) -> Tuple[str, list, list, Optional[Dict], bool]:
        """L2 ???SQL ??????P6d ?? sql_pipeline??"""
        from angineer_core.sql_pipeline import dispatch_sql

        return dispatch_sql(self, query, doc_nodes, library_id, doc_ids)

    def _dispatch_sop(
        self,
        query: str,
        sop_loader,
        intent_result: IntentResult,
        step_callback=None,
    ) -> Tuple[str, list, str, bool, Optional[float], list, Dict[str, Any], Dict[str, Any]]:
        """L3 ???SOP ??????P6d ?? sop_dispatch??"""
        from angineer_core.sop_dispatch import dispatch_sop

        return dispatch_sop(self, query, sop_loader, intent_result, step_callback=step_callback)

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
        """L1/L2??/L3??????????P6d ?? semantic_dispatch??

        enforce_evidence=True ?????????????????? LLM ?????
        """
        from angineer_core.semantic_dispatch import dispatch_semantic

        return dispatch_semantic(
            self,
            query,
            doc_nodes,
            library_id,
            doc_ids,
            intent_result,
            inline_citations=inline_citations,
            filters=filters,
            enforce_evidence=enforce_evidence,
        )

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
        """???????????P6d ?? qa_pipeline??"""
        from angineer_core.qa_pipeline import parse_gap_analysis

        return parse_gap_analysis(answer)

    @staticmethod
    def _extract_answer_from_sop_context(
        context: Dict[str, Any], query: str, config_name: str = None,
    ) -> str:
        """? SOP ??????????P6d ?? qa_pipeline??"""
        from angineer_core.qa_pipeline import extract_answer_from_sop_context

        return extract_answer_from_sop_context(context, query, config_name)

    @staticmethod
    def _compose_sop_answer(query: str, calc_vars: Dict[str, Any], config_name: str = None) -> str:
        """?? SOP ?????????????P6d ?? qa_pipeline??"""
        from angineer_core.qa_pipeline import compose_sop_answer

        return compose_sop_answer(query, calc_vars, config_name)

    @staticmethod
    def _build_citations_from_retrieved(fused, doc_nodes) -> list:
        """从检索结果构建 citations 数组。"""
        from angineer_core.retrieval_pipeline import build_citations_from_retrieved

        return build_citations_from_retrieved(fused, doc_nodes)


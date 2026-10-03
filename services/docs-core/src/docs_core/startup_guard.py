"""启动时向量库健康守卫。

职责：
1. 调一次 embedding 端点，验证返回维度是否匹配向量库期望维度
2. 检查向量库行数完整性（空行、维度为 0 的脏数据）
3. 结构化报告供 startup hook 和 retrieve_service 消费

设计约束：
- 非阻塞：失败只 log + 返回报告，不抛异常（restart: unless-stopped 下会死循环）
- 惰性导入：避免在模块级触发 vector store 初始化拖慢启动
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class VectorGuardReport:
    """启动守卫检查结果。"""
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)
        logger.error("启动守卫: %s", msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        logger.warning("启动守卫: %s", msg)


def _probe_embedding_dimension() -> tuple[int, Optional[str]]:
    """调一次 embedding 端点，返回 (实际维度, 错误信息)。"""
    try:
        from docs_core.step06_vectors.embedding_provider import default_embedding_provider
        result = default_embedding_provider.embed_texts(["健康检查探针"])
        dim = len(result[0]) if result else 0
        if dim == 0:
            return 0, "embedding 返回空向量"
        return dim, None
    except Exception as exc:
        return 0, f"embedding 端点调用失败: {exc}"


def _check_vector_store() -> Dict[str, Any]:
    """读取向量库全局统计。"""
    try:
        from docs_core.step06_vectors import get_vectorstore_provider_name
        provider_name = get_vectorstore_provider_name()
        if provider_name == "sqlite":
            from docs_core.step06_vectors.sqlite_vector_store import SQLiteVectorStore
            store = SQLiteVectorStore()
            return store.get_global_stats()
        elif provider_name == "qdrant":
            from docs_core import library_registry
            from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore
            store = QdrantVectorStore()
            stats = store.get_global_stats()
            # 库组拆分后各组 collection 独立成桶：逐个体检并汇总，单桶不可访问即报错
            collections = sorted({
                record.collection for record in library_registry.list_libraries()
            } - {store._collection})
            per_collection: Dict[str, Any] = {}
            for name in collections:
                sub = store.get_global_stats(name)
                per_collection[name] = sub
                stats["total_rows"] += sub.get("total_rows", 0)
            if per_collection:
                stats["collections"] = per_collection
            return stats
        else:
            from docs_core.step06_vectors.chroma_vector_store import ChromaVectorStore
            store = ChromaVectorStore()
            count = store.collection.count()
            return {"total_rows": count, "zero_dimension_rows": 0, "expected_dimension": 0, "dimension_distribution": {}}
    except Exception as exc:
        return {"error": str(exc), "total_rows": 0, "zero_dimension_rows": 0, "expected_dimension": 0, "dimension_distribution": {}}


def run_vector_startup_guard() -> VectorGuardReport:
    """执行启动时向量库健康检查，返回结构化报告。"""
    report = VectorGuardReport()
    started = time.perf_counter()

    # 1. 检查向量库状态
    store_stats = _check_vector_store()
    report.details["vector_store"] = store_stats

    if "error" in store_stats:
        # 必须升 error：get_retrieve_warning 只在 ok=False 时给用户可见文本，
        # warning 会让"连不上库"在检索侧与 /health 都装没事、与真空库无法区分
        report.add_error(f"向量库不可访问: {store_stats['error']}")
        _save_report(report)
        return report

    total = store_stats.get("total_rows", 0)
    zero_dim = store_stats.get("zero_dimension_rows", 0)
    expected_dim = store_stats.get("expected_dimension", 0)
    dim_dist = store_stats.get("dimension_distribution", {})

    report.details["total_rows"] = total
    report.details["expected_dimension"] = expected_dim

    if total == 0:
        report.add_warning("向量库为空，跳过维度校验")
        _save_report(report)
        return report

    if zero_dim > 0:
        report.add_warning(f"发现 {zero_dim} 条维度为 0 的脏数据行")

    if len(dim_dist) > 1:
        report.add_warning(f"向量库存在异构维度: {dim_dist}")

    # 2. 探针调用 embedding 端点
    probe_dim, probe_error = _probe_embedding_dimension()
    report.details["probe_dimension"] = probe_dim

    if probe_error:
        report.add_error(probe_error)
    elif expected_dim > 0 and probe_dim != expected_dim:
        report.add_error(
            f"embedding 维度不匹配: 端点返回 {probe_dim}，向量库期望 {expected_dim}。"
            f"请检查 EMBEDDING_CONFIGS 中的模型是否与建库时一致"
        )
    elif expected_dim == 0:
        report.add_warning("向量库期望维度为 0（可能未初始化），跳过维度比对")

    elapsed = time.perf_counter() - started
    report.details["elapsed_seconds"] = round(elapsed, 2)
    logger.info(
        "启动向量库守卫完成: ok=%s, rows=%d, expected_dim=%d, probe_dim=%d, %.2fs",
        report.ok, total, expected_dim, probe_dim, elapsed,
    )
    _save_report(report)
    return report


def report_to_dict(report: VectorGuardReport) -> Dict[str, Any]:
    """将报告转为可序列化的 dict，供 /health 端点使用。"""
    return {
        "ok": report.ok,
        "errors": report.errors,
        "warnings": report.warnings,
        "details": report.details,
    }


# ---- 全局单例：启动后存储报告，供 retrieve_service 注入 warning ----
_last_report: Optional[VectorGuardReport] = None
# 坏报告重探间隔：向量库恢复后横幅自愈，启动时序抖动造成的一次性故障
# 不再挂到进程重启为止（2026-10-01 qdrant 先于后端重启、横幅驻留实踩）
_RECHECK_INTERVAL_SECONDS = 60.0
_last_check_monotonic: float = 0.0
_recheck_lock = threading.Lock()


def _save_report(report: VectorGuardReport) -> None:
    global _last_report, _last_check_monotonic
    _last_report = report
    _last_check_monotonic = time.monotonic()


def get_last_report() -> Optional[VectorGuardReport]:
    """返回最近一次启动守卫报告（retrieve_service 消费）。"""
    return _last_report


def _maybe_schedule_recheck() -> Optional[threading.Thread]:
    """坏报告超过重探间隔时，起后台线程重跑守卫；返回重探线程（节流命中返回 None）。

    先占坑再起线程：并发查询同时读到过期坏报告时只起一条重探，不会打成一窝探测。
    返回线程便于调用方（测试）等待重探落地。
    """
    global _last_check_monotonic
    if time.monotonic() - _last_check_monotonic < _RECHECK_INTERVAL_SECONDS:
        return None
    with _recheck_lock:
        if time.monotonic() - _last_check_monotonic < _RECHECK_INTERVAL_SECONDS:
            return None
        _last_check_monotonic = time.monotonic()
        thread = threading.Thread(
            target=run_vector_startup_guard, daemon=True, name="vector-guard-recheck"
        )
        thread.start()
        return thread


def get_retrieve_warning() -> Optional[str]:
    """如果向量库不健康，返回用户可见的 warning 文本；否则返回 None。

    报告仅在启动时生成一次；坏报告超过重探间隔会触发一次后台重探，重探发现
    已恢复则下一轮查询横幅自然消失（本次调用仍返回旧报告，不在请求路径里等探测）。
    """
    report = _last_report
    if report is None or report.ok:
        return None
    _maybe_schedule_recheck()
    parts = report.errors or report.warnings
    return f"向量库健康检查异常，检索结果可能不完整: {'; '.join(parts)}"

"""文档解析阶段化管线：阶段注册表 + 依赖排序 + 状态派生 + 运行器。

设计约定：
- 每个阶段是 {key, title, kind(hard/soft), depends_on, run(ctx)} 的注册项；
- hard 阶段失败 → 终止后续阶段；soft 阶段失败 → 仅标记自身 failed，继续后续；
- 阶段状态通过 meta_store.upsert_parse_stage 持久化（doc_parse_stages 表）。
"""
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

STAGE_KIND_HARD = "hard"
STAGE_KIND_SOFT = "soft"


@dataclass
class StageContext:
    """跨阶段共享的上下文。"""
    task_id: str
    library_id: str
    doc_id: str
    file_path: str
    parse_options: Dict[str, Any] = field(default_factory=dict)
    source_path: Optional[str] = None
    ext: str = ".pdf"
    temp_output_dir: Optional[str] = None
    popo_ran: bool = False


@dataclass
class StageDef:
    key: str
    title: str
    kind: str
    depends_on: List[str]
    run: Callable[["StageContext"], str]


# ---- 阶段执行函数（骨架，Task 3 填充）----

def _run_source_prep(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_convert(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_raw_parse(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_popo(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_structure(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_fts(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_vectors(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_graph(ctx: StageContext) -> str:
    raise NotImplementedError

def _run_sop(ctx: StageContext) -> str:
    raise NotImplementedError


STAGE_REGISTRY: Dict[str, StageDef] = {s.key: s for s in [
    StageDef("source_prep", "源文件准备", STAGE_KIND_HARD, [], _run_source_prep),
    StageDef("convert", "格式转换", STAGE_KIND_HARD, ["source_prep"], _run_convert),
    StageDef("raw_parse", "MinerU 解析", STAGE_KIND_HARD, ["convert"], _run_raw_parse),
    StageDef("popo", "PoPo 语义增强", STAGE_KIND_SOFT, ["raw_parse"], _run_popo),
    StageDef("structure", "结构化入库", STAGE_KIND_HARD, ["raw_parse"], _run_structure),
    StageDef("fts", "全文索引", STAGE_KIND_HARD, ["structure"], _run_fts),
    StageDef("vectors", "向量索引", STAGE_KIND_SOFT, ["structure"], _run_vectors),
    StageDef("graph", "知识图谱", STAGE_KIND_SOFT, ["structure"], _run_graph),
    StageDef("sop", "SOP 生成", STAGE_KIND_SOFT, ["graph"], _run_sop),
]}

_PIPELINE_ORDER = [
    "source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph", "sop",
]


def resolve_stage_order(stages) -> List[str]:
    if isinstance(stages, str):
        if stages != "all":
            raise ValueError(f"未知的 stages 参数: {stages}")
        return list(_PIPELINE_ORDER)
    unknown = [s for s in stages if s not in STAGE_REGISTRY]
    if unknown:
        raise ValueError(f"未知阶段: {unknown}")
    selected = set(stages)
    return [key for key in _PIPELINE_ORDER if key in selected]


def derive_overall_status(stage_status: Dict[str, str]) -> str:
    values = list(stage_status.values())
    if any(v == "running" for v in values):
        return "processing"
    if not values:
        return "queued"
    hard_failed = any(
        stage_status.get(key) == "failed"
        for key, stage in STAGE_REGISTRY.items()
        if stage.kind == STAGE_KIND_HARD
    )
    if hard_failed:
        return "failed"
    if any(v == "failed" for v in values):
        return "partial"
    if all(v in ("completed", "skipped") for v in values):
        return "completed"
    return "processing"


def run_pipeline(
    ctx: StageContext,
    stages,
    *,
    meta_store,
    on_stage_update: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    raise_if_cancelled: Optional[Callable[[], None]] = None,
) -> Dict[str, str]:
    order = resolve_stage_order(stages)
    results: Dict[str, str] = {}
    for key in order:
        stage = STAGE_REGISTRY[key]
        failed_deps = [d for d in stage.depends_on if results.get(d) == "failed"]
        if failed_deps:
            results[key] = "skipped"
            meta_store.upsert_parse_stage(ctx.doc_id, key, status="skipped",
                                          message=f"依赖阶段失败: {failed_deps}")
            continue
        if raise_if_cancelled:
            raise_if_cancelled()
        started = datetime.now().isoformat()
        meta_store.upsert_parse_stage(ctx.doc_id, key, status="running", started_at=started)
        t0 = time.time()
        try:
            message = stage.run(ctx) or "完成"
            if str(message).startswith("__skipped__"):
                results[key] = "skipped"
                meta_store.upsert_parse_stage(
                    ctx.doc_id, key, status="skipped",
                    message=str(message)[len("__skipped__"):],
                    started_at=started,
                    finished_at=datetime.now().isoformat(),
                )
                continue
            results[key] = "completed"
            meta_store.upsert_parse_stage(
                ctx.doc_id, key, status="completed",
                message=f"{message}（{round(time.time() - t0, 1)}s）",
                started_at=started, finished_at=datetime.now().isoformat(),
            )
        except Exception as exc:
            results[key] = "failed"
            error_message = f"{type(exc).__name__}: {exc}"
            meta_store.upsert_parse_stage(
                ctx.doc_id, key, status="failed",
                error=error_message + "\n" + traceback.format_exc(limit=3),
                started_at=started, finished_at=datetime.now().isoformat(),
            )
            if stage.kind == STAGE_KIND_HARD:
                for rest in order[order.index(key) + 1:]:
                    results[rest] = "skipped"
                    meta_store.upsert_parse_stage(ctx.doc_id, rest, status="skipped",
                                                  message=f"前置硬阶段 {key} 失败")
                break
        if on_stage_update:
            on_stage_update(key, dict(results))
    return results

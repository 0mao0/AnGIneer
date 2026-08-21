"""PoPo 4B 推理闸门契约测试：排队状态、瞬时失败重试、重试耗尽回滚。"""

import subprocess
import threading
import time

import docs_core.parse_pipeline as pp
from docs_core.parse_pipeline import _FifoGpuGate, StageContext


class _FakeMetaStore:
    def __init__(self) -> None:
        self.stage_upserts: list[dict] = []

    def insert_parse_stage_step(self, doc_id: str, stage: str, step: str, status: str, detail: str) -> None:
        pass

    def upsert_parse_stage(self, doc_id: str, stage: str, *, status: str, message: str = "", **kwargs) -> None:
        self.stage_upserts.append({"stage": stage, "status": status, "message": message, **kwargs})


class _FakeKS:
    def __init__(self) -> None:
        self.task_updates: list[dict] = []

    def update_parse_task(self, task_id: str, **kwargs) -> None:
        self.task_updates.append(kwargs)


class _FakePopoPipeline:
    def __init__(self, fail_times: int = 0, exc: Exception | None = None) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.exc = exc

    def run_full_pipeline(self, **kwargs) -> dict:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return {}


def _make_ctx(tmp_path, meta, task_id: str = "t1", arrival_seq: int = 1) -> StageContext:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    ctx = StageContext(
        task_id=task_id, library_id="lib", doc_id="doc",
        file_path=str(pdf), meta_store=meta, stage_key="popo",
        stage_started_at="2026-08-20T00:00:00",
        arrival_seq=arrival_seq,
        source_path=str(pdf),
    )
    return ctx


def _patch_env(monkeypatch, tmp_path, pipeline: _FakePopoPipeline) -> None:
    import docs_core.docs_file_io as dfio
    import docs_core.paths as paths
    from docs_core.step03_mineru_parse import popo_enhance

    monkeypatch.setattr(paths, "get_mineru_raw_dir", lambda library_id, doc_id, base_dir=None: tmp_path)
    monkeypatch.setattr(paths, "get_popo_dir", lambda library_id, doc_id, base_dir=None: tmp_path / "popo")
    monkeypatch.setattr(paths, "get_source_dir", lambda library_id, doc_id, base_dir=None: tmp_path)
    monkeypatch.setattr(popo_enhance, "get_popo_pipeline", lambda: pipeline)
    monkeypatch.setattr(
        dfio.file_storage, "read_popo_enriched_blocks",
        lambda library_id, doc_id: [{"id": 1}],
    )
    monkeypatch.setattr(pp, "_POPO_RETRY_BACKOFF_SECONDS", 0)


def test_popo_marks_queued_then_running_when_gate_busy(monkeypatch, tmp_path) -> None:
    gate = _FifoGpuGate(max_concurrency=1)
    gate.acquire(1)  # 占用唯一槽位，模拟前序任务在跑 PoPo
    meta = _FakeMetaStore()
    ks = _FakeKS()
    monkeypatch.setattr(pp, "get_docs_service", lambda: ks)
    monkeypatch.setattr(pp, "_POPO_GATE", gate)
    pipeline = _FakePopoPipeline()
    _patch_env(monkeypatch, tmp_path, pipeline)

    ctx = _make_ctx(tmp_path, meta, arrival_seq=2)
    sync_calls: list[str] = []
    ctx.sync_record = lambda task_id, doc_id, status: sync_calls.append(status)

    result: dict = {}
    t = threading.Thread(
        target=lambda: result.setdefault("msg", pp._run_popo(ctx)),
        daemon=True,
    )
    t.start()
    try:
        deadline = time.time() + 3
        while time.time() < deadline and not (
            meta.stage_upserts and meta.stage_upserts[-1]["status"] == "queued"
        ):
            time.sleep(0.02)
        assert meta.stage_upserts and meta.stage_upserts[-1]["status"] == "queued"
        assert meta.stage_upserts[-1]["message"] == "等待 PoPo 4B 推理资源"
        assert any(u.get("stage") == "queued" for u in ks.task_updates)
        assert sync_calls and sync_calls[0] == "queued"
    finally:
        gate.release()
    t.join(timeout=3)

    assert result["msg"].startswith("PoPo 强化完成")
    statuses = [u["status"] for u in meta.stage_upserts]
    assert "queued" in statuses
    assert statuses[-1] == "running"
    task_stages = [u["stage"] for u in ks.task_updates if "stage" in u]
    assert task_stages[0] == "queued"
    assert task_stages[-1] == "popo"
    assert sync_calls[-1] == "processing"
    assert pipeline.calls == 1


def test_popo_skips_queued_when_gate_free(monkeypatch, tmp_path) -> None:
    gate = _FifoGpuGate(max_concurrency=1)
    meta = _FakeMetaStore()
    ks = _FakeKS()
    monkeypatch.setattr(pp, "get_docs_service", lambda: ks)
    monkeypatch.setattr(pp, "_POPO_GATE", gate)
    pipeline = _FakePopoPipeline()
    _patch_env(monkeypatch, tmp_path, pipeline)

    ctx = _make_ctx(tmp_path, meta)
    msg = pp._run_popo(ctx)
    assert msg.startswith("PoPo 强化完成")
    statuses = [u["status"] for u in meta.stage_upserts]
    assert "queued" not in statuses
    assert statuses[-1] == "running"
    task_stages = [u["stage"] for u in ks.task_updates if "stage" in u]
    assert task_stages[-1] == "popo"
    assert pipeline.calls == 1


def test_popo_retries_transient_failure_once(monkeypatch, tmp_path) -> None:
    gate = _FifoGpuGate(max_concurrency=1)
    meta = _FakeMetaStore()
    ks = _FakeKS()
    monkeypatch.setattr(pp, "get_docs_service", lambda: ks)
    monkeypatch.setattr(pp, "_POPO_GATE", gate)
    monkeypatch.setattr(pp, "_POPO_INFERENCE_RETRIES", 1)
    transient = subprocess.CalledProcessError(
        1, ["python", "run_inference.py"], output=b"Maximum number of retries exceeded"
    )
    pipeline = _FakePopoPipeline(fail_times=1, exc=transient)
    _patch_env(monkeypatch, tmp_path, pipeline)

    ctx = _make_ctx(tmp_path, meta)
    msg = pp._run_popo(ctx)
    assert msg.startswith("PoPo 强化完成")
    assert pipeline.calls == 2
    assert ctx.fallback_target is None


def test_popo_retry_exhausted_rolls_back_and_falls_back(monkeypatch, tmp_path) -> None:
    gate = _FifoGpuGate(max_concurrency=1)
    meta = _FakeMetaStore()
    ks = _FakeKS()
    monkeypatch.setattr(pp, "get_docs_service", lambda: ks)
    monkeypatch.setattr(pp, "_POPO_GATE", gate)
    monkeypatch.setattr(pp, "_POPO_INFERENCE_RETRIES", 1)
    rollback_calls: list[str] = []
    monkeypatch.setattr(pp, "_rollback_popo_products", lambda ctx: rollback_calls.append(ctx.doc_id))
    transient = subprocess.CalledProcessError(
        1, ["python", "run_inference.py"], output=b"Maximum number of retries exceeded"
    )
    pipeline = _FakePopoPipeline(fail_times=99, exc=transient)
    _patch_env(monkeypatch, tmp_path, pipeline)

    ctx = _make_ctx(tmp_path, meta)
    with __import__("pytest").raises(RuntimeError, match="PoPo 子进程失败"):
        pp._run_popo(ctx)
    assert pipeline.calls == 2
    assert rollback_calls == ["doc"]
    assert ctx.fallback_target == "solo"


def test_popo_permanent_failure_not_retried(monkeypatch, tmp_path) -> None:
    gate = _FifoGpuGate(max_concurrency=1)
    meta = _FakeMetaStore()
    ks = _FakeKS()
    monkeypatch.setattr(pp, "get_docs_service", lambda: ks)
    monkeypatch.setattr(pp, "_POPO_GATE", gate)
    monkeypatch.setattr(pp, "_POPO_INFERENCE_RETRIES", 1)
    rollback_calls: list[str] = []
    monkeypatch.setattr(pp, "_rollback_popo_products", lambda ctx: rollback_calls.append(ctx.doc_id))
    pipeline = _FakePopoPipeline(fail_times=99, exc=RuntimeError("mineru_raw_dir missing"))
    _patch_env(monkeypatch, tmp_path, pipeline)

    ctx = _make_ctx(tmp_path, meta)
    with __import__("pytest").raises(RuntimeError, match="mineru_raw_dir missing"):
        pp._run_popo(ctx)
    assert pipeline.calls == 1
    assert rollback_calls == ["doc"]
    assert ctx.fallback_target == "solo"


def test_run_pipeline_completed_stage_preserves_work_started_at(monkeypatch, tmp_path) -> None:
    """排队阶段完成后 started_at 保留拿到槽位后的时间（总耗时=各阶段累加，不含排队）。"""
    import re
    from datetime import datetime

    from docs_core.parse_pipeline import STAGE_KIND_HARD, StageDef, run_pipeline
    from docs_core.step05_sqlite_fts.store.blocks_sql_store import KnowledgeMetaStore

    class _NoopKS:
        def update_parse_task(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(pp, "get_docs_service", lambda: _NoopKS())

    def _fake_run(ctx):
        pp._mark_stage_queued(
            ctx, "MinerU GPU 排队",
            "等待 MinerU GPU 资源（前序任务完成后自动开始）",
            "等待 MinerU GPU 资源",
        )
        time.sleep(0.4)  # 模拟排队等待
        pp._mark_stage_running(ctx, "raw_parse", "MinerU 解析中")
        return "MinerU解析完成"

    monkeypatch.setitem(
        pp.STAGE_REGISTRY, "raw_parse",
        StageDef("raw_parse", "MinerU解析", STAGE_KIND_HARD, [], _fake_run, None, step="3.1"),
    )

    store = KnowledgeMetaStore(db_path=tmp_path / "meta.sqlite", schema_version="1.0.0")
    ctx = StageContext(
        task_id="t1", library_id="lib", doc_id="doc",
        file_path="x.pdf", meta_store=store,
    )
    run_pipeline(ctx, ["raw_parse"], meta_store=store)

    rows = store.list_parse_stages("doc")
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "completed"
    # 完成记录保留拿到槽位后的开工时间，而不是阶段进入（含排队）的时间
    assert row["started_at"] == ctx.stage_work_started_at
    assert row["started_at"] is not None
    assert row["started_at"] > ctx.stage_started_at

    work = datetime.fromisoformat(row["started_at"])
    finished = datetime.fromisoformat(row["finished_at"])
    entered = datetime.fromisoformat(ctx.stage_started_at)
    # 实际执行耗时 ≈ 0（开工即完成）；阶段进入到结束明显更大（含 0.4s 排队）
    assert 0 <= (finished - work).total_seconds() < 0.2
    assert (finished - entered).total_seconds() >= 0.3

    match = re.search(r"耗时([\d.]+)秒", row["message"])
    assert match is not None
    assert float(match.group(1)) < 0.2

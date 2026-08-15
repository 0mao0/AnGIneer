"""MinerU GPU 闸门契约测试：并发上限、取消不泄漏令牌、非法并发数钳制。"""

import threading
import time

import docs_core.parse_pipeline as pp
from docs_core.parse_pipeline import _FifoGpuGate, StageContext


def test_gate_limits_concurrency_to_one() -> None:
    gate = _FifoGpuGate(max_concurrency=1)
    peak = 0
    active = 0
    lock = threading.Lock()
    done: list[bool] = []

    def worker(seq: int) -> None:
        nonlocal peak, active
        gate.acquire(seq)
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        gate.release()
        done.append(True)

    threads = [threading.Thread(target=worker, args=(seq,)) for seq in range(1, 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1
    assert len(done) == 4


def test_gate_configured_concurrency_allows_overlap() -> None:
    gate = _FifoGpuGate(max_concurrency=2)
    entered = threading.Barrier(2)
    seen: list[str] = []
    lock = threading.Lock()

    def worker(seq: int) -> None:
        gate.acquire(seq)
        entered.wait(timeout=2)  # 两个 worker 同时持令牌才会通过
        with lock:
            seen.append("in")
        time.sleep(0.05)
        gate.release()

    threads = [threading.Thread(target=worker, args=(seq,)) for seq in range(1, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == 2


def test_gate_cancel_does_not_consume_token() -> None:
    gate = _FifoGpuGate(max_concurrency=1)
    gate.acquire(1)  # 主线程占用唯一令牌
    polls = {"n": 0}
    cancelled: list[str] = []

    def cancel_check() -> None:
        polls["n"] += 1
        if polls["n"] >= 2:
            raise RuntimeError("cancel requested")

    def waiter() -> None:
        try:
            gate.acquire(2, cancel_check, poll_interval=0.01)
        except RuntimeError as exc:
            cancelled.append(str(exc))

    t = threading.Thread(target=waiter)
    t.start()
    t.join(timeout=2)
    assert len(cancelled) == 1
    # 取消者未消费令牌：主线程释放后，新获取立即可成功
    gate.release()
    gate.acquire(3)
    gate.release()


def test_gate_clamps_invalid_concurrency() -> None:
    gate = _FifoGpuGate(max_concurrency=0)
    assert gate._max_concurrency == 1
    gate2 = _FifoGpuGate(max_concurrency=-3)
    assert gate2._max_concurrency == 1


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


class _FakeParser:
    def __init__(self) -> None:
        self._abort_event = threading.Event()

    def parse_to_raw_artifacts(self, **kwargs) -> dict:
        return {"success": True, "persisted": {"output_summary": "out", "has_images": False}}


def test_raw_parse_marks_queued_then_running_when_gate_busy(monkeypatch) -> None:
    """排队等待时阶段状态为 queued（不计时）；拿到槽位后重置为 running。"""
    gate = _FifoGpuGate(max_concurrency=1)
    gate.acquire(1)  # 占用唯一令牌，模拟前序任务在跑

    meta = _FakeMetaStore()
    ks = _FakeKS()
    monkeypatch.setattr(pp, "get_docs_service", lambda: ks)
    monkeypatch.setattr(pp, "_MINERU_GPU_GATE", gate)

    ctx = StageContext(
        task_id="t1", library_id="lib", doc_id="doc",
        file_path="x.pdf", task_parser=_FakeParser(),
        meta_store=meta, stage_key="raw_parse",
        stage_started_at="2026-08-05T00:00:00",
        arrival_seq=2,
    )
    sync_calls: list[str] = []
    ctx.sync_record = lambda task_id, doc_id, status: sync_calls.append(status)

    result: dict = {}
    t = threading.Thread(
        target=lambda: result.setdefault("msg", pp._run_raw_parse(ctx)),
        daemon=True,
    )
    t.start()
    try:
        deadline = time.time() + 3
        while time.time() < deadline and not (
            meta.stage_upserts and meta.stage_upserts[-1]["status"] == "queued"
        ):
            time.sleep(0.02)
        # 等待期间：阶段处于 queued，任务 stage=queued，记录状态已同步为 queued
        assert meta.stage_upserts and meta.stage_upserts[-1]["status"] == "queued"
        assert meta.stage_upserts[-1]["message"] == "等待 MinerU GPU 资源"
        assert any(u.get("stage") == "queued" for u in ks.task_updates)
        assert sync_calls and sync_calls[0] == "queued"
    finally:
        # 无论断言结果都释放令牌，避免工作线程堵死 pytest 退出
        gate.release()
    t.join(timeout=3)
    assert result["msg"].startswith("MinerU解析完成")
    statuses = [u["status"] for u in meta.stage_upserts]
    assert "queued" in statuses
    assert statuses[-1] == "running"
    task_stages = [u["stage"] for u in ks.task_updates if "stage" in u]
    assert task_stages[0] == "queued"
    assert task_stages[-1] == "raw_parse"
    assert sync_calls[-1] == "processing"


def test_raw_parse_skips_queued_when_gate_free(monkeypatch) -> None:
    """GPU 空闲时直接进入 running，不经过 queued，也不重置计时起点。"""
    gate = _FifoGpuGate(max_concurrency=1)
    meta = _FakeMetaStore()
    ks = _FakeKS()
    monkeypatch.setattr(pp, "get_docs_service", lambda: ks)
    monkeypatch.setattr(pp, "_MINERU_GPU_GATE", gate)

    ctx = StageContext(
        task_id="t2", library_id="lib", doc_id="doc",
        file_path="x.pdf", task_parser=_FakeParser(),
        meta_store=meta, stage_key="raw_parse",
        stage_started_at="2026-08-05T00:00:00",
    )
    msg = pp._run_raw_parse(ctx)
    assert msg.startswith("MinerU解析完成")
    statuses = [u["status"] for u in meta.stage_upserts]
    assert "queued" not in statuses
    assert statuses[-1] == "running"
    assert not ks.task_updates or ks.task_updates[-1]["stage"] == "raw_parse"

"""取消收敛与启动行级自愈（2026-10-04 业主报障「取消失败: 任务不存在」）。

根因：列表行状态存 sqlite，任务存进程内存；重启后内存清空、占位行（task_id=
pending-<doc_id>）本来就无任务，取消接口查内存查不到即 404，僵尸行永远点不动。
本测试锁四件事：
- 占位行取消 = 幂等成功且不改写状态（未开跑的书不能被打成已取消）；
- queued/processing 行无任务 = 收敛为 cancelled 并同步节点（node failed + stage cancelled）；
- 行不存在仍 404；行已终态幂等成功；
- 启动行级兜底把遗留 queued 行标 failed、不碰 pending 占位行、跳过活线程行。
"""
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import docs_routes  # noqa: E402


class _FakeKs:
    def __init__(self, nodes=None, tasks=None):
        self.nodes = nodes or {}
        self.tasks = tasks or {}
        self.node_updates = []

    def get_parse_task(self, task_id):
        return self.tasks.get(task_id)

    def get_node(self, doc_id):
        return self.nodes.get(doc_id)

    def update_node(self, doc_id, **kwargs):
        self.node_updates.append({"doc_id": doc_id, **kwargs})


def _patch(monkeypatch, ks, records):
    """把取消接口依赖的三件套换成内存替身；返回被改写的记录字典。"""
    updates = []

    def fake_list_records(limit=5000):
        return list(records.values())

    def fake_update_record_status(task_id, status, error=None):
        rec = records.get(task_id)
        if rec is not None:
            rec["status"] = status
            rec["error"] = error
            updates.append((task_id, status))
        return rec is not None

    monkeypatch.setattr(docs_routes, "get_docs_service", lambda: ks)
    monkeypatch.setattr(docs_routes, "list_records", fake_list_records)
    monkeypatch.setattr(docs_routes, "update_record_status", fake_update_record_status)
    return updates


def test_pending_placeholder_cancel_is_noop_success(monkeypatch):
    ks = _FakeKs()
    records = {"pending-doc1": {"task_id": "pending-doc1", "doc_id": "doc1", "status": "pending"}}
    updates = _patch(monkeypatch, ks, records)
    resp = docs_routes.cancel_parse_task("pending-doc1")
    assert resp["status"] == "success"
    assert "尚未开始" in resp["message"]
    assert updates == []                       # 占位行不改写
    assert records["pending-doc1"]["status"] == "pending"


def test_queued_row_without_task_converges_to_cancelled(monkeypatch):
    ks = _FakeKs(nodes={"doc2": types.SimpleNamespace(status="processing")})
    records = {"t2": {"task_id": "t2", "doc_id": "doc2", "status": "queued"}}
    updates = _patch(monkeypatch, ks, records)
    resp = docs_routes.cancel_parse_task("t2")
    assert resp["status"] == "success"
    assert updates == [("t2", "cancelled")]
    assert len(ks.node_updates) == 1
    synced = ks.node_updates[0]
    assert synced["status"] == "failed" and synced["parse_stage"] == "cancelled"


def test_missing_row_still_404(monkeypatch):
    ks = _FakeKs()
    _patch(monkeypatch, ks, {})
    with pytest.raises(HTTPException) as exc:
        docs_routes.cancel_parse_task("nope")
    assert exc.value.status_code == 404


def test_terminal_row_cancel_idempotent_success(monkeypatch):
    ks = _FakeKs()
    records = {"t3": {"task_id": "t3", "doc_id": "doc3", "status": "failed"}}
    updates = _patch(monkeypatch, ks, records)
    resp = docs_routes.cancel_parse_task("t3")
    assert resp["status"] == "success" and updates == []


def _patch_startup(monkeypatch, records):
    """行级兜底的两个函数依赖要分别打桩：
    list_records 是函数内 from-import（调用时才取属性，打 models 侧有效）；
    update_record_status 是 startup_recovery 顶部绑定，必须打它自己的全局名。"""
    import models.parse_record as mpr
    import startup_recovery

    def fake_list_records(limit=10000):
        return list(records.values())

    def fake_update_record_status(task_id, status, error=None):
        records[task_id]["status"] = status
        return True

    monkeypatch.setattr(mpr, "list_records", fake_list_records)
    monkeypatch.setattr(startup_recovery, "update_record_status", fake_update_record_status)
    return startup_recovery


def test_startup_row_sweep_marks_stale_queued_only(monkeypatch):
    class _NoThreads:
        _threads = {}

    records = {
        "tA": {"task_id": "tA", "doc_id": "dA", "status": "queued"},   # 僵尸 → failed
        "pending-dB": {"task_id": "pending-dB", "doc_id": "dB", "status": "pending"},  # 占位不动
        "tC": {"task_id": "tC", "doc_id": "dC", "status": "completed"},  # 终态不动
        "": {"task_id": "", "doc_id": "dE", "status": "processing"},   # 空 task_id 跳过
    }
    ks = _FakeKs(nodes={"dA": types.SimpleNamespace(status="processing")})
    mod = _patch_startup(monkeypatch, records)
    count = mod.reconcile_stale_records(_NoThreads(), docs_service=ks)
    assert count == 1
    assert records["tA"]["status"] == "failed"
    assert records["pending-dB"]["status"] == "pending"
    assert records["tC"]["status"] == "completed"
    assert records[""]["status"] == "processing"
    assert ks.node_updates and ks.node_updates[0]["doc_id"] == "dA"


def test_startup_row_sweep_skips_live_thread(monkeypatch):
    class _Alive:
        def is_alive(self):
            return True

    class _Threads:
        _threads = {"tL": _Alive()}

    records = {"tL": {"task_id": "tL", "doc_id": "dL", "status": "processing"}}
    ks = _FakeKs()
    mod = _patch_startup(monkeypatch, records)
    count = mod.reconcile_stale_records(_Threads(), docs_service=ks)
    assert count == 0
    assert records["tL"]["status"] == "processing"

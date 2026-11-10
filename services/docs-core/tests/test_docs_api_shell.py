"""docs_core.docs_api 包内测试：装配/health/静态键鉴权/v1 端点契约。

全桩替身（orchestrator / docs_service 均替换或用 tmp 数据根），不触网、不写真库。
鉴权矩阵与 R2 对齐：静态键命中放行、未配置 401/403、不注入不限制 library_id。
"""
import io
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

KEY_ENV = "DOCS_API_STATIC_KEYS"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """每测试独立 app（重读 env）+ 静态键 demo-key + 台账库指向 tmp。

    注意包 __init__ 把名字 ``app`` 重绑成 FastAPI 实例——要拿装配模块得用
    ``docs_core.docs_api.app`` 完整路径（或直接 from import create_app）。
    """
    monkeypatch.setenv(KEY_ENV, "demo-key")
    monkeypatch.setenv("PARSE_RECORDS_DB_PATH", str(tmp_path / "pr.sqlite"))
    from docs_core.docs_api.app import create_app

    test_client = TestClient(create_app())
    test_client.headers.update({"X-API-Key": "demo-key"})
    return test_client


@pytest.fixture()
def stub_orchestrator(monkeypatch):
    """替换 documents 模块命名空间里的编排器单例（不真正起线程）。"""

    class _StubOrchestrator:
        def __init__(self):
            self._threads = {}
            self.calls = []

        def create_parse_task(self, library_id, doc_id, file_path, parse_options=None):
            self.calls.append({"library_id": library_id, "doc_id": doc_id,
                               "file_path": file_path, "parse_options": parse_options})
            return {"task_id": "task-stub-1", "doc_id": doc_id, "status": "queued",
                    "progress": 0, "stage": "queued"}

        def get_parse_task(self, task_id):
            if task_id != "task-stub-1":
                return None
            return {"task_id": task_id, "status": "processing", "progress": 42,
                    "stage": "structure", "stage_message": "结构化中"}

        def cancel_parse_task(self, task_id):
            return True

    from docs_core.docs_api import documents as documents_module

    stub = _StubOrchestrator()
    monkeypatch.setattr(documents_module, "parse_orchestrator", stub)
    return stub


def _upload(client, filename="spec.pdf", content=b"%PDF-1.4 tiny", stages="structure",
            library_id="bid-docs"):
    return client.post(
        "/api/v1/documents/parse",
        params={"stages": stages, "library_id": library_id},
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )


# ---- 装配与 health（R1）----

def test_package_import_and_app():
    import docs_core.docs_api as docs_api

    assert docs_api.app is not None
    assert callable(docs_api.create_app)


def test_health_contract(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "docs-api"
    assert body["started_at"]
    assert isinstance(body["pid"], int)
    assert body["status"] in ("ok", "degraded")
    if body["status"] == "degraded":
        assert "config_errors" in body


def test_health_degraded_on_bad_config(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "")
    monkeypatch.setenv("MINERU_CONFIGS", "{not-json")
    from docs_core.docs_api import _config
    from docs_core.docs_api.app import create_app

    _config.ensure_env()
    test_client = TestClient(create_app())
    body = test_client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["config_errors"]


# ---- 静态键鉴权（R2）----

def test_auth_missing_header_401(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "demo-key")
    from docs_core.docs_api.app import create_app

    test_client = TestClient(create_app())
    resp = test_client.get("/api/v1/documents/whatever/status")
    assert resp.status_code == 401


def test_auth_invalid_key_403(client):
    bad = TestClient(client.app)
    resp = bad.get("/api/v1/documents/whatever/status", headers={"X-API-Key": "nope"})
    assert resp.status_code == 403


def test_auth_unconfigured_keys_401(monkeypatch):
    """静态键未配置时行为与现状一致：无头 401（有头会 403）。"""
    monkeypatch.delenv(KEY_ENV, raising=False)
    from docs_core.docs_api.app import create_app

    test_client = TestClient(create_app())
    assert test_client.get("/api/v1/documents/whatever/status").status_code == 401
    assert (
        test_client.get("/api/v1/documents/whatever/status", headers={"X-API-Key": "k"}).status_code
        == 403
    )


def test_health_open_without_key(client):
    """/health 不在 /api/v1/* 内，不要求 X-API-Key。"""
    bare = TestClient(client.app)
    assert bare.get("/health").status_code == 200


# ---- parse / status / delete 契约（R3）----

def test_parse_creates_doc_node_record_and_task(client, stub_orchestrator):
    resp = _upload(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_id"] == "task-stub-1"
    assert body["status"] == "queued"
    assert body["is_pdf_input"] is True
    doc_id = body["doc_id"]

    # 编排器收到的 library_id 是请求显式参数（静态键不注入/不限制）
    assert stub_orchestrator.calls[0]["library_id"] == "bid-docs"
    assert stub_orchestrator.calls[0]["parse_options"]["stages"] == ["structure"]

    # 文件层：源文件落 <data_root>/knowledge/libraries/... source/
    assert Path(stub_orchestrator.calls[0]["file_path"]).is_file()

    # 台账：pending 占位行已插（走档位适配层）
    from docs_core.docs_api.records import list_by_doc_id

    records = list_by_doc_id(doc_id)
    assert records and records[0]["status"] == "pending"
    assert records[0]["library_id"] == "bid-docs"
    assert records[0]["uploaded_by"] == "StaticAPI"


def test_parse_rejects_bad_stage(client):
    resp = _upload(client, stages="not-a-stage")
    assert resp.status_code == 400


def test_parse_missing_file_422(client):
    resp = client.post("/api/v1/documents/parse", params={"stages": "structure"})
    assert resp.status_code == 422


def test_status_from_orchestrator(client, stub_orchestrator):
    doc_id = _upload(client).json()["doc_id"]
    # pending 占位改名成真实 task_id（create_parse_task 回填语义）后，状态读编排器
    from docs_core.docs_api.records import update_record_status
    from docs_core.parse_records_store import update_task_id

    update_record_status(f"pending-{doc_id}", "processing")
    update_task_id(f"pending-{doc_id}", "task-stub-1")
    resp = client.get(f"/api/v1/documents/{doc_id}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processing"
    assert body["progress"] == 42
    assert body["stage"] == "structure"


def test_status_unknown_doc_404(client):
    resp = client.get(f"/api/v1/documents/v1-{uuid.uuid4().hex[:12]}/status")
    assert resp.status_code == 404


def test_delete_idempotent_404(client, stub_orchestrator):
    doc_id = _upload(client).json()["doc_id"]
    resp = client.delete(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    # 幂等：已删除后再删 → 404，消费方按成功处理（R3 契约）
    assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 404


def test_delete_unknown_404(client):
    assert client.delete(f"/api/v1/documents/v1-{uuid.uuid4().hex[:12]}").status_code == 404


# ---- resume（R3：进行中 409 / 断点续跑）----

def test_resume_unknown_doc_404(client, stub_orchestrator):
    resp = client.post(f"/api/v1/documents/v1-{uuid.uuid4().hex[:12]}/resume")
    assert resp.status_code == 404


def test_resume_static_key_allowed_and_requeues(client, stub_orchestrator):
    """静态键（id=None）跳过 api_key_id 归属比对；无已完成阶段 → 全量重排。"""
    doc_id = _upload(client).json()["doc_id"]
    # 台账仍是 pending → 把它改成 processing + 真实 task_id（模拟中途重启）
    from docs_core.docs_api.records import update_record_status

    update_record_status(f"pending-{doc_id}", "processing")
    from docs_core.parse_records_store import update_task_id

    update_task_id(f"pending-{doc_id}", "task-stub-1")

    resp = client.post(f"/api/v1/documents/{doc_id}/resume")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_id"] == "task-stub-1"  # stub 固定返回
    assert body["status"] == "queued"
    # record.stages="structure" 且 meta 无任何阶段行 → 剩余全量
    assert stub_orchestrator.calls[-1]["parse_options"]["stages"] == ["structure"]


def test_resume_conflict_409_when_running(client, stub_orchestrator):
    import threading

    doc_id = _upload(client).json()["doc_id"]
    from docs_core.docs_api.records import update_record_status
    from docs_core.parse_records_store import update_task_id

    update_record_status(f"pending-{doc_id}", "processing")
    update_task_id(f"pending-{doc_id}", "task-stub-1")
    # 伪装任务线程仍存活（Event 保持活跃，避免线程秒退后 is_alive()=False 的竞态）
    released = threading.Event()
    live = threading.Thread(target=released.wait, daemon=True)
    live.start()
    stub_orchestrator._threads["task-stub-1"] = live
    try:
        resp = client.post(f"/api/v1/documents/{doc_id}/resume")
        assert resp.status_code == 409
    finally:
        released.set()
        live.join(timeout=1)
        stub_orchestrator._threads.pop("task-stub-1", None)


# ---- 产物（R3：至少含 jsonl/meta/content.md/images.zip 的清单契约）----

def test_artifacts_unknown_doc_404(client):
    resp = client.get(f"/api/v1/documents/v1-{uuid.uuid4().hex[:12]}/artifacts")
    assert resp.status_code == 404


def test_artifacts_whitelist_400(client, stub_orchestrator):
    doc_id = _upload(client).json()["doc_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/artifacts/evil.exe")
    assert resp.status_code == 400


# ---- 启动自愈（A4 前置：重启后未完成文档标记可续跑）----

def test_startup_recovery_marks_stale_record_failed(monkeypatch, stub_orchestrator):
    import sys

    from docs_core.docs_api import startup_recovery
    from docs_core.docs_api.records import insert_record, list_by_doc_id, ParseRecord

    doc_id = f"v1-{uuid.uuid4().hex[:12]}"
    insert_record(ParseRecord(doc_id=doc_id, task_id="task-stale-1", status="processing",
                              library_id="bid-docs"))

    class _StubKS:
        parse_tasks = []

        def get_node(self, node_id):
            return None

    # docs_core.__init__ 把包属性 docs_service 重绑成单例代理——真模块要从 sys.modules 拿
    docs_service_module = sys.modules["docs_core.docs_service"]
    monkeypatch.setattr(docs_service_module, "get_docs_service", lambda: _StubKS())
    count = startup_recovery.reconcile_stale_records(stub_orchestrator)
    assert count == 1
    rec = list_by_doc_id(doc_id)[0]
    assert rec["status"] == "failed"
    assert "resume" in (rec["error"] or "")

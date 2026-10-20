"""删库异步路由契约：DELETE 202、任务查询、按库恢复。"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import docs_routes
from docs_core.library_delete import (
    DeleteInProgress,
    DeleteTask,
    DeleteTasks,
    LibraryNotFound,
)


class _FakeRunner:
    def __init__(self, task: DeleteTask | None = None):
        self.task = task
        self.tasks = SimpleNamespace(get=self._get)

    def _get(self, task_id: str):
        return self.task if self.task and self.task.task_id == task_id else None

    def start(self, library_id: str) -> DeleteTask:
        if library_id == "missing":
            raise LibraryNotFound("知识库不存在: missing")
        if library_id == "busy":
            raise DeleteInProgress("已有删除任务在执行")
        assert self.task is not None
        return self.task

    def latest_for_library(self, library_id: str):
        return self.task


@pytest.fixture()
def client(monkeypatch):
    task = DeleteTask(task_id="del-test", library_id="lib-a", status="running", stage="vectors")
    monkeypatch.setattr(docs_routes, "_library_delete_runner", _FakeRunner(task))
    app = FastAPI()
    app.include_router(docs_routes.docs_router, prefix="/api/knowledge")
    return TestClient(app)


def test_delete_returns_202(client):
    resp = client.delete("/api/knowledge/libraries/lib-a")
    assert resp.status_code == 202
    body = resp.json()
    assert body["task_id"] == "del-test"
    assert body["library_id"] == "lib-a"
    assert body["status"] == "running"


def test_get_delete_task(client):
    resp = client.get("/api/knowledge/libraries/deletions/del-test")
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "del-test"


def test_get_delete_task_by_library(client):
    resp = client.get("/api/knowledge/libraries/lib-a/deletion")
    assert resp.status_code == 200
    assert resp.json()["library_id"] == "lib-a"


def test_delete_missing_returns_404(client):
    resp = client.delete("/api/knowledge/libraries/missing")
    assert resp.status_code == 404


def test_delete_busy_returns_409(client):
    resp = client.delete("/api/knowledge/libraries/busy")
    assert resp.status_code == 409


def test_delete_tasks_single_flight():
    tasks = DeleteTasks()
    first = tasks.start("lib-a")
    try:
        with pytest.raises(DeleteInProgress):
            tasks.start("lib-b")
    finally:
        tasks.clear_active(first.task_id)
    assert tasks.start("lib-b").library_id == "lib-b"

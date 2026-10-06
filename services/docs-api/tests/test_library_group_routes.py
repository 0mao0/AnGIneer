"""POST /libraries/groups 路由契约：建组 200 回显；slug 非法/撞内置组 ValueError → 400。

服务层链路已有真测（docs-core/test_custom_group_flow.py），本文件 stub 掉 docs_service，
只钉 HTTP 边界（校验失败必须转 400，不得 500）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import docs_routes


class _StubService:
    def __init__(self):
        self.calls = []

    def create_group(self, group_name, display_name=""):
        self.calls.append((group_name, display_name))
        if group_name in ("standards", "Bridge", "../evil"):
            raise ValueError(f"非法/冲突组名: {group_name}")
        from docs_core.library_registry import GroupRecord

        return GroupRecord(group_name=group_name, display_name=display_name or group_name)


@pytest.fixture()
def client(monkeypatch):
    svc = _StubService()
    monkeypatch.setattr(docs_routes, "get_docs_service", lambda: svc)
    app = FastAPI()
    app.include_router(docs_routes.docs_router, prefix="/api/knowledge")
    return TestClient(app), svc


def test_create_group_ok(client):
    c, svc = client
    resp = c.post("/api/knowledge/libraries/groups", json={"group_name": "bridge", "display_name": "外服 · 桥梁工程"})
    assert resp.status_code == 200
    assert resp.json() == {"group_name": "bridge", "display_name": "外服 · 桥梁工程"}
    assert svc.calls == [("bridge", "外服 · 桥梁工程")]


def test_create_group_invalid_slug_400(client):
    c, _ = client
    for bad in ("Bridge", "../evil", "standards"):
        resp = c.post("/api/knowledge/libraries/groups", json={"group_name": bad})
        assert resp.status_code == 400, bad

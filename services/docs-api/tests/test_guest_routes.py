"""游客设置端点契约（docs/design-guest-settings.md §3.2/§3.6）：

- settings 读写必须管理员鉴权（无头 401）；PUT 校验失败一律 400（V1-V4）；
- config 公开；按允许集过滤分组清单；evals 组永不出现；读坏时 enabled=False。
服务层链路（文件读写）有真测（tests/unit/test_guest_settings.py），本文件 stub docs_service、
monkeypatch 设置文件路径，只钉 HTTP 边界。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import guest_routes
from admin_auth import resolve_admin_session


class _Lib:
    def __init__(self, group_name="system"):
        self.group_name = group_name


class _StubService:
    def __init__(self):
        self.libs = {"default": _Lib(), "guifan": _Lib(), "evals-demo": _Lib("evals")}

    def get_library(self, lid):
        return self.libs.get(lid)

    def list_grouped_libraries(self):
        return [
            {"group_name": "system", "display_name": "", "libraries": [
                {"id": "default", "name": "默认库"},
                {"id": "guifan", "name": "规范库"},
            ]},
            {"group_name": "evals", "display_name": "", "libraries": [
                {"id": "evals-demo", "name": "评测语料"},
            ]},
        ]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    svc = _StubService()
    monkeypatch.setattr(guest_routes, "get_docs_service", lambda: svc)
    # 隔离外部 env：本地 .env 可能带 ANGINEER_GUEST_ROUNDS 调试值（如实测期=5），默认语义按 30 断言
    monkeypatch.setenv("ANGINEER_GUEST_ROUNDS", "30")
    monkeypatch.setenv("GUEST_SETTINGS_FILE", str(tmp_path / "guest_settings.json"))
    app = FastAPI()
    app.include_router(guest_routes.router)
    return TestClient(app), svc


def _as_admin(c):
    c.app.dependency_overrides[resolve_admin_session] = lambda: None


_VALID = {"enabled": True, "rounds": 30, "library_ids": ["default"]}


def test_settings_requires_admin(client):
    c, _ = client
    assert c.get("/api/guest/settings").status_code == 401
    assert c.put("/api/guest/settings", json=_VALID).status_code == 401


def test_settings_route_has_admin_dependency(client):
    """防回归：settings 两方法的依赖必须挂在路由上（config 不需要）。"""
    by_path = {}
    for r in guest_routes.router.routes:
        by_path.setdefault(r.path, []).append(r)
    for r in by_path["/api/guest/settings"]:
        assert r.dependencies, r.methods


def test_settings_put_and_get_roundtrip(client):
    c, _ = client
    _as_admin(c)
    resp = c.put("/api/guest/settings", json={"enabled": True, "rounds": 5, "library_ids": ["guifan"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True and body["rounds"] == 5 and body["library_ids"] == ["guifan"]
    got = c.get("/api/guest/settings").json()
    assert got["load_error"] == "" and got["library_ids"] == ["guifan"]


def test_settings_put_validation_400(client):
    c, _ = client
    _as_admin(c)
    for bad in (
        {"enabled": True, "rounds": 30, "library_ids": []},            # V1 至少 1 个
        {"enabled": True, "rounds": 30, "library_ids": ["nope"]},      # V2 不存在
        {"enabled": True, "rounds": 30, "library_ids": ["evals-demo"]},  # V3 evals 组
        {"enabled": True, "rounds": 0, "library_ids": ["default"]},    # V4 越界（明确 400）
        {"enabled": True, "rounds": 1001, "library_ids": ["default"]},
    ):
        resp = c.put("/api/guest/settings", json=bad)
        assert resp.status_code == 400, bad


def test_get_settings_exposes_load_error(client, tmp_path):
    path = tmp_path / "guest_settings.json"
    path.write_text("{ 半截", encoding="utf-8")
    c, _ = client
    _as_admin(c)
    body = c.get("/api/guest/settings").json()
    assert body["enabled"] is False
    assert body["load_error"]


def test_config_public_filtered_by_allowed_set(client):
    c, _ = client
    resp = c.get("/api/guest/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True and body["rounds"] == 30
    # 默认设置（无文件）允许集 = ["default"] → 只回 default；evals 组永不出现
    assert [g["group_name"] for g in body["groups"]] == ["system"]
    assert [l["id"] for g in body["groups"] for l in g["libraries"]] == ["default"]


def test_config_respects_disabled_and_allowed_set(client):
    c, _ = client
    _as_admin(c)
    c.put("/api/guest/settings", json={"enabled": False, "rounds": 5, "library_ids": ["guifan"]})
    body = c.get("/api/guest/config").json()
    assert body["enabled"] is False and body["rounds"] == 5
    assert [l["id"] for g in body["groups"] for l in g["libraries"]] == ["guifan"]

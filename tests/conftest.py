"""测试全局约定：ops 观测落盘默认停用（P0-1 测试卫生）。

agent loop / classifier 的单测会真实执行打点路径；不加此开关，pytest 会把测试流量
写进仓库 data/ops/*.jsonl 污染生产观测。需要专门验证落盘行为的测试（如
tests/angineer-core/test_ops_metrics.py）应自行设置 ANGINEER_OPS_DIR 指向临时目录。
"""
import os

os.environ.setdefault("ANGINEER_OPS_DISABLE", "1")


import pytest


@pytest.fixture(autouse=True)
def _isolate_library_registry(tmp_path, monkeypatch):
    """库组注册表隔离（2026-10-03 实踩）：docs_service 组文件路由经注册表解析，
    不隔离时单测的 default 库路由到真盘 knowledge/groups/standards.sqlite——写读错位
    （test_unit_docs_core_indexing 两例失败）且污染真库。每测试独立注册表 + data 根。"""
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))
    yield

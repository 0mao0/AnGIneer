"""docs-api 测试公共配置：把服务根目录挂上 sys.path（路由模块按 `import docs_routes` 引用）。"""
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture(autouse=True)
def _isolate_registry_env(tmp_path, monkeypatch):
    """库组注册表与数据根隔离（2026-10-04 实踩）。

    不隔离时：注册表路由（resolve_libraries_dir 等）命中开发机真实 data/registry.sqlite，
    测试结果依赖本机真实数据状态——test_parse_route_source_fallback 两个用例因此恒红
    （真实 evals 组目录存在 → canonical 兜底不走 KNOWLEDGE_BASE_DIR 口径的 tmp 夹具）。
    与仓库根 tests/conftest.py 的 _isolate_library_registry 同款口径。"""
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))
    yield

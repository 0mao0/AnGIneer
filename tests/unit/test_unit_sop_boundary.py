"""
模块边界守卫：sop-core / sop-api 不得直连 docs_core / engtools 内部模块。

plan-sop-api-l4 阶段 2（Task 2.5）：跨模块只允许经 graph_port Protocol 注入或
docs-api HTTP 契约；本测试防复发（违例在 import 期即被拦下）。
"""
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SCOPES = {
    "sop-core": REPO_ROOT / "services" / "sop-core" / "src" / "sop_core",
    "sop-api": REPO_ROOT / "services" / "sop-api",
}

FORBIDDEN = ("from docs_core", "import docs_core")

# engtools 允许且仅允许这一处 try/except 受保护导入（engtools 不上 PyPI，
# 独立安装时走 _FALLBACK_KNOWN_TOOLS 名单；见 sop_loader._is_known_tool）
ALLOWED_ENGTOOLS = {
    "sop-core/sop_loader.py": "    from engtools import ToolRegistry as _ToolRegistry",
}


@pytest.mark.parametrize("scope_name", sorted(SCOPES))
def test_no_cross_module_internal_imports(scope_name):
    root = SCOPES[scope_name]
    assert root.is_dir(), f"目录不存在: {root}"
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        rel = f"{scope_name}/{py.relative_to(root)}"
        for bad in FORBIDDEN:
            assert bad not in text, f"{rel} 违例: {bad!r}"
        if "engtools" in text:
            hits = [
                line for line in text.splitlines()
                if ("import engtools" in line or "from engtools import" in line)
                and line.strip().startswith(("import ", "from "))
            ]
            allowed = ALLOWED_ENGTOOLS.get(rel, "")
            for line in hits:
                assert line == allowed, f"{rel} 违例（engtools 仅允许受保护导入）: {line!r}"


def test_graph_port_defines_protocol_surface():
    """生成器依赖的图谱只读面在 graph_port 有定义（防漂移）。"""
    from sop_core import graph_port

    for name in (
        "GraphReader",
        "LAYER_CONCEPT",
        "LAYER_CONDITION",
        "LAYER_ACTION",
    ):
        assert hasattr(graph_port, name), f"graph_port 缺 {name}"

"""docs-core 测试公共配置。"""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _reset_docs_service_singleton():
    """每测试前后重置 docs_service 单例，防跨测试串库（乃至直写真库）。

    ``import docs_core.docs_service as module`` 拿到的是包级 _DocsServiceProxy（包 __init__ 重导出），
    对它赋 ``_docs_service = None`` 并不会重置模块全局；组合跑时上一测试留下的单例（绑 tmp 甚至真库）
    会被后续测试沿用——test_document_mentions 曾因此在组合跑里直写 data/knowledge_base 真库
    （2026-09-30 实测：单独跑写 tmp、组合跑写真库）。重置必须打在 sys.modules 里的真模块上。
    """

    def _reset() -> None:
        module = sys.modules.get("docs_core.docs_service")
        if module is not None:
            module._docs_service = None

    _reset()
    yield
    _reset()

"""docs-core 测试公共配置。"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ---- 环境兜底（2026-10-07 独立发版）----
# 主仓库开发机：这些值来自仓库根 .env（dotenv 在 import 期加载、不覆盖已有变量），行为不变；
# 独立安装（wheel / 独立仓 CI）没有 .env，缺值会让收集期就报「无法定位主仓库根目录」或
# 「DOCS_VECTORSTORE_PROVIDER 未配置」。按同样的"不覆盖"语义补：
#   - 先把仓库 .env 装进环境（若有）；
#   - DOCS_VECTORSTORE_PROVIDER 缺省 sqlite（单测不依赖 qdrant 服务）；
#   - 仅当本文件不在主仓库树里（无 apps/+services/+package.json 标记）时，
#     才给 ANGINEER_REPO_ROOT 一个临时根——仓库树内绝不覆盖，免得改动开发机的路径解析。
from dotenv import load_dotenv  # noqa: E402

load_dotenv(override=False)
os.environ.setdefault("DOCS_VECTORSTORE_PROVIDER", "sqlite")


def _in_monorepo() -> bool:
    for parent in Path(__file__).resolve().parents:
        if (
            (parent / "apps").exists()
            and (parent / "services").exists()
            and (parent / "package.json").exists()
        ):
            return True
    return False


if not _in_monorepo():
    _TEST_ROOT = Path(os.environ.get("ANGINEER_TEST_ROOT") or tempfile.mkdtemp(prefix="docs-core-tests-"))
    (_TEST_ROOT / "knowledge").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ANGINEER_REPO_ROOT", str(_TEST_ROOT))


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


@pytest.fixture(autouse=True)
def _isolate_library_registry(tmp_path, monkeypatch):
    """注册表隔离：create_library 会顺带写库组注册表，缺省路径是真 data/registry.sqlite——
    不隔离则测试库（lib-late 等）直接污染真注册表（2026-10-03 实踩）。"""
    monkeypatch.setenv("ANGINEER_REGISTRY_DB", str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv("ANGINEER_DATA_ROOT", str(tmp_path / "data"))

"""自定义库组服务层链路：建组 → 组内建库/改组 → 分组聚合带空组与 display_name。

注册表与 meta 双隔离（REGISTRY_DB/DATA_ROOT/KNOWLEDGE_BASE_DIR 三件套），不写真盘。
"""
import pytest

from docs_core import library_registry as registry
from docs_core.docs_service import get_docs_service


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv(registry.REGISTRY_DB_ENV, str(tmp_path / "registry.sqlite"))
    monkeypatch.setenv(registry.DATA_ROOT_ENV, str(tmp_path / "data"))


def test_create_library_in_custom_group(iso):
    ks = get_docs_service()
    ks.create_group("bridge", "外服 · 桥梁工程")
    ks.create_library("lib-bridge-demo", "桥梁库", "", group_name="bridge")
    rec = registry.get_library("lib-bridge-demo")
    assert rec is not None and rec.group_name == "bridge" and rec.collection == "bridge"


def test_create_library_unknown_group_rejected(iso):
    ks = get_docs_service()
    with pytest.raises(ValueError):
        ks.create_library("lib-x", "x", "", group_name="ghost")


def test_update_library_to_custom_group(iso):
    ks = get_docs_service()
    ks.create_library("lib-mov", "待迁库", "")
    ks.create_group("bridge", "桥梁")
    ks.update_library("lib-mov", group_name="bridge")
    assert registry.get_library("lib-mov").group_name == "bridge"


def test_grouped_includes_empty_custom_group_with_display(iso):
    ks = get_docs_service()
    ks.create_group("bridge", "外服 · 桥梁工程")
    groups = {g["group_name"]: g for g in ks.list_grouped_libraries()}
    assert "bridge" in groups
    assert groups["bridge"]["display_name"] == "外服 · 桥梁工程"
    assert groups["bridge"]["known_group"] is True
    assert groups["bridge"]["libraries"] == []

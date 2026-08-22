"""知识库删除级联清理冒烟测试：节点/产物/图谱/库记录全清，default 禁止删除。"""
import sqlite3

import pytest
from docs_core.docs_service import get_docs_service


def test_delete_library_cascade(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    ks = get_docs_service()
    lib_id = "lib-del-test"
    ks.create_library(lib_id, "删除测试库", "test")
    node_id = "doc-" + "a" * 8
    from docs_core.step09_query.protocols.contracts import KnowledgeNode
    node = KnowledgeNode(
        id=node_id,
        title="测试文档",
        type="document",
        parent_id=None,
        library_id=lib_id,
        file_path=None,
        visible=True,
    )
    ks.register_document(lib_id, node_id, title="测试文档")

    # 打断点验证执行中状态
    assert ks.get_library(lib_id) is not None
    assert ks.get_node(node_id) is not None

    ok = ks.delete_library(lib_id)
    assert ok is True

    # 内存态
    assert ks.get_library(lib_id) is None
    assert ks.get_node(node_id) is None
    assert not [n for n in ks.nodes if n.library_id == lib_id]

    # 库记录已删
    with ks.meta_store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM libraries WHERE id=?", (lib_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM nodes WHERE library_id=?", (lib_id,)).fetchone()[0] == 0


def test_delete_default_library_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    ks = get_docs_service()
    assert ks.delete_library("default") is False
    assert ks.get_library("default") is not None


def test_delete_missing_library_returns_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    ks = get_docs_service()
    assert ks.delete_library("lib-not-exist") is False

# -*- coding: utf-8 -*-
"""tree_store 回归：建表幂等 / 插入排序 / 移动与同级归一化 / 软硬删除 / 作用域隔离 / 契约模型。"""
import sqlite3

import pytest
from pydantic import ValidationError

from tree_core import MoveNodeRequest, TreeNodeData, tree_store


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    tree_store.init_table(c)
    yield c
    c.close()


@pytest.fixture()
def raw_conn():
    """不给 row_factory 的连接：init_table 应自己补上，库照常可用。"""
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


def _insert(conn, node_id, *, title="", parent=None, tree_type="doc", scope="lib1", **kw):
    return tree_store.insert_node(conn, {
        "node_id": node_id, "tree_type": tree_type, "title": title,
        "parent_id": parent, "scope_id": scope, **kw,
    })


class TestInitAndInsert:
    def test_init_table_is_idempotent(self, conn):
        tree_store.init_table(conn)  # 第二次不应抛（ALTER deleted 已存在时忽略）
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tree_node)")}
        assert {"node_id", "tree_type", "scope_id", "sort_order", "deleted", "extra_json"} <= cols

    def test_insert_appends_sort_order_and_roundtrips_extra(self, conn):
        a = _insert(conn, "a", title="第一")
        b = _insert(conn, "b", title="第二", extra={"size": 12})
        c = _insert(conn, "c", title="第三")
        # 回归：sort_order 必须逐个递增（曾有 `row[0] or -1` 把 0 当"没有"，第二个起全是 0）
        assert (a["sort_order"], b["sort_order"], c["sort_order"]) == (0, 1, 2)
        assert b["extra"] == {"size": 12}
        assert b["is_folder"] is False

    def test_children_order_follows_insertion(self, conn):
        for nid in ("a", "b", "c"):
            _insert(conn, nid)
        assert [n["node_id"] for n in tree_store.list_children(conn, None, "lib1")] == ["a", "b", "c"]

    def test_init_table_supplies_row_factory(self, raw_conn):
        tree_store.init_table(raw_conn)
        assert raw_conn.row_factory is sqlite3.Row
        tree_store.insert_node(raw_conn, {"node_id": "x", "tree_type": "doc", "scope_id": "lib1"})
        assert tree_store.get_node(raw_conn, "x")["node_id"] == "x"

    def test_scope_and_tree_type_isolate_siblings(self, conn):
        _insert(conn, "a", scope="lib1")
        _insert(conn, "b", scope="lib2")
        assert [n["node_id"] for n in tree_store.list_children(conn, None, "lib1")] == ["a"]
        assert [n["node_id"] for n in tree_store.list_children(conn, None, "lib2")] == ["b"]
        assert [n["node_id"] for n in tree_store.list_nodes_by_scope(conn, "doc", "lib1")] == ["a"]
        assert tree_store.list_nodes_by_scope(conn, "folder", "lib1") == []


class TestUpdateMoveDelete:
    def test_move_across_parents_normalizes_both_sides(self, conn):
        _insert(conn, "p1", is_folder=True)
        _insert(conn, "p2", is_folder=True)
        _insert(conn, "c1", parent="p1")
        _insert(conn, "c2", parent="p1")

        tree_store.move_node(conn, "c1", "p2")

        assert tree_store.get_node(conn, "c1")["parent_id"] == "p2"
        # 原父级只剩 c2，排序重排为 0 起连续；新父级里 c1 排到末尾
        assert [n["node_id"] for n in tree_store.list_children(conn, "p1", "lib1")] == ["c2"]
        assert [n["sort_order"] for n in tree_store.list_children(conn, "p1", "lib1")] == [0]
        kids = tree_store.list_children(conn, "p2", "lib1")
        assert [n["node_id"] for n in kids] == ["c1"] and kids[0]["sort_order"] == 0

    def test_normalize_siblings_compacts_gaps(self, conn):
        _insert(conn, "a", sort_order=5)
        _insert(conn, "b", sort_order=9)
        tree_store.normalize_siblings(conn, None, "lib1")
        assert [n["sort_order"] for n in tree_store.list_children(conn, None, "lib1")] == [0, 1]

    def test_delete_removes_subtree_and_repacks(self, conn):
        _insert(conn, "p", is_folder=True)
        _insert(conn, "c", parent="p")
        _insert(conn, "g", parent="c")
        _insert(conn, "keep")

        assert tree_store.delete_node(conn, "p") is True

        assert tree_store.get_node(conn, "c") is None
        assert tree_store.get_node(conn, "g") is None
        assert [n["node_id"] for n in tree_store.list_children(conn, None, "lib1")] == ["keep"]
        assert tree_store.delete_node(conn, "not-exist") is False

    def test_soft_delete_marker_does_not_commit(self, conn):
        _insert(conn, "a")
        tree_store.mark_node_deleted(conn, "a", True)
        assert tree_store.is_node_deleted(conn, "a") is True
        conn.rollback()
        assert tree_store.is_node_deleted(conn, "a") is False  # 未提交 → 回滚即还原

    def test_update_rejects_unknown_fields(self, conn):
        _insert(conn, "a", title="旧")
        node = tree_store.update_node(conn, "a", {"title": "新", "node_id": "hacked"})
        assert node["title"] == "新"
        assert node["node_id"] == "a"  # 白名单外字段被忽略
        assert tree_store.update_node(conn, "missing", {"title": "x"}) is None


class TestContracts:
    def test_tree_node_data_defaults(self):
        d = TreeNodeData(node_id="n1", tree_type="doc")
        assert (d.parent_id, d.scope_id, d.sort_order, d.is_folder) == (None, "", 0, False)

    def test_move_node_request_and_validation(self):
        assert MoveNodeRequest().parent_id is None
        with pytest.raises(ValidationError):
            TreeNodeData(tree_type="doc")  # 缺 node_id

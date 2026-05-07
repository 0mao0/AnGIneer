"""通用树节点存储层。

提供树节点的 CRUD、移动、排序归一化等操作。
所有函数接收 sqlite3.Connection 参数，由调用方控制连接和事务。
"""
import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


def init_table(conn: sqlite3.Connection) -> None:
    """建表建索引。幂等，可重复调用。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tree_node (
            node_id TEXT PRIMARY KEY,
            tree_type TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            parent_id TEXT,
            scope_id TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_folder INTEGER NOT NULL DEFAULT 0,
            extra_json TEXT,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tree_node_scope
        ON tree_node(tree_type, scope_id, parent_id, sort_order)
    """)
    conn.commit()


def insert_node(conn: sqlite3.Connection, data: Dict[str, Any]) -> Dict[str, Any]:
    """插入节点。若 sort_order 未指定，自动排到同级末尾。"""
    now = datetime.now().isoformat()
    node_id = data["node_id"]
    tree_type = data["tree_type"]
    scope_id = data.get("scope_id", "")
    parent_id = data.get("parent_id")

    sort_order = data.get("sort_order", -1)
    if sort_order < 0:
        sort_order = _next_sort_order(conn, parent_id, scope_id)

    extra_json = json.dumps(data.get("extra", {}), ensure_ascii=False) if data.get("extra") else None

    conn.execute(
        """INSERT OR REPLACE INTO tree_node
           (node_id, tree_type, title, parent_id, scope_id, sort_order, is_folder, extra_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            node_id,
            tree_type,
            data.get("title", ""),
            parent_id,
            scope_id,
            sort_order,
            1 if data.get("is_folder") else 0,
            extra_json,
            now,
            now,
        ),
    )
    conn.commit()
    return _row_to_dict(conn, node_id)


def get_node(conn: sqlite3.Connection, node_id: str) -> Optional[Dict[str, Any]]:
    """获取单个节点。"""
    row = conn.execute("SELECT * FROM tree_node WHERE node_id = ?", (node_id,)).fetchone()
    return _row_to_dict_from_row(row) if row else None


def update_node(conn: sqlite3.Connection, node_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新节点。parent_id 变更时自动归一化新旧兄弟排序。"""
    node = get_node(conn, node_id)
    if not node:
        return None

    allowed = {"title", "parent_id", "scope_id", "sort_order", "is_folder", "extra"}
    fields = [k for k in updates if k in allowed and updates[k] is not None]
    # parent_id=None 是合法值（表示根节点），需要特殊处理
    if "parent_id" in updates and updates["parent_id"] is None and "parent_id" not in fields:
        fields.append("parent_id")
    if not fields:
        return node

    old_parent_id = node.get("parent_id")
    old_scope_id = node.get("scope_id")

    now = datetime.now().isoformat()
    values = []
    set_parts = []
    for k in fields:
        if k == "extra":
            set_parts.append("extra_json = ?")
            values.append(json.dumps(updates[k], ensure_ascii=False))
        elif k == "is_folder":
            set_parts.append("is_folder = ?")
            values.append(1 if updates[k] else 0)
        else:
            set_parts.append(f"{k} = ?")
            values.append(updates[k])

    set_parts.append("updated_at = ?")
    values.append(now)
    values.append(node_id)

    conn.execute(f"UPDATE tree_node SET {', '.join(set_parts)} WHERE node_id = ?", values)
    conn.commit()

    new_parent_id = updates.get("parent_id", old_parent_id)
    new_scope_id = updates.get("scope_id", old_scope_id)
    parent_changed = old_parent_id != new_parent_id or old_scope_id != new_scope_id
    if parent_changed:
        normalize_siblings(conn, old_parent_id, old_scope_id)
        if "sort_order" not in updates:
            sort_order = _next_sort_order(conn, new_parent_id, new_scope_id)
            conn.execute("UPDATE tree_node SET sort_order = ? WHERE node_id = ?", (sort_order, node_id))
            conn.commit()
            normalize_siblings(conn, new_parent_id, new_scope_id)

    return get_node(conn, node_id)


def delete_node(conn: sqlite3.Connection, node_id: str) -> bool:
    """删除节点及子树，自动归一化兄弟排序。"""
    node = get_node(conn, node_id)
    if not node:
        return False

    subtree_ids = _collect_subtree_ids(conn, node_id)
    for sid in subtree_ids:
        conn.execute("DELETE FROM tree_node WHERE node_id = ?", (sid,))
    conn.commit()

    normalize_siblings(conn, node.get("parent_id"), node.get("scope_id"))
    return True


def move_node(conn: sqlite3.Connection, node_id: str, new_parent_id: Optional[str], sort_order: int = -1) -> Optional[Dict[str, Any]]:
    """移动节点到新父节点。"""
    updates: Dict[str, Any] = {"parent_id": new_parent_id}
    if sort_order >= 0:
        updates["sort_order"] = sort_order
    return update_node(conn, node_id, updates)


def list_children(conn: sqlite3.Connection, parent_id: Optional[str], scope_id: str = "") -> List[Dict[str, Any]]:
    """列出直接子节点。"""
    if parent_id is None:
        rows = conn.execute(
            "SELECT * FROM tree_node WHERE parent_id IS NULL AND scope_id = ? ORDER BY sort_order, created_at",
            (scope_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tree_node WHERE parent_id = ? AND scope_id = ? ORDER BY sort_order, created_at",
            (parent_id, scope_id),
        ).fetchall()
    return [_row_to_dict_from_row(r) for r in rows]


def list_nodes_by_scope(conn: sqlite3.Connection, tree_type: str, scope_id: str) -> List[Dict[str, Any]]:
    """按 tree_type 和 scope_id 列出所有节点。"""
    rows = conn.execute(
        "SELECT * FROM tree_node WHERE tree_type = ? AND scope_id = ? ORDER BY parent_id, sort_order, created_at",
        (tree_type, scope_id),
    ).fetchall()
    return [_row_to_dict_from_row(r) for r in rows]


def list_nodes_by_type(conn: sqlite3.Connection, tree_type: str) -> List[Dict[str, Any]]:
    """按 tree_type 列出所有节点。"""
    rows = conn.execute(
        "SELECT * FROM tree_node WHERE tree_type = ? ORDER BY scope_id, parent_id, sort_order, created_at",
        (tree_type,),
    ).fetchall()
    return [_row_to_dict_from_row(r) for r in rows]


def normalize_siblings(conn: sqlite3.Connection, parent_id: Optional[str], scope_id: str) -> None:
    """对同一父节点下的兄弟节点重新排序，使 sort_order 连续从 0 开始。"""
    siblings = list_children(conn, parent_id, scope_id)
    for idx, sib in enumerate(siblings):
        if sib.get("sort_order") != idx:
            conn.execute(
                "UPDATE tree_node SET sort_order = ?, updated_at = ? WHERE node_id = ?",
                (idx, datetime.now().isoformat(), sib["node_id"]),
            )
    conn.commit()


def _next_sort_order(conn: sqlite3.Connection, parent_id: Optional[str], scope_id: str) -> int:
    """获取同级下一个 sort_order。"""
    if parent_id is None:
        row = conn.execute(
            "SELECT MAX(sort_order) FROM tree_node WHERE parent_id IS NULL AND scope_id = ?",
            (scope_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(sort_order) FROM tree_node WHERE parent_id = ? AND scope_id = ?",
            (parent_id, scope_id),
        ).fetchone()
    return (row[0] or -1) + 1


def _collect_subtree_ids(conn: sqlite3.Connection, node_id: str) -> List[str]:
    """递归收集节点及其所有后代的 ID。"""
    ids = [node_id]
    children = conn.execute("SELECT node_id FROM tree_node WHERE parent_id = ?", (node_id,)).fetchall()
    for child in children:
        ids.extend(_collect_subtree_ids(conn, child[0]))
    return ids


def _row_to_dict(conn: sqlite3.Connection, node_id: str) -> Dict[str, Any]:
    """按 ID 查询并转为字典。"""
    row = conn.execute("SELECT * FROM tree_node WHERE node_id = ?", (node_id,)).fetchone()
    return _row_to_dict_from_row(row)


def _row_to_dict_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    """将 sqlite3.Row 转为字典，解析 extra_json。"""
    d = dict(row)
    if d.get("extra_json"):
        try:
            d["extra"] = json.loads(d["extra_json"])
        except (json.JSONDecodeError, TypeError):
            d["extra"] = {}
    else:
        d["extra"] = {}
    d.pop("extra_json", None)
    d["is_folder"] = bool(d.get("is_folder", 0))
    if d.get("parent_id") is None:
        d["parent_id"] = None
    return d

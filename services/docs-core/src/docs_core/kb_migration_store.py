"""知识库迁移任务行存储：meta 库 kb_migration_tasks 表（设计 §5.4）。

任务行 = 页面轮询与启动自愈的唯一真相源；步骤流水与已迁 doc 清单走 JSON 列（评审定稿，不单建表）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.paths import resolve_knowledge_meta_db_path
from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection, run_with_write_lock

_NONTERMINAL = ("running", "cancelling")


class KbMigrationStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else resolve_knowledge_meta_db_path()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return create_connection(self.db_path)

    def _init_schema(self) -> None:
        def _write() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kb_migration_tasks (
                        id TEXT PRIMARY KEY,
                        op TEXT NOT NULL,
                        params_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'running',
                        stage TEXT NOT NULL DEFAULT 'preview',
                        progress_done INTEGER NOT NULL DEFAULT 0,
                        progress_total INTEGER NOT NULL DEFAULT 0,
                        stage_message TEXT,
                        error TEXT,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        steps_json TEXT NOT NULL DEFAULT '[]',
                        migrated_json TEXT NOT NULL DEFAULT '[]',
                        preview_json TEXT,
                        verify_json TEXT,
                        rollback_deadline TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        run_with_write_lock(self.db_path, _write)

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Dict[str, Any]:
        task = dict(row)
        task["params"] = json.loads(task.pop("params_json") or "{}")
        task["steps"] = json.loads(task.pop("steps_json") or "[]")
        task["migrated_doc_ids"] = json.loads(task.pop("migrated_json") or "[]")
        task["preview"] = json.loads(task.pop("preview_json") or "null")
        task["verify"] = json.loads(task.pop("verify_json") or "null")
        task["cancel_requested"] = bool(task["cancel_requested"])
        return task

    def create_task(self, task_id: str, *, op: str, params: Dict[str, Any], total: int,
                    preview: Optional[Dict[str, Any]] = None) -> None:
        now = self._now()

        def _write() -> None:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO kb_migration_tasks "
                    "(id, op, params_json, status, stage, progress_total, preview_json, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (task_id, op, json.dumps(params, ensure_ascii=False), "running", "execute",
                     total, json.dumps(preview, ensure_ascii=False) if preview else None, now, now),
                )
        run_with_write_lock(self.db_path, _write)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM kb_migration_tasks WHERE id=?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM kb_migration_tasks ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_task(self, task_id: str, **fields: Any) -> None:
        json_cols = {"preview": "preview_json", "verify": "verify_json"}
        sets, values = [], []
        for key, value in fields.items():
            col = json_cols.get(key, key)
            sets.append(f"{col}=?")
            values.append(json.dumps(value, ensure_ascii=False) if key in json_cols else value)
        sets.append("updated_at=?")
        values.append(self._now())
        values.append(task_id)

        def _write() -> None:
            with self._connect() as conn:
                conn.execute(f"UPDATE kb_migration_tasks SET {', '.join(sets)} WHERE id=?", values)
        run_with_write_lock(self.db_path, _write)

    def request_cancel(self, task_id: str) -> None:
        self.update_task(task_id, cancel_requested=1, status="cancelling")

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM kb_migration_tasks WHERE id=?", (task_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def append_step(self, task_id: str, stage: str, message: str, status: str = "done") -> None:
        def _write() -> None:
            with self._connect() as conn:
                row = conn.execute("SELECT steps_json FROM kb_migration_tasks WHERE id=?", (task_id,)).fetchone()
                steps = json.loads(row["steps_json"] or "[]") if row else []
                steps.append({"at": self._now(), "stage": stage, "step": message, "status": status})
                conn.execute(
                    "UPDATE kb_migration_tasks SET steps_json=?, stage_message=?, updated_at=? WHERE id=?",
                    (json.dumps(steps[-200:], ensure_ascii=False), message, self._now(), task_id),
                )
        run_with_write_lock(self.db_path, _write)

    def mark_doc_migrated(self, task_id: str, doc_id: str) -> None:
        def _write() -> None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT migrated_json, progress_done FROM kb_migration_tasks WHERE id=?", (task_id,)
                ).fetchone()
                migrated = json.loads(row["migrated_json"] or "[]") if row else []
                if doc_id not in migrated:
                    migrated.append(doc_id)
                conn.execute(
                    "UPDATE kb_migration_tasks SET migrated_json=?, progress_done=?, updated_at=? WHERE id=?",
                    (json.dumps(migrated, ensure_ascii=False), len(migrated), self._now(), task_id),
                )
        run_with_write_lock(self.db_path, _write)

    def unmark_doc_migrated(self, task_id: str, doc_id: str) -> None:
        def _write() -> None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT migrated_json FROM kb_migration_tasks WHERE id=?", (task_id,)
                ).fetchone()
                migrated = json.loads(row["migrated_json"] or "[]") if row else []
                migrated = [d for d in migrated if d != doc_id]
                conn.execute(
                    "UPDATE kb_migration_tasks SET migrated_json=?, progress_done=?, updated_at=? WHERE id=?",
                    (json.dumps(migrated, ensure_ascii=False), len(migrated), self._now(), task_id),
                )
        run_with_write_lock(self.db_path, _write)

"""SQLite 结果持久化存储。"""
import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

_DB_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../..")), "data", "evals", "evals.db")

_LOCAL = threading_local = None


def _get_thread_local():
    """延迟初始化线程局部存储。"""
    global _LOCAL
    if _LOCAL is None:
        import threading
        _LOCAL = threading.local()
    return _LOCAL


def _get_conn() -> sqlite3.Connection:
    """获取当前线程的数据库连接。"""
    local = _get_thread_local()
    conn = getattr(local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        local.conn = conn
    return conn


def init_db() -> None:
    """初始化数据库表结构。"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eval_dataset (
            dataset_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'knowledge',
            description TEXT NOT NULL DEFAULT '',
            schema_version TEXT NOT NULL DEFAULT 'eval.bundle.v2',
            version TEXT NOT NULL DEFAULT '1.0',
            library_id TEXT NOT NULL DEFAULT 'default',
            question_count INTEGER NOT NULL DEFAULT 0,
            source_file TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS eval_question (
            question_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL REFERENCES eval_dataset(dataset_id) ON DELETE CASCADE,
            question TEXT NOT NULL DEFAULT '',
            task_type TEXT NOT NULL DEFAULT 'definition',
            intent_level TEXT NOT NULL DEFAULT 'L1',
            difficulty TEXT NOT NULL DEFAULT 'easy',
            tags TEXT NOT NULL DEFAULT '[]',
            library_id TEXT NOT NULL DEFAULT 'default',
            doc_ids TEXT NOT NULL DEFAULT '[]',
            retrieval_gold TEXT,
            answer_gold TEXT,
            sql_gold TEXT,
            sop_gold TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (question_id, dataset_id)
        );

        CREATE TABLE IF NOT EXISTS eval_run (
            run_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL REFERENCES eval_dataset(dataset_id),
            status TEXT NOT NULL DEFAULT 'running',
            total_questions INTEGER NOT NULL DEFAULT 0,
            completed_questions INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL DEFAULT '',
            completed_at TEXT,
            summary_scores TEXT,
            config_snapshot TEXT
        );

        CREATE TABLE IF NOT EXISTS eval_run_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES eval_run(run_id) ON DELETE CASCADE,
            question_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            prediction TEXT,
            scores TEXT,
            error TEXT,
            latency_ms INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_eval_question_dataset ON eval_question(dataset_id);
        CREATE INDEX IF NOT EXISTS idx_eval_run_dataset ON eval_run(dataset_id);
        CREATE INDEX IF NOT EXISTS idx_eval_run_detail_run ON eval_run_detail(run_id);
    """)
    try:
        conn.execute("ALTER TABLE eval_run_detail ADD COLUMN all_scores TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE eval_run_detail ADD COLUMN all_predictions TEXT")
    except Exception:
        pass
    conn.commit()


def insert_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
    """插入一条测试集记录。"""
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO eval_dataset
           (dataset_id, title, category, description, schema_version, version,
            library_id, question_count, source_file, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["dataset_id"],
            data.get("title", ""),
            data.get("category", "knowledge"),
            data.get("description", ""),
            data.get("schema_version", "eval.bundle.v2"),
            data.get("version", "1.0"),
            data.get("library_id", "default"),
            data.get("question_count", 0),
            data.get("source_file", ""),
            now,
            now,
        ),
    )
    conn.commit()
    return {**data, "created_at": now, "updated_at": now}


def update_dataset_question_count(dataset_id: str, count: int) -> None:
    """更新测试集的题目数量。"""
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        "UPDATE eval_dataset SET question_count = ?, updated_at = ? WHERE dataset_id = ?",
        (count, now, dataset_id),
    )
    conn.commit()


def list_datasets() -> List[Dict[str, Any]]:
    """列出所有测试集。"""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM eval_dataset ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def get_dataset(dataset_id: str) -> Optional[Dict[str, Any]]:
    """获取单个测试集。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM eval_dataset WHERE dataset_id = ?", (dataset_id,)).fetchone()
    return dict(row) if row else None


def delete_dataset(dataset_id: str) -> bool:
    """删除测试集及其所有题目。"""
    conn = _get_conn()
    conn.execute("DELETE FROM eval_question WHERE dataset_id = ?", (dataset_id,))
    cursor = conn.execute("DELETE FROM eval_dataset WHERE dataset_id = ?", (dataset_id,))
    conn.commit()
    return cursor.rowcount > 0


def update_dataset(dataset_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新测试集元信息。"""
    allowed = {"title", "description", "category"}
    fields = [k for k in updates if k in allowed and updates[k] is not None]
    if not fields:
        return get_dataset(dataset_id)
    conn = _get_conn()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [updates[k] for k in fields] + [dataset_id]
    conn.execute(f"UPDATE eval_dataset SET {set_clause} WHERE dataset_id = ?", values)
    conn.commit()
    return get_dataset(dataset_id)


def insert_question(data: Dict[str, Any]) -> Dict[str, Any]:
    """插入一条题目记录。"""
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO eval_question
           (question_id, dataset_id, question, task_type, intent_level, difficulty,
            tags, library_id, doc_ids, retrieval_gold, answer_gold, sql_gold, sop_gold, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["question_id"],
            data["dataset_id"],
            data.get("question", ""),
            data.get("task_type", "definition"),
            data.get("intent_level", "L1"),
            data.get("difficulty", "easy"),
            json.dumps(data.get("tags", []), ensure_ascii=False),
            data.get("library_id", "default"),
            json.dumps(data.get("doc_ids", []), ensure_ascii=False),
            json.dumps(data["retrieval_gold"], ensure_ascii=False) if data.get("retrieval_gold") else None,
            json.dumps(data["answer_gold"], ensure_ascii=False) if data.get("answer_gold") else None,
            json.dumps(data["sql_gold"], ensure_ascii=False) if data.get("sql_gold") else None,
            json.dumps(data["sop_gold"], ensure_ascii=False) if data.get("sop_gold") else None,
            data.get("sort_order", 0),
        ),
    )
    conn.commit()
    return data


def list_questions(dataset_id: str) -> List[Dict[str, Any]]:
    """列出测试集下的所有题目。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM eval_question WHERE dataset_id = ? ORDER BY sort_order, question_id",
        (dataset_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["tags"] = json.loads(item.get("tags") or "[]")
        item["doc_ids"] = json.loads(item.get("doc_ids") or "[]")
        item["retrieval_gold"] = json.loads(item["retrieval_gold"]) if item.get("retrieval_gold") else None
        item["answer_gold"] = json.loads(item["answer_gold"]) if item.get("answer_gold") else None
        item["sql_gold"] = json.loads(item["sql_gold"]) if item.get("sql_gold") else None
        item["sop_gold"] = json.loads(item["sop_gold"]) if item.get("sop_gold") else None
        result.append(item)
    return result


def get_question(dataset_id: str, question_id: str) -> Optional[Dict[str, Any]]:
    """获取单条题目。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM eval_question WHERE dataset_id = ? AND question_id = ?",
        (dataset_id, question_id),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["tags"] = json.loads(item.get("tags") or "[]")
    item["doc_ids"] = json.loads(item.get("doc_ids") or "[]")
    item["retrieval_gold"] = json.loads(item["retrieval_gold"]) if item.get("retrieval_gold") else None
    item["answer_gold"] = json.loads(item["answer_gold"]) if item.get("answer_gold") else None
    item["sql_gold"] = json.loads(item["sql_gold"]) if item.get("sql_gold") else None
    item["sop_gold"] = json.loads(item["sop_gold"]) if item.get("sop_gold") else None
    return item


def delete_question(dataset_id: str, question_id: str) -> bool:
    """删除单条题目。"""
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM eval_question WHERE dataset_id = ? AND question_id = ?",
        (dataset_id, question_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def update_question(dataset_id: str, question_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新题目字段。"""
    existing = get_question(dataset_id, question_id)
    if not existing:
        return None
    for key, value in updates.items():
        if key in ("tags", "doc_ids"):
            existing[key] = value
        elif key in ("retrieval_gold", "answer_gold", "sql_gold", "sop_gold"):
            existing[key] = value
        elif key in ("question", "task_type", "intent_level", "difficulty", "library_id"):
            existing[key] = value
    conn = _get_conn()
    conn.execute(
        """UPDATE eval_question SET
           question=?, task_type=?, intent_level=?, difficulty=?,
           tags=?, library_id=?, doc_ids=?,
           retrieval_gold=?, answer_gold=?, sql_gold=?, sop_gold=?
           WHERE dataset_id=? AND question_id=?""",
        (
            existing.get("question", ""),
            existing.get("task_type", "definition"),
            existing.get("intent_level", "L1"),
            existing.get("difficulty", "easy"),
            json.dumps(existing.get("tags", []), ensure_ascii=False),
            existing.get("library_id", "default"),
            json.dumps(existing.get("doc_ids", []), ensure_ascii=False),
            json.dumps(existing["retrieval_gold"], ensure_ascii=False) if existing.get("retrieval_gold") else None,
            json.dumps(existing["answer_gold"], ensure_ascii=False) if existing.get("answer_gold") else None,
            json.dumps(existing["sql_gold"], ensure_ascii=False) if existing.get("sql_gold") else None,
            json.dumps(existing["sop_gold"], ensure_ascii=False) if existing.get("sop_gold") else None,
            dataset_id,
            question_id,
        ),
    )
    conn.commit()
    return existing


def create_run(dataset_id: str, total_questions: int) -> Dict[str, Any]:
    """创建一条评测运行记录。"""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO eval_run (run_id, dataset_id, status, total_questions, completed_questions, started_at)
           VALUES (?, ?, 'running', ?, 0, ?)""",
        (run_id, dataset_id, total_questions, now),
    )
    conn.commit()
    return {"run_id": run_id, "dataset_id": dataset_id, "status": "running",
            "total_questions": total_questions, "completed_questions": 0, "started_at": now}


def update_run_progress(run_id: str, completed_questions: int) -> None:
    """更新运行进度。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE eval_run SET completed_questions = ? WHERE run_id = ?",
        (completed_questions, run_id),
    )
    conn.commit()


def complete_run(run_id: str, summary_scores: Dict[str, Any]) -> None:
    """标记运行完成并写入汇总得分。"""
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        "UPDATE eval_run SET status = 'completed', completed_at = ?, summary_scores = ? WHERE run_id = ?",
        (now, json.dumps(summary_scores, ensure_ascii=False), run_id),
    )
    conn.commit()


def fail_run(run_id: str, error: str) -> None:
    """标记运行失败。"""
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        "UPDATE eval_run SET status = 'failed', completed_at = ?, summary_scores = ? WHERE run_id = ?",
        (now, json.dumps({"error": error}, ensure_ascii=False), run_id),
    )
    conn.commit()


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    """获取单条运行记录。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM eval_run WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["summary_scores"] = json.loads(item["summary_scores"]) if item.get("summary_scores") else None
    item["config_snapshot"] = json.loads(item["config_snapshot"]) if item.get("config_snapshot") else None
    return item


def list_runs(dataset_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出运行记录。"""
    conn = _get_conn()
    if dataset_id:
        rows = conn.execute(
            "SELECT * FROM eval_run WHERE dataset_id = ? ORDER BY started_at DESC",
            (dataset_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM eval_run ORDER BY started_at DESC").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["summary_scores"] = json.loads(item["summary_scores"]) if item.get("summary_scores") else None
        item["config_snapshot"] = json.loads(item["config_snapshot"]) if item.get("config_snapshot") else None
        result.append(item)
    return result


def insert_run_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    """插入一条运行详情记录。"""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO eval_run_detail (run_id, question_id, status, prediction, scores, all_scores, all_predictions, error, latency_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["run_id"],
            data["question_id"],
            data.get("status", "pending"),
            json.dumps(data["prediction"], ensure_ascii=False) if data.get("prediction") else None,
            json.dumps(data["scores"], ensure_ascii=False) if data.get("scores") else None,
            json.dumps(data["all_scores"], ensure_ascii=False) if data.get("all_scores") else None,
            json.dumps(data["all_predictions"], ensure_ascii=False) if data.get("all_predictions") else None,
            data.get("error"),
            data.get("latency_ms"),
        ),
    )
    conn.commit()
    return data


def update_run_detail(run_id: str, question_id: str, updates: Dict[str, Any]) -> None:
    """更新运行详情记录。"""
    set_clauses = []
    values = []
    for key in ("status", "prediction", "scores", "all_scores", "all_predictions", "error", "latency_ms"):
        if key in updates:
            set_clauses.append(f"{key} = ?")
            if key in ("prediction", "scores", "all_scores", "all_predictions") and updates[key] is not None:
                values.append(json.dumps(updates[key], ensure_ascii=False))
            else:
                values.append(updates[key])
    if not set_clauses:
        return
    values.extend([run_id, question_id])
    conn = _get_conn()
    conn.execute(
        f"UPDATE eval_run_detail SET {', '.join(set_clauses)} WHERE run_id = ? AND question_id = ?",
        values,
    )
    conn.commit()


def list_run_details(run_id: str) -> List[Dict[str, Any]]:
    """列出某次运行的所有详情。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM eval_run_detail WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["prediction"] = json.loads(item["prediction"]) if item.get("prediction") else None
        item["scores"] = json.loads(item["scores"]) if item.get("scores") else None
        item["all_scores"] = json.loads(item["all_scores"]) if item.get("all_scores") else None
        item["all_predictions"] = json.loads(item["all_predictions"]) if item.get("all_predictions") else None
        result.append(item)
    return result

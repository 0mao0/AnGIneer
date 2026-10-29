"""知识库删除：批量清理 + 异步任务（P4-0）。

语义（2026-10-20 定版）：
- 共享桶（多个 registry 行指向同一 sqlite_file/collection）：只清本库行、向量点、文件；
  **不删** sqlite 文件/collection 容器。
- 独立桶：引用计数为 0（含 retired）且非默认单文件/内置组桶时，才删 sqlite/collection。
- `doc_catalog` 一并清（旧 delete_library 漏了这张表）。
- registry 状态：deleting（开始）→ retired（成功）；失败保留 deleting，任务可重试。

本模块不 import docs_service，避免循环；调用方传入 KnowledgeService 实例。
"""
from __future__ import annotations

import logging
import gc
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import library_registry
from .paths import resolve_knowledge_base_dir
from .step05_sqlite_fts.store.sqlite_utils import create_connection, run_with_write_lock
from .step06_vectors.qdrant_vector_store import QdrantVectorStore
from .step07_graph.graph_store import GraphStore

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_FILE = "knowledge/knowledge_index.sqlite"

# 清理顺序：子表 → canonical_documents；doc_catalog 单独按 library_id。
INDEX_CHILD_TABLES = (
    "canonical_chunk_fts",
    "canonical_citation_targets",
    "canonical_tables",
    "canonical_chunks",
    "canonical_outlines",
    "canonical_blocks",
    "canonical_pages",
    "canonical_vectors",
    "doc_blocks",
    "document_segments",
    "doc_block_corrections",
)

Progress = Callable[[str, int, int], None]


class LibraryDeleteError(RuntimeError):
    """删库任务错误基类。"""


class LibraryNotFound(LibraryDeleteError):
    """库不存在。"""


class DeleteInProgress(LibraryDeleteError):
    """已有删库任务在跑。"""


TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_SUCCEEDED = "succeeded"
TASK_FAILED = "failed"


@dataclass
class DeleteTask:
    task_id: str
    library_id: str
    status: str = TASK_QUEUED
    stage: str = "queued"
    done: int = 0
    total: int = 0
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "library_id": self.library_id,
            "status": self.status,
            "stage": self.stage,
            "done": self.done,
            "total": self.total,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class DeleteTasks:
    """进程内任务表；全局单飞（同一时间只跑一个删库任务）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, DeleteTask] = {}
        self._active: Optional[str] = None

    def start(self, library_id: str) -> DeleteTask:
        with self._lock:
            if self._active:
                active = self._tasks.get(self._active)
                if active and active.status in (TASK_QUEUED, TASK_RUNNING):
                    raise DeleteInProgress(
                        f"已有删除任务在执行：库={active.library_id} task={active.task_id}"
                    )
            task = DeleteTask(task_id=f"del-{uuid.uuid4().hex[:12]}", library_id=library_id)
            self._tasks[task.task_id] = task
            self._active = task.task_id
            return task

    def update(self, task_id: str, **fields: Any) -> Optional[DeleteTask]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            for key, value in fields.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            return task

    def get(self, task_id: str) -> Optional[DeleteTask]:
        with self._lock:
            task = self._tasks.get(task_id)
            return task

    def latest_for_library(self, library_id: str) -> Optional[DeleteTask]:
        with self._lock:
            rows = [t for t in self._tasks.values() if t.library_id == library_id]
            return max(rows, key=lambda t: t.created_at) if rows else None

    def clear_active(self, task_id: str) -> None:
        with self._lock:
            if self._active == task_id:
                self._active = None


class LibraryDeleteRunner:
    """后台执行删库；route 只负责提交任务和查状态。"""

    def __init__(self, service_factory: Callable[[], Any]) -> None:
        self._service_factory = service_factory
        self.tasks = DeleteTasks()
        self._threads: Dict[str, threading.Thread] = {}

    def start(self, library_id: str) -> DeleteTask:
        service = self._service_factory()
        # default 不再特殊（2026-10-29：系统不再自动创建默认库，任何注册库都可删）
        record = library_registry.get_library(library_id)
        if record is None and service.get_library(library_id) is None:
            raise LibraryNotFound(f"知识库不存在: {library_id}")
        task = self.tasks.start(library_id)
        thread = threading.Thread(
            target=self._run,
            args=(task.task_id, library_id),
            daemon=True,
            name=f"library-delete-{library_id}",
        )
        self._threads[task.task_id] = thread
        thread.start()
        return task

    def _run(self, task_id: str, library_id: str) -> None:
        self.tasks.update(task_id, status=TASK_RUNNING, stage="vectors", started_at=time.time())
        try:
            service = self._service_factory()

            def progress(stage: str, done: int, total: int) -> None:
                self.tasks.update(task_id, stage=stage, done=done, total=total)

            result = delete_library_data(service, library_id, progress=progress)
            total = int(result.get("docs") or 0)
            self.tasks.update(
                task_id,
                status=TASK_SUCCEEDED,
                stage="done",
                done=total,
                total=total,
                finished_at=time.time(),
                error="",
            )
        except Exception as exc:  # noqa: BLE001 — 任务失败要落状态，不把线程异常吞掉
            logger.exception("删库任务失败: library=%s task=%s", library_id, task_id)
            self.tasks.update(
                task_id,
                status=TASK_FAILED,
                error=str(exc),
                finished_at=time.time(),
            )
        finally:
            self.tasks.clear_active(task_id)

    def latest_for_library(self, library_id: str) -> Optional[DeleteTask]:
        return self.tasks.latest_for_library(library_id)


def _notify(progress: Optional[Progress], stage: str, done: int = 0, total: int = 0) -> None:
    if progress is not None:
        try:
            progress(stage, done, total)
        except Exception:  # noqa: BLE001 — 进度回调失败不影响删库
            logger.debug("删库进度回调失败", exc_info=True)


def _node_ids(service: Any, library_id: str) -> List[str]:
    """优先读 meta 库（服务内存可能不是全量）；读不到再退回内存。"""
    from .pg_support import is_pg

    if is_pg():
        meta_store = getattr(service, "meta_store", None)
        if meta_store is not None:
            try:
                conn = meta_store.connect()
                try:
                    return [str(r[0]) for r in conn.execute(
                        "SELECT id FROM nodes WHERE library_id = ?", (library_id,)
                    ).fetchall()]
                finally:
                    conn.close()
            except Exception:  # noqa: BLE001
                logger.warning("PG 读取 meta nodes 失败，退回内存: library=%s", library_id, exc_info=True)
        return [str(n.id) for n in getattr(service, "nodes", []) if str(getattr(n, "library_id", "")) == library_id]
    db_path = getattr(getattr(service, "meta_store", None), "db_path", None)
    if db_path and Path(db_path).exists():
        try:
            conn = create_connection(Path(db_path))
            try:
                return [str(r[0]) for r in conn.execute(
                    "SELECT id FROM nodes WHERE library_id = ?", (library_id,)
                )]
            finally:
                conn.close()
        except sqlite3.Error:
            logger.warning("读取 meta nodes 失败，退回内存: library=%s", library_id, exc_info=True)
    return [str(n.id) for n in getattr(service, "nodes", []) if str(getattr(n, "library_id", "")) == library_id]


def _clear_vectors(service: Any, library_id: str, collection: str, node_ids: List[str]) -> None:
    """共享 collection：一次 filter library_id 删点；其他 provider 回退逐篇。"""
    store = getattr(service, "vector_store", None)
    if store is None:
        return
    if isinstance(store, QdrantVectorStore):
        if collection:
            store.clear_library(library_id, collection=collection)
        return
    for doc_id in node_ids:
        try:
            store.clear_document(doc_id, collection=collection or None)
        except Exception:  # noqa: BLE001 — 非 qdrant provider 的逐篇删除尽力而为
            logger.warning("清理文档向量失败: library=%s doc=%s", library_id, doc_id, exc_info=True)


def _clear_index_rows(service: Any, library_id: str, node_ids: List[str]) -> None:
    from .pg_support import is_pg

    if is_pg():
        # PG 共库：canonical/doc_blocks/segments 按 library_id/doc_id 清（单事务）
        index_store = getattr(service, "index_store", None)
        canonical_store = getattr(service, "canonical_store", None)
        if index_store is None or canonical_store is None:
            return
        conn = canonical_store.connect()
        try:
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS _lib_del_ids(doc_id TEXT PRIMARY KEY)"
            )
            conn.execute("TRUNCATE _lib_del_ids")
            if node_ids:
                conn.executemany(
                    "INSERT INTO _lib_del_ids(doc_id) VALUES (?)",
                    [(doc_id,) for doc_id in node_ids],
                )
                for table in INDEX_CHILD_TABLES:
                    if table == "canonical_vectors":  # SQLite 专属（PG 向量在 vector_records）
                        continue
                    conn.execute(
                        f'DELETE FROM "{table}" WHERE doc_id IN (SELECT doc_id FROM _lib_del_ids)'
                    )
            for table in ("doc_blocks", "document_segments", "doc_block_corrections"):
                if node_ids:
                    conn.execute(
                        f'DELETE FROM "{table}" WHERE doc_id IN (SELECT doc_id FROM _lib_del_ids)'
                    )
            conn.execute("DELETE FROM canonical_documents WHERE library_id = ?", (library_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    db_path = library_registry.resolve_index_db_path(library_id)
    if not db_path.exists():
        return

    def _delete() -> None:
        conn = create_connection(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = {
                str(r[0]) for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS _lib_del_ids(doc_id TEXT PRIMARY KEY)")
            conn.executemany(
                "INSERT OR IGNORE INTO _lib_del_ids(doc_id) VALUES (?)",
                [(doc_id,) for doc_id in node_ids],
            )
            for table in INDEX_CHILD_TABLES:
                if table in existing:
                    conn.execute(
                        f'DELETE FROM "{table}" WHERE doc_id IN (SELECT doc_id FROM _lib_del_ids)'
                    )
            if "canonical_documents" in existing:
                conn.execute(
                    "DELETE FROM canonical_documents WHERE library_id = ?", (library_id,)
                )
            if "doc_catalog" in existing:
                conn.execute("DELETE FROM doc_catalog WHERE library_id = ?", (library_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    run_with_write_lock(db_path, _delete)


def _clear_parse_records(library_id: str) -> None:
    """删除上传台账（parse_records）中该库的行；台账独立于 meta/index。"""
    from .pg_support import is_pg

    if is_pg():
        from .parse_records_store import connect as pr_connect

        conn = pr_connect()
        try:
            conn.execute("DELETE FROM parse_records WHERE library_id = ?", (library_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    from .parse_records_store import db_path

    path = Path(db_path())
    if not path.exists():
        return
    conn = sqlite3.connect(str(path))
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='parse_records'"
        ).fetchone()
        if has:
            conn.execute("DELETE FROM parse_records WHERE library_id = ?", (library_id,))
            conn.commit()
    finally:
        conn.close()


def _clear_meta_rows(service: Any, library_id: str, node_ids: List[str]) -> None:
    from .pg_support import is_pg

    meta_store = getattr(service, "meta_store", None)
    if is_pg():
        if meta_store is None:
            return
        conn = meta_store.connect()
        try:
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS _lib_del_ids(doc_id TEXT PRIMARY KEY)"
            )
            conn.execute("TRUNCATE _lib_del_ids")
            if node_ids:
                conn.executemany(
                    "INSERT INTO _lib_del_ids(doc_id) VALUES (?)",
                    [(doc_id,) for doc_id in node_ids],
                )
                for table in ("parse_task_steps", "parse_stage_steps", "doc_parse_stages"):
                    conn.execute(
                        f'DELETE FROM "{table}" WHERE doc_id IN (SELECT doc_id FROM _lib_del_ids)'
                    )
            conn.execute("DELETE FROM parse_tasks WHERE library_id = ?", (library_id,))
            conn.execute("DELETE FROM nodes WHERE library_id = ?", (library_id,))
            conn.execute("DELETE FROM tree_node WHERE scope_id = ?", (library_id,))
            conn.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    db_path = getattr(meta_store, "db_path", None)
    if not db_path or not Path(db_path).exists():
        return

    def _delete() -> None:
        conn = create_connection(Path(db_path))
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = {
                str(r[0]) for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS _lib_del_ids(doc_id TEXT PRIMARY KEY)")
            conn.executemany(
                "INSERT OR IGNORE INTO _lib_del_ids(doc_id) VALUES (?)",
                [(doc_id,) for doc_id in node_ids],
            )
            for table in ("parse_task_steps", "parse_stage_steps", "doc_parse_stages"):
                if table in existing:
                    conn.execute(
                        f'DELETE FROM "{table}" WHERE doc_id IN (SELECT doc_id FROM _lib_del_ids)'
                    )
            if "parse_tasks" in existing:
                conn.execute("DELETE FROM parse_tasks WHERE library_id = ?", (library_id,))
            if "nodes" in existing:
                conn.execute("DELETE FROM nodes WHERE library_id = ?", (library_id,))
            if "tree_node" in existing:
                conn.execute("DELETE FROM tree_node WHERE scope_id = ?", (library_id,))
            if "libraries" in existing:
                conn.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    run_with_write_lock(Path(db_path), _delete)


def _remove_library_dirs(library_id: str) -> None:
    candidates = [
        library_registry.resolve_libraries_dir(library_id) / library_id,
        resolve_knowledge_base_dir() / "libraries" / library_id,
        library_registry.resolve_data_root() / "knowledge" / "libraries" / library_id,
        library_registry.resolve_data_root() / "evals" / "corpora" / "libraries" / library_id,
    ]
    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_dir():
            for attempt in range(5):
                try:
                    shutil.rmtree(path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    gc.collect()
                    time.sleep(0.25)


def _delete_graph(library_id: str) -> None:
    """删库图谱数据：按库文件整文件删（迁移后）；迁移前全局文件仍在则按行删。"""
    from docs_core.step07_graph.graph_files import (
        global_graph_db_path,
        library_graph_db_path,
    )

    per_lib = library_graph_db_path(library_id)
    if per_lib.exists():
        per_lib.unlink()
        for suffix in ("-wal", "-shm"):
            stale = per_lib.parent / f"{per_lib.name}{suffix}"
            if stale.exists():
                stale.unlink()
    legacy = global_graph_db_path()
    if legacy.exists():
        GraphStore(str(legacy)).delete_library(library_id)


def _registry_refcounts(library_id: str, sqlite_file: str, collection: str) -> tuple[int, int]:
    conn = create_connection(library_registry.resolve_registry_db_path())
    try:
        sql_refs = conn.execute(
            "SELECT COUNT(*) FROM library_registry WHERE library_id <> ? AND sqlite_file = ?",
            (library_id, sqlite_file),
        ).fetchone()[0]
        col_refs = conn.execute(
            "SELECT COUNT(*) FROM library_registry WHERE library_id <> ? AND collection = ?",
            (library_id, collection),
        ).fetchone()[0]
        return int(sql_refs), int(col_refs)
    finally:
        conn.close()


def _is_builtin_bucket(record: library_registry.LibraryRecord) -> bool:
    defaults = library_registry.GROUP_DEFAULTS.get(record.group_name, {})
    if record.sqlite_file == DEFAULT_SQLITE_FILE:
        return True
    if defaults:
        if record.sqlite_file and record.sqlite_file == defaults.get("sqlite_file"):
            return True
        if record.collection and record.collection == defaults.get("collection"):
            return True
    return False


def _maybe_delete_container(
    service: Any, library_id: str, record: Optional[library_registry.LibraryRecord], collection: str
) -> bool:
    """独立桶容器删除；共享桶/内置组桶一律保留。"""
    if record is None or _is_builtin_bucket(record):
        return False
    sqlite_file = str(record.sqlite_file or "")
    if not sqlite_file or not collection:
        return False
    sql_refs, col_refs = _registry_refcounts(library_id, sqlite_file, collection)
    if sql_refs or col_refs:
        return False
    sqlite_path = library_registry.resolve_data_root() / sqlite_file
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            Path(str(sqlite_path) + suffix).unlink(missing_ok=True)
        except OSError:
            logger.warning("删除独立 sqlite 失败: %s", sqlite_path, exc_info=True)
            raise
    store = getattr(service, "vector_store", None)
    if isinstance(store, QdrantVectorStore):
        store.delete_collection(collection)
    return True


def delete_library_data(
    service: Any, library_id: str, *, progress: Optional[Progress] = None
) -> Dict[str, Any]:
    """同步执行删库（runner 与单测共用）；返回 {docs, container_deleted}。"""
    # default 不再特殊（2026-10-29：系统不再自动创建默认库，任何注册库都可删）
    record = library_registry.get_library(library_id)
    # 失败重试：meta 快照可能已清、service 看不到该库，但 registry 还在（deleting）
    if record is None and service.get_library(library_id) is None:
        raise LibraryNotFound(f"知识库不存在: {library_id}")

    collection = (record.collection if record else "") or library_registry.resolve_collection(library_id)
    node_ids = _node_ids(service, library_id)
    total = len(node_ids)

    _notify(progress, "vectors", 0, total)
    if record is not None:
        try:
            library_registry.set_status(library_id, library_registry.STATUS_DELETING)
        except Exception:  # noqa: BLE001 — 注册表缺行时仍允许清数据
            logger.warning("置 deleting 失败: library=%s", library_id, exc_info=True)

    _clear_vectors(service, library_id, collection, node_ids)
    _notify(progress, "index", total, total)
    _clear_index_rows(service, library_id, node_ids)
    _notify(progress, "meta", total, total)
    _clear_parse_records(library_id)
    _clear_meta_rows(service, library_id, node_ids)
    _notify(progress, "files", total, total)
    try:
        service.forget_library_stores(library_id)
    except Exception:  # noqa: BLE001 — fake/旧 service 无此方法
        pass
    gc.collect()
    _remove_library_dirs(library_id)
    _notify(progress, "graph", total, total)
    _delete_graph(library_id)

    service.nodes = [
        node for node in getattr(service, "nodes", [])
        if str(getattr(node, "library_id", "")) != library_id
    ]
    service.libraries = [
        lib for lib in getattr(service, "libraries", [])
        if str(getattr(lib, "id", "")) != library_id
    ]

    _notify(progress, "container", total, total)
    container_deleted = _maybe_delete_container(service, library_id, record, collection)

    if record is not None:
        try:
            library_registry.set_status(library_id, library_registry.STATUS_RETIRED)
        except Exception:  # noqa: BLE001
            logger.warning("置 retired 失败: library=%s", library_id, exc_info=True)
    _notify(progress, "registry", total, total)
    try:
        service.reload_scope_cache()
    except Exception:  # noqa: BLE001 — 刷新失败不应把已完成的删库判失败
        logger.warning("删库后刷新缓存失败: library=%s", library_id, exc_info=True)
    _notify(progress, "done", total, total)
    return {"docs": total, "container_deleted": container_deleted}

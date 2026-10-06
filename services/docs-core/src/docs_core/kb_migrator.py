"""知识库拆分/合并编排器（设计 §5.1-§5.5）。

同组迁移 = 逐 doc 幂等原子单元（文件 move → 组文件改标 → meta 改标 → qdrant 改标 → graph 移动/复制）
+ 全局两阶段（执行 → 对账 → 切换）。回滚 = 反向再跑一遍。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core import library_registry, paths
from docs_core.kb_migration_audit import write_audit
from docs_core.kb_migration_store import KbMigrationStore
from docs_core.parse_records_store import update_library_for_docs
from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection, run_with_write_lock

DEFAULT_LIBRARY_ID = "default"
ROLLBACK_WINDOW_DAYS = 7


class MigrationBlocked(Exception):
    """预览阻断（同组校验/default 保护/迁移中冲突等），路由层转 400。"""


class PreviewStaleError(Exception):
    """提交时 preview_digest 与服务端重算不一致，路由层转 409。"""


class LibraryMigratingError(Exception):
    """库在迁移中，写操作拒绝，路由层转 409。"""


def assert_library_not_migrating(library_id: Optional[str]) -> None:
    """写路径门禁（设计 D6）：migrating 中的库拒绝入库/重解析/移动/删除。"""
    if not library_id:
        return
    record = library_registry.get_library(library_id)
    if record is not None and record.status == library_registry.STATUS_MIGRATING:
        raise LibraryMigratingError(f"知识库 {library_id} 正在迁移，请等待完成后再操作")


@dataclass
class PreviewResult:
    op: str
    source_library_id: str
    target_library_id: str
    doc_ids: List[str]
    new_name: str = ""
    counts: Dict[str, Any] = field(default_factory=dict)
    eval_refs: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    digest: str = ""


class KbMigrator:
    def __init__(self, *, meta_db: Optional[Path] = None, group_db: Optional[Path] = None,
                 graph_db: Optional[Path] = None, evals_db: Optional[Path] = None,
                 libraries_root: Optional[Path] = None, vector_store: Any = None,
                 store: Optional[KbMigrationStore] = None,
                 source_library_id: Optional[str] = None) -> None:
        # source_library_id：生产模式按注册表解析组文件；测试注入 group_db 直给。
        self.meta_db = Path(meta_db) if meta_db else paths.resolve_knowledge_meta_db_path()
        self._group_db_override = Path(group_db) if group_db else None
        self.graph_db = Path(graph_db) if graph_db else paths.resolve_graph_db_path()
        self.evals_db = Path(evals_db) if evals_db else library_registry.resolve_data_root() / "evals" / "evals.sqlite"
        self._libraries_root = libraries_root
        self.vector_store = vector_store  # None = 向量面跳过（测试）
        self.store = store or KbMigrationStore(db_path=self.meta_db)

    # ---- 基础设施 ----
    def group_db_for(self, library_id: str) -> Path:
        if self._group_db_override is not None:
            return self._group_db_override
        return library_registry.resolve_index_db_path(library_id)

    def libraries_root_for(self, library_id: str) -> Path:
        if self._libraries_root is not None:
            return self._libraries_root / library_id
        return paths.library_root(library_id)

    def _graph_store(self):
        from docs_core.step07_graph.graph_store import GraphStore
        return GraphStore(str(self.graph_db))

    # ---- 预览（设计 §5.3 Phase P，只读）----
    def compute_preview(self, *, op: str, source_library_id: str,
                        target_library_id: Optional[str] = None,
                        new_library_id: Optional[str] = None, new_name: str = "",
                        doc_ids: Optional[List[str]] = None) -> PreviewResult:
        blockers = self._check_blockers(op, source_library_id, target_library_id, new_library_id)
        with create_connection(self.meta_db) as conn:
            source_docs = [r[0] for r in conn.execute(
                "SELECT id FROM nodes WHERE library_id=? AND type='document' AND COALESCE(deleted,0)=0",
                (source_library_id,),
            )]
        if op == "merge":
            target = target_library_id
            moved = sorted(source_docs)
        else:
            target = new_library_id
            moved = sorted(doc_ids or [])
            unknown = set(moved) - set(source_docs)
            if unknown:
                blockers.append(f"所选文档不属于源库: {sorted(unknown)[:3]}")
            if not moved:
                blockers.append("至少选择 1 篇文档")
            if len(moved) == len(source_docs) and source_docs:
                blockers.append("已选择全部文档，请改用合并")
        if blockers:
            raise MigrationBlocked("；".join(blockers))
        counts = self._face_counts(source_library_id, target, moved, op)
        counts["fingerprint"] = self._doc_table_fingerprint(source_library_id, moved)  # doc_id 锚定不变量（P0-1 改法）
        eval_refs = self._detect_eval_refs(source_library_id, moved)
        preview = PreviewResult(op=op, source_library_id=source_library_id,
                                target_library_id=target or "", doc_ids=moved,
                                new_name=new_name, counts=counts,
                                eval_refs=eval_refs, blockers=[])
        preview.digest = self._digest(preview)
        write_audit(operator="admin", action="preview",
                    params={"op": op, "source": source_library_id, "target": target,
                            "doc_count": len(moved)},
                    preview_digest=preview.digest, result="ok")
        return preview

    def _check_blockers(self, op: str, source: str, target: Optional[str],
                        new_library_id: Optional[str]) -> List[str]:
        blockers: List[str] = []
        if source == DEFAULT_LIBRARY_ID:
            blockers.append("默认库不支持拆分/合并")
        source_rec = library_registry.get_library(source)
        if source_rec is None:
            blockers.append(f"源库未注册: {source}")
            return blockers
        if source_rec.status == library_registry.STATUS_MIGRATING:
            blockers.append("源库正在迁移中")
        if source_rec.status == library_registry.STATUS_RETIRED:
            blockers.append("源库已停用")
        if op == "merge":
            if not target or target == source:
                blockers.append("合并需指定不同的目标库")
            else:
                target_rec = library_registry.get_library(target)
                if target_rec is None:
                    blockers.append(f"目标库未注册: {target}")
                else:
                    if target_rec.status != library_registry.STATUS_ACTIVE:
                        blockers.append("目标库不是可用状态")
                    if target_rec.group_name != source_rec.group_name:
                        blockers.append("v1 仅支持同组合并（两库组不同）")
        else:
            if not new_library_id:
                blockers.append("缺少新库 ID")
            elif library_registry.get_library(new_library_id) is not None:
                blockers.append(f"新库 ID 已存在: {new_library_id}")
        return blockers

    def _face_counts(self, source: str, target: str, moved: List[str], op: str) -> Dict[str, Any]:
        ph = ",".join("?" for _ in moved) or "''"  # 空集兜底（合并空源库）
        with create_connection(self.meta_db) as conn:
            source_total = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE library_id=? AND type='document' AND COALESCE(deleted,0)=0",
                (source,),
            ).fetchone()[0]
        group_db = self.group_db_for(source)
        with create_connection(group_db) as conn:
            chunks = conn.execute(
                f"SELECT COUNT(*) FROM canonical_chunks c JOIN canonical_documents d ON c.doc_id=d.doc_id "
                f"WHERE d.doc_id IN ({ph})", moved,
            ).fetchone()[0]
        vectors = self._count_vectors(source, moved)
        graph_stats = self._graph_counts(moved)
        files = self._file_counts(source, moved)
        return {
            "docs": {"source_before": source_total, "source_after": source_total - len(moved),
                     "target_before": self._lib_doc_count(target), "target_after": self._lib_doc_count(target) + len(moved)},
            "chunks": {"moved": chunks},
            "vectors": {"moved": vectors},
            "graph": graph_stats,
            "files": files,
        }

    def _lib_doc_count(self, library_id: str) -> int:
        with create_connection(self.meta_db) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE library_id=? AND type='document' AND COALESCE(deleted,0)=0",
                (library_id,),
            ).fetchone()[0]

    def _count_vectors(self, source: str, moved: List[str]) -> int:
        if self.vector_store is None:
            return 0
        collection = library_registry.resolve_collection(source)
        total = 0
        for doc_id in moved:
            total += int(self.vector_store.count_points_for_doc(doc_id, collection=collection))
        return total

    def _graph_counts(self, moved: List[str]) -> Dict[str, int]:
        if not self.graph_db.exists():
            return {"entities": 0, "relations": 0}
        ph = ",".join("?" for _ in moved) or "''"  # 空集兜底，杜绝 IN () 语法错误（评审 P0-1）
        with create_connection(self.graph_db) as conn:
            relations = conn.execute(
                f"SELECT source_id, target_id FROM graph_relations WHERE doc_id IN ({ph})", moved,
            ).fetchall()
            entities = {r[0] for r in relations} | {r[1] for r in relations}
        return {"entities": len(entities), "relations": len(relations)}

    def _file_counts(self, source: str, moved: List[str]) -> Dict[str, int]:
        root = self.libraries_root_for(source) / "documents"
        found = sum(1 for d in moved if (root / d).is_dir())
        return {"doc_dirs": found}

    def _detect_eval_refs(self, source: str, moved: List[str]) -> Dict[str, Any]:
        if not self.evals_db.exists():
            return {"datasets": [], "question_count": 0}
        ph = ",".join("?" for _ in moved)
        with create_connection(self.evals_db) as conn:
            datasets = [dict(zip(("dataset_id", "title"), r)) for r in conn.execute(
                "SELECT dataset_id, title FROM eval_dataset WHERE library_id=?", (source,),
            )]
            q_total = conn.execute(
                "SELECT COUNT(*) FROM eval_question WHERE library_id=?", (source,),
            ).fetchone()[0]
            q_moved = 0
            for (doc_ids_json,) in conn.execute(
                f"SELECT doc_ids FROM eval_question WHERE library_id=?", (source,),
            ):
                try:
                    if set(json.loads(doc_ids_json or "[]")) & set(moved):
                        q_moved += 1
                except json.JSONDecodeError:
                    continue
        return {"datasets": datasets, "question_count": q_total, "questions_on_moved_docs": q_moved}

    @staticmethod
    def _digest(preview: PreviewResult) -> str:
        payload = json.dumps({
            "op": preview.op, "source": preview.source_library_id,
            "target": preview.target_library_id, "doc_ids": preview.doc_ids,
            "counts": preview.counts,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # 组文件 doc 键全表清单：与 scripts/split_sqlite_groups.py:26-38 的 _DOC_TABLES 逐字同步（12 张）
    _DOC_TABLES: tuple = (
        "canonical_documents", "canonical_pages", "canonical_blocks", "canonical_chunks",
        "canonical_tables", "canonical_outlines", "canonical_citation_targets",
        "canonical_chunk_fts", "canonical_vectors", "doc_blocks", "document_segments",
        "doc_block_corrections",
    )

    def _doc_table_fingerprint(self, source: str, doc_ids: List[str]) -> Dict[str, Any]:
        """按 doc_id 锚定的搬迁不变量（二轮评审 P0-1 改法）：逐表行数 + 逐列长度和。

        改标 library_id 不改变这些值 → 预览与对账两侧同形状可比，
        杜绝「按 library_id 查源库恒得 0」的假对账。
        """
        if not doc_ids:
            return {}
        fp: Dict[str, Any] = {}
        with create_connection(self.group_db_for(source)) as conn:
            for table in self._DOC_TABLES:
                try:
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
                except sqlite3.OperationalError:
                    continue
                ph = ",".join("?" for _ in doc_ids)
                try:
                    count = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE doc_id IN ({ph})", doc_ids,
                    ).fetchone()[0]
                    len_sum = 0
                    for c in cols:
                        len_sum += conn.execute(
                            f"SELECT COALESCE(SUM(LENGTH(CAST({c} AS TEXT))), 0) "
                            f"FROM {table} WHERE doc_id IN ({ph})", doc_ids,
                        ).fetchone()[0] or 0
                    fp[table] = {"count": count, "len_sum": len_sum}
                except sqlite3.OperationalError:
                    continue  # 组文件缺表按无数据处理
        return fp

    def assert_preview_fresh(self, preview: PreviewResult) -> None:
        """提交前重算 digest 比对（设计 §5.7 防预览过期）。"""
        fresh = self.compute_preview(
            op=preview.op, source_library_id=preview.source_library_id,
            target_library_id=preview.target_library_id or None,
            new_library_id=preview.target_library_id if preview.op == "split" else None,
            new_name=preview.new_name, doc_ids=preview.doc_ids,
        )
        if fresh.digest != preview.digest:
            raise PreviewStaleError("预览已过期（数据在预览后发生变化），请重新预览")

    # ---- 单 doc 原子单元（设计 §5.3：任一步失败 → 本 doc 内回滚 → 任务报错停）----
    # collection 由 run_task 在任务开始时从源库注册行解析一次传入（评审 P0-2）：
    # 同组同桶恒成立；补偿/回滚方向不再碰注册表，未注册新库也不会回退默认桶。
    def migrate_doc(self, doc_id: str, source: str, target: str, collection: str = "") -> None:
        self._move_doc(doc_id, source, target, collection)

    def rollback_doc(self, doc_id: str, source: str, target: str, collection: str = "") -> None:
        self._move_doc(doc_id, target, source, collection)

    def _move_doc(self, doc_id: str, from_lib: str, to_lib: str, collection: str = "") -> None:
        done: List[str] = []
        try:
            self._move_doc_files(doc_id, from_lib, to_lib)
            done.append("files")
            self._relabel_group_tables(doc_id, to_lib)
            done.append("group")
            self._relabel_meta(doc_id, from_lib, to_lib)
            done.append("meta")
            self._relabel_vectors(doc_id, to_lib, collection)
            done.append("vectors")
            self._move_doc_graph(doc_id, from_lib, to_lib)
            done.append("graph")
        except Exception:
            for face in reversed(done):
                try:
                    self._undo_face(face, doc_id, from_lib, to_lib, collection)
                except Exception:  # noqa: BLE001 — 补偿尽力而为，原异常优先抛出
                    pass
            raise

    def _undo_face(self, face: str, doc_id: str, from_lib: str, to_lib: str, collection: str) -> None:
        if face == "files":
            self._move_doc_files(doc_id, to_lib, from_lib)
        elif face == "group":
            self._relabel_group_tables(doc_id, from_lib)
        elif face == "meta":
            self._relabel_meta(doc_id, to_lib, from_lib)
        elif face == "vectors":
            self._relabel_vectors(doc_id, from_lib, collection)
        elif face == "graph":
            self._move_doc_graph(doc_id, to_lib, from_lib)

    def _move_doc_files(self, doc_id: str, from_lib: str, to_lib: str) -> None:
        src = self.libraries_root_for(from_lib) / "documents" / doc_id
        dst = self.libraries_root_for(to_lib) / "documents" / doc_id
        if src.resolve() == dst.resolve():
            return
        if dst.exists() and not src.exists():
            return  # 幂等：已迁过
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)

    def _relabel_group_tables(self, doc_id: str, to_lib: str) -> None:
        group_db = self.group_db_for(to_lib)
        now = datetime.now().isoformat(timespec="seconds")

        def _write() -> None:
            with create_connection(group_db) as conn:
                conn.execute("UPDATE canonical_documents SET library_id=?, updated_at=? WHERE doc_id=?",
                             (to_lib, now, doc_id))
                conn.execute("UPDATE document_segments SET library_id=?, updated_at=? WHERE doc_id=?",
                             (to_lib, now, doc_id))
        run_with_write_lock(group_db, _write)

    def _relabel_meta(self, doc_id: str, from_lib: str, to_lib: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        old_root = str(self.libraries_root_for(from_lib) / "documents" / doc_id)
        new_root = str(self.libraries_root_for(to_lib) / "documents" / doc_id)

        def _write() -> None:
            with create_connection(self.meta_db) as conn:
                row = conn.execute("SELECT file_path FROM nodes WHERE id=?", (doc_id,)).fetchone()
                file_path = row["file_path"] if row else None
                if file_path and str(file_path).startswith(old_root):
                    file_path = new_root + str(file_path)[len(old_root):]
                elif file_path:
                    # P0-2 认账：file_path 不在旧 doc 目录下（外部上传路径）→ 不改写、留痕告警，
                    # 该 doc 重解析可能报「源文件不存在」，需人工核（AGENTS.md 数据目录迁移契约）
                    import logging
                    logging.getLogger(__name__).warning(
                        "迁移改写跳过: doc=%s file_path 不在旧目录前缀下: %s", doc_id, file_path)
                    file_path = None
                conn.execute("UPDATE nodes SET library_id=?, file_path=COALESCE(?, file_path), updated_at=? "
                             "WHERE id=?", (to_lib, file_path, now, doc_id))
                conn.execute("UPDATE tree_node SET scope_id=?, updated_at=? WHERE node_id=?",
                             (to_lib, now, doc_id))
                conn.execute("UPDATE parse_tasks SET library_id=?, updated_at=? WHERE doc_id=?",
                             (to_lib, now, doc_id))
        run_with_write_lock(self.meta_db, _write)
        update_library_for_docs([doc_id], to_lib)

    def _relabel_vectors(self, doc_id: str, to_lib: str, collection: str) -> None:
        if self.vector_store is None or not collection:
            return
        current = self._payload_library_id(doc_id, collection)
        if current == to_lib:
            return  # 幂等
        self.vector_store.set_payload_by_docs([doc_id], to_lib, collection=collection)

    def _payload_library_id(self, doc_id: str, collection: str) -> Optional[str]:
        # 读一个点的 payload 判幂等；vector_store 无 scroll 接口时退化为总是改标（幂等写无害）
        try:
            from qdrant_client import models
            client = self.vector_store._get_client()
            points, _ = client.scroll(
                collection_name=collection,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
                ),
                limit=1, with_payload=True,
            )
            if points:
                return str((points[0].payload or {}).get("library_id") or "")
        except Exception:  # noqa: BLE001
            return None
        return None

    def _move_doc_graph(self, doc_id: str, from_lib: str, to_lib: str) -> None:
        if not self.graph_db.exists():
            return
        self._graph_store().move_doc_graph(from_lib, to_lib, [doc_id])

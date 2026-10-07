"""知识库拆分/合并编排器（设计 §5.1-§5.5）。

同组迁移 = 逐 doc 幂等原子单元（文件 move → 组文件改标 → meta 改标 → qdrant 改标 → graph 移动/复制）
+ 全局两阶段（执行 → 对账 → 切换）。回滚 = 反向再跑一遍。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
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


def resolve_destination(params: Dict[str, Any]) -> str:
    """目的地解析：拆分=新库或已有库二选一（new_library_id / target_library_id）；合并=目标库。"""
    if params.get("op") == "split":
        return str(params.get("new_library_id") or params.get("target_library_id") or "")
    return str(params.get("target_library_id") or "")


def second_lib_gated(params: Dict[str, Any]) -> bool:
    """任务期间是否还有第二个库上门禁：目的地是「已有库」才有（拆到新库时新库尚不在注册表）。"""
    if "gate_second" in params:
        return bool(params["gate_second"])
    if "rollback_kind" in params:
        # 兼容部署前建的老任务：老形态只有 merge（第二库=原源库）与 split-new（无第二库）
        return params.get("rollback_kind") == "merge"
    return bool(params.get("target_library_id"))


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
    # 拆分到新库时记新库 ID（目的地形态判据：非空=新建、空=并入已有库）；
    # 与 target_library_id 的关系：新建时两者同值，并入已有库时只有 target_library_id
    new_library_id: str = ""
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
            target = target_library_id or ""
            moved = sorted(source_docs)
        else:
            # 目的地二选一（双给/双缺已由 _check_blockers 拦下）
            target = new_library_id or target_library_id or ""
            moved = sorted(doc_ids or [])
            unknown = set(moved) - set(source_docs)
            if unknown:
                blockers.append(f"所选文档不属于源库: {sorted(unknown)[:3]}")
            if not moved:
                blockers.append("至少选择 1 篇文档")
            if len(moved) == len(source_docs) and source_docs:
                if source_library_id == DEFAULT_LIBRARY_ID:
                    # 默认库不能整体合并（是系统兜底库），提示不能指向死路
                    blockers.append("默认库不能整体拆空，请至少保留 1 篇文档")
                else:
                    blockers.append("已选择全部文档，请改用合并")
        if blockers:
            raise MigrationBlocked("；".join(blockers))
        counts = self._face_counts(source_library_id, target, moved, op)
        counts["fingerprint"] = self._doc_table_fingerprint(source_library_id, moved)  # doc_id 锚定不变量（P0-1 改法）
        eval_refs = self._detect_eval_refs(source_library_id, moved)
        preview = PreviewResult(op=op, source_library_id=source_library_id,
                                target_library_id=target or "", doc_ids=moved,
                                new_name=new_name, new_library_id=new_library_id or "",
                                counts=counts,
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
        if op not in ("split", "merge"):
            return [f"未知操作: {op}"]
        if op == "split":
            # 目的地二选一：新库（new_library_id）或已有库（target_library_id）
            if new_library_id and target:
                blockers.append("拆分目的地只能二选一：新建库或并入已有库")
            elif not new_library_id and not target:
                blockers.append("拆分需指定目的地：新建库或并入已有库")
        source_rec = library_registry.get_library(source)
        if source_rec is None:
            blockers.append(f"源库未注册: {source}")
            return blockers
        if source_rec.status == library_registry.STATUS_MIGRATING:
            blockers.append("源库正在迁移中")
        if source_rec.status == library_registry.STATUS_RETIRED:
            blockers.append("源库已停用")
        if op == "merge":
            if source == DEFAULT_LIBRARY_ID:
                # 默认库是匿名/未绑定请求的兜底库：retired 会静默断兜底检索；要腾挪请用拆分
                blockers.append("默认库不支持整体合并，请改用拆分")
            if not target or target == source:
                blockers.append("合并需指定不同的目标库")
            else:
                self._check_destination_blockers(target, source_rec, blockers)
        else:
            if new_library_id:
                if library_registry.get_library(new_library_id) is not None:
                    blockers.append(f"新库 ID 已存在: {new_library_id}")
            elif target == source:
                blockers.append("目标库不能是源库自己")
            else:
                self._check_destination_blockers(target, source_rec, blockers)
        return blockers

    def _check_destination_blockers(self, target: str, source_rec: Any,
                                    blockers: List[str]) -> None:
        """已有库目的地共用校验：可迁移、同组、非默认库（默认库只出不进）。"""
        if target == DEFAULT_LIBRARY_ID:
            blockers.append("默认库不支持作为迁移目标")
            return
        target_rec = library_registry.get_library(target)
        if target_rec is None:
            blockers.append(f"目标库未注册: {target}")
            return
        if target_rec.status != library_registry.STATUS_ACTIVE:
            blockers.append("目标库不是可用状态")
        if target_rec.group_name != source_rec.group_name:
            blockers.append("v1 仅支持同组迁移（两库组不同）")

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
            # 目的地形态入 digest：同 ID 的「新建」与「并入已有库」语义不同（退役与否），不可互认
            "destination_new": bool(preview.new_library_id),
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

    # 迁移有意改写的列，不计入长度和不变量（施工修：计划稿「改标不改变这些值」的前提
    # 对 updated_at/library_id 两列不成立——迁移恰恰会重写它们）
    _FP_EXCLUDE_COLS = ("updated_at", "library_id")

    def _doc_table_fingerprint(self, source: str, doc_ids: List[str]) -> Dict[str, Any]:
        """按 doc_id 锚定的搬迁不变量（二轮评审 P0-1 改法）：逐表行数 + 内容列长度和。

        预览与对账两侧同形状可比，杜绝「按 library_id 查源库恒得 0」的假对账；
        排除列见 _FP_EXCLUDE_COLS（迁移有意重写，非搬迁内容）。
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
                        if c in self._FP_EXCLUDE_COLS:
                            continue
                        len_sum += conn.execute(
                            f"SELECT COALESCE(SUM(LENGTH(CAST({c} AS TEXT))), 0) "
                            f"FROM {table} WHERE doc_id IN ({ph})", doc_ids,
                        ).fetchone()[0] or 0
                    fp[table] = {"count": count, "len_sum": len_sum}
                except sqlite3.OperationalError:
                    continue  # 组文件缺表按无数据处理
        return fp

    def assert_preview_fresh(self, preview: PreviewResult) -> None:
        """提交前重算 digest 比对（设计 §5.7 防预览过期）。目的地按形态回填，双给会被 blockers 拦。"""
        fresh = self.compute_preview(
            op=preview.op, source_library_id=preview.source_library_id,
            target_library_id=None if preview.new_library_id else (preview.target_library_id or None),
            new_library_id=preview.new_library_id or None,
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

    # ---- 主循环（设计 §5.3 全局两阶段 + 评审 P0-3 显式回滚分支）----
    def run_task(self, task_id: str, *, operator: str = "admin") -> None:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"迁移任务不存在: {task_id}")
        params = task["params"]
        if task["op"] == "rollback":
            self._run_rollback(task, operator)
            return
        op = params["op"]
        source = params["source_library_id"]
        target = resolve_destination(params)
        # P0-1：doc_ids 三层兜底——params（提交时落入）→ 任务行 preview → merge 现查源库全部文档
        doc_ids = list(params.get("doc_ids") or (task.get("preview") or {}).get("doc_ids") or [])
        if not doc_ids and op == "merge":
            with create_connection(self.meta_db) as conn:
                doc_ids = sorted(r[0] for r in conn.execute(
                    "SELECT id FROM nodes WHERE library_id=? AND type='document' AND COALESCE(deleted,0)=0",
                    (source,),
                ))
        if not doc_ids:
            self.store.update_task(task_id, status="failed", error="文档集合为空，无可迁移内容")
            return
        # P0-2：桶在任务开始时解析一次（同组同桶恒成立），全程不再碰注册表
        source_rec = library_registry.get_library(source)
        collection = source_rec.collection if source_rec else ""
        try:
            self._gate_libraries(source, target if second_lib_gated(params) else None, on=True)
            migrated = set(task["migrated_doc_ids"])
            for doc_id in doc_ids:
                if self.store.is_cancel_requested(task_id):
                    self._compensate(task_id, source, target, collection, operator)
                    return
                if doc_id in migrated:
                    continue  # 幂等续跑跳过
                self.migrate_doc(doc_id, source, target, collection)
                self.store.mark_doc_migrated(task_id, doc_id)
                self.store.append_step(task_id, "execute", f"{doc_id} 迁移完成")
            if self.store.is_cancel_requested(task_id):
                self._compensate(task_id, source, target, collection, operator)
                return
            self.store.update_task(task_id, stage="verify")
            # 施工修：_verify 原从 params 重推 doc_ids，merge 任务 params 无此键 → 空集假对账；
            # 执行侧已解析的有效 doc_ids 显式传入
            verify = self._verify(params, task.get("preview"), collection, doc_ids=doc_ids)
            self.store.update_task(task_id, verify=verify)
            if not verify["ok"]:
                raise RuntimeError(f"对账不一致: {verify['mismatches']}")
            self._switch(params, task_id, operator)
            # _switch 内部失败已自行标 switch_reload_failed 并 return（评审 P2），不抛进本 except
            if self.store.get_task(task_id)["status"] == "switch_reload_failed":
                return
            self.store.update_task(
                task_id, status="completed", stage="switch", stage_message="迁移完成",
                rollback_deadline=(datetime.now() + timedelta(days=ROLLBACK_WINDOW_DAYS)).isoformat(timespec="seconds"),
            )
            write_audit(operator=operator, action="switch", params=params,
                        verify_digest=verify.get("digest"), result="completed")
        except Exception as exc:
            self.store.update_task(task_id, status="failed", error=str(exc), stage_message=str(exc))
            write_audit(operator=operator, action="switch", params=params, result="failed", error=str(exc))
            try:
                self._gate_libraries(source, target if second_lib_gated(params) else None, on=False)
            except Exception:  # noqa: BLE001
                pass
            raise

    def _run_rollback(self, task: Dict[str, Any], operator: str) -> None:
        """回滚分支（评审 P0-3）：全程禁止 register_library——它是 7 列覆盖 upsert，只允许在拆分切换时刻注册新库。

        doc_ids 取法（三条规则，提交时已落进 params）：
        - 拆分到新库回滚 = 新库当前全部文档（migrated + 增量，业主已确认增量一并带走）
        - 拆分入已有库回滚 = 原任务行 migrated_doc_ids（目标库自有文档绝不动）
        - 合并回滚 = 原任务行 migrated_doc_ids（目标库自有文档绝不动）
        注册表收尾：拆到新库回滚=新库 retired；拆入已有库回滚=目标库不退役、双方回 active；
        合并回滚=源库回 active（A 行从未消失，只是 retired）。
        """
        params = task["params"]
        task_id = task["id"]  # N①修正：原代码未绑定 task_id，下文引用必 NameError
        original_source = params["original_source_library_id"]
        new_lib = params["library_id"]           # 拆分的新库/已有库目的地 / 合并的源库 A
        rollback_kind = params["rollback_kind"]  # split | merge
        destination_is_new = bool(params.get("destination_is_new", True))
        doc_ids = list(params.get("doc_ids") or [])
        collection = params.get("collection", "")
        try:
            self._gate_libraries(new_lib, original_source if second_lib_gated(params) else None, on=True)
            verify_before = self._verify(
                {"op": "split", "source_library_id": new_lib, "new_library_id": original_source,
                 "doc_ids": doc_ids}, None, collection)  # 回滚前各面计数落 verify（兑现 spec §5.5「同样预览+对账」）
            migrated = set(task["migrated_doc_ids"])
            for doc_id in doc_ids:
                if self.store.is_cancel_requested(task_id):
                    self._compensate(task_id, new_lib, original_source, collection, operator)
                    return
                if doc_id in migrated:
                    continue
                self.rollback_doc(doc_id, original_source, new_lib, collection)
                self.store.mark_doc_migrated(task_id, doc_id)
                self.store.append_step(task_id, "rollback", f"{doc_id} 已撤回")
            verify_after = self._verify(
                {"op": "split", "source_library_id": new_lib, "new_library_id": original_source,
                 "doc_ids": doc_ids}, None, collection)
            verify_after["before"] = verify_before.get("digest")
            self.store.update_task(task_id, verify=verify_after)
            if not verify_after["ok"]:
                raise RuntimeError(f"回滚对账不一致: {verify_after['mismatches']}")
            # 注册表收尾（禁止 register_library）
            if rollback_kind == "split":
                if destination_is_new:
                    library_registry.set_status(new_lib, library_registry.STATUS_RETIRED)
                else:
                    # 并入已有库回滚：目标库是别人的库，绝不退役，放回可用
                    library_registry.set_status(new_lib, library_registry.STATUS_ACTIVE)
                library_registry.set_status(original_source, library_registry.STATUS_ACTIVE)
            else:
                # 合并回滚：源库 A 回 active；当前持有方 B 从 migrating 门禁放回 active
                library_registry.set_status(original_source, library_registry.STATUS_ACTIVE)
                library_registry.set_status(new_lib, library_registry.STATUS_ACTIVE)
            try:
                from docs_core.docs_service import get_docs_service
                get_docs_service().reload_scope_cache()
            except Exception as exc:  # noqa: BLE001
                self.store.update_task(task_id, status="switch_reload_failed",
                                       error=f"reload_scope_cache 失败，请重启 docs-api 容器: {exc}")
                write_audit(operator=operator, action="rollback", params=params,
                            result="switch_reload_failed", error=str(exc))
                return
            self.store.update_task(task_id, status="completed", stage="rollback",
                                   stage_message="回滚完成")
            write_audit(operator=operator, action="rollback", params=params,
                        verify_digest=verify_after.get("digest"), result="completed")
        except Exception as exc:
            self.store.update_task(task_id, status="failed", error=str(exc), stage_message=str(exc))
            # N2 修正：回滚异常按方向恢复门禁，避免库锁死 migrating
            try:
                if rollback_kind == "merge":
                    library_registry.set_status(original_source, library_registry.STATUS_RETIRED)
                    library_registry.set_status(new_lib, library_registry.STATUS_ACTIVE)
                else:
                    library_registry.set_status(new_lib, library_registry.STATUS_ACTIVE)
                    if not destination_is_new:
                        # 并入已有库回滚失败：原源库也放回 active，别锁死成 migrating
                        library_registry.set_status(original_source, library_registry.STATUS_ACTIVE)
            except Exception:  # noqa: BLE001
                pass
            write_audit(operator=operator, action="rollback", params=params, result="failed", error=str(exc))
            raise

    def _compensate(self, task_id: str, source: str, target: str, collection: str, operator: str) -> None:
        """取消 = doc 边界停止 + 自动反向补偿已迁 doc（设计 D10）。"""
        task = self.store.get_task(task_id)
        failed = False
        for doc_id in list(task["migrated_doc_ids"]):
            try:
                self.rollback_doc(doc_id, source, target, collection)
                self.store.unmark_doc_migrated(task_id, doc_id)
            except Exception as exc:  # noqa: BLE001
                failed = True
                self.store.append_step(task_id, "rollback", f"{doc_id} 补偿失败: {exc}", status="failed")
        params = task["params"]
        try:
            # N2 修正：第二库判定兼容回滚任务（rollback_params 没有 target_library_id），统一走 second_lib_gated
            self._gate_libraries(source, target if second_lib_gated(params) else None, on=False)
        finally:
            status = "cancel_failed" if failed else "cancelled"
            self.store.update_task(task_id, status=status, stage="rollback",
                                   stage_message="已取消并回滚" if not failed else "取消补偿部分失败，需人工介入")
            write_audit(operator=operator, action="cancel", params=params, result=status)

    def _gate_libraries(self, source: str, target: Optional[str], *, on: bool) -> None:
        for lib in filter(None, (source, target)):
            library_registry.set_status(
                lib, library_registry.STATUS_MIGRATING if on else library_registry.STATUS_ACTIVE,
            )

    def _verify(self, params: Dict[str, Any], preview: Optional[Dict[str, Any]],
                collection: str = "", doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """逐面对比实际 vs 预览（设计 §5.3 Phase V + 评审 P2 补向量/文件两面）。

        doc_ids 显式传入优先；未传才回退 params（merge 提交体不带 doc_ids，
        靠回退会拿空集做指纹/文件面 → 假对账）。
        """
        source = params["source_library_id"]
        target = resolve_destination(params)
        doc_ids = list(doc_ids if doc_ids is not None else (params.get("doc_ids") or []))
        mismatches: List[str] = []
        actual_target_docs = self._lib_doc_count(target)
        expected = (preview or {}).get("counts", {}).get("docs", {}).get("target_after")
        if expected is not None and actual_target_docs != expected:
            mismatches.append(f"docs: 目标库实际 {actual_target_docs} != 预览 {expected}")
        ph = ",".join("?" for _ in doc_ids) or "''"
        with create_connection(self.group_db_for(source)) as conn:
            relabeled = conn.execute(
                f"SELECT COUNT(*) FROM canonical_documents WHERE library_id=? AND doc_id IN ({ph})",
                [target, *doc_ids],
            ).fetchone()[0]
        # 预期数取预览指纹里 canonical_documents 的实际行数：未解析/解析失败的文档本来就没有这一行，
        # 拿 len(doc_ids) 去比会把「迁对了」判成假失败（2026-10-07 生产实踩：默认库拆 2 篇、1 篇无 canonical 行）
        expected_group = (((preview or {}).get("counts", {}).get("fingerprint", {}) or {})
                          .get("canonical_documents", {}) or {}).get("count")
        if expected_group is None:
            expected_group = len(doc_ids)
        if relabeled != expected_group:
            mismatches.append(f"group: 组文件改标 {relabeled}/{expected_group}")
        if self.graph_db.exists():
            with create_connection(self.graph_db) as conn:
                moved_rel = conn.execute(
                    f"SELECT COUNT(*) FROM graph_relations WHERE library_id=? AND doc_id IN ({ph})",
                    [target, *doc_ids],
                ).fetchone()[0]
            graph = self._graph_counts(doc_ids)
            if moved_rel != graph["relations"]:
                mismatches.append(f"graph: 关系改标 {moved_rel}/{graph['relations']}")
        # 向量面（评审 P2：缺这面 P0-2 类漏迁永远不可发现）
        if self.vector_store is not None and collection:
            expected_vectors = (preview or {}).get("counts", {}).get("vectors", {}).get("moved")
            actual_vectors = sum(
                int(self.vector_store.count_points_for_doc(d, collection=collection)) for d in doc_ids)
            if expected_vectors is not None and actual_vectors != expected_vectors:
                mismatches.append(f"vectors: 实际 {actual_vectors} != 预览 {expected_vectors}")
        # 文件面
        files_found = self._file_counts(target, doc_ids)["doc_dirs"]
        expected_files = (preview or {}).get("counts", {}).get("files", {}).get("doc_dirs")
        if expected_files is not None and files_found != expected_files:
            mismatches.append(f"files: 目标目录 {files_found} != 预览 {expected_files}")
        # 搬迁不变量（P0-1 改法）：fingerprint 逐表比对——改标 library_id 不影响行数/列长和，必须全等
        expected_fp = (preview or {}).get("counts", {}).get("fingerprint")
        if expected_fp is not None:
            actual_fp = self._doc_table_fingerprint(source, doc_ids)
            for table, exp in expected_fp.items():
                act = actual_fp.get(table)
                if act != exp:
                    mismatches.append(f"fingerprint.{table}: 实际 {act} != 预览 {exp}")
        digest = hashlib.sha256(json.dumps(
            {"target_docs": actual_target_docs, "relabeled": relabeled, "files": files_found},
            sort_keys=True).encode()).hexdigest()
        return {"ok": not mismatches, "mismatches": mismatches, "digest": digest}

    def _switch(self, params: Dict[str, Any], task_id: str, operator: str) -> None:
        """原子切换（设计 §5.5）：拆到新库=此刻才注册新库 + meta libraries 行；拆入已有库=只放行两端门禁；
        合并=源库 retired。

        reload 失败：标 switch_reload_failed 并 return（评审 P2），不抛进 run_task 通用 except——
        避免「failed 覆写 + 把已 retired 源库拉回 active」的中间态。
        """
        op = params["op"]
        source = params["source_library_id"]
        source_rec = library_registry.get_library(source)
        try:
            from docs_core.docs_service import KnowledgeLibrary, get_docs_service
            ks = get_docs_service()
            if op == "split":
                new_lib = params.get("new_library_id")
                if new_lib:
                    library_registry.register_library(
                        new_lib, name=params.get("new_name") or new_lib,
                        group_name=source_rec.group_name, sqlite_file=source_rec.sqlite_file,
                        collection=source_rec.collection, status=library_registry.STATUS_ACTIVE,
                    )
                    # meta libraries 行（spec 面 5；list_libraries 读穿 meta，缺这行新库对读方不可见）
                    ks.meta_store.upsert_library(KnowledgeLibrary(
                        id=new_lib, name=params.get("new_name") or new_lib))
                else:
                    # 并入已有库：目的地已在注册表，无新库登记；切换=放行目标库门禁
                    library_registry.set_status(params["target_library_id"],
                                                library_registry.STATUS_ACTIVE)
                library_registry.set_status(source, library_registry.STATUS_ACTIVE)
            else:
                target = params["target_library_id"]
                library_registry.set_status(target, library_registry.STATUS_ACTIVE)
                library_registry.set_status(source, library_registry.STATUS_RETIRED)
            # 运行中进程内存一致性（D5）
            ks.reload_scope_cache()
        except Exception as exc:  # noqa: BLE001
            self.store.update_task(task_id, status="switch_reload_failed",
                                   error=f"切换失败，请重启 docs-api 容器后核对: {exc}")
            write_audit(operator=operator, action="switch", params=params,
                        result="switch_reload_failed", error=str(exc))
            return


# ---- 后台任务执行器（设计 §5.4，克隆解析任务模式，不发明新框架）----
class KbMigrationRunner:
    def __init__(self, migrator: Optional["KbMigrator"] = None) -> None:
        self.migrator = migrator or KbMigrator()
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def _has_live_task(self) -> bool:
        return any(t.is_alive() for t in self._threads.values())

    def submit(self, task_id: str, *, operator: str = "admin") -> threading.Thread:
        """全局单飞：同一时间只允许一个迁移任务（设计 §5.4 互斥）。

        返回线程句柄——_run 收尾会把任务从 _threads 自摘，调用方（含测试）
        必须拿返回值 join，不能按下标回读字典（施工修：计划测试按下标读有竞态）。
        """
        with self._lock:
            if self._has_live_task():
                raise MigrationBlocked("已有迁移任务在运行，请等待完成")
            worker = threading.Thread(
                target=self._run, args=(task_id, operator), daemon=True, name=f"kb-migration-{task_id}",
            )
            self._threads[task_id] = worker
            worker.start()
            return worker

    def _run(self, task_id: str, operator: str) -> None:
        try:
            self.migrator.run_task(task_id, operator=operator)
        except Exception:  # noqa: BLE001 — run_task 内部已落任务行 error/audit
            pass
        finally:
            self._threads.pop(task_id, None)

    def request_cancel(self, task_id: str) -> None:
        self.migrator.store.request_cancel(task_id)

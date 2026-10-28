"""语料包导出核心 v2：大包（bundle）套每库自包含小包（library），流式不落盘。

产出形态：
- ``iter_bundle_zip``   流式 zip 字节（管理后台：边读边出网，服务端不落盘）
- ``build_bundle``      落盘 zip（CLI：``scripts/kb_corpus_export.py``）

包结构（v2 定版，两侧契约）：
    外层 <组名>-<日期>.zip（ZIP_STORED，流式嵌套）
    ├─ manifest.json                 # kind=bundle/schema_version=2；libraries[]（entry/sha256/bytes/counts）
    └─ libraries/<library_id>.zip    # 每库自包含小包（可单独交付/单独导入）
         ├─ manifest.json            # kind=library；counts{docs,chunks,vectors,graph_relations,graph_tables}
         ├─ registry/rows.json       # 本库 registry 行（原 sqlite_file/collection 供追溯）+ 其组行
         ├─ meta/rows.json           # 本库 nodes/tree_node + meta libraries 行（修 F10 缺口）
         ├─ index/index.sqlite       # 组 sqlite 按库切片（corpus_slicing）
         ├─ files/…                  # 文档树（排除 parsed/{mineru_raw,popo} 与 lib 根 index/graph sqlite 及边车）
         ├─ qdrant/vectors.snapshot  # 本库向量快照（临时 collection 拷贝或独占直取）
         └─ graph/graph.sqlite       # 本库图谱闭包切片（corpus_slicing）

嵌套流式契约（P1-1 spike 结论，py3.11.17/3.12.6 双端实测）：
内层 zip 写进外层 entry 写句柄（_CountingSink，无 tell/seek）→ zipfile 自动走 data descriptor
路径，无需临时落盘；manifest 排最后（sha256 边流边算）；force_zip64 默认开。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional, Sequence, Tuple
from urllib import request as urlrequest

from .kb_migrator import assert_library_not_migrating
from .library_registry import (
    REGISTRY_DB_NAME,
    resolve_data_root,
    resolve_libraries_dir,
)
from .paths import resolve_knowledge_base_dir

EXPORT_SCHEMA_VERSION = 2
PAGE_BASE = 0  # canonical 页码 0-based，交付说明写死
DEFAULT_EXCLUDE_DIRS: Tuple[str, ...] = ("mineru_raw", "popo")
_READ_CHUNK = 1 << 20

# qdrant 快照体积经验系数（字节/点）：仅供预览估算；正式进度分母用快照创建响应里的真实 size。
SNAPSHOT_BYTES_PER_POINT = 7000


class ExportCancelled(Exception):
    """调用方请求取消（zips 流中途停止，勿当错误上报）。"""


# ---------------------------------------------------------------- 基础读取


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def embed_model_from_env() -> str:
    raw = os.getenv("EMBEDDING_CONFIGS", "").strip()
    if not raw:
        return ""
    try:
        first = json.loads(raw)[0]
    except (ValueError, IndexError):
        return ""
    return str(first.get("model") or first.get("model_name") or "")


def read_registry(data_root: Path, libs: Sequence[str]) -> Tuple[List[dict], List[dict]]:
    """读 registry 行。只读用途开普通连接：URI mode=ro 对非 ASCII 路径（中文用户目录）打不开（实踩）。"""
    with closing(sqlite3.connect(data_root / REGISTRY_DB_NAME)) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" * len(libs))
        libraries = [dict(r) for r in conn.execute(f"SELECT * FROM library_registry WHERE library_id IN ({marks})", list(libs))]
        missing = sorted(set(libs) - {row["library_id"] for row in libraries})
        if missing:
            raise ValueError(f"registry 缺行: {missing}")
        groups_found = sorted({row["group_name"] for row in libraries})
        gmarks = ",".join("?" * len(groups_found))
        groups = [dict(r) for r in conn.execute(f"SELECT * FROM library_groups WHERE group_name IN ({gmarks})", groups_found)]
    return libraries, groups


def read_meta_rows(data_root: Path, libs: Sequence[str]) -> Dict[str, list]:
    """共享 meta 库按 library_id 摘行：nodes/tree_node + libraries 行（F10 缺口：旧版不带 libraries）。"""
    meta_db = data_root / "knowledge" / "knowledge_meta.sqlite"
    if not meta_db.exists():
        raise ValueError(f"meta 库不存在: {meta_db}")
    with closing(sqlite3.connect(meta_db)) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" * len(libs))
        nodes = [dict(r) for r in conn.execute(f"SELECT * FROM nodes WHERE library_id IN ({marks})", list(libs))]
        tree = [dict(r) for r in conn.execute(f"SELECT * FROM tree_node WHERE scope_id IN ({marks})", list(libs))]
        has_libraries = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='libraries'").fetchone()
        lib_rows = (
            [dict(r) for r in conn.execute(f"SELECT * FROM libraries WHERE id IN ({marks})", list(libs))]
            if has_libraries else []
        )
    return {"nodes": nodes, "tree_nodes": tree, "libraries": lib_rows}


def _iter_doc_files(lib_root: Path, exclude_dirs: Sequence[str]) -> Iterator[Tuple[Path, str, int]]:
    """库目录下全部文件 → (绝对路径, 相对库根 POSIX 路径, 字节数)。

    跳过 documents/<doc_id>/parsed/<exclude> 整棵：mineru_raw/popo 只在重解析时被读
    （parse_pipeline 的 stage 输入），检索链只查 sqlite+qdrant，不进包（省 ~2.2GB/库）。

    用 os.scandir 而非 Path.rglob：DirEntry 自带目录项里已读到的 stat（Windows 上无需再逐个
    stat），25500 文件的库实测把「遍历 + 取大小」从 ~1.5s 压到 ~0.2s——预览要等这一步。
    """
    exclude = set(exclude_dirs)
    root_len = len(str(lib_root)) + 1
    stack = [str(lib_root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    rel = entry.path[root_len:].replace("\\", "/")
                    parts = rel.split("/")
                    if len(parts) >= 4 and parts[0] == "documents" and parts[2] == "parsed" and parts[3] in exclude:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        yield Path(entry.path), rel, entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue


def _is_lib_root_sqlite(rel_in_lib: str) -> bool:
    """lib 根的 index.sqlite*/graph.sqlite*——专条切片通道已进包（index/、graph/），
    原样再进 files/ 既重复计数、WAL/SHM 边车又会在流式拷贝中途蒸发炸断
    （2026-10-28 生产实踩 FileNotFoundError graph.sqlite-wal）。"""
    return "/" not in rel_in_lib and rel_in_lib.startswith(("index.sqlite", "graph.sqlite"))


def checkpoint_sqlite(path: Path) -> None:
    """WAL 落盘：不 checkpoint 拷出去/读出去都缺最近写入。连接必须关（Windows 文件锁）。"""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _library_counts_and_estimates(data_root: Path, libraries: Sequence[dict]
                                  ) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
    """逐库 (docs,chunks) 计数 + 组库体积占比估算（仅参考值，FTS 体积与 chunk 数不成线性，不设门槛）。"""
    counts = {row["library_id"]: {"docs": 0, "chunks": 0} for row in libraries}
    estimates = {row["library_id"]: 0 for row in libraries}
    dbs: Dict[str, List[dict]] = {}
    for row in libraries:
        dbs.setdefault(str(row["sqlite_file"]), []).append(row)
    for rel, db_rows in dbs.items():
        db_path = Path(data_root) / rel
        db_counts: Dict[str, Dict[str, int]] = {}
        if db_path.exists():
            try:
                with closing(sqlite3.connect(db_path)) as conn:
                    for lib_id, n in conn.execute(
                            "SELECT library_id, COUNT(*) FROM canonical_documents GROUP BY library_id"):
                        db_counts.setdefault(str(lib_id), {"docs": 0, "chunks": 0})["docs"] = int(n)
                    for lib_id, n in conn.execute(
                            "SELECT d.library_id, COUNT(*) FROM canonical_chunks c "
                            "JOIN canonical_documents d ON c.doc_id = d.doc_id GROUP BY d.library_id"):
                        db_counts.setdefault(str(lib_id), {"docs": 0, "chunks": 0})["chunks"] = int(n)
            except sqlite3.Error:
                db_counts = {}
        total_chunks = sum(v["chunks"] for v in db_counts.values())
        db_size = db_path.stat().st_size if db_path.exists() else 0
        for row in db_rows:
            lib_id = row["library_id"]
            counts[lib_id] = db_counts.get(lib_id, {"docs": 0, "chunks": 0})
            share = (counts[lib_id]["chunks"] / total_chunks) if total_chunks else 0.0
            estimates[lib_id] = int(db_size * share)
    return counts, estimates


def _library_doc_prefixes(library_id: str, data_root: Path) -> List[str]:
    """该库文档树相对 data 根的合法前缀（按组解析；兼容 knowledge_base 旧布局）。"""
    doc_root = resolve_libraries_dir(library_id) / library_id / "documents"
    prefixes: List[str] = []
    for base in (data_root, resolve_knowledge_base_dir()):
        try:
            rel = doc_root.resolve().relative_to(base.resolve()).as_posix()
        except (ValueError, OSError):
            continue
        prefix = rel.rstrip("/") + "/"
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _file_path_warnings(nodes: Sequence[dict], data_root: Optional[Path] = None) -> List[str]:
    """file_path 守卫（数据迁移契约 Stage A）：按库根判断 POSIX 相对路径。

    knowledge 组的合法前缀是 ``knowledge/libraries/<lib>/documents/``，evals 组是
    ``evals/corpora/libraries/<lib>/documents/``（F22）。绝对路径/反斜杠/他库前缀仍告警。
    """
    warnings: List[str] = []
    root = Path(data_root) if data_root is not None else resolve_data_root()
    prefix_cache: Dict[str, List[str]] = {}
    for row in nodes:
        path = str(row.get("file_path") or "")
        if not path:
            continue
        lib_id = str(row.get("library_id") or "")
        if lib_id not in prefix_cache:
            prefix_cache[lib_id] = _library_doc_prefixes(lib_id, root)
        ok = (
            "\\" not in path
            and not path.startswith("/")
            and ":" not in path
            and any(path.startswith(prefix) for prefix in prefix_cache[lib_id])
        )
        if not ok:
            warnings.append(
                f"nodes 行 {row.get('id')} 的 file_path 非规范相对路径（Stage A 相对化契约）: {path}")
    return warnings


def _meta_for_lib(meta_rows: Dict[str, list], lib_id: str) -> Dict[str, list]:
    return {
        "nodes": [r for r in meta_rows.get("nodes", []) if str(r.get("library_id") or "") == lib_id],
        "tree_nodes": [r for r in meta_rows.get("tree_nodes", []) if str(r.get("scope_id") or "") == lib_id],
        "libraries": [r for r in meta_rows.get("libraries", []) if str(r.get("id") or "") == lib_id],
    }


# ---------------------------------------------------------------- qdrant REST


def _qdrant_base(qdrant_url: Optional[str] = None) -> str:
    return (qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")).rstrip("/")


def count_points_filtered(collection: str, library_id: str, qdrant_url: Optional[str] = None) -> int:
    """本库点数（REST count + library_id 过滤）。估算/对账用途，失败返回 0 不阻断。"""
    base = _qdrant_base(qdrant_url)
    body = json.dumps({
        "filter": {"must": [{"key": "library_id", "match": {"value": library_id}}]},
        "exact": True,
    }).encode("utf-8")
    req = urlrequest.Request(
        f"{base}/collections/{collection}/points/count", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            return int(json.load(resp).get("result", {}).get("count") or 0)
    except Exception:  # noqa: BLE001 — 估算失败不阻断预览
        return 0


def create_snapshot(collection: str, qdrant_url: Optional[str] = None) -> Tuple[str, int]:
    """建快照并返回 (name, size)。size 是真实字节数——进度分母用它，不用估算。"""
    base = _qdrant_base(qdrant_url)
    req = urlrequest.Request(f"{base}/collections/{collection}/snapshots", method="POST")
    with urlrequest.urlopen(req, timeout=600) as resp:
        result = json.load(resp)["result"]
    return str(result["name"]), int(result.get("size") or 0)


def delete_snapshot(collection: str, name: str, qdrant_url: Optional[str] = None) -> None:
    base = _qdrant_base(qdrant_url)
    req = urlrequest.Request(f"{base}/collections/{collection}/snapshots/{name}", method="DELETE")
    try:
        with urlrequest.urlopen(req, timeout=60):
            pass
    except Exception:  # noqa: BLE001 — 清理失败不影响导出结果
        pass


def open_snapshot(collection: str, name: str, qdrant_url: Optional[str] = None):
    base = _qdrant_base(qdrant_url)
    return urlrequest.urlopen(f"{base}/collections/{collection}/snapshots/{name}", timeout=600)


# ---------------------------------------------------------------- 预览（逐库明细）


def scan_selection(data_root: Path, libs: Sequence[str], *,
                   exclude_dirs: Sequence[str] = DEFAULT_EXCLUDE_DIRS,
                   qdrant_url: Optional[str] = None) -> Dict[str, Any]:
    """预览：逐库明细（files 字节/ sqlite 估算/ vector_points/ snapshot 估算/ counts）+ 总量。

    v2 无同组闸、无 peers 警告（每库自包含）；估算仅参考，最终以包内 manifest 实测 bytes 为准。
    """
    data_root = Path(data_root).resolve()
    libraries, _groups = read_registry(data_root, libs)
    for row in libraries:
        assert_library_not_migrating(row["library_id"])

    counts_map, est_map = _library_counts_and_estimates(data_root, libraries)
    details: List[dict] = []
    for row in libraries:
        lib_id = row["library_id"]
        lib_root = resolve_libraries_dir(lib_id) / lib_id
        files_bytes = 0
        file_count = 0
        if lib_root.is_dir():
            for _path, rel_in_lib, size in _iter_doc_files(lib_root, exclude_dirs):
                if _is_lib_root_sqlite(rel_in_lib):
                    continue  # lib 根 index/graph sqlite 及边车走专条切片，不进 files/
                files_bytes += size
                file_count += 1
        points = count_points_filtered(str(row["collection"]), lib_id, qdrant_url)
        details.append({
            "library_id": lib_id,
            "name": row.get("name", ""),
            "group_name": row.get("group_name", ""),
            "collection": row.get("collection", ""),
            "files_bytes": files_bytes,
            "file_count": file_count,
            "sqlite_estimate": est_map.get(lib_id, 0),
            "vector_points": points,
            "snapshot_estimate": points * SNAPSHOT_BYTES_PER_POINT,
            "counts": counts_map.get(lib_id, {"docs": 0, "chunks": 0}),
        })
    totals = {key: sum(d[key] for d in details) for key in (
        "files_bytes", "file_count", "sqlite_estimate", "vector_points", "snapshot_estimate")}
    totals["total_estimate"] = totals["files_bytes"] + totals["sqlite_estimate"] + totals["snapshot_estimate"]
    return {
        "embed_model": embed_model_from_env(),
        "libraries": details,
        "totals": totals,
        "warnings": [],
    }


# ---------------------------------------------------------------- 流式 bundle


class _ZipSink:
    """非 seekable 写目标：把 zip 产出推给生成器消费（zipfile 自动用 data descriptor）。"""

    def __init__(self, cancelled: Callable[[], bool]) -> None:
        self.buf: List[bytes] = []
        self.cancelled = cancelled
        self.written = 0

    def write(self, b) -> int:
        if self.cancelled():
            raise ExportCancelled("已取消")
        data = bytes(b)
        self.buf.append(data)
        self.written += len(data)
        return len(data)

    def flush(self) -> None:
        return None


class _CountingSink:
    """外层 entry 写句柄的包装：只暴露 write/flush（无 tell）→ 内层 zip 走 data descriptor；
    边流边算内层小包的字节数与 sha256（外层 manifest 要用）。"""

    def __init__(self, dst) -> None:
        self.dst = dst
        self.written = 0
        self.sha256 = hashlib.sha256()

    def write(self, b) -> int:
        data = bytes(b)
        self.sha256.update(data)
        self.written += len(data)
        self.dst.write(data)
        return len(data)

    def flush(self) -> None:
        self.dst.flush()


def _copy_file_into(zf: zipfile.ZipFile, arcname: str, path: Path, cancelled, drain
                    ) -> Generator[bytes, None, str]:
    """本地文件 → zip 条目（边流边算 sha256，返回 hexdigest）。"""
    h = hashlib.sha256()
    with zf.open(zipfile.ZipInfo(arcname), "w", force_zip64=True) as dst, path.open("rb") as fh:
        while True:
            if cancelled():
                raise ExportCancelled("已取消")
            chunk = fh.read(_READ_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            dst.write(chunk)
            yield from drain()
    return h.hexdigest()


def _copy_response_into(zf: zipfile.ZipFile, arcname: str, resp, cancelled, drain
                        ) -> Generator[bytes, None, str]:
    """HTTP 流（快照下载）→ zip 条目（边流边算 sha256，返回 hexdigest）。"""
    h = hashlib.sha256()
    with zf.open(zipfile.ZipInfo(arcname), "w", force_zip64=True) as dst, resp:
        while True:
            if cancelled():
                raise ExportCancelled("已取消")
            chunk = resp.read(_READ_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            dst.write(chunk)
            yield from drain()
    return h.hexdigest()


def iter_bundle_zip(libs: List[str], *, exclude_dirs: Sequence[str] = DEFAULT_EXCLUDE_DIRS,
                    with_vectors: bool = True, data_root: Optional[Path] = None,
                    on_stage: Optional[Callable[[str, str], None]] = None,
                    on_progress: Optional[Callable[[int, int], None]] = None,
                    is_cancelled: Optional[Callable[[], bool]] = None) -> Iterator[bytes]:
    """流式产出 v2 bundle zip 字节。服务端不落盘；中断即弃（无续传）。

    阶段：scan（registry/meta/文件清单）→ snapshot（每库向量快照，无字节输出）
    → stream（逐库切片 + 嵌套打包出网；逐库前重闸迁移）。
    """
    from . import corpus_slicing  # 延迟导入：corpus_slicing 反向依赖本模块的 checkpoint/快照工具

    data_root = Path(data_root).resolve() if data_root else resolve_data_root()
    cancelled = is_cancelled or (lambda: False)
    stage_cb = on_stage or (lambda _s, _m: None)
    report = on_progress or (lambda _d, _t: None)
    exclude = tuple(exclude_dirs)

    stage_cb("scan", "扫描待打包内容…")
    libraries, groups = read_registry(data_root, libs)
    for row in libraries:
        assert_library_not_migrating(row["library_id"])  # scan 闸（切片前另有逐库重闸）
    embed_model = embed_model_from_env()  # 导出开始固化一次（关 settings console 热替换窗口）
    meta_rows = read_meta_rows(data_root, list(libs))
    now = datetime.now(timezone(timedelta(hours=8)))

    counts_map, est_map = _library_counts_and_estimates(data_root, libraries)

    per_lib_files: Dict[str, List[Tuple[Path, str, int]]] = {}
    est_files = 0
    for row in libraries:
        lib_id = row["library_id"]
        lib_root = resolve_libraries_dir(lib_id) / lib_id
        entries: List[Tuple[Path, str, int]] = []
        if lib_root.is_dir():
            for path, rel_in_lib, size in _iter_doc_files(lib_root, exclude):
                if _is_lib_root_sqlite(rel_in_lib):
                    continue  # 专条切片/边车不进 files/（防再导带旧切片、防 WAL 蒸发断流）
                entries.append((path, f"files/{path.relative_to(data_root).as_posix()}", size))
                est_files += size
        per_lib_files[lib_id] = entries

    stack = ExitStack()
    snaps: Dict[str, Dict[str, Any]] = {}
    snapshot_bytes = 0
    zf_ref: Optional[zipfile.ZipFile] = None
    inner_ref: Optional[zipfile.ZipFile] = None
    try:
        if with_vectors:
            stage_cb("snapshot", "生成每库向量快照（临时集合，约 1-3 分钟/库）…")
            corpus_slicing.cleanup_stale_temp_collections()  # 清上次导出残留
            for row in libraries:
                lib_id = row["library_id"]
                exclusive = corpus_slicing.library_owns_collection_exclusively(lib_id, str(row["collection"]))
                snaps[lib_id] = stack.enter_context(
                    corpus_slicing.library_vector_snapshot(lib_id, str(row["collection"]), exclusive=exclusive))
                snapshot_bytes += int(snaps[lib_id]["size"])

        total = est_files + sum(est_map.values()) + snapshot_bytes
        report(0, total)
        stage_cb("stream", "打包中…")

        sink = _ZipSink(cancelled)
        done = [0]

        def drain() -> Iterator[bytes]:
            while sink.buf:
                chunk = sink.buf.pop(0)
                done[0] += len(chunk)
                report(done[0], total)
                yield chunk

        zf = zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True)
        zf_ref = zf
        outer_files: Dict[str, str] = {}
        outer_libs: List[dict] = []
        outer_files_index: Dict[str, str] = {}

        for row in libraries:
            lib_id = row["library_id"]
            if cancelled():
                raise ExportCancelled("已取消")
            stage_cb("slice", f"构建「{row.get('name') or lib_id}」的索引/图谱切片…")
            assert_library_not_migrating(lib_id)  # 切片前逐库重闸（窗口收到单库切片时长）

            staging = Path(tempfile.mkdtemp(prefix=f"kb-bundle-{lib_id}-"))
            try:
                index_info = corpus_slicing.build_library_sqlite_slice(
                    data_root, row, staging / "index.sqlite")
                # 图谱一库一文件（plan-graph-per-library-split）：用全站唯一解析器
                # resolve_graph_db_for_library（库文件 > 全局迁移源 > 库文件新建）。
                # 旧写法拿 sqlite_file 的父目录找 graph.sqlite——组路由后 sqlite_file 指向
                # knowledge/groups/*.sqlite，父目录下没有 graph 文件，本库真实图谱被漏掉，
                # 导出包静默 0 relations（2026-10-28 生产实跑实踩）。
                from docs_core.step07_graph.graph_files import resolve_graph_db_for_library

                graph_db = resolve_graph_db_for_library(lib_id)
                if graph_db.exists():
                    graph_info = corpus_slicing.build_library_graph_slice(
                        graph_db, lib_id, staging / "graph.sqlite")
                else:
                    # closing 只是上下文管理器，没有 .close()（Py3.11 实跑炸过）：
                    # 这里只为在 zip 里留一份空 graph.sqlite 保持包结构一致，用 with 落盘即走。
                    with closing(sqlite3.connect(staging / "graph.sqlite")):
                        pass
                    graph_info = {"relations": 0, "tables": {}, "fk_violations": 0}

                snap = snaps.get(lib_id)
                if snap is not None:
                    vectors = int(snap["points"]) if snap["points"] is not None else \
                        count_points_filtered(str(row["collection"]), lib_id)
                else:
                    vectors = 0
                warnings = _file_path_warnings(_meta_for_lib(meta_rows, lib_id)["nodes"], data_root)
                fk_dirty = int(graph_info.get("fk_violations") or 0)
                if fk_dirty:
                    warnings = warnings + [
                        f"图谱切片含 {fk_dirty} 条继承自源库的 FK 悬空行（源 graph.sqlite 历史脏数据；"
                        f"切片为忠实镜像，导入侧请以 counts.graph_fk_violations 为准判断，勿据此阻断）"
                    ]
                counts = {
                    "docs": index_info["docs"],
                    "chunks": index_info["chunks"],
                    "vectors": vectors,
                    "graph_relations": graph_info["relations"],
                    "graph_tables": graph_info["tables"],
                    "graph_fk_violations": fk_dirty,
                }

                entry_name = f"libraries/{lib_id}.zip"
                oinfo = zipfile.ZipInfo(entry_name)
                oinfo.compress_type = zipfile.ZIP_STORED
                # force_zip64：内层小包实测可超 4GiB（P1-7 实采：std 库全树 2GB+ 文件叠 ~3GB
                # 索引切片即越界），不预留 zip64 头会在 close 时 RuntimeError；小额条目零影响
                with zf.open(oinfo, "w", force_zip64=True) as outer_dst:
                    counter = _CountingSink(outer_dst)
                    inner_zf = zipfile.ZipFile(counter, "w", zipfile.ZIP_STORED, allowZip64=True)
                    inner_ref = inner_zf
                    inner_files: Dict[str, str] = {}

                    registry_bytes = json.dumps({
                        "libraries": [row],
                        "groups": [g for g in groups if g.get("group_name") == row.get("group_name")],
                    }, ensure_ascii=False, indent=1).encode("utf-8")
                    meta_bytes = json.dumps(
                        _meta_for_lib(meta_rows, lib_id), ensure_ascii=False).encode("utf-8")
                    for arcname, data in (("registry/rows.json", registry_bytes),
                                          ("meta/rows.json", meta_bytes)):
                        inner_zf.writestr(zipfile.ZipInfo(arcname), data)
                        inner_files[arcname] = hashlib.sha256(data).hexdigest()
                        yield from drain()

                    inner_files["index/index.sqlite"] = yield from _copy_file_into(
                        inner_zf, "index/index.sqlite", staging / "index.sqlite", cancelled, drain)

                    for path, arcname, _size in per_lib_files.get(lib_id, []):
                        inner_files[arcname] = yield from _copy_file_into(
                            inner_zf, arcname, path, cancelled, drain)

                    if snap is not None:
                        inner_files["qdrant/vectors.snapshot"] = yield from _copy_response_into(
                            inner_zf, "qdrant/vectors.snapshot",
                            open_snapshot(str(snap["collection"]), str(snap["snapshot"])),
                            cancelled, drain)

                    inner_files["graph/graph.sqlite"] = yield from _copy_file_into(
                        inner_zf, "graph/graph.sqlite", staging / "graph.sqlite", cancelled, drain)

                    inner_manifest = {
                        "kind": "library",
                        "schema_version": EXPORT_SCHEMA_VERSION,
                        "created_at": now.isoformat(),
                        "library_id": lib_id,
                        "name": row.get("name", ""),
                        "group_name": row.get("group_name", ""),
                        "embed_model": embed_model,
                        "page_base": PAGE_BASE,
                        "counts": counts,
                        "warnings": warnings,
                        "files": inner_files,
                    }
                    inner_zf.writestr(zipfile.ZipInfo("manifest.json"),
                                      json.dumps(inner_manifest, ensure_ascii=False, indent=1))
                    inner_zf.close()
                    yield from drain()

                outer_files_index[entry_name] = counter.sha256.hexdigest()
                outer_libs.append({
                    "library_id": lib_id,
                    "name": row.get("name", ""),
                    "group_name": row.get("group_name", ""),
                    "entry": entry_name,
                    "sha256": counter.sha256.hexdigest(),
                    "bytes": counter.written,
                    "counts": counts,
                })
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        outer_manifest = {
            "kind": "bundle",
            "schema_version": EXPORT_SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "embed_model": embed_model,
            "page_base": PAGE_BASE,
            "libraries": outer_libs,
            "files": outer_files_index,
        }
        zf.writestr(zipfile.ZipInfo("manifest.json"),
                    json.dumps(outer_manifest, ensure_ascii=False, indent=1))
        zf.close()
        yield from drain()
        report(total, total)
    finally:
        # 无论正常结束、取消还是客户端断连，快照与临时集合都清掉（服务端不留残留）。
        # 中断时 ZipFile 未走完 close：显式静默收尾，防 GC 期 __del__ 对已断路 sink 写尾部
        # 抛「I/O operation on closed file」噪声（2026-10-18 取消演练实见；截断包无需收尾）。
        for zombie in (inner_ref, zf_ref):
            if zombie is not None:
                try:
                    zombie.close()
                except Exception:  # noqa: BLE001 — 截断包的收尾写入失败无需上报
                    pass
        stack.close()


def build_bundle(libs: List[str], out_path: Path, **kwargs) -> Path:
    """落盘 bundle zip（CLI 用）。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        for chunk in iter_bundle_zip(libs, **kwargs):
            fh.write(chunk)
    return out_path


# ---------------------------------------------------------------- 任务注册表（进程内）


class ExportTasks:
    """管理后台导出任务的进程内状态。不落库：导出不需要历史，服务重启即失效。

    单飞闸带**僵死回收**（2026-10-09 实踩）：客户端断连后生成器可能停在挂起点永不收尾
    （Starlette 用线程池迭代同步生成器，请求取消后不会主动关它），任务就永远停在 running，
    把后续导出全挡成 409（实测日志见 backend.log）。所以 start() 先看上一个任务是否还在推进：
    超过 STALE_AFTER 秒没有新的字节产出即判僵死、让位。
    """

    # 多久没有字节推进就判僵死（正常导出每秒都在出字节，60s 足够保守）
    STALE_AFTER_S = 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._running: Optional[str] = None

    def start(self, task_id: str, *, group: str, libs: List[str], total_estimate: int) -> None:
        with self._lock:
            holder = self._tasks.get(self._running) if self._running else None
            if holder and holder.get("status") == "running":
                idle = time.time() - float(holder.get("updated_at") or 0)
                if idle <= self.STALE_AFTER_S:
                    raise RuntimeError(
                        f"已有导出任务在运行（{self._running}，{idle:.0f}s 前仍在推进），请等待完成或取消"
                    )
                # 僵死：客户端断连后没人再拉流，任务不会自己收尾——标记失败让位
                holder["status"] = "failed"
                holder["stage"] = "failed"
                holder["error"] = f"任务超过 {self.STALE_AFTER_S}s 无字节推进（客户端可能已断开），已回收"
                holder["message"] = holder["error"]
            self._running = task_id
            self._tasks[task_id] = {
                "task_id": task_id, "group": group, "libs": libs,
                "status": "running", "stage": "scan", "message": "准备中…",
                "bytes_out": 0, "total_bytes": total_estimate,
                "error": "", "cancel_requested": False, "updated_at": time.time(),
            }

    def finish(self, task_id: str, *, error: str = "", cancelled: bool = False) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "cancelled" if cancelled else ("failed" if error else "completed")
            task["stage"] = task["status"]
            task["message"] = error or ("已取消" if cancelled else "完成")
            task["error"] = error
            if self._running == task_id:
                self._running = None

    def request_cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task["status"] != "running":
                return False
            task["cancel_requested"] = True
            task["message"] = "取消中…"
            return True

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            return bool(task and task["cancel_requested"])

    def set_progress(self, task_id: str, *, stage: Optional[str] = None, message: Optional[str] = None,
                     bytes_out: Optional[int] = None, total: Optional[int] = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if stage:
                task["stage"] = stage
            if message:
                task["message"] = message
            if bytes_out is not None:
                task["bytes_out"] = bytes_out
            if total:
                task["total_bytes"] = total
            task["updated_at"] = time.time()   # 僵死判据：最后推进时刻（见 STALE_AFTER_S）

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def active(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._running:
                task = self._tasks.get(self._running)
                return dict(task) if task else None
            return None


# ================================================================ 导入侧（P2：读取 + 预检闸）
# 契约：docs/plan-kb-per-library-package.md Stage P2。
# v2 判据与导出侧对偶：外层 bundle zip / 单库小包 zip 两种输入；v1 目录/tar 不再支持。

SUPPORTED_SCHEMA = {2}

# P2-4 定版文案：CLI / P3-1 预检响应 / P3-2 前端提示三处逐字一致。
REEMBED_BLOCK_MESSAGE = "embed 模型不一致，v2 导入不支持 reembed；请用目标环境模型重新导出"


class BundleError(ValueError):
    """导入侧包结构/完整性/预检闸错误（CLI 捕获 → stderr + 非零退出）。"""


@dataclass
class BundleLibrary:
    """单库小包句柄：manifest + 落位临时文件 + 打开的 ZipFile。"""

    library_id: str
    name: str
    group_name: str
    entry: str
    manifest: Dict[str, Any]
    files_index: Dict[str, str]
    zip_path: Optional[Path] = None
    outer_sha256: str = ""
    outer_bytes: int = 0
    _zip: Optional[zipfile.ZipFile] = field(default=None, repr=False)

    def open_entry(self, arcname: str):
        if self._zip is None:
            raise BundleError(f"包已关闭或内层 zip 不可用: {self.entry}")
        return self._zip.open(arcname)


@dataclass
class Bundle:
    mode: str                       # "bundle"（外层大包）| "library"（单库小包）
    path: Path
    embed_model: str
    libraries: List[BundleLibrary]
    manifest: Dict[str, Any] = field(default_factory=dict)
    _tmpdir: Optional[Path] = field(default=None, repr=False)
    _outer_zip: Optional[zipfile.ZipFile] = field(default=None, repr=False)

    @property
    def library_ids(self) -> List[str]:
        return [lb.library_id for lb in self.libraries]

    def close(self) -> None:
        for lb in self.libraries:
            if lb._zip is not None:
                try:
                    lb._zip.close()
                except Exception:  # noqa: BLE001 — 关闭失败无需上报
                    pass
                lb._zip = None
        if self._outer_zip is not None:
            try:
                self._outer_zip.close()
            except Exception:  # noqa: BLE001
                pass
            self._outer_zip = None
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None


def _sha_stream(f, bufsize: int = _READ_CHUNK) -> str:
    h = hashlib.sha256()
    while True:
        chunk = f.read(bufsize)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


def _spool_zip_entry(zf: zipfile.ZipFile, entry: str, dst: Path) -> Tuple[str, int]:
    """把外层 zip 的内层小包条目边流边算 sha256、边落临时文件（大包不整读进内存）。"""
    h = hashlib.sha256()
    n = 0
    with zf.open(entry) as src, dst.open("wb") as out:
        while True:
            chunk = src.read(_READ_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
            out.write(chunk)
    return h.hexdigest(), n


def check_schema_gate(manifest: Dict[str, Any]) -> None:
    if manifest.get("schema_version") not in SUPPORTED_SCHEMA:
        raise BundleError(f"不支持的包 schema_version={manifest.get('schema_version')}，先升级导入工具")


@contextmanager
def open_bundle(path) -> Iterator[Bundle]:
    """识别并打开两种输入：v2 大包 zip（kind=bundle）、v2 小包 zip（kind=library）。

    v2 大包：内层小包**流式落临时文件**（内容大者 9GB+，不整读内存），外层 sha256/bytes
    在落盘时同步算出（对账在 ``check_package_files``）；退出时清理临时文件与句柄。
    v1 目录/tar 已不支持，收到即报错要求用 v2 重新导出。
    """
    p = Path(path)
    stack = ExitStack()
    try:
        if p.is_dir() or p.suffix.lower() in (".tar", ".tgz"):
            raise BundleError(
                "v1 目录/tar 旧包不再支持；请用 v2 重新导出（.zip 外层大包或单库小包）")

        try:
            zf = zipfile.ZipFile(p)
        except zipfile.BadZipFile as exc:
            raise BundleError(f"不是 zip 包: {p}") from exc
        stack.callback(zf.close)

        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError as exc:
            raise BundleError(f"包里没有 manifest.json: {p}") from exc
        except ValueError as exc:
            raise BundleError(f"manifest.json 解析失败: {exc}") from exc
        check_schema_gate(manifest)

        kind = manifest.get("kind")
        if kind == "bundle":
            tmpdir = Path(tempfile.mkdtemp(prefix="kb-bundle-open-"))
            stack.callback(shutil.rmtree, tmpdir, ignore_errors=True)
            outer_model = str(manifest.get("embed_model") or "")
            libs: List[BundleLibrary] = []
            for e in manifest.get("libraries") or []:
                entry = str(e.get("entry") or "")
                lib_id = str(e.get("library_id") or "")
                if not entry or not lib_id:
                    raise BundleError(f"外层 manifest.libraries 行缺 entry/library_id: {e}")
                spool = tmpdir / f"{lib_id}.zip"
                sha, n = _spool_zip_entry(zf, entry, spool)
                try:
                    iz = zipfile.ZipFile(spool)
                    iman = json.loads(iz.read("manifest.json"))
                except (zipfile.BadZipFile, KeyError, ValueError) as exc:
                    raise BundleError(f"内层包损坏或缺 manifest: {entry}") from exc
                stack.callback(iz.close)
                if iman.get("kind") != "library":
                    raise BundleError(f"内层 {entry} kind={iman.get('kind')!r} ≠ library")
                check_schema_gate(iman)
                im_model = str(iman.get("embed_model") or "")
                if im_model != outer_model:
                    raise BundleError(
                        f"内层 {entry} embed_model={im_model!r} 与外层 {outer_model!r} 不一致（包被改动？）")
                libs.append(BundleLibrary(
                    library_id=lib_id,
                    name=str(iman.get("name") or e.get("name") or lib_id),
                    group_name=str(iman.get("group_name") or e.get("group_name") or ""),
                    entry=entry, manifest=iman, files_index=dict(iman.get("files") or {}),
                    zip_path=spool, outer_sha256=sha, outer_bytes=n, _zip=iz,
                ))
            if not libs:
                raise BundleError("外层 manifest.libraries 为空——包不完整")
            bundle = Bundle(mode="bundle", path=p, embed_model=outer_model, libraries=libs,
                            manifest=manifest, _tmpdir=tmpdir, _outer_zip=zf)
        elif kind == "library":
            lib_id = str(manifest.get("library_id") or "")
            if not lib_id:
                raise BundleError("小包 manifest 缺 library_id")
            libs = [BundleLibrary(
                library_id=lib_id, name=str(manifest.get("name") or lib_id),
                group_name=str(manifest.get("group_name") or ""), entry=p.name,
                manifest=manifest, files_index=dict(manifest.get("files") or {}),
                zip_path=p, outer_sha256="", outer_bytes=p.stat().st_size, _zip=zf,
            )]
            bundle = Bundle(mode="library", path=p, embed_model=str(manifest.get("embed_model") or ""),
                            libraries=libs, manifest=manifest, _outer_zip=zf)
        else:
            raise BundleError("无法识别的包：manifest.kind 缺失或未知（只支持 v2 bundle/library）")

        stack.callback(bundle.close)
        yield bundle
    finally:
        stack.close()


def check_package_files(bundle: Bundle) -> None:
    """两层 sha256 全量对账（外层=小包字节，内层=条目文件）+ 缺文件/多出条目判据。

    完整性判据与导出侧镜像：外层 sha256/bytes 在 open_bundle 落临时文件时已同步算出，
    内层逐条目复算。任何不符即 BundleError（不静默降级）。
    """
    if bundle.mode not in ("bundle", "library"):
        raise BundleError(f"未知包模式: {bundle.mode}")
    outer_rows: Dict[str, dict] = {}
    if bundle.mode == "bundle":
        outer_rows = {str(e.get("entry")): e for e in (bundle.manifest.get("libraries") or [])}
    for lb in bundle.libraries:
        if bundle.mode == "bundle":
            row = outer_rows.get(lb.entry) or {}
            if lb.outer_sha256 != row.get("sha256"):
                raise BundleError(f"小包 sha256 不符: {lb.entry}（传输损坏或包被改动）")
            if lb.outer_bytes != row.get("bytes"):
                raise BundleError(
                    f"小包字节数不符: {lb.entry}（manifest={row.get('bytes')} 实读={lb.outer_bytes}）")
        if not lb.files_index:
            raise BundleError(f"[{lb.library_id}] 内层 manifest.files 为空——包不完整")
        if lb._zip is None:
            raise BundleError(f"[{lb.library_id}] 内层 zip 不可用（句柄已关闭？）")
        names = set(lb._zip.namelist()) - {"manifest.json"}
        expected = set(lb.files_index)
        missing = sorted(expected - names)
        if missing:
            more = f" 等 {len(missing)} 个" if len(missing) > 1 else ""
            raise BundleError(f"[{lb.library_id}] 缺文件: {missing[0]}{more}")
        extra = sorted(names - expected)
        if extra:
            more = f" 等 {len(extra)} 个" if len(extra) > 1 else ""
            raise BundleError(f"[{lb.library_id}] 包内多出未登记条目: {extra[0]}{more}（manifest 与包不符）")
        for arc, digest in lb.files_index.items():
            with lb.open_entry(arc) as f:
                got = _sha_stream(f)
            if got != digest:
                raise BundleError(f"[{lb.library_id}] sha256 不符: {arc}（传输损坏或包被改动）")


def check_embed_gate(manifest: Dict[str, Any], env_model: str) -> None:
    """v2 硬闸（定版 b）：模型不一致即阻断，**不留 reembed 口**。"""
    pkg_model = str(manifest.get("embed_model") or "")
    if not pkg_model:
        raise BundleError("包 manifest 没记录 embed_model，无法对账——重出包")
    if pkg_model != env_model:
        raise BundleError(
            f"{REEMBED_BLOCK_MESSAGE}"
            f"（包={pkg_model} 现网={env_model or '(EMBEDDING_CONFIGS 未设置)'}）"
        )


def check_conflict_gate(*, package_libs: Sequence[dict], package_node_ids: Sequence[str] = (),
                        target_library_ids: Sequence[str] = (), target_node_ids: Sequence[str] = (),
                        target_collections: Sequence[str] = (), existing_index_files: Sequence[str] = (),
                        ) -> Dict[str, list]:
    """冲突闸（v2 扩展）：调用方采集目标侧四类占用，本函数纯判据。

    - ``target_collections``：目标 registry 行 collection 值 ∪ qdrant 现存集合名。
      qdrant 实测（P2-0）：目标集合已存在时 snapshot upload **不报错**（覆盖）——
      本闸是唯一防线，不能指望 qdrant 拒绝。
    - ``existing_index_files``：目标已存在的 ``knowledge/libraries/<lib>/index.sqlite``（相对 data 根的库 id 列表）。
    - 实体重名检查已于 2026-10-28 移除（plan-graph-per-library-split）：图谱一库一文件，
      导入的新库整文件落位，与目标既有图谱零交集，不存在跨库实体撞名面。
    """
    clashes: List[str] = []
    lib_ids = [str(l.get("library_id")) for l in package_libs]
    for x in sorted(set(lib_ids) & set(target_library_ids)):
        clashes.append(f"library_id 已存在: {x}")
    for x in sorted(set(package_node_ids) & set(target_node_ids)):
        clashes.append(f"节点 id 已存在: {x}")
    for x in sorted({lid for lid in lib_ids if lid in set(target_collections)}):
        clashes.append(f"collection 名已被占用: {x}")
    existing = set(existing_index_files)
    for x in sorted(set(lib_ids) & existing):
        clashes.append(f"目标已有 index.sqlite: knowledge/libraries/{x}/index.sqlite")
    return {"clashes": clashes}


def apply_import(*args, **kwargs):
    """v2 导入应用入口（惰性 import，避免 corpus_package ↔ apply 模块循环）。"""
    from .corpus_import_apply import import_bundle

    return import_bundle(*args, **kwargs)

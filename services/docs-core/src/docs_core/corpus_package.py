"""语料包导出核心：CLI 落盘包与管理后台流式 zip 共用同一套逻辑。

两种产出形态（内容一致）：
- ``build_package``    落盘目录包（CLI：``scripts/kb_corpus_export.py``）
- ``iter_package_zip``  流式 zip 字节（管理后台：边读边出网，服务端不落盘）

包结构：
    <root>/
    ├─ registry/rows.json           # library_registry + library_groups 行原样
    ├─ meta/rows.json               # 共享 meta 库按 library_id 摘的 nodes/tree_node
    ├─ files/<相对 data 根路径>      # 组 sqlite（checkpoint 后）+ libraries/<id>/ 文档树
    ├─ qdrant/<collection>.snapshot # with_vectors=False 时跳过
    └─ manifest.json                # 全量文件 sha256；流式时排最后（sha256 边读边算）

为什么流式一趟就够：CLI 旧路径是「staging 拷贝 → sha256 全扫 → zip」四趟 IO；
流式读每个文件一次（同时算 sha256）→ 写 zip → 直接出网，只有一趟 IO。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple
from urllib import request as urlrequest

from .library_registry import REGISTRY_DB_NAME, resolve_data_root

SCHEMA_VERSION = 1
PAGE_BASE = 0  # canonical 页码 0-based，交付说明写死
DEFAULT_EXCLUDE_DIRS: Tuple[str, ...] = ("mineru_raw", "popo")
_READ_CHUNK = 1 << 20

# qdrant 快照体积经验系数（字节/点）：system 8.5KB、standards 6.2KB → 取 7KB 做预览估算。
# （2026-10-09 两组换名前，这两个系数分别测得于 standards / guifan 集合，数字未变、归属随换名。）
# 正式进度分母用快照创建响应里的真实 size（见 iter_package_zip），不依赖此系数。
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
    meta_db = data_root / "knowledge" / "knowledge_meta.sqlite"
    if not meta_db.exists():
        raise ValueError(f"meta 库不存在: {meta_db}")
    with closing(sqlite3.connect(meta_db)) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" * len(libs))
        nodes = [dict(r) for r in conn.execute(f"SELECT * FROM nodes WHERE library_id IN ({marks})", list(libs))]
        tree = [dict(r) for r in conn.execute(f"SELECT * FROM tree_node WHERE scope_id IN ({marks})", list(libs))]
    return {"nodes": nodes, "tree_nodes": tree}


def group_peer_libraries(data_root: Path, libs: Sequence[str]) -> List[dict]:
    """同组但不在 libs 里的库：它们的数据仍在组 sqlite 内（FTS/graph 不可拆），预览时要警告。"""
    libraries, _ = read_registry(data_root, libs)
    groups = sorted({row["group_name"] for row in libraries})
    with closing(sqlite3.connect(data_root / REGISTRY_DB_NAME)) as conn:
        conn.row_factory = sqlite3.Row
        marks = ",".join("?" * len(groups))
        rows = [dict(r) for r in conn.execute(
            f"SELECT library_id, name, group_name FROM library_registry WHERE group_name IN ({marks})", groups)]
    chosen = set(libs)
    return [r for r in rows if r["library_id"] not in chosen]


# ---------------------------------------------------------------- 待打包条目


@dataclass
class FileEntry:
    arcname: str          # 包内相对路径（POSIX）
    path: Path            # 源文件绝对路径
    size: int
    rel_to_data: str      # 相对 data 根（staged_roots 用）


@dataclass
class ScanResult:
    libraries: List[dict] = field(default_factory=list)
    groups: List[dict] = field(default_factory=list)
    files_bytes: int = 0
    file_count: int = 0
    sqlite_bytes: int = 0
    snapshot_points: int = 0
    snapshot_estimate: int = 0
    peers: List[dict] = field(default_factory=list)   # 同组未选中的库
    warnings: List[str] = field(default_factory=list)

    @property
    def total_estimate(self) -> int:
        return self.files_bytes + self.sqlite_bytes + self.snapshot_estimate


def _iter_doc_files(lib_root: Path, exclude_dirs: Sequence[str]) -> Iterator[Path]:
    """库目录下全部文件，跳过 documents/<doc_id>/parsed/<exclude> 整棵。

    mineru_raw/popo 只在重解析时被读（parse_pipeline 的 stage 输入），检索链只查
    sqlite+qdrant，不进包（省 ~2.2GB/库）。
    """
    exclude = set(exclude_dirs)
    for path in lib_root.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(lib_root).parts
        if len(parts) >= 4 and parts[0] == "documents" and parts[2] == "parsed" and parts[3] in exclude:
            continue
        yield path


def checkpoint_sqlite(path: Path) -> None:
    """WAL 落盘：不 checkpoint 拷出去/读出去都缺最近写入。连接必须关（Windows 文件锁）。"""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _validate_single_group(libraries: Sequence[dict]) -> str:
    groups = {row["group_name"] for row in libraries}
    if len(groups) != 1:
        raise ValueError(f"一次只能导一个组（同组共用一个 sqlite），收到: {sorted(groups)}")
    return groups.pop()


def plan_entries(data_root: Path, libraries: Sequence[dict], exclude_dirs: Sequence[str]
                 ) -> Tuple[Dict[str, bytes], List[FileEntry], List[str]]:
    """返回 (内存条目, 文件条目, staged_roots)。两种产出形态共用，保证内容一致。"""
    mem: Dict[str, bytes] = {}
    files: List[FileEntry] = []
    staged: List[str] = []

    for rel in sorted({row["sqlite_file"] for row in libraries}):
        src = data_root / rel
        if not src.exists():
            continue
        checkpoint_sqlite(src)
        # 只拷主库：checkpoint(TRUNCATE) 后 WAL 已归零（数据全在主库），-wal/-shm 都是瞬态——
        # SQLite 会在最后一个连接关闭时自己删它们，拷了就是竞态（2026-10-09 实踩：
        # 拷进包后被后端连接收尾删掉，manifest 却已扫进 sha256 表 → 导入侧报缺文件整包中止）。
        files.append(FileEntry(arcname=f"files/{rel}", path=src, size=src.stat().st_size, rel_to_data=rel))
        staged.append(rel)

    for row in libraries:
        lib_root = data_root / "knowledge" / "libraries" / row["library_id"]
        if not lib_root.is_dir():
            continue
        rel_root = lib_root.relative_to(data_root).as_posix()
        for path in _iter_doc_files(lib_root, exclude_dirs):
            rel = path.relative_to(data_root).as_posix()
            files.append(FileEntry(arcname=f"files/{rel}", path=path, size=path.stat().st_size, rel_to_data=rel))
        staged.append(rel_root)
    return mem, files, sorted(set(staged))


def scan_selection(data_root: Path, libs: Sequence[str], *, exclude_dirs: Sequence[str] = DEFAULT_EXCLUDE_DIRS,
                   qdrant_url: Optional[str] = None) -> ScanResult:
    """预览：体积估算 + 同组未选警告。不创建快照（那是导出时的实际工作）。"""
    libraries, groups = read_registry(data_root, libs)
    _validate_single_group(libraries)
    result = ScanResult(libraries=libraries, groups=groups)

    for rel in sorted({row["sqlite_file"] for row in libraries}):
        src = data_root / rel
        if src.exists():
            result.sqlite_bytes += src.stat().st_size
    for row in libraries:
        lib_root = data_root / "knowledge" / "libraries" / row["library_id"]
        if not lib_root.is_dir():
            continue
        for path in _iter_doc_files(lib_root, exclude_dirs):
            result.files_bytes += path.stat().st_size
            result.file_count += 1

    collections = sorted({row["collection"] for row in libraries})
    result.snapshot_points = _collection_points(collections, qdrant_url)
    result.snapshot_estimate = result.snapshot_points * SNAPSHOT_BYTES_PER_POINT

    result.peers = group_peer_libraries(data_root, libs)
    if result.peers:
        names = "、".join(f"{p['name']}({p['library_id']})" for p in result.peers)
        # 只说事实，不建议动作：未选中的同组库未必都在可选清单里（空库不进库列表），
        # 「建议全选」会指向一个点不到的目标——前端按可选择性自行补建议。
        result.warnings.append(
            f"同组共用一份 sqlite（FTS/graph 无法按库拆分）：该组另有 {names} 未纳入本次导出，"
            "但包内仍会含它们的索引数据。它们没有源文件随包，检索可能命中、溯源会 404。"
        )
    return result


def _qdrant_base(qdrant_url: Optional[str] = None) -> str:
    return (qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")).rstrip("/")


def _collection_points(collections: Sequence[str], qdrant_url: Optional[str] = None) -> int:
    total = 0
    base = _qdrant_base(qdrant_url)
    for col in collections:
        try:
            with urlrequest.urlopen(f"{base}/collections/{col}", timeout=10) as resp:
                total += int(json.load(resp).get("result", {}).get("points_count") or 0)
        except Exception:  # noqa: BLE001 — 估算失败不阻断预览
            pass
    return total


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


# ---------------------------------------------------------------- 产物：落盘目录包


def build_package(libs: List[str], out_parent: Path, with_vectors: bool = True, pack_tar: bool = False,
                  exclude_dirs: Optional[Sequence[str]] = None, data_root: Optional[Path] = None,
                  on_stage: Optional[Callable[[str, str], None]] = None) -> Path:
    """落盘目录包（CLI 用）。"""
    data_root = data_root or resolve_data_root()
    exclude = tuple(exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS)
    now = datetime.now(timezone(timedelta(hours=8)))
    libraries, groups = read_registry(data_root, libs)
    group = _validate_single_group(libraries)
    out_root = out_parent / f"{group}-{now.strftime('%Y%m%d')}-{libs[0]}"

    if on_stage:
        on_stage("registry", "写 registry 行")
    (out_root / "registry").mkdir(parents=True)
    (out_root / "meta").mkdir(parents=True)
    (out_root / "registry" / "rows.json").write_text(
        json.dumps({"libraries": libraries, "groups": groups}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_root / "meta" / "rows.json").write_text(
        json.dumps(read_meta_rows(data_root, libs), ensure_ascii=False), encoding="utf-8")

    if on_stage:
        on_stage("files", "拷贝文件")
    _, file_entries, staged = plan_entries(data_root, libraries, exclude)
    for entry in file_entries:
        dst = out_root / entry.arcname
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.path, dst)

    collections: List[str] = []
    if with_vectors:
        if on_stage:
            on_stage("snapshot", "生成向量快照")
        for col in sorted({row["collection"] for row in libraries}):
            name, _size = create_snapshot(col)
            target = out_root / "qdrant" / f"{col}.snapshot"
            target.parent.mkdir(parents=True, exist_ok=True)
            with open_snapshot(col, name) as resp, target.open("wb") as fh:
                shutil.copyfileobj(resp, fh, _READ_CHUNK)
            delete_snapshot(col, name)
            print(f"  snapshot {col} → {target.name} ({target.stat().st_size // 1048576}MB)")
            collections.append(col)

    if on_stage:
        on_stage("manifest", "算 sha256")
    file_index = {entry.arcname: sha256_file(entry.path) for entry in file_entries}
    file_index["registry/rows.json"] = sha256_file(out_root / "registry" / "rows.json")
    file_index["meta/rows.json"] = sha256_file(out_root / "meta" / "rows.json")
    for col in collections:
        rel = f"qdrant/{col}.snapshot"
        file_index[rel] = sha256_file(out_root / rel)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now.isoformat(),
        "group": group,
        "embed_model": embed_model_from_env(),
        "page_base": PAGE_BASE,
        "collections": collections,
        "libraries": [{"library_id": r["library_id"], "sqlite_file": r["sqlite_file"], "collection": r["collection"]}
                      for r in libraries],
        "staged_roots": staged,
        "files": file_index,
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"包: {out_root}  文件={len(file_index)}  embed_model={manifest['embed_model'] or '(空!)'}")

    if pack_tar:
        import tarfile
        tar_path = out_root.with_suffix(".tar")
        with tarfile.open(tar_path, "w") as tf:
            tf.add(out_root, arcname=out_root.name)
        print(f"tar: {tar_path} ({tar_path.stat().st_size // 1048576}MB)")
    return out_root


# ---------------------------------------------------------------- 产物：流式 zip


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


def iter_package_zip(libs: List[str], *, exclude_dirs: Sequence[str] = DEFAULT_EXCLUDE_DIRS,
                     with_vectors: bool = True, data_root: Optional[Path] = None,
                     on_stage: Optional[Callable[[str, str], None]] = None,
                     on_progress: Optional[Callable[[int, int], None]] = None,
                     is_cancelled: Optional[Callable[[], bool]] = None) -> Iterator[bytes]:
    """流式产出 zip 字节。服务端不落盘；中断即弃（无续传）。

    阶段：scan（统计）→ snapshot（向量快照，无字节输出）→ stream（打包出网）。
    进度分母在 snapshot 建好后就精确（用真实快照字节数，不用估算系数）。
    """
    data_root = data_root or resolve_data_root()
    cancelled = is_cancelled or (lambda: False)
    stage_cb = on_stage or (lambda _s, _m: None)
    report = on_progress or (lambda _d, _t: None)

    stage_cb("scan", "扫描待打包文件…")
    libraries, groups = read_registry(data_root, libs)
    group = _validate_single_group(libraries)
    meta_rows = read_meta_rows(data_root, libs)

    registry_bytes = json.dumps({"libraries": libraries, "groups": groups},
                                ensure_ascii=False, indent=1).encode("utf-8")
    meta_bytes = json.dumps(meta_rows, ensure_ascii=False).encode("utf-8")
    _, file_entries, staged = plan_entries(data_root, libraries, exclude_dirs)
    payload_bytes = len(registry_bytes) + len(meta_bytes) + sum(e.size for e in file_entries)

    snapshots: List[Tuple[str, str, int]] = []
    snapshot_bytes = 0
    if with_vectors:
        for col in sorted({row["collection"] for row in libraries}):
            stage_cb("snapshot", f"生成并拉取向量的快照（{col}，约 1-3 分钟）…")
            name, size = create_snapshot(col)
            snapshots.append((col, name, size))
            snapshot_bytes += size

    total = payload_bytes + snapshot_bytes
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

    try:
        import zipfile

        zf = zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True)
        file_index: Dict[str, str] = {}

        for arcname, data in (("registry/rows.json", registry_bytes), ("meta/rows.json", meta_bytes)):
            zf.writestr(zipfile.ZipInfo(arcname), data)
            file_index[arcname] = hashlib.sha256(data).hexdigest()
            yield from drain()

        for entry in file_entries:
            if cancelled():
                raise ExportCancelled("已取消")
            h = hashlib.sha256()
            with zf.open(zipfile.ZipInfo(entry.arcname), "w") as dst, entry.path.open("rb") as fh:
                while True:
                    if cancelled():
                        raise ExportCancelled("已取消")
                    chunk = fh.read(_READ_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
                    dst.write(chunk)
                    yield from drain()
            file_index[entry.arcname] = h.hexdigest()
            yield from drain()

        for col, name, _size in snapshots:
            if cancelled():
                raise ExportCancelled("已取消")
            arcname = f"qdrant/{col}.snapshot"
            h = hashlib.sha256()
            with zf.open(zipfile.ZipInfo(arcname), "w") as dst, open_snapshot(col, name) as resp:
                while True:
                    if cancelled():
                        raise ExportCancelled("已取消")
                    chunk = resp.read(_READ_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
                    dst.write(chunk)
                    yield from drain()
            file_index[arcname] = h.hexdigest()
            yield from drain()

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "group": group,
            "embed_model": embed_model_from_env(),
            "page_base": PAGE_BASE,
            "collections": [col for col, _n, _s in snapshots],
            "libraries": [{"library_id": r["library_id"], "sqlite_file": r["sqlite_file"], "collection": r["collection"]}
                          for r in libraries],
            "staged_roots": staged,
            "files": file_index,
        }
        zf.writestr(zipfile.ZipInfo("manifest.json"), json.dumps(manifest, ensure_ascii=False, indent=1))
        zf.close()
        yield from drain()
        report(total, total)
    finally:
        # 无论正常结束、取消还是客户端断连，都清掉 qdrant 侧快照（服务端不留残留）
        for col, name, _size in snapshots:
            delete_snapshot(col, name)


# ---------------------------------------------------------------- 任务注册表（进程内）


class ExportTasks:
    """管理后台导出任务的进程内状态。不落库：导出不需要历史，服务重启即失效。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._running: Optional[str] = None

    def start(self, task_id: str, *, group: str, libs: List[str], total_estimate: int) -> None:
        with self._lock:
            if self._running and self._tasks.get(self._running, {}).get("status") == "running":
                raise RuntimeError("已有导出任务在运行，请等待完成或取消")
            self._running = task_id
            self._tasks[task_id] = {
                "task_id": task_id, "group": group, "libs": libs,
                "status": "running", "stage": "scan", "message": "准备中…",
                "bytes_out": 0, "total_bytes": total_estimate,
                "error": "", "cancel_requested": False,
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

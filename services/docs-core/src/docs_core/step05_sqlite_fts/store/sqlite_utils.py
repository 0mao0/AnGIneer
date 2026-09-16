"""SQLite 连接工具（write 层共享）。"""
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, TypeVar

_T = TypeVar("_T")

_BUSY_MARKERS = ("database is locked", "database is busy")


# 构造 SQLite 连接并启用 WAL 模式与 Row 映射。
def create_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------- 写串行化：同进程按库文件一把锁 + busy 有界重试 ----------
# 事故（2026-09-15）：批量断点续跑每文档一个线程（parse_pipeline），fts 阶段并发
# save_document 打同一库，单写者模型下大事务排队把 timeout=10 击穿成
# `database is locked`，整篇文档被误判 failed。

_WRITE_LOCKS: Dict[str, threading.Lock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def db_write_lock(db_path: Path) -> threading.Lock:
    """按库文件（resolve 后路径）取进程内写串行锁。"""
    key = str(Path(db_path).resolve())
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _WRITE_LOCKS[key] = lock
        return lock


def is_busy_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and any(
        marker in str(exc).lower() for marker in _BUSY_MARKERS
    )


def run_with_write_lock(
    db_path: Path,
    fn: Callable[[], _T],
    *,
    attempts: int = 8,
    base_delay: float = 0.25,
) -> _T:
    """串行化同库写入（进程内）；busy 冲突（跨进程写者）指数退避后重试。

    - fn 必须幂等（canonical 写入口均为 clear+insert 形状，重放安全）；
      busy 在 commit 前抛出时事务已回滚，不会留半截数据。
    - 锁在每次尝试内获取、退避睡眠前已释放，失败方不会持锁阻塞他人。
    """
    lock = db_write_lock(db_path)
    last_exc: Optional[sqlite3.OperationalError] = None
    for attempt in range(attempts):
        try:
            with lock:
                return fn()
        except sqlite3.OperationalError as exc:
            if not is_busy_error(exc):
                raise
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
    assert last_exc is not None
    raise last_exc

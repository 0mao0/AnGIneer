"""fts 写入串行化 + busy 有界重试（2026-09-15 批量断点续跑 9 线程并发 fts 写实锤 `database is locked`）。

事故形状：批量解析每文档一个线程（parse_pipeline.create_parse_task），fts 阶段并发
save_document 打同一 knowledge_index.sqlite，单写者模型下 timeout=10 被大事务排队击穿。
修复：同进程按库文件加写锁串行化 + busy 指数退避重试（覆盖跨进程写者）。
"""
import sqlite3
import threading
from pathlib import Path

import pytest

from docs_core.step05_sqlite_fts.store import sqlite_utils
from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore
from fixtures.popo_fixtures import build_document_with_printed_labels


# ---------- run_with_write_lock / db_write_lock 机制 ----------

def test_busy_retry_recovers_after_transient_busy(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    result = sqlite_utils.run_with_write_lock(
        tmp_path / "a.sqlite", flaky, attempts=5, base_delay=0.001
    )
    assert result == "ok"
    assert calls["n"] == 3


def test_busy_retry_reraises_non_busy_immediately(tmp_path: Path) -> None:
    calls = {"n": 0}

    def bad() -> None:
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table: canonical_chunks")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        sqlite_utils.run_with_write_lock(
            tmp_path / "a.sqlite", bad, attempts=5, base_delay=0.001
        )
    assert calls["n"] == 1  # 非 busy 不重试


def test_busy_retry_exhausts_and_raises_last(tmp_path: Path) -> None:
    calls = {"n": 0}

    def always_busy() -> None:
        calls["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        sqlite_utils.run_with_write_lock(
            tmp_path / "a.sqlite", always_busy, attempts=3, base_delay=0.001
        )
    assert calls["n"] == 3


def test_write_lock_is_per_db_file(tmp_path: Path) -> None:
    p1, p2 = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    assert sqlite_utils.db_write_lock(p1) is sqlite_utils.db_write_lock(p1)
    assert sqlite_utils.db_write_lock(p1) is not sqlite_utils.db_write_lock(p2)


# ---------- CanonicalSQLiteStore 写入口接线 ----------

def test_save_document_holds_db_write_lock(tmp_path: Path) -> None:
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    captured = {}

    def fake_txn(document):
        captured["locked"] = sqlite_utils.db_write_lock(store.db_path).locked()
        return {}

    store._save_document_txn = fake_txn
    store.save_document(build_document_with_printed_labels("doc-1"))
    assert captured["locked"] is True


def test_save_document_retries_when_busy(tmp_path: Path) -> None:
    """首次 busy 必须重试并最终落库，而不是把整个文档判 failed。"""
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    original = store._save_document_txn
    calls = {"n": 0}

    def flaky(document):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return original(document)

    store._save_document_txn = flaky
    stats = store.save_document(build_document_with_printed_labels("doc-retry"))
    assert calls["n"] == 2
    assert store.get_document("doc-retry") is not None
    assert stats["pages"] == 2


def test_save_document_txn_does_not_nest_lock(tmp_path: Path) -> None:
    """save_document 内部清库必须走 _clear_document_txn，不能嵌套获取同一把写锁（自死锁）。"""
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    document = build_document_with_printed_labels("doc-nest")
    store.save_document(document)
    store.save_document(document)  # 锁已被 wrapper 持有时重入 clear 路径不得死锁
    assert store.get_document("doc-nest") is not None


def test_concurrent_batch_saves_all_land(tmp_path: Path) -> None:
    """批量续跑事故复现形状：多线程并发 save_document，全部成功且数据完整。"""
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    doc_ids = [f"doc-{i}" for i in range(6)]
    errors = []

    def worker(doc_id: str) -> None:
        try:
            store.save_document(build_document_with_printed_labels(doc_id))
        except Exception as exc:  # noqa: BLE001
            errors.append((doc_id, exc))

    threads = [threading.Thread(target=worker, args=(d,)) for d in doc_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"并发 fts 写失败: {errors}"
    for doc_id in doc_ids:
        assert store.get_document(doc_id) is not None

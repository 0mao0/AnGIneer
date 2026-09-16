"""parse_records 文件元信息回填（2026-09 实锤：5 条流水建row时节点查失败，
file_name/format/size 永远停在默认空值 → 管理端「文件名称」列空白）。

修复：终态状态更新时，空 file_name 的行从节点补一次（有值则不覆盖）。
"""
import sqlite3
from pathlib import Path

import pytest

from docs_core import parse_records_store as prs


@pytest.fixture()
def rec_db(tmp_path, monkeypatch):
    db = tmp_path / "parse_records.sqlite"
    monkeypatch.setenv("PARSE_RECORDS_DB_PATH", str(db))
    yield db
    conn = sqlite3.connect(db)
    conn.close()


def _rows(db: Path):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM parse_records ORDER BY id")]
    finally:
        conn.close()


def test_completed_backfills_empty_meta(rec_db, monkeypatch) -> None:
    prs.insert_record(doc_id="d1", task_id="t1", uploaded_by="管理员", status="processing")
    monkeypatch.setattr(prs, "_document_meta", lambda doc_id: {
        "library_id": "lib-x", "file_name": "规范A.pdf", "file_format": "pdf", "file_size": 123,
    })

    prs.sync_record_for_task("t1", "d1", "completed")

    row = _rows(rec_db)[0]
    assert row["file_name"] == "规范A.pdf"
    assert row["file_format"] == "pdf"
    assert row["file_size"] == 123
    assert row["status"] == "completed"


def test_failed_terminal_also_backfills(rec_db, monkeypatch) -> None:
    prs.insert_record(doc_id="d2", task_id="t2", status="processing")
    monkeypatch.setattr(prs, "_document_meta", lambda doc_id: {
        "library_id": "l", "file_name": "x.docx", "file_format": "docx", "file_size": 9,
    })
    prs.sync_record_for_task("t2", "d2", "failed", error="boom")
    assert _rows(rec_db)[0]["file_name"] == "x.docx"


def test_existing_file_name_not_overwritten(rec_db, monkeypatch) -> None:
    prs.insert_record(doc_id="d3", task_id="t3", file_name="原名.pdf",
                      file_format="pdf", file_size=50, status="processing")
    calls = {"n": 0}

    def spy(doc_id):
        calls["n"] += 1
        return {"library_id": "l", "file_name": "新名.pdf", "file_format": "pdf", "file_size": 1}

    monkeypatch.setattr(prs, "_document_meta", spy)
    prs.sync_record_for_task("t3", "d3", "completed")
    row = _rows(rec_db)[0]
    assert row["file_name"] == "原名.pdf" and row["file_size"] == 50
    assert calls["n"] == 0  # 有值时连节点都不查


def test_still_empty_meta_stays_empty(rec_db, monkeypatch) -> None:
    prs.insert_record(doc_id="d4", task_id="t4", status="processing")
    monkeypatch.setattr(prs, "_document_meta", lambda doc_id: {
        "library_id": "l", "file_name": "", "file_format": "", "file_size": 0,
    })
    prs.sync_record_for_task("t4", "d4", "completed")
    assert _rows(rec_db)[0]["file_name"] == ""


def test_document_meta_handles_windows_path(tmp_path, monkeypatch) -> None:
    """迁移遗留的 Windows 路径：Linux 上 basename 按 '\' 兜底拆名，不能把整串路径当文件名。"""
    class Node:
        library_id = "lib-1"
        title = ""
        file_path = "D:\\AI\\AnGIneer\\data\\knowledge_base\\x\\印染园总体施工组织设计.docx"

    class Svc:
        def get_node(self, doc_id):
            return Node()

    import importlib

    docs_service = importlib.import_module("docs_core.docs_service")
    monkeypatch.setattr(docs_service, "get_docs_service", lambda: Svc())
    meta = prs._document_meta("d5")
    assert meta["file_name"] == "印染园总体施工组织设计.docx"
    assert meta["file_format"] == "docx"
    assert meta["file_size"] == 0  # 路径不存在时大小静默为 0，不抛错

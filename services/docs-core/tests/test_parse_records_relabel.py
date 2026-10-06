import importlib
import docs_core.parse_records_store as prs


def test_update_library_for_docs(tmp_path, monkeypatch):
    monkeypatch.setenv("PARSE_RECORDS_DB_PATH", str(tmp_path / "pr.sqlite"))
    importlib.reload(prs)
    prs.insert_record(doc_id="d1", task_id="t1", uploaded_by="u", library_id="lib-a")
    prs.insert_record(doc_id="d1", task_id="t2", uploaded_by="u", library_id="lib-a")
    prs.insert_record(doc_id="d2", task_id="t3", uploaded_by="u", library_id="lib-a")
    changed = prs.update_library_for_docs(["d1"], "lib-b")
    assert changed == 2  # 一个 doc 的多条流水全量改（重解析历史同走）
    with prs.connect() as conn:
        rows = conn.execute("SELECT doc_id, library_id FROM parse_records ORDER BY id").fetchall()
    assert [(r["doc_id"], r["library_id"]) for r in rows] == [
        ("d1", "lib-b"), ("d1", "lib-b"), ("d2", "lib-a"),
    ]

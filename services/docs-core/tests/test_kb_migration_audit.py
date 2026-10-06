from docs_core import kb_migration_audit


def test_write_read_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(kb_migration_audit, "AUDIT_PATH", path)
    kb_migration_audit.write_audit(
        operator="admin", action="split",
        params={"source": "a", "docs": ["d1"]},
        preview_digest="abc", result="submitted",
    )
    kb_migration_audit.write_audit(operator="admin", action="switch", params={}, result="ok")
    entries, total = kb_migration_audit.read_audit()
    assert total == 2
    assert entries[0]["action"] == "split" and entries[0]["preview_digest"] == "abc"
    assert entries[1]["operator"] == "admin"


def test_read_skips_corrupt_lines(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"action":"ok"}\nnot-json\n', encoding="utf-8")
    monkeypatch.setattr(kb_migration_audit, "AUDIT_PATH", path)
    entries, total = kb_migration_audit.read_audit()
    assert total == 1 and entries[0]["action"] == "ok"

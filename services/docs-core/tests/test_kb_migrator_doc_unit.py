import sqlite3
import pytest
from docs_core.kb_migrator import KbMigrator
from test_kb_migrator_preview import migrator as _base  # noqa: F401  复用 fixture


@pytest.fixture
def doc_env(_base, tmp_path):
    mig = _base
    src_dir = mig.libraries_root_for("lib-a") / "documents" / "d1"
    src_dir.mkdir(parents=True)
    (src_dir / "source.txt").write_text("hello", encoding="utf-8")
    # file_path 必须真落在 lib-a 目录下，否则改写不会发生、断言必败（评审 P1-7②）
    with sqlite3.connect(mig.meta_db) as conn:
        conn.execute("UPDATE nodes SET file_path=? WHERE id='d1'", (str(src_dir / "source.txt"),))
    return mig


def test_migrate_doc_moves_all_faces(doc_env):
    mig = doc_env
    mig.migrate_doc("d1", "lib-a", "lib-b")
    # 文件
    assert (mig.libraries_root_for("lib-b") / "documents" / "d1" / "source.txt").exists()
    assert not (mig.libraries_root_for("lib-a") / "documents" / "d1").exists()
    # meta 三面 + file_path 改写
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-b"
        assert conn.execute("SELECT file_path FROM nodes WHERE id='d1'").fetchone()[0].startswith(
            str(mig.libraries_root_for("lib-b")))
    # 组文件
    with sqlite3.connect(mig.group_db_for("lib-a")) as conn:
        assert conn.execute("SELECT library_id FROM canonical_documents WHERE doc_id='d1'").fetchone()[0] == "lib-b"


def test_migrate_doc_idempotent(doc_env):
    mig = doc_env
    mig.migrate_doc("d1", "lib-a", "lib-b")
    mig.migrate_doc("d1", "lib-a", "lib-b")  # 重跑无害
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-b"


def test_rollback_doc_restores(doc_env):
    mig = doc_env
    mig.migrate_doc("d1", "lib-a", "lib-b")
    mig.rollback_doc("d1", "lib-a", "lib-b")
    assert (mig.libraries_root_for("lib-a") / "documents" / "d1" / "source.txt").exists()
    with sqlite3.connect(mig.meta_db) as conn:
        assert conn.execute("SELECT library_id FROM nodes WHERE id='d1'").fetchone()[0] == "lib-a"
    with sqlite3.connect(mig.group_db_for("lib-a")) as conn:
        assert conn.execute("SELECT library_id FROM canonical_documents WHERE doc_id='d1'").fetchone()[0] == "lib-a"

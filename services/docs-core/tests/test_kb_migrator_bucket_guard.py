"""P4-1：同组异构桶（导入独立桶）不允许拆并。"""
from types import SimpleNamespace

from docs_core import library_registry
from docs_core.kb_migrator import KbMigrator


def _rec(group: str, sqlite_file: str, collection: str):
    return SimpleNamespace(
        group_name=group, sqlite_file=sqlite_file, collection=collection,
        status=library_registry.STATUS_ACTIVE,
    )


def _migrator(monkeypatch, target_rec):
    monkeypatch.setattr(library_registry, "get_library", lambda lib: target_rec)
    return KbMigrator.__new__(KbMigrator)


def test_same_group_same_bucket_allowed(monkeypatch):
    rec = _rec("evals", "evals/groups/evals_corpus.sqlite", "evals_corpus")
    mig = _migrator(monkeypatch, rec)
    blockers: list[str] = []
    mig._check_destination_blockers("lib-b", rec, blockers)
    assert blockers == []


def test_same_group_independent_bucket_blocked(monkeypatch):
    src = _rec("evals", "evals/groups/evals_corpus.sqlite", "evals_corpus")
    dst = _rec("evals", "evals/corpora/libraries/lib-b/index.sqlite", "lib-b")
    mig = _migrator(monkeypatch, dst)
    blockers: list[str] = []
    mig._check_destination_blockers("lib-b", src, blockers)
    assert any("同组异构桶" in b for b in blockers)

"""冒烟测试：确认 docs-core 测试基建可用。"""


def test_import_core_modules() -> None:
    from docs_core.models.types import CanonicalBlock, CanonicalPage  # noqa: F401
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import build_canonical_chunks  # noqa: F401
    from docs_core.step04_structure.popo.popo_signal_aligner import align_popo_blocks  # noqa: F401

    assert True

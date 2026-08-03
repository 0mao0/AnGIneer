"""冒烟测试：确认 docs-core 测试基建可用。"""


def test_import_core_modules() -> None:
    from docs_core.ingest.canonical.types import CanonicalBlock, CanonicalPage  # noqa: F401
    from docs_core.ingest.canonical.builder import build_canonical_chunks  # noqa: F401
    from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical  # noqa: F401

    assert True

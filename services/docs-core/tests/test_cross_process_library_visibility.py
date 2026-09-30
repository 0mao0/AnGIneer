"""跨进程库可见性回归：读方进程的库/节点清单不得停留在启动快照（2026-09-30）。

背景：DocsService 曾把 libraries/nodes 一次性灌进进程内存（``_load_from_db``），
aichat-api（读方）启动后，docs-api（写方）新建的库/导入的文档对
``list_libraries``/``get_library``/``list_nodes`` 永远不可见——eval 链路
dense=0.00s 全拒答，只能重启 aichat-api。修复=读入口现查 SQLite（读穿）。
本测试用同进程两个 DocsService 实例模拟两个进程共享同一 SQLite。
"""
from docs_core.docs_service import DocsService


def _make_service(monkeypatch, tmp_path) -> DocsService:
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DOCS_VECTORSTORE_PROVIDER", "sqlite")
    return DocsService()


def test_reader_sees_library_created_after_startup(tmp_path, monkeypatch) -> None:
    reader = _make_service(monkeypatch, tmp_path)  # 先启动：清单定格在 default
    writer = _make_service(monkeypatch, tmp_path)  # 另一「进程」：运行中新建库

    writer.create_library("lib-late", "运行中新建的库", "cross-process")

    assert reader.get_library("lib-late") is not None
    assert any(lib.id == "lib-late" for lib in reader.list_libraries())


def test_reader_sees_document_ingested_after_startup(tmp_path, monkeypatch) -> None:
    reader = _make_service(monkeypatch, tmp_path)
    writer = _make_service(monkeypatch, tmp_path)
    writer.create_library("lib-late-docs", "晚导文档的库", "")
    writer.register_document("lib-late-docs", "doc-late-001", title="晚到的文档")

    nodes = [
        n for n in reader.list_nodes("lib-late-docs")
        if getattr(n, "type", "") == "document"
    ]

    assert any(n.id == "doc-late-001" for n in nodes)

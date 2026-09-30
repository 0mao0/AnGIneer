"""@ 文档级提及检索冒烟测试：types=['document'] 只按标题匹配文档，不下探块级；current_doc_id 请求字段存在（此前漏定义导致 /knowledge/references/search 必 500）。"""
from docs_core.docs_service import get_docs_service
from docs_core.step09_query.protocols.contracts import KnowledgeNode


def _make_service(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    # 单例重置由本目录 conftest 的 autouse fixture 负责（模块级 `module._docs_service = None` 打到的是包级 proxy，无效）
    return get_docs_service()


def _register_doc(ks, library_id: str, node_id: str, title: str) -> None:
    ks.create_library(library_id, "文档提及测试库", "test")
    # 经 create_node 走正经写路径落库（list_nodes 已读穿，直塞内存清单不再可见）
    ks.create_node(
        KnowledgeNode(
            id=node_id,
            title=title,
            type="document",
            parent_id=None,
            library_id=library_id,
            file_path=None,
            visible=True,
        )
    )


def test_document_type_matches_titles_only(tmp_path, monkeypatch) -> None:
    ks = _make_service(tmp_path, monkeypatch)
    lib = "lib-doc-mention"
    _register_doc(ks, lib, "doc-gb", "GB 50010-2010混凝土结构设计规范.pdf")
    _register_doc(ks, lib, "doc-jtj", "JTJ 305-2001 船闸总体设计规范.pdf")

    items = ks.search_references(library_id=lib, query="GB", limit=5, types=["document"])
    assert [item["doc_id"] for item in items] == ["doc-gb"]
    item = items[0]
    assert item["target_type"] == "document"
    assert item["target_id"] == "doc-gb" and item["doc_id"] == "doc-gb"
    # 候选标签去扩展名并带书名号（chip 直接可展示）
    assert item["label"] == "《GB 50010-2010混凝土结构设计规范》"

    # 空查询返回全部文档；无匹配查询返回空
    assert {item["doc_id"] for item in ks.search_references(library_id=lib, query="", limit=5, types=["document"])} == {"doc-gb", "doc-jtj"}
    assert ks.search_references(library_id=lib, query="不存在的文档", limit=5, types=["document"]) == []


def test_references_search_request_has_current_doc_id_field() -> None:
    """处理器透传 request.current_doc_id，字段缺失时整个 @ 检索接口 500（历史事故守卫）。"""
    import sys
    from pathlib import Path

    api_dir = Path(__file__).resolve().parents[2] / "docs-api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from docs_routes import KnowledgeReferenceSearchRequest

    payload = KnowledgeReferenceSearchRequest(library_id="default", query="", types=["document"])
    assert hasattr(payload, "current_doc_id")
    assert payload.current_doc_id is None

"""table_semantics 旁路字段单测：04 生成、05 透传、编辑失效。"""

from docs_core.step04_structure.shared.table_semantics import (
    TABLE_SEMANTICS_VERSION,
    TABLE_TYPE_NUMERIC_DENSE,
    enrich_graph_nodes_table_semantics,
)


TABLE_HTML = (
    "<table><tr><td>项目</td><td>数值</td></tr>"
    "<tr><td>高度</td><td>100</td></tr>"
    "<tr><td>宽度</td><td>200</td></tr></table>"
)


def _table_node(uid, html, caption=None):
    node = {
        "block_uid": uid,
        "id": uid,
        "block_type": "table",
        "page_idx": 0,
        "block_seq": 1,
        "table_html": html,
        "plain_text": caption or "",
    }
    if caption is not None:
        node["caption"] = caption
    return node


def test_enrich_graph_nodes_writes_table_semantics_sidecar() -> None:
    paragraph = {
        "block_uid": "d:0:2",
        "id": "d:0:2",
        "block_type": "paragraph",
        "page_idx": 0,
        "block_seq": 2,
        "plain_text": "正文",
    }
    nodes = [
        _table_node("d:0:1", TABLE_HTML, caption="表1 标题"),
        paragraph,
    ]
    updated, stats = enrich_graph_nodes_table_semantics(nodes)
    assert stats == {"total_tables": 1, "enriched": 1, "skipped": 0}

    sidecar = updated[0]["table_semantics"]
    assert set(sidecar) == {
        "table_type",
        "table_meta",
        "table_schema",
        "table_row_keys",
        "table_summary",
        "table_text_chunks",
        "version",
    }
    assert sidecar["version"] == TABLE_SEMANTICS_VERSION
    assert sidecar["table_meta"]["title"] == "表1 标题"
    assert sidecar["table_schema"] == ["项目", "数值"]
    assert sidecar["table_row_keys"] == ["高度", "宽度"]
    assert sidecar["table_summary"] == "表格《表1 标题》包含 2 行、2 列。 列：项目、数值"
    assert updated[1] == paragraph  # 非表格节点不写旁路


def test_enrich_skips_table_without_html() -> None:
    nodes = [
        {
            "block_uid": "d:0:1",
            "id": "d:0:1",
            "block_type": "table",
            "page_idx": 0,
            "block_seq": 1,
        }
    ]
    updated, stats = enrich_graph_nodes_table_semantics(nodes)
    assert stats == {"total_tables": 1, "enriched": 0, "skipped": 1}
    assert "table_semantics" not in updated[0]


def test_canonical_builder_passes_through_table_semantics(monkeypatch) -> None:
    import docs_core.step05_sqlite_fts.rebuild.canonical_builder as canonical_builder
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (
        build_canonical_blocks_from_source,
        build_canonical_tables_from_source,
    )

    def _boom(_table):
        raise AssertionError("已有 table_semantics 时不应重算")

    monkeypatch.setattr(canonical_builder, "enrich_canonical_table", _boom)

    sidecar = {
        "table_type": TABLE_TYPE_NUMERIC_DENSE,
        "table_meta": {"title": "表1", "row_count": 2, "col_count": 2},
        "table_schema": ["项目", "数值"],
        "table_row_keys": ["高度", "宽度"],
        "table_summary": "表格《表1》包含 2 行、2 列。",
        "table_text_chunks": [],
        "version": TABLE_SEMANTICS_VERSION,
    }
    raw = [{
        "block_uid": "d:0:1",
        "block_type": "table",
        "page_idx": 0,
        "block_seq": 1,
        "text": "表1 标题",
        "table_html": TABLE_HTML,
        "table_semantics": sidecar,
    }]
    blocks = build_canonical_blocks_from_source("d", raw)
    tables, _chunks = build_canonical_tables_from_source("d", raw, blocks)
    assert len(tables) == 1
    table = tables[0]
    assert table.table_type == TABLE_TYPE_NUMERIC_DENSE
    assert table.summary == sidecar["table_summary"]
    assert table.row_keys == sidecar["table_row_keys"]
    assert table.text_chunks == []


def test_graph_editor_invalidates_table_semantics_on_html_change() -> None:
    from docs_core.step05_sqlite_fts.graph_editor import (
        _invalidate_edited_table_semantics,
    )

    node = {
        "block_uid": "d:0:1",
        "id": "d:0:1",
        "block_type": "table",
        "page_idx": 0,
        "block_seq": 1,
        "table_html": "<table><tr><td>a</td></tr></table>",
        "table_semantics": {"table_type": "hybrid", "version": TABLE_SEMANTICS_VERSION},
    }
    before = {"nodes": [dict(node)]}
    after = {"nodes": [dict(node)]}
    after["nodes"][0]["table_html_corrected"] = "<table><tr><td>b</td></tr></table>"

    invalidated = _invalidate_edited_table_semantics(after, before)
    assert invalidated == ["d:0:1"]
    assert "table_semantics" not in after["nodes"][0]


def test_graph_editor_keeps_table_semantics_when_unchanged() -> None:
    from docs_core.step05_sqlite_fts.graph_editor import (
        _invalidate_edited_table_semantics,
    )

    node = {
        "block_uid": "d:0:1",
        "id": "d:0:1",
        "block_type": "table",
        "page_idx": 0,
        "block_seq": 1,
        "table_html": "<table><tr><td>a</td></tr></table>",
        "table_semantics": {"table_type": "hybrid", "version": TABLE_SEMANTICS_VERSION},
    }
    before = {"nodes": [dict(node)]}
    after = {"nodes": [dict(node)]}
    assert _invalidate_edited_table_semantics(after, before) == []
    assert "table_semantics" in after["nodes"][0]


def test_rebuild_module_reexports_shared_impl() -> None:
    from docs_core.step05_sqlite_fts.rebuild.table_semantics import (
        build_table_representations,
        enrich_canonical_table,
        enrich_graph_nodes_table_semantics,
    )

    assert callable(enrich_canonical_table)
    assert callable(build_table_representations)
    assert callable(enrich_graph_nodes_table_semantics)


def test_adapt_graph_node_carries_table_semantics() -> None:
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import adapt_graph_node

    sidecar = {"table_type": "hybrid", "version": TABLE_SEMANTICS_VERSION}
    raw = {
        "block_uid": "d:0:1",
        "block_type": "table",
        "page_idx": 0,
        "block_seq": 1,
        "plain_text": "表1",
        "table_html": TABLE_HTML,
        "table_semantics": sidecar,
    }
    adapted = adapt_graph_node(raw, 0, "")
    assert adapted["table_semantics"] == sidecar

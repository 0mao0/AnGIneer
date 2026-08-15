"""PoPo 续接/表格合并 pass 单元测试（Phase 9）。"""

import json
import sqlite3
from pathlib import Path

import pytest

from docs_core.models.types import BoundingBox, CanonicalBlock, CanonicalDocument, CanonicalTable, PageBBox
from docs_core.step04_structure.popo.popo_signal_aligner import align_popo_blocks
from docs_core.step04_structure.popo.popo_signal_injector import inject_popo_signals
from docs_core.step04_structure.popo.popo_block_merger import merge_blocks

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = REPO_ROOT / "data" / "knowledge_base" / "libraries" / "default" / "documents"


def _node(uid, page_idx, block_seq, block_type="paragraph", text="", *, bbox=None, contd=None, content_json=None, **extra):
    node = {
        "block_uid": uid,
        "id": uid,
        "page_idx": page_idx,
        "block_seq": block_seq,
        "block_type": block_type,
        "plain_text": text,
        "bbox": list(bbox) if bbox else [0.0, 0.0, 1.0, 0.1],
    }
    if contd is not None:
        node["contd_target_id"] = contd
    if content_json is not None:
        node["content_json"] = content_json
    node.update(extra)
    return node


def test_contd_merges_text_and_page_bboxes() -> None:
    nodes = [
        _node(
            "d:0:1", 0, 1,
            text="4.1.3.2 大型闸门和高水头阀门可采用 ZG35CrMo、ZG50Mn2、",
            bbox=[0.1, 0.9, 0.9, 0.95],
            contd="d:1:1",
            content_json={"paragraph_content": [
                {"type": "text", "content": "4.1.3.2 大型闸门和高水头阀门可采用 ZG35CrMo、ZG50Mn2、"}
            ]},
        ),
        _node(
            "d:1:1", 1, 1,
            text="ZG34CrNiMo等合金铸钢，其质量应符合现行行业标准《大型铸件用低合金铸钢》(JB6402)的规定。",
            bbox=[0.08, 0.11, 0.88, 0.16],
            content_json={"paragraph_content": [
                {"type": "text", "content": "ZG34CrNiMo等合金铸钢，其质量应符合现行行业标准《大型铸件用低合金铸钢》(JB6402)的规定。"}
            ]},
        ),
    ]
    updated, stats = merge_blocks("d", nodes)
    assert stats["applied"] == 1
    assert len(updated) == 1
    merged = updated[0]
    assert merged["block_uid"] == "d:0:1"
    assert merged["plain_text"] == (
        "4.1.3.2 大型闸门和高水头阀门可采用 ZG35CrMo、ZG50Mn2、"
        "ZG34CrNiMo等合金铸钢，其质量应符合现行行业标准《大型铸件用低合金铸钢》(JB6402)的规定。"
    )
    assert merged["merged_from"] == ["d:1:1"]
    assert "contd_target_id" not in merged
    assert merged["page_bboxes"] == [
        {"page_idx": 0, "bbox": [0.1, 0.9, 0.9, 0.95]},
        {"page_idx": 1, "bbox": [0.08, 0.11, 0.88, 0.16]},
    ]
    assert merged["content_json"]["paragraph_content"][0]["content"] == merged["plain_text"]


def test_contd_keeps_page_furniture_and_resequences() -> None:
    nodes = [
        _node("d:0:1", 0, 1, text="前半", contd="d:1:1"),
        _node("d:0:2", 0, 2, block_type="page_header", text="页眉"),
        _node("d:0:3", 0, 3, block_type="page_number", text="9"),
        _node("d:0:4", 0, 4, block_type="page_footer", text="页脚"),
        _node("d:1:1", 1, 1, text="后半"),
    ]
    updated, stats = merge_blocks("d", nodes)
    uids = [n["block_uid"] for n in updated]
    assert uids == ["d:0:1", "d:0:2", "d:0:3", "d:0:4"]
    assert updated[0]["plain_text"] == "前半后半"
    assert updated[0]["page_bboxes"][1]["page_idx"] == 1
    assert [n["block_seq"] for n in updated] == [1, 2, 3, 4]


TABLE_SRC = (
    "<table>"
    "<tr><td>项目</td><td>数值</td></tr>"
    "<tr><td>高度</td><td>100</td></tr>"
    "</table>"
)
TABLE_TGT = (
    "<table>"
    "<tr><td>项目</td><td>数值</td></tr>"
    "<tr><td>宽度</td><td>200</td></tr>"
    "</table>"
)


def _table_node(uid, page_idx, block_seq, html, *, bbox=None, caption=None, footnote=None, table_merge=None, content_json=None):
    node = {
        "block_uid": uid,
        "id": uid,
        "page_idx": page_idx,
        "block_seq": block_seq,
        "block_type": "table",
        "plain_text": caption or "",
        "bbox": list(bbox) if bbox else [0.0, 0.0, 1.0, 0.5],
        "table_html": html,
        "caption": caption or "",
        "footnote": footnote or "",
    }
    if table_merge is not None:
        node["table_merge_id"] = table_merge
    if content_json is not None:
        node["content_json"] = content_json
    return node


def test_table_merge_concats_rows_and_dedups_header() -> None:
    nodes = [
        _table_node("d:0:1", 0, 1, TABLE_SRC, bbox=[0.1, 0.5, 0.9, 0.7], table_merge="d:1:1",
                    caption="表4.1.1 钢号",
                    content_json={"html": TABLE_SRC, "table_caption": [{"type": "text", "content": "表4.1.1 钢号"}]}),
        _table_node("d:1:1", 1, 1, TABLE_TGT, bbox=[0.08, 0.1, 0.9, 0.3],
                    footnote="注：单位 mm",
                    content_json={"html": TABLE_TGT, "table_footnote": [{"type": "text", "content": "注：单位 mm"}]}),
    ]
    updated, stats = merge_blocks("d", nodes)
    assert stats["applied"] == 1
    merged = updated[0]
    assert merged["block_uid"] == "d:0:1"
    assert merged["table_html"].count("<tr") == 3  # 表头 + 2 行数据，重复表头已去重
    assert merged["caption"] == "表4.1.1 钢号"
    assert "注：单位 mm" in merged["footnote"]
    assert merged["content_json"]["html"] == merged["table_html"]
    assert merged["page_bboxes"][-1]["page_idx"] == 1
    assert merged["merged_from"] == ["d:1:1"]
    assert "table_merge_id" not in merged


def test_table_merge_preserves_fragment_image_paths() -> None:
    """跨页表合并后，首表应保留全部页图片路径，供弹框逐页展示。"""
    src_cj = {"html": TABLE_SRC, "image_source": {"path": "images/first.jpg"}}
    tgt_cj = {"html": TABLE_TGT, "image_source": {"path": "images/second.jpg"}}
    src = _table_node("d:0:1", 0, 1, TABLE_SRC, table_merge="d:1:1", content_json=src_cj)
    src["image_path"] = "images/first.jpg"
    tgt = _table_node("d:1:1", 1, 1, TABLE_TGT, content_json=tgt_cj)
    tgt["image_path"] = "images/second.jpg"
    updated, _stats = merge_blocks("d", [src, tgt])
    merged = updated[0]
    assert merged["image_path"] == "images/first.jpg"
    assert merged["image_paths"] == ["images/first.jpg", "images/second.jpg"]


def test_table_merge_keeps_source_caption_and_target_footnote() -> None:
    nodes = [
        _table_node("d:0:1", 0, 1, TABLE_SRC, table_merge="d:1:1", caption="表1 标题",
                    content_json={"html": TABLE_SRC, "table_caption": [{"type": "text", "content": "表1 标题"}],
                                  "table_footnote": [{"type": "text", "content": "注：来源A"}]}),
        _table_node("d:1:1", 1, 1, TABLE_TGT, caption="表2 标题",
                    content_json={"html": TABLE_TGT, "table_caption": [{"type": "text", "content": "表2 标题"}],
                                  "table_footnote": [{"type": "text", "content": "注：来源B"}]}),
    ]
    updated, _ = merge_blocks("d", nodes)
    merged = updated[0]
    assert merged["caption"] == "表1 标题"  # caption 归首页
    assert merged["content_json"]["table_footnote"] == [
        {"type": "text", "content": "注：来源A"},
        {"type": "text", "content": "注：来源B"},
    ]


def test_table_merge_refreshes_plain_text_with_target_footnote() -> None:
    """续页脚注只存在 content_json 时（真实 graph 节点形态），合并后 plain_text 必须同步刷新。"""
    src_cj = {
        "html": TABLE_SRC,
        "table_caption": [{"type": "text", "content": "表1.1.1 钢号"}],
    }
    tgt_cj = {
        "html": TABLE_TGT,
        "table_footnote": [{"type": "text", "content": "注：单位 mm"}],
    }
    nodes = [
        _table_node("d:0:1", 0, 1, TABLE_SRC, bbox=[0.1, 0.5, 0.9, 0.7],
                    table_merge="d:1:1", content_json=src_cj),
        _table_node("d:1:1", 1, 1, TABLE_TGT, bbox=[0.08, 0.1, 0.9, 0.3],
                    content_json=tgt_cj),
    ]
    updated, _ = merge_blocks("d", nodes)
    merged = updated[0]
    assert merged["plain_text"] == "表1.1.1 钢号 注：单位 mm"
    assert merged["footnote"] == "注：单位 mm"
    assert merged["content_json"]["table_footnote"] == [
        {"type": "text", "content": "注：单位 mm"}
    ]


def test_table_merge_inherits_missing_source_caption_from_target() -> None:
    """首页缺表题、续页有正式表题时，合并后继承续页表题。"""
    src_cj = {"html": TABLE_SRC}
    tgt_cj = {
        "html": TABLE_TGT,
        "table_caption": [{"type": "text", "content": "表1.1.1 钢号"}],
    }
    nodes = [
        _table_node("d:0:1", 0, 1, TABLE_SRC, table_merge="d:1:1", content_json=src_cj),
        _table_node("d:1:1", 1, 1, TABLE_TGT, content_json=tgt_cj),
    ]
    updated, _ = merge_blocks("d", nodes)
    merged = updated[0]
    assert merged["plain_text"] == "表1.1.1 钢号"
    assert merged["content_json"]["table_caption"] == [
        {"type": "text", "content": "表1.1.1 钢号"}
    ]


def test_table_merge_ignores_fragment_caption() -> None:
    """OCR 碎片（如 .10）不应被当作表题继承，避免生成垃圾标题。"""
    src_cj = {"html": TABLE_SRC}
    tgt_cj = {
        "html": TABLE_TGT,
        "table_caption": [{"type": "text", "content": ".10"}],
    }
    nodes = [
        _table_node("d:0:1", 0, 1, TABLE_SRC, table_merge="d:1:1", content_json=src_cj),
        _table_node("d:1:1", 1, 1, TABLE_TGT, content_json=tgt_cj),
    ]
    updated, _ = merge_blocks("d", nodes)
    merged = updated[0]
    assert merged["plain_text"] == ""
    assert merged["content_json"].get("table_caption") is None


def test_contd_chain_merges_all_hops() -> None:
    nodes = [
        _node("d:0:1", 0, 1, text="A", contd="d:1:1"),
        _node("d:1:1", 1, 1, text="B", contd="d:2:1"),
        _node("d:2:1", 2, 1, text="C"),
    ]
    updated, stats = merge_blocks("d", nodes)
    assert stats["applied"] == 2
    assert len(updated) == 1
    merged = updated[0]
    assert merged["plain_text"] == "ABC"
    assert merged["merged_from"] == ["d:1:1", "d:2:1"]
    assert len(merged["page_bboxes"]) == 3


def test_chain_cycle_rejected() -> None:
    nodes = [
        _node("d:0:1", 0, 1, text="A", contd="d:0:2"),
        _node("d:0:2", 0, 2, text="B", contd="d:0:1"),
    ]
    updated, stats = merge_blocks("d", nodes)
    assert stats["rejected"] >= 1
    assert stats["applied"] == 0
    assert len(updated) == 2


def test_chain_length_capped() -> None:
    nodes = [_node(f"d:0:{i}", 0, i, text=str(i), contd=f"d:0:{i+1}") for i in range(1, 7)]
    nodes[-1].pop("contd_target_id")
    updated, stats = merge_blocks("d", nodes)
    assert stats["applied"] == 4  # MAX_MERGE_CHAIN=5 → 吸收 4 个 target
    assert len(updated) == 2
    assert updated[0]["plain_text"] == "12345"
    assert updated[0]["merged_from"] == ["d:0:2", "d:0:3", "d:0:4", "d:0:5"]


def test_refs_and_edges_remapped_to_survivor() -> None:
    nodes = [
        _node("d:0:1", 0, 1, text="前半", contd="d:1:1"),
        _node("d:1:1", 1, 1, text="后半"),
        _node("d:0:2", 0, 0, block_type="title", text="标题", parent_uid="d:1:1",
              caption_block_uids=["d:1:1"]),
    ]
    edges = [
        {"from": "d:1:1", "to": "d:0:2"},
        {"from": "d:0:1", "to": "d:1:1"},
    ]
    updated, stats = merge_blocks("d", nodes, edges=edges)
    assert stats["applied"] == 1
    by_uid = {n["block_uid"]: n for n in updated}
    assert by_uid["d:0:2"]["parent_uid"] == "d:0:1"
    assert by_uid["d:0:2"]["caption_block_uids"] == ["d:0:1"]
    assert edges[0]["from"] == "d:0:1"
    assert edges[1]["to"] == "d:0:1"


def test_apply_signals_wiring_invokes_merge(monkeypatch, tmp_path) -> None:
    """_apply_popo_signals 在 inject 之后调用 merge_blocks，edges 透传、统计并入 popo_signal。"""
    import json

    import docs_core.docs_file_io as afs
    import docs_core.step04_structure.popo.popo_block_merger as merger
    from docs_core.step04_structure import solo2json_pipeline

    middle_dir = tmp_path / "mineru_raw"
    middle_dir.mkdir(parents=True)
    (middle_dir / "middle.json").write_text(json.dumps({"pdf_info": []}), encoding="utf-8")

    class _FS:
        def read_popo_enriched_blocks(self, library_id, doc_id):
            return []

    monkeypatch.setattr(afs, "file_storage", _FS())
    monkeypatch.setattr(
        solo2json_pipeline.paths,
        "get_mineru_raw_dir",
        lambda *a, **k: tmp_path / "mineru_raw",
    )

    calls = {}

    def _fake_merge(doc_id, nodes, *, edges=None):
        calls["doc_id"] = doc_id
        calls["edges"] = edges
        return nodes, {"applied": 1, "rejected": 0}

    monkeypatch.setattr(merger, "merge_blocks", _fake_merge)

    edges = [{"from": "d:0:1", "to": "d:0:2"}]
    nodes = [{"block_uid": "d:0:1", "block_type": "paragraph", "plain_text": "A", "page_idx": 0, "block_seq": 1}]
    updated, stats, popo_candidates = solo2json_pipeline._apply_popo_signals(
        "lib", "doc", nodes, edges=edges
    )
    assert calls["doc_id"] == "doc"
    assert calls["edges"] is edges
    assert stats["merge"]["applied"] == 1
    assert updated == nodes
    assert popo_candidates["popo_levels"] == {}


def test_canonical_blocks_read_page_bboxes_from_raw() -> None:
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import build_canonical_blocks_from_source

    raw = [{
        "block_uid": "d:0:1", "block_type": "paragraph", "page_idx": 0, "block_seq": 1,
        "text": "完整段落", "content": "完整段落",
        "page_bboxes": [
            {"page_idx": 0, "bbox": [0.1, 0.9, 0.9, 0.95]},
            {"page_idx": 1, "bbox": [0.08, 0.11, 0.88, 0.16]},
        ],
        "merged_from": ["d:1:1"],
    }]
    blocks = build_canonical_blocks_from_source("d", raw)
    assert blocks[0].page_bboxes is not None
    assert blocks[0].page_bboxes[1].page_idx == 1
    assert blocks[0].merged_from == ["d:1:1"]


def test_chunk_page_range_spans_merged_block() -> None:
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import build_canonical_chunks

    block = CanonicalBlock(
        block_id="d:0:1", doc_id="d", page_idx=0, block_type="paragraph",
        text="完整段落", text_clean="完整段落", reading_order=1,
        page_bboxes=[
            PageBBox(page_idx=0, bbox=BoundingBox()),
            PageBBox(page_idx=1, bbox=BoundingBox()),
        ],
    )
    chunks = build_canonical_chunks([block])
    assert chunks[0].page_start == 0
    assert chunks[0].page_end == 1


def test_canonical_table_page_range_spans_merged_block() -> None:
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (
        build_canonical_blocks_from_source,
        build_canonical_tables_from_source,
    )

    raw = [{
        "block_uid": "d:0:1", "block_type": "table", "page_idx": 0, "block_seq": 1,
        "table_html": "<table><tr><td>a</td><td>b</td></tr></table>",
        "page_bboxes": [
            {"page_idx": 0, "bbox": [0.0, 0.0, 1.0, 1.0]},
            {"page_idx": 1, "bbox": [0.0, 0.0, 1.0, 1.0]},
        ],
    }]
    blocks = build_canonical_blocks_from_source("d", raw)
    tables, _chunks = build_canonical_tables_from_source("d", raw, blocks)
    assert tables[0].page_start == 0
    assert tables[0].page_end == 1
    assert tables[0].page_bboxes[1].page_idx == 1


def test_adapt_graph_node_preserves_page_bboxes() -> None:
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import adapt_graph_node

    raw = {
        "block_uid": "d:0:1", "block_type": "paragraph", "page_idx": 0, "block_seq": 1,
        "plain_text": "x",
        "page_bboxes": [{"page_idx": 0, "bbox": [0.0, 0.0, 1.0, 1.0]}],
        "merged_from": ["d:1:1"],
    }
    adapted = adapt_graph_node(raw, 0, "")
    assert adapted["page_bboxes"] == raw["page_bboxes"]
    assert adapted["merged_from"] == ["d:1:1"]


def test_store_roundtrip_page_bboxes(tmp_path) -> None:
    from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore

    block = CanonicalBlock(
        block_id="d:0:1", doc_id="d", page_idx=0, block_type="paragraph",
        text="完整段落", text_clean="完整段落", reading_order=1,
        page_bboxes=[
            PageBBox(page_idx=0, bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1)),
            PageBBox(page_idx=1, bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1)),
        ],
        merged_from=["d:1:1"],
    )
    document = CanonicalDocument(doc_id="d", library_id="lib", title="t", blocks=[block])
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    store.save_document(document)
    loaded = store.get_document("d")
    assert loaded.blocks[0].page_bboxes is not None
    assert loaded.blocks[0].page_bboxes[1].page_idx == 1
    assert loaded.blocks[0].merged_from == ["d:1:1"]


def test_store_roundtrip_table_page_bboxes(tmp_path) -> None:
    from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore

    table = CanonicalTable(
        table_id="t-1", doc_id="d", page_start=0, page_end=1,
        page_bboxes=[
            PageBBox(page_idx=0, bbox=BoundingBox()),
            PageBBox(page_idx=1, bbox=BoundingBox()),
        ],
    )
    document = CanonicalDocument(doc_id="d", library_id="lib", title="t", tables=[table])
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    store.save_document(document)
    loaded = store.get_document("d")
    assert loaded.tables[0].page_start == 0
    assert loaded.tables[0].page_end == 1
    assert loaded.tables[0].page_bboxes[1].page_idx == 1


def test_migration_adds_page_bbox_columns(tmp_path) -> None:
    from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore

    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE canonical_blocks (block_id TEXT PRIMARY KEY, doc_id TEXT, "
        "page_idx INTEGER, reading_order INTEGER, text_clean TEXT, clause_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE canonical_chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT, "
        "chunk_type TEXT, page_start INTEGER, section_path TEXT, text_clean TEXT, clause_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE canonical_tables (table_id TEXT PRIMARY KEY, doc_id TEXT, "
        "table_type TEXT, page_start INTEGER)"
    )
    conn.execute("CREATE TABLE canonical_pages (doc_id TEXT, page_idx INTEGER)")
    conn.execute(
        "CREATE TABLE canonical_citation_targets (row_id TEXT PRIMARY KEY, doc_id TEXT, target_id TEXT)"
    )
    conn.commit()
    conn.close()

    CanonicalSQLiteStore(db_path=db)  # init_schema 触发迁移
    conn = sqlite3.connect(db)
    block_cols = {row[1] for row in conn.execute("PRAGMA table_info(canonical_blocks)")}
    table_cols = {row[1] for row in conn.execute("PRAGMA table_info(canonical_tables)")}
    conn.close()
    assert "page_bboxes_json" in block_cols
    assert "merged_from_json" in block_cols
    assert "page_bboxes_json" in table_cols


def test_rows_projection_carries_page_bboxes() -> None:
    from docs_core.step05_sqlite_fts.rows_projection import (
        build_doc_block_rows,
        build_document_segments,
    )

    block = CanonicalBlock(
        block_id="d:0:1", doc_id="d", page_idx=0, block_type="paragraph",
        text="完整段落", text_clean="完整段落", reading_order=1,
        page_bboxes=[PageBBox(page_idx=0, bbox=BoundingBox()), PageBBox(page_idx=1, bbox=BoundingBox())],
        merged_from=["d:1:1"],
    )
    document = CanonicalDocument(doc_id="d", library_id="lib", title="t", blocks=[block])
    segments = build_document_segments(document, [])
    base_rows, derived_rows = build_doc_block_rows(document)
    assert segments[0]["meta"]["page_bboxes"] is not None
    assert segments[0]["meta"]["merged_from"] == ["d:1:1"]
    assert base_rows[0]["page_bboxes"] is not None
    assert base_rows[0]["merged_from"] == ["d:1:1"]


def test_graph_editor_projection_carries_page_bboxes() -> None:
    from docs_core.step05_sqlite_fts.graph_editor import _build_doc_block_projection_rows

    graph = {
        "doc_name": "doc",
        "nodes": [{
            "block_uid": "d:0:1", "block_type": "paragraph", "page_idx": 0, "block_seq": 1,
            "plain_text": "完整段落",
            "page_bboxes": [{"page_idx": 0, "bbox": [0.0, 0.0, 1.0, 1.0]}],
            "merged_from": ["d:1:1"],
        }],
        "edges": [],
        "stats": {},
    }
    base_rows, _derived = _build_doc_block_projection_rows("doc", graph)
    assert base_rows[0]["page_bboxes"] == [{"page_idx": 0, "bbox": [0.0, 0.0, 1.0, 1.0]}]
    assert base_rows[0]["merged_from"] == ["d:1:1"]


def _load_doc(doc_id: str):
    parsed = KB / doc_id / "parsed"
    middle = json.loads((parsed / "mineru_raw" / "middle.json").read_text(encoding="utf-8"))
    enriched = json.loads((parsed / "popo" / "enriched_blocks.json").read_text(encoding="utf-8"))
    return middle, enriched


def _solo_nodes_for(doc_id: str):
    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles

    parsed = KB / doc_id / "parsed"
    return build_structured_from_rawfiles(
        parsed, doc_id, doc_id, llm_client=None, options={"use_llm": False}
    ).nodes


@pytest.mark.skipif(not (KB / "doc-406e43e8" / "parsed").exists(), reason="真实数据目录缺失")
def test_real_doc_contd_merged_into_complete_block() -> None:
    """船闸规范 4.1.3.2 跨页续接：merge 后为单节点完整段落 + 两页 bbox + merged_from。"""
    doc_id = "doc-406e43e8"
    middle, enriched = _load_doc(doc_id)
    nodes = _solo_nodes_for(doc_id)
    alignment = align_popo_blocks(doc_id, middle, enriched)
    assert not alignment.degraded
    nodes, _stats = inject_popo_signals(doc_id, nodes, enriched, alignment)

    updated, stats = merge_blocks(doc_id, nodes)
    assert stats["applied"] >= 1
    by_uid = {n["block_uid"]: n for n in updated}
    merged = by_uid["doc-406e43e8:12:8"]
    assert merged["plain_text"].startswith("4.1.3.2 大型闸门和高水头阀门可采用")
    compact = merged["plain_text"].replace(" ", "")
    assert "ZG34CrNiMo等合金铸钢" in compact
    assert compact.endswith("(JB6402)的规定。")
    assert len(merged["page_bboxes"]) >= 2
    assert merged["page_bboxes"][-1]["page_idx"] == 13
    assert merged["merged_from"] == ["doc-406e43e8:13:1"]
    assert "doc-406e43e8:13:1" not in by_uid


@pytest.mark.skipif(not (KB / "doc-12f45ca9" / "parsed").exists(), reason="真实数据目录缺失")
def test_real_doc_without_signals_unchanged() -> None:
    """海港1 无 contd/table_merge：merge 零改动，流程不回归。"""
    doc_id = "doc-12f45ca9"
    middle, enriched = _load_doc(doc_id)
    nodes = _solo_nodes_for(doc_id)
    alignment = align_popo_blocks(doc_id, middle, enriched)
    assert not alignment.degraded
    nodes, _stats = inject_popo_signals(doc_id, nodes, enriched, alignment)
    updated, stats = merge_blocks(doc_id, nodes)
    assert stats["applied"] == 0
    assert stats["rejected"] == 0
    assert len(updated) == len(nodes)


def test_injector_dedupes_mutual_table_merge_pair() -> None:
    """PoPo 双向打标（A→B 且 B→A）只保留阅读序在前的一方为 source，避免合并成环。"""
    from docs_core.step04_structure.popo.popo_signal_injector import build_contd_instructions

    class _FakeAlignment:
        solo_block_uid_map = {"src13": "doc:3:1", "src14": "doc:4:1"}

    enriched = [
        {"id": 1, "source_id": "src13", "page": 4, "type": "table", "table_merge": 2},
        {"id": 2, "source_id": "src14", "page": 5, "type": "table", "table_merge": 1},
    ]
    instructions, reasons = build_contd_instructions("d", enriched, _FakeAlignment())
    assert not reasons
    assert len(instructions) == 1
    assert instructions[0]["source_uid"] == "doc:3:1"
    assert instructions[0]["target_uid"] == "doc:4:1"


def _text_node(uid, page_idx, block_seq, text):
    return {
        "block_uid": uid,
        "id": uid,
        "page_idx": page_idx,
        "block_seq": block_seq,
        "block_type": "text",
        "plain_text": text,
    }


_HDR = "<tr><td>项目</td><td>数值</td></tr>"


def test_heuristic_detects_marker_header_pair() -> None:
    from docs_core.step04_structure.popo.popo_table_continuation import detect_table_continuations

    src_html = f"<table>{_HDR}<tr><td>高度</td><td>100</td></tr></table>"
    tgt_html = f"<table>{_HDR}<tr><td>宽度</td><td>200</td></tr></table>"
    nodes = [
        _table_node("d:0:1", 0, 1, src_html, bbox=[0.1, 0.5, 0.9, 0.7]),
        _text_node("d:1:1", 1, 1, "续表"),
        _table_node("d:1:2", 1, 2, tgt_html, bbox=[0.08, 0.1, 0.9, 0.3]),
    ]
    instructions = detect_table_continuations(nodes, doc_id="d")
    assert instructions == [{"kind": "table_merge", "source_uid": "d:0:1", "target_uid": "d:1:2"}]


def test_heuristic_rejects_when_only_columns_match() -> None:
    from docs_core.step04_structure.popo.popo_table_continuation import detect_table_continuations

    src_html = "<table><tr><td>项目</td><td>数值</td></tr><tr><td>高度</td><td>100</td></tr></table>"
    tgt_html = "<table><tr><td>类别</td><td>金额</td></tr><tr><td>宽度</td><td>200</td></tr></table>"
    nodes = [
        _table_node("d:0:1", 0, 1, src_html, bbox=[0.1, 0.5, 0.9, 0.7]),
        # 宽度 0.62 vs 0.8（>10%），无标记、表头不一致：仅列数一致不足以合并
        _table_node("d:1:1", 1, 1, tgt_html, bbox=[0.08, 0.1, 0.7, 0.3]),
    ]
    instructions = detect_table_continuations(nodes, doc_id="d")
    assert instructions == []


def test_heuristic_rejects_caption_number_conflict() -> None:
    from docs_core.step04_structure.popo.popo_table_continuation import detect_table_continuations

    src_html = f"<table>{_HDR}<tr><td>高度</td><td>100</td></tr></table>"
    tgt_html = f"<table>{_HDR}<tr><td>宽度</td><td>200</td></tr></table>"
    nodes = [
        _table_node(
            "d:0:1", 0, 1, src_html, bbox=[0.1, 0.5, 0.9, 0.7],
            content_json={"html": src_html, "table_caption": [{"type": "text", "content": "表 A.0.2-2 甲表"}]},
        ),
        _table_node(
            "d:1:1", 1, 1, tgt_html, bbox=[0.08, 0.1, 0.9, 0.3],
            content_json={"html": tgt_html, "table_caption": [{"type": "text", "content": "表 A.0.2-3 乙表"}]},
        ),
    ]
    instructions = detect_table_continuations(nodes, doc_id="d")
    assert instructions == []


EXPECTED_ALL_CONTINUATION_PAIRS = {
    ("doc-3ef8bdc1:0:6", "doc-3ef8bdc1:1:2"),
    ("doc-3ef8bdc1:1:3", "doc-3ef8bdc1:2:2"),
    ("doc-3ef8bdc1:3:1", "doc-3ef8bdc1:4:1"),
    ("doc-3ef8bdc1:4:1", "doc-3ef8bdc1:5:2"),
    ("doc-3ef8bdc1:5:2", "doc-3ef8bdc1:6:1"),
    ("doc-3ef8bdc1:6:1", "doc-3ef8bdc1:7:2"),
}


@pytest.mark.skipif(not (KB / "doc-3ef8bdc1" / "parsed").exists(), reason="真实数据目录缺失")
def test_real_doc_heuristic_detects_continuation_pairs() -> None:
    from docs_core.step04_structure.popo.popo_table_continuation import detect_table_continuations

    doc_id = "doc-3ef8bdc1"
    middle, enriched = _load_doc(doc_id)
    nodes = _solo_nodes_for(doc_id)
    alignment = align_popo_blocks(doc_id, middle, enriched)
    nodes, _stats = inject_popo_signals(doc_id, nodes, enriched, alignment)
    instructions = detect_table_continuations(nodes, doc_id="doc-3ef8bdc1")
    pairs = {
        (i["source_uid"], i["target_uid"])
        for i in instructions
    }
    assert pairs == EXPECTED_ALL_CONTINUATION_PAIRS


@pytest.mark.skipif(not (KB / "doc-3ef8bdc1" / "parsed").exists(), reason="真实数据目录缺失")
def test_real_doc_inject_heuristic_merge_combines_all_continuations() -> None:
    """启发式 6 对全部合并；LNG 序号表 5 页合成单节点（hybrid 数据下 PoPo 未打标）。"""
    from docs_core.step04_structure.popo.popo_table_continuation import detect_table_continuations

    doc_id = "doc-3ef8bdc1"
    middle, enriched = _load_doc(doc_id)
    nodes = _solo_nodes_for(doc_id)
    alignment = align_popo_blocks(doc_id, middle, enriched)
    nodes, _stats = inject_popo_signals(doc_id, nodes, enriched, alignment)

    heuristic = detect_table_continuations(nodes, doc_id=doc_id)
    by_uid = {n["block_uid"]: n for n in nodes}
    added = 0
    skipped = 0
    for instruction in heuristic:
        source = by_uid[instruction["source_uid"]]
        if source.get("table_merge_id"):
            skipped += 1
            continue
        source["table_merge_id"] = instruction["target_uid"]
        added += 1
    assert added + skipped == len(EXPECTED_ALL_CONTINUATION_PAIRS)
    assert skipped == 0  # hybrid 产物下 PoPo 未打标，全部由启发式补齐

    updated, stats = merge_blocks(doc_id, nodes)
    assert stats["applied"] == 6
    by_uid_after = {n["block_uid"]: n for n in updated}
    lng = by_uid_after["doc-3ef8bdc1:3:1"]
    assert [p["page_idx"] for p in lng["page_bboxes"]] == [3, 4, 5, 6, 7]
    assert lng["merged_from"] == [
        "doc-3ef8bdc1:4:1",
        "doc-3ef8bdc1:5:2",
        "doc-3ef8bdc1:6:1",
        "doc-3ef8bdc1:7:2",
    ]


@pytest.mark.skipif(not (KB / "doc-3ef8bdc1" / "parsed").exists(), reason="真实数据目录缺失")
def test_real_doc_merged_table_plain_text_includes_continuation_footnote() -> None:
    """跨页表格合并后，续页上的脚注必须同步进 plain_text（A0.2-2/A0.2-3）。"""
    from docs_core.step04_structure.popo.popo_table_continuation import detect_table_continuations

    doc_id = "doc-3ef8bdc1"
    middle, enriched = _load_doc(doc_id)
    nodes = _solo_nodes_for(doc_id)
    alignment = align_popo_blocks(doc_id, middle, enriched)
    nodes, _stats = inject_popo_signals(doc_id, nodes, enriched, alignment)

    heuristic = detect_table_continuations(nodes, doc_id=doc_id)
    by_uid = {n["block_uid"]: n for n in nodes}
    for instruction in heuristic:
        source = by_uid[instruction["source_uid"]]
        if source.get("table_merge_id"):
            continue
        source["table_merge_id"] = instruction["target_uid"]

    updated, stats = merge_blocks(doc_id, nodes)
    assert stats["applied"] == 6
    by_uid = {n["block_uid"]: n for n in updated}

    a022 = by_uid["doc-3ef8bdc1:0:6"]
    assert "注：表中船舶吨级按DWT划分档级" in a022["plain_text"]
    assert "DWT系指船舶载重吨(t)" in a022["plain_text"].replace(" ", "")

    a023 = by_uid["doc-3ef8bdc1:1:3"]
    assert "注：表中船舶吨级按DWT划分档级" in a023["plain_text"]
    assert "DWT系指船舶载重吨(t)" in a023["plain_text"].replace(" ", "")


@pytest.mark.skipif(not (KB / "doc-c8be9f8b" / "parsed").exists(), reason="真实数据目录缺失")
def test_real_doc_haigang2_empty_continuation_merged_by_solo_fallback() -> None:
    """海港2 6.5.4：PoPo 无 contd 标记时，solo 空续块兜底仍把 12:1 并入 11:14。"""
    doc_id = "doc-c8be9f8b"
    nodes = _solo_nodes_for(doc_id)
    by_uid = {n["block_uid"]: n for n in nodes}
    merged = by_uid["doc-c8be9f8b:11:14"]
    assert merged["merged_from"] == ["doc-c8be9f8b:12:1"]
    assert [p["page_idx"] for p in merged["page_bboxes"]] == [11, 12]
    assert "doc-c8be9f8b:12:1" not in by_uid
    assert merged["plain_text"].endswith("并应符合下列规定。")

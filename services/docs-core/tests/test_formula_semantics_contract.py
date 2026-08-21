"""公式语义契约测试：语义层 Canonical 入口（表格四分类 + 公式契约）。"""

import json

from docs_core.step05_sqlite_fts.rebuild.canonical_builder import build_canonical_document_from_blocks
from docs_core.models.types import CanonicalBlock, CanonicalTable
from docs_core.step04_structure.shared.formula_semantics import (
    collect_canonical_explanation_lines,
    enrich_blocks_formula_semantics,
    enrich_formula_block,
    enrich_graph_nodes_formula_semantics,
)
from docs_core.step05_sqlite_fts.rows_projection import _build_content_json
from docs_core.step05_sqlite_fts.rebuild.table_semantics import (
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
    enrich_canonical_table,
)
from fixtures.popo_fixtures import build_canonical_from_solo_jsonl, content_list_block


def test_enrich_canonical_table_contract() -> None:
    table = CanonicalTable(
        table_id="t1",
        doc_id="d",
        title="构件参数表",
        header_rows=[["参数", "数值"]],
        body_rows=[["高度", "100"], ["宽度", "200"]],
    )
    enriched = enrich_canonical_table(table)
    assert set(enriched) == {"table_type", "summary", "row_keys", "text_chunks"}
    assert enriched["table_type"] in {
        TABLE_TYPE_HYBRID,
        TABLE_TYPE_MAPPING_ENUM,
        TABLE_TYPE_NUMERIC_DENSE,
        TABLE_TYPE_TEXT_DENSE,
    }
    assert enriched["summary"]
    assert enriched["row_keys"] == ["高度", "宽度"]
    assert enriched["text_chunks"]


def test_enrich_canonical_block_contract() -> None:
    formula = CanonicalBlock(
        block_id="f1", doc_id="d", page_idx=2, reading_order=10,
        block_type="formula", text="N = μ·F", section_path="5.1",
    )
    explain = CanonicalBlock(
        block_id="p1", doc_id="d", page_idx=2, reading_order=11,
        block_type="paragraph", text="式中：μ 为摩擦系数；F 为法向力。", section_path="5.1",
    )
    distant = CanonicalBlock(
        block_id="p2", doc_id="d", page_idx=5, reading_order=12,
        block_type="paragraph", text="远处无关段落", section_path="其他章节",
    )
    contract = enrich_formula_block(formula, [formula, explain, distant])
    assert contract["formula_text"] == "N = μ·F"
    assert contract["formula_params"], "公式参数契约必须非空"
    assert all(item["extracted_by"] == "rule" for item in contract["formula_params"])
    symbols = [item["symbol"] for item in contract["formula_params"]]
    assert "μ" in symbols and "F" in symbols
    assert contract["llm_status"] == "disabled"
    # 远处/跨章节段落不进入解释段
    assert collect_canonical_explanation_lines(formula, [explain, distant]) == [
        "式中：μ 为摩擦系数；F 为法向力。"
    ]


def test_enrich_canonical_block_skips_non_formula() -> None:
    paragraph = CanonicalBlock(block_id="p", doc_id="d", block_type="paragraph", text="正文")
    contract = enrich_formula_block(paragraph, [paragraph])
    assert contract["formula_params"] == []
    assert contract["llm_status"] == "skipped"


def test_solo_jsonl_chain_preserves_semantics_and_outlines(tmp_path) -> None:
    """solo 04 只出 jsonl，05 重建后公式语义与 outline 无损。"""
    pages = [
        [content_list_block("title", "第一章 总则", level=1)],
        [
            content_list_block("equation_interline", "F = ma", math="F = ma"),
            content_list_block("paragraph", "式中：F 为合力。"),
        ],
    ]
    document = build_canonical_from_solo_jsonl("doc-1", pages, tmp_path)
    formula_block = next(b for b in document.blocks if b.block_type == "formula")
    assert formula_block.formula_semantics, "公式块必须挂载语义契约"
    assert formula_block.formula_semantics["formula_params"]
    assert formula_block.formula_semantics["formula_params"][0]["extracted_by"] == "rule"
    assert document.outlines and document.outlines[0].title == "第一章 总则"


def test_rebuild_from_graph_enriches_tables_and_formulas() -> None:
    """graph 重建路径（solo 降级后端）下表格与公式语义同时生效。"""
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import rebuild_canonical_document_from_graph

    graph = {
        "nodes": [
            {
                "block_uid": "t1", "block_type": "table", "page_idx": 0, "block_seq": 1,
                "plain_text": "参数 | 数值",
                "table_html": "<table><tr><td>参数</td><td>数值</td></tr>"
                              "<tr><td>高度</td><td>100</td></tr></table>",
                "section_path": "", "derived_level": None,
            },
            {
                "block_uid": "f1", "block_type": "formula", "page_idx": 1, "block_seq": 2,
                "plain_text": "N = μ·F", "section_path": "5.1", "derived_level": None,
            },
            {
                "block_uid": "p1", "block_type": "paragraph", "page_idx": 1, "block_seq": 3,
                "plain_text": "式中：μ 为摩擦系数；F 为法向力。",
                "section_path": "5.1", "derived_level": None,
            },
        ],
        "edges": [],
    }
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", graph, title="示例")
    assert document.tables and document.tables[0].row_count == 1
    formula_block = next(b for b in document.blocks if b.block_type == "formula")
    assert formula_block.formula_semantics
    assert formula_block.formula_semantics["formula_params"]


class _MockLLMClient:
    """记录调用次数的 LLM 客户端替身，chat 返回可解析的公式参数 JSON。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, **kwargs) -> str:
        self.calls += 1
        return (
            '{"params":[{"symbol":"μ","description":"摩擦系数","confidence":0.9},'
            '{"symbol":"F","description":"法向力","confidence":0.9}]}'
        )


def _formula_blocks_with_unparseable_explanation() -> list:
    return [
        CanonicalBlock(
            block_id="f1", doc_id="d", page_idx=2, reading_order=10,
            block_type="formula", text="N = μ·F", section_path="5.1",
        ),
        CanonicalBlock(
            block_id="p1", doc_id="d", page_idx=2, reading_order=11,
            block_type="paragraph",
            text="该公式用于计算法向力，具体取值见正文说明。",
            section_path="5.1",
        ),
    ]


def test_build_from_blocks_passes_use_llm_to_formula_semantics() -> None:
    """P2b：blocks 入口必须把 use_llm/llm_client/llm_model 透传给公式语义。"""
    llm = _MockLLMClient()
    document = build_canonical_document_from_blocks(
        "lib-1", "doc-1", title="示例",
        blocks=_formula_blocks_with_unparseable_explanation(),
        use_llm=True, llm_client=llm, llm_model="mock-model",
    )
    assert llm.calls == 1, "use_llm=True 时必须触发公式语义 LLM 调用"
    formula_block = next(b for b in document.blocks if b.block_type == "formula")
    assert formula_block.formula_semantics["llm_status"] == "ok"
    assert formula_block.formula_semantics["formula_params"]
    assert all(item["extracted_by"] == "llm" for item in formula_block.formula_semantics["formula_params"])


def test_build_from_blocks_skips_llm_when_disabled() -> None:
    llm = _MockLLMClient()
    document = build_canonical_document_from_blocks(
        "lib-1", "doc-1", title="示例",
        blocks=_formula_blocks_with_unparseable_explanation(),
        use_llm=False, llm_client=llm, llm_model="mock-model",
    )
    assert llm.calls == 0, "use_llm=False 时不得发起 LLM 调用"
    formula_block = next(b for b in document.blocks if b.block_type == "formula")
    assert formula_block.formula_semantics["llm_status"] == "disabled"


def test_rebuild_preserves_jsonl_formula_semantics() -> None:
    """jsonl 节点带 formula_semantics 时，05 重建原样透传且零 LLM 调用。"""
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import rebuild_canonical_document_from_graph

    contract = {
        "formula_text": "N = μ·F",
        "formula_body": "N = μ·F",
        "formula_number": "5.1-1",
        "formula_params": [
            {"symbol": "μ", "description": "摩擦系数", "unit": None, "reference_hint": None,
             "confidence": 0.9, "extracted_by": "llm"},
        ],
        "formula_param_count": 1,
        "formula_summary": "公式(5.1-1) N = μ·F；包含 1 个参数：μ",
        "llm_status": "ok",
        "explanation_lines": ["式中：μ 为摩擦系数。"],
    }
    graph = {
        "nodes": [
            {
                "block_uid": "f1", "block_type": "formula", "page_idx": 0, "block_seq": 1,
                "plain_text": "N = μ·F", "section_path": "5.1", "derived_level": None,
                "formula_semantics": contract,
            },
        ],
        "edges": [],
    }
    llm = _MockLLMClient()
    document = rebuild_canonical_document_from_graph(
        "lib-1", "doc-1", graph, title="示例",
        use_llm=False, llm_client=llm,
    )
    assert llm.calls == 0
    formula_block = next(b for b in document.blocks if b.block_type == "formula")
    assert formula_block.formula_semantics == contract


def test_rows_projection_writes_formula_semantics_to_content_json() -> None:
    contract = {
        "formula_text": "N = μ·F",
        "formula_body": "N = μ·F",
        "formula_number": "5.1-1",
        "formula_params": [],
        "formula_param_count": 0,
        "formula_summary": "公式(5.1-1) N = μ·F",
        "llm_status": "disabled",
        "explanation_lines": [],
    }
    block = CanonicalBlock(
        block_id="f1", doc_id="d", block_type="formula",
        text="N = μ·F", formula_semantics=contract,
    )
    payload = _build_content_json(block)
    assert payload["formula_semantics"] == contract
    assert payload["math_content"] == "N = μ·F"

    bare = CanonicalBlock(block_id="f2", doc_id="d", block_type="formula", text="E = mc²")
    payload = _build_content_json(bare)
    assert "formula_semantics" not in payload
    assert payload["math_content"] == "E = mc²"


def test_enrich_graph_nodes_formula_semantics_writes_contract() -> None:
    nodes = [
        {
            "block_uid": "d:1:1", "block_type": "equation_interline",
            "page_idx": 1, "block_seq": 1, "math_content": "N = μ·F",
            "plain_text": "N = μ·F", "title_path": "5.1",
        },
        {
            "block_uid": "d:1:2", "block_type": "paragraph",
            "page_idx": 1, "block_seq": 2,
            "plain_text": "式中：μ 为摩擦系数；F 为法向力。", "title_path": "5.1",
        },
    ]
    updated, stats = enrich_graph_nodes_formula_semantics(nodes, use_llm=False)
    assert stats == {
        "total_formulas": 1,
        "enriched": 1,
        "llm_status": "disabled",
        "symbol_corrections": 0,
    }
    formula = next(n for n in updated if n.get("block_uid") == "d:1:1")
    assert formula["formula_semantics"]["formula_param_count"] >= 1
    assert all(
        p["extracted_by"] == "rule"
        for p in formula["formula_semantics"]["formula_params"]
    )
    paragraph = next(n for n in updated if n.get("block_uid") == "d:1:2")
    assert "formula_semantics" not in paragraph


def test_enrich_graph_nodes_prefers_explanation_uids() -> None:
    # explanation_uids 指向远页/跨节段落（重定位规则会拒绝），仍必须被采用
    nodes = [
        {
            "block_uid": "d:1:1", "block_type": "equation_interline",
            "page_idx": 1, "block_seq": 1, "math_content": "N = μ·F",
            "plain_text": "N = μ·F", "title_path": "5.1",
            "explanation_uids": ["d:9:9"],
        },
        {
            "block_uid": "d:9:9", "block_type": "paragraph",
            "page_idx": 9, "block_seq": 99,
            "plain_text": "式中：μ 为摩擦系数；F 为法向力。", "title_path": "其他章",
        },
    ]
    updated, _ = enrich_graph_nodes_formula_semantics(nodes, use_llm=False)
    formula = next(n for n in updated if n.get("block_uid") == "d:1:1")
    lines = formula["formula_semantics"]["explanation_lines"]
    # 归一化会把"；F 为法向力"拆成独立行，但远页/跨节段落必须被采用
    assert any("式中" in line and "μ" in line for line in lines)
    assert any("F 为法向力" in line for line in lines)


def test_enrich_graph_nodes_merges_linked_and_rederived_lines() -> None:
    # 关联只覆盖 1 行时，重定位应补充其余解释段（并集，避免上下文变少）
    nodes = [
        {
            "block_uid": "d:1:1", "block_type": "equation_interline",
            "page_idx": 1, "block_seq": 1, "math_content": "F = ma",
            "plain_text": "F = ma", "title_path": "5.1",
            "explanation_uids": ["d:1:2"],
        },
        {
            "block_uid": "d:1:2", "block_type": "paragraph",
            "page_idx": 1, "block_seq": 2,
            "plain_text": "式中：F 为合力。", "title_path": "5.1",
        },
        {
            "block_uid": "d:1:3", "block_type": "paragraph",
            "page_idx": 1, "block_seq": 3,
            "plain_text": "m 为质量。", "title_path": "5.1",
        },
    ]
    updated, _ = enrich_graph_nodes_formula_semantics(nodes, use_llm=False)
    formula = next(n for n in updated if n.get("block_uid") == "d:1:1")
    lines = formula["formula_semantics"]["explanation_lines"]
    assert any("式中" in line and "F" in line for line in lines)
    assert any("m 为质量" in line for line in lines)


def test_build_structured_index_wires_formula_enrichment(monkeypatch, tmp_path) -> None:
    import docs_core.step04_structure.solo2json_pipeline as pipeline
    from docs_core.step04_structure.solo_engine import StructuredResult

    nodes = [
        {
            "block_uid": "doc-1:0:1", "block_type": "equation_interline",
            "page_idx": 0, "block_seq": 1, "math_content": "F = ma",
            "plain_text": "F = ma", "title_path": "",
        },
        {
            "block_uid": "doc-1:0:2", "block_type": "paragraph",
            "page_idx": 0, "block_seq": 2,
            "plain_text": "式中：F 为合力。", "title_path": "",
        },
    ]
    captured: dict = {}

    def fake_build_structured(*args, **kwargs):
        return StructuredResult(nodes=nodes, edges=[], index_rows=[], stats={})

    def fake_save(library_id, doc_id, result):
        captured["nodes"] = result.nodes
        return "meta.json"

    monkeypatch.setattr(pipeline, "build_structured_from_rawfiles", fake_build_structured)
    monkeypatch.setattr(pipeline, "_save_doc_blocks_graph", fake_save)
    monkeypatch.setattr(pipeline.paths, "get_parsed_dir", lambda lib, doc: tmp_path / "parsed")
    monkeypatch.setattr(pipeline.paths, "resolve_structure_input_dir", lambda lib, doc: tmp_path / "mineru_raw")
    monkeypatch.setattr(pipeline.paths, "resolve_structured_input_dir", lambda d: d)
    monkeypatch.setattr(pipeline._afs.file_storage, "get_doc_manifest", lambda lib, doc: {})

    def raise_no_popo(*args, **kwargs):
        raise FileNotFoundError("no popo enriched blocks")

    monkeypatch.setattr(
        pipeline._afs.file_storage, "read_popo_enriched_blocks", raise_no_popo
    )
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))

    output = pipeline.build_structured_index_for_doc(
        "lib-1", "doc-1", options={"use_llm": False}
    )
    formula = next(n for n in captured["nodes"] if n.get("block_type") == "equation_interline")
    assert formula["formula_semantics"]["formula_param_count"] >= 1
    assert output["stats"]["formula_semantics"]["enriched"] == 1


def test_meta_stats_carry_pipeline_formula_stats(monkeypatch, tmp_path) -> None:
    import docs_core.step04_structure.solo2json_pipeline as pipeline
    from docs_core.step04_structure.solo_engine import StructuredResult

    nodes = [
        {
            "block_uid": "doc-1:0:1", "block_type": "equation_interline",
            "page_idx": 0, "block_seq": 1, "math_content": "F = ma",
            "plain_text": "F = ma", "title_path": "",
        },
        {
            "block_uid": "doc-1:0:2", "block_type": "paragraph",
            "page_idx": 0, "block_seq": 2,
            "plain_text": "式中：F 为合力。", "title_path": "",
        },
    ]

    def fake_build_structured(*args, **kwargs):
        return StructuredResult(nodes=nodes, edges=[], index_rows=[], stats={})

    def raise_no_popo(*a, **k):
        raise FileNotFoundError("no popo")

    monkeypatch.setattr(pipeline, "build_structured_from_rawfiles", fake_build_structured)
    monkeypatch.setattr(pipeline.paths, "get_parsed_dir", lambda lib, doc, **kw: tmp_path / "parsed")
    monkeypatch.setattr(pipeline.paths, "resolve_structure_input_dir", lambda lib, doc: tmp_path / "mineru_raw")
    monkeypatch.setattr(pipeline.paths, "resolve_structured_input_dir", lambda d: d)
    monkeypatch.setattr(pipeline._afs.file_storage, "get_doc_manifest", lambda lib, doc: {})
    monkeypatch.setattr(pipeline._afs.file_storage, "read_popo_enriched_blocks", raise_no_popo)
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text("正文", encoding="utf-8")

    pipeline.build_structured_index_for_doc("lib-1", "doc-1", options={"use_llm": False})
    meta_path = tmp_path / "parsed" / "doc_blocks_graph_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # meta.stats 必须携带管线级 stats（含 formula_semantics），而非 solo_engine 原始 stats
    assert meta["stats"]["formula_semantics"]["enriched"] == 1
    assert meta["stats"]["nodes_count"] == 2


def test_rebuild_passthrough_keeps_existing_semantics() -> None:
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import (
        rebuild_canonical_document_from_graph,
    )

    contract = {
        "formula_text": "F = ma",
        "formula_body": "F = ma",
        "formula_number": "6.4.5-1",
        "formula_params": [
            {"symbol": "F", "description": "合力", "unit": "N",
             "confidence": 0.99, "extracted_by": "llm"}
        ],
        "formula_param_count": 1,
        "formula_summary": "公式(6.4.5-1) F = ma；包含 1 个参数：F",
        "llm_status": "ok",
        "explanation_lines": ["式中：F 为合力。"],
    }
    graph = {
        "nodes": [
            {
                "block_uid": "f1", "block_type": "formula", "page_idx": 0,
                "block_seq": 1, "plain_text": "F = ma", "section_path": "5.1",
                "formula_semantics": dict(contract),
            },
        ],
        "edges": [],
    }
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", graph, title="")
    formula = next(b for b in document.blocks if b.block_type == "formula")
    # use_llm=False 且已有契约 → 原样透传（llm_status=ok 保留，说明未被重算）
    assert formula.formula_semantics == contract


def test_extract_formula_number_supports_latex_tag() -> None:
    from docs_core.step04_structure.shared.formula_semantics import extract_formula_number
    assert extract_formula_number(r"W = 2A + b + 2c\tag{6.4.2-2}", []) == "6.4.2-2"
    assert extract_formula_number("N = μ·F", ["公式(6.2.8)"]) == "6.2.8"


def test_strip_formula_tag_from_semantics() -> None:
    from docs_core.step04_structure.shared.formula_semantics import strip_formula_tag
    assert strip_formula_tag(r"W = A + 2c\tag{6.4.2-1}") == "W = A + 2c"
    assert strip_formula_tag(r"x = 1\tag*{6.2.8}") == "x = 1"
    assert strip_formula_tag("F = ma") == "F = ma"


def test_parse_formula_param_rule_rejects_latex_residue() -> None:
    from docs_core.step04_structure.shared.formula_semantics import parse_formula_param_rule
    # 软匹配把 LaTeX 残留当成参数（垃圾结果），必须判失败以便触发 LLM
    assert parse_formula_param_rule("K _ { t }——时间富裕系数，取1.1~1.3;") is None
    assert parse_formula_param_rule("t _ { 2 }艘船舶在港内转头的时间(h)；") is None
    assert parse_formula_param_rule("\\pmb { t }——每潮次持续时间(h);") is None
    # 合法行仍要解析成功
    assert parse_formula_param_rule("A——航迹带宽度(m)；") is not None
    assert parse_formula_param_rule("F 为法向力。") is not None


def test_use_llm_always_calls_llm_when_enabled() -> None:
    class _StubLLM:
        def chat(self, messages, temperature=0.0, model=None):
            return json.dumps(
                {"formulas": [{"index": 0, "params": [
                    {"symbol": "F", "description": "合力", "unit": "N", "confidence": 0.95},
                    {"symbol": "m", "description": "质量", "unit": "kg", "confidence": 0.95},
                ]}]},
                ensure_ascii=False,
            )

    nodes = [
        {
            "block_uid": "d:1:1", "block_type": "equation_interline",
            "page_idx": 1, "block_seq": 1, "math_content": "F = ma",
            "plain_text": "F = ma", "title_path": "5.1",
        },
        {
            "block_uid": "d:1:2", "block_type": "paragraph",
            "page_idx": 1, "block_seq": 2,
            "plain_text": "式中：F 为合力。", "title_path": "5.1",
        },
    ]
    updated, _ = enrich_graph_nodes_formula_semantics(
        nodes, use_llm=True, llm_client=_StubLLM()
    )
    formula = next(n for n in updated if n.get("block_uid") == "d:1:1")
    contract = formula["formula_semantics"]
    # 规则全解析成功也必须走 LLM（不再 not_needed）
    assert contract["llm_status"] == "ok"
    # LLM 独有符号保留 extracted_by=llm（同一符号仍按规则优先合并）
    llm_param = next(p for p in contract["formula_params"] if p["symbol"] == "m")
    assert llm_param["extracted_by"] == "llm"

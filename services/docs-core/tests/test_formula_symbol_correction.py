from docs_core.step04_structure.shared.formula_semantics import (
    _build_symbol_corrections,
    _should_write_llm_correction,
    enrich_graph_nodes_formula_semantics,
)


def test_symbol_mismatch_generates_math_correction():
    # 公式 H_{nar} 与参数 H_{aa v} 不一致（6.4.5-3 场景）
    formula_text = "\\pmb { Z } = H _ { \\mathrm { n a r } } - D\\tag{6.4.5-3}"
    params = [{"symbol": "H_{\\mathrm{aa v}}", "description": "航道设计通航水位"}]
    corrections = _build_symbol_corrections(formula_text, params)
    assert any(c["field"] == "math_content_corrected" for c in corrections)
    match = next(c for c in corrections if c["field"] == "math_content_corrected")
    assert match["original"] == "H _ { \\mathrm { n a r } }"
    assert match["corrected"] == "H_{\\mathrm{aa v}}"


def test_no_correction_when_consistent():
    formula_text = "D _ { 0 } = T + Z _ { 0 }"
    params = [{"symbol": "D_0"}, {"symbol": "T"}, {"symbol": "Z_0"}]
    assert _build_symbol_corrections(formula_text, params) == []


def test_no_correction_when_multiple_tokens_share_base():
    # 同一基础符号 t 有多个下标（t_s/t_1/t_2/t_3），各自匹配则不应修正
    formula_text = (
        "t _ { \\mathrm { s } } = K _ { \\mathrm { t } } "
        "\\big ( t _ { 1 } + t _ { 2 } + t _ { 3 } \\big )\\tag{6.2.8}"
    )
    params = [
        {"symbol": "t_s"},
        {"symbol": "K_t"},
        {"symbol": "t_1"},
        {"symbol": "t_2"},
        {"symbol": "t_3"},
    ]
    assert _build_symbol_corrections(formula_text, params) == []


def test_no_correction_when_multiple_params_share_base():
    # D_0 与 D、Z_0 与 Z_4 同基础符号：无法消歧，不应修正（6.4.5-1 场景）
    formula_text = "D _ { 0 } = T + Z _ { 0 }"
    params = [
        {"symbol": "D_0"},
        {"symbol": "T"},
        {"symbol": "Z_0"},
        {"symbol": "D"},
        {"symbol": "Z_4"},
    ]
    assert _build_symbol_corrections(formula_text, params) == []


def test_greek_command_symbol_not_misparsed():
    # \\sigma _ { m x B } 是希腊命令 + 下标，不应拆成 m/x/B 三个假 token（5.2.6-3 场景）
    formula_text = (
        "\\sigma _ { m x B } = \\frac { k _ { x } q \\alpha ^ { 2 } } "
        "{ \\delta ^ { 2 } } \\leqslant \\eta _ { 3 } \\alpha "
        "\\lfloor \\sigma \\rfloor\\tag{5.2.6-3}"
    )
    params = [
        {"symbol": "\\sigma _ { m x B }"},
        {"symbol": "k _ { x }"},
        {"symbol": "\\eta _ { 3 }"},
    ]
    assert _build_symbol_corrections(formula_text, params) == []


def test_greek_command_symbol_mismatch_corrected():
    formula_text = "\\eta _ { 1 } + \\alpha"
    params = [{"symbol": "\\eta _ { 2 }"}]
    corrections = _build_symbol_corrections(formula_text, params)
    assert len(corrections) == 1
    assert corrections[0]["original"] == "\\eta _ { 1 }"
    assert corrections[0]["corrected"] == "\\eta_{ 2 }"


def test_user_correction_not_overwritten():
    node = {
        "block_type": "equation_interline",
        "math_content": "H _ { \\mathrm { n a r } }",
        "math_content_corrected": "H _ { \\mathrm { a a v } }",
        "corrected_by": "user",
    }
    assert not _should_write_llm_correction(node)


def test_enrich_writes_llm_correction_and_preserves_original():
    nodes = [
        {
            "block_uid": "d:1:1",
            "block_type": "equation_interline",
            "page_idx": 0,
            "block_seq": 0,
            "math_content": "H _ { \\mathrm { n a r } }",
            "plain_text": "H _ { \\mathrm { n a r } }",
            "explanation_uids": ["d:1:2"],
        },
        {
            "block_uid": "d:1:2",
            "block_type": "paragraph",
            "page_idx": 0,
            "block_seq": 1,
            "plain_text": "式中 H_{\\mathrm{aav}}——航道设计通航水位",
        },
    ]
    updated, stats = enrich_graph_nodes_formula_semantics(nodes, use_llm=False)
    formula = updated[0]
    assert formula["math_content"] == "H _ { \\mathrm { n a r } }"  # 原始字段不动
    assert formula["math_content_corrected"] == "H_{\\mathrm{aav}}"
    assert formula["plain_text_corrected"] == "H_{\\mathrm{aav}}"
    assert formula["corrected_by"] == "llm"
    assert formula["symbol_mismatch"] is True
    assert "corrected_at" in formula
    assert stats.get("symbol_corrections", 0) >= 1


def test_enrich_skips_when_user_corrected():
    nodes = [
        {
            "block_uid": "d:1:1",
            "block_type": "equation_interline",
            "page_idx": 0,
            "block_seq": 0,
            "math_content": "H _ { \\mathrm { n a r } }",
            "plain_text": "H _ { \\mathrm { n a r } }",
            "math_content_corrected": "H _ { \\mathrm { a a v } }",
            "corrected_by": "user",
            "explanation_uids": ["d:1:2"],
        },
        {
            "block_uid": "d:1:2",
            "block_type": "paragraph",
            "page_idx": 0,
            "block_seq": 1,
            "plain_text": "式中 H_{\\mathrm{aa v}}——航道设计通航水位",
        },
    ]
    updated, stats = enrich_graph_nodes_formula_semantics(nodes, use_llm=False)
    formula = updated[0]
    assert formula["math_content_corrected"] == "H _ { \\mathrm { a a v } }"
    assert formula["corrected_by"] == "user"
    assert stats.get("symbol_corrections", 0) == 0

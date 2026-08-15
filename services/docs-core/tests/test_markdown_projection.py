"""jsonl -> content.md 保真投影单测。"""
from docs_core.step04_structure.shared.markdown_projection import build_faithful_markdown


def _node(**kw):
    base = {
        "block_uid": "d:0:1",
        "block_type": "paragraph",
        "page_idx": 0,
        "block_seq": 1,
        "plain_text": "正文",
    }
    base.update(kw)
    return base


def test_build_id_header_first_line():
    md, _ = build_faithful_markdown([], "abc123def456")
    assert md.splitlines()[0] == "<!-- build_id: abc123def456 -->"


def test_title_heading_and_line_range():
    md, ranges = build_faithful_markdown([
        _node(block_uid="d:0:1", block_type="title", derived_level=2, plain_text="标题"),
    ], "abc123def456")
    assert md.splitlines()[1] == "## 标题"
    assert ranges["d:0:1"] == {"start": 2, "end": 2}


def test_paragraph_blank_separator_and_ranges():
    md, ranges = build_faithful_markdown([
        _node(block_uid="d:0:1", plain_text="第一段"),
        _node(block_uid="d:0:2", page_idx=0, block_seq=2, plain_text="第二段"),
    ], "abc123def456")
    lines = md.splitlines()
    assert lines[1] == "第一段"
    assert lines[2] == ""
    assert lines[3] == "第二段"
    assert ranges["d:0:2"] == {"start": 4, "end": 4}


def test_table_pipe_rendering_with_caption_and_footnote():
    md, _ = build_faithful_markdown([
        _node(
            block_uid="d:0:3", block_type="table", page_idx=0, block_seq=3,
            caption="表 1 示例", footnote="注：单位 m。",
            table_html=(
                "<table><tr><th>项目</th><th>数值</th></tr>"
                "<tr><td>长度</td><td>10</td></tr></table>"
            ),
        ),
    ], "abc123def456")
    assert "表 1 示例" in md
    assert "| 项目 | 数值 |" in md
    assert "| --- | --- |" in md
    assert "| 长度 | 10 |" in md
    assert "注：单位 m。" in md


def test_formula_and_image_rendering():
    md, _ = build_faithful_markdown([
        _node(
            block_uid="d:0:4", block_type="equation_interline", page_idx=0, block_seq=4,
            formula_body="F = ma", formula_number="3.1",
        ),
        _node(
            block_uid="d:0:5", block_type="image", page_idx=0, block_seq=5,
            image_path="images/a.jpg", plain_text="图 1",
        ),
    ], "abc123def456")
    assert "$$" in md
    assert "F = ma" in md
    assert r"\tag{3.1}" in md
    assert "![图 1](images/a.jpg)" in md


def test_furniture_and_inactive_skipped():
    md, ranges = build_faithful_markdown([
        _node(block_uid="d:0:1", block_type="page_header", plain_text="页眉"),
        _node(block_uid="d:0:2", page_idx=0, block_seq=2, plain_text="停用", is_active=0),
        _node(block_uid="d:0:3", page_idx=0, block_seq=3, plain_text="保留"),
    ], "abc123def456")
    assert "页眉" not in md
    assert "停用" not in md
    assert "保留" in md
    assert ranges == {"d:0:3": {"start": 2, "end": 2}}


def test_save_graph_writes_projected_markdown(monkeypatch, tmp_path):
    from docs_core.step04_structure import solo2json_pipeline
    from docs_core.step04_structure.solo_engine import StructuredResult

    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text("原文", encoding="utf-8")
    result = StructuredResult(
        nodes=[{
            "id": 1, "block_uid": "d:0:1", "block_type": "title",
            "derived_level": 1, "page_idx": 0, "block_seq": 1, "plain_text": "第一章",
        }],
        edges=[], index_rows=[], stats={"derived_rows": []},
    )
    solo2json_pipeline._save_doc_blocks_graph("lib", "doc", result)
    md = (parsed / "content.md").read_text(encoding="utf-8")
    assert md.splitlines()[1] == "# 第一章"
    assert result.nodes[0]["markdown_line_start"] == 2
    assert result.nodes[0]["markdown_line_end"] == 2
    edited = tmp_path / "libraries" / "lib" / "documents" / "doc" / "edited" / "current.md"
    assert not edited.exists()

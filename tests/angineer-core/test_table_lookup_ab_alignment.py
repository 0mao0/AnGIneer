"""新老查表 A/B 对齐：同一批表格，老 TableLookupTool（结构化模式，HTML 文件输入）
与新 canonical_table_lookup（canonical 行输入）必须给出相同结果。

老工具的表格解析走 BS4（_parse_table_headers/_parse_table_rows），新工具消费
canonical pipeline 解析好的 header_rows/body_rows——两边解析器的差异正是
对齐风险点，本文件用同一 HTML 双边驱动，把差异钉在测试里。
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core import ports  # noqa: E402
from angineer_core.canonical_table_lookup import canonical_table_lookup  # noqa: E402
from engtools.TableTool import TableLookupTool  # noqa: E402


def html_table(headers, rows):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


CASES = [
    {
        "name": "尺度表-文本+数值条件",
        "caption": "表A.0.1-1 杂货船设计船型尺度",
        "headers": ["船型", "吨级(t)", "总长L(m)", "型宽B(m)", "型深D(m)", "满载吃水T(m)"],
        "rows": [
            ["杂货船", "10000", "135", "20.5", "11.0", "8.5"],
            ["杂货船", "40000", "192", "32.2", "17.5", "12.3"],
            ["集装箱船", "40000", "246", "32.2", "19.0", "12.5"],
        ],
        "table_name": "表A.0.1-1",
        "query_conditions": {"船型": "杂货船", "吨级": "40000"},
        "target_column": "型宽B(m)",
    },
    {
        "name": "系数表-纯文本条件-成对列",
        "caption": "表A.0.2-2 波浪系数",
        "headers": ["船型", "系数K1"],
        "rows": [["杂货船", "0.3"], ["油船", "0.5"]],
        "table_name": "表A.0.2-2",
        "query_conditions": {"船型": "油船"},
        "target_column": "系数K1",
    },
    {
        "name": "范围表名",
        "caption": "表A.0.2-2 波浪系数",
        "headers": ["船型", "系数K1"],
        "rows": [["杂货船", "0.3"], ["油船", "0.5"]],
        "table_name": "表A.0.2-1~表A.0.2-3",
        "query_conditions": {"船型": "杂货船"},
        "target_column": "系数K1",
    },
    {
        "name": "区间单元格-数值落区间",
        "caption": "表B.1-1 富裕深度",
        "headers": ["吨级(t)", "富裕深度Z1(m)"],
        "rows": [["10000-50000", "0.4"], ["50000-100000", "0.5"]],
        "table_name": "表B.1-1",
        "query_conditions": {"吨级": "40000"},
        "target_column": "富裕深度Z1(m)",
    },
    {
        "name": "未命中-行过滤为空",
        "caption": "表A.0.1-1 杂货船设计船型尺度",
        "headers": ["船型", "吨级(t)"],
        "rows": [["杂货船", "10000"]],
        "table_name": "表A.0.1-1",
        "query_conditions": {"船型": "航天飞机"},
        "target_column": None,
    },
    {
        "name": "无目标列-返回整行",
        "caption": "表A.0.2-2 波浪系数",
        "headers": ["船型", "系数K1"],
        "rows": [["杂货船", "0.3"]],
        "table_name": "表A.0.2-2",
        "query_conditions": {"船型": "杂货船"},
        "target_column": None,
    },
]


def run_old_tool(case, tmpdir):
    """老工具结构化模式：HTML 写进 md 文件，_resolve_file 打桩直达。"""
    content = f"<p>{case['caption']}</p>\n{html_table(case['headers'], case['rows'])}\n"
    path = os.path.join(tmpdir, "对齐测试规范.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    tool = TableLookupTool(knowledge_dir=tmpdir)
    with patch.object(TableLookupTool, "_resolve_file", return_value=path):
        return tool.run(
            table_name=case["table_name"],
            query_conditions=case["query_conditions"],
            file_name="对齐测试规范.md",
            target_column=case["target_column"],
            use_llm=False,
        )


def run_new_engine(case):
    """新引擎：同一 HTML 按 canonical 语义（首行表头）切header_rows/body_rows。"""
    blocks = [{
        "doc_id": "doc-ab",
        "header_rows": [case["headers"]],
        "rows": case["rows"],
        "context": case["caption"],
        "page_idx": 0,
    }]
    ports.register_agent_search(table_blocks=lambda library_id="default", doc_ids=None: blocks)
    try:
        return canonical_table_lookup(
            table_name=case["table_name"],
            query_conditions=case["query_conditions"],
            target_column=case["target_column"],
        )
    finally:
        ports.register_agent_search(table_blocks=None)


class TableLookupABAlignmentTests(unittest.TestCase):
    def test_old_new_parity(self):
        mismatches = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for case in CASES:
                old = run_old_tool(case, tmpdir)
                new = run_new_engine(case)
                old_val = old.get("result") if isinstance(old, dict) else old
                new_val = new.get("result") if isinstance(new, dict) else new
                old_err = old.get("error") if isinstance(old, dict) else None
                new_err = new.get("error") if isinstance(new, dict) else None
                if bool(old_err) != bool(new_err) or (not old_err and old_val != new_val):
                    mismatches.append(
                        f"[{case['name']}] old={'ERR:' + old_err if old_err else old_val!r}"
                        f" new={'ERR:' + new_err if new_err else new_val!r}"
                    )
        self.assertEqual(mismatches, [], "新老查表结果不一致：\n" + "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main()

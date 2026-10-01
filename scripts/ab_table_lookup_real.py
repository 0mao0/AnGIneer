"""table_lookup 新老实现真实数据 A/B：存量 SOP 的 table_lookup 步骤双侧对比。

用法：python scripts/ab_table_lookup_real.py
- 从 data/sops/**/*.json 抽取 table_lookup 步骤，模板变量代入典型值
- 老：engtools TableLookupTool 结构化模式（file_name → 解析产物 .md）
- 新：canonical_table_lookup（file_name 标题解析 → doc_ids scope → canonical 表格块）
- 判定：result 相等，或双侧同为 error（错误文案不必相同）
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services/angineer-core/src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services/engtools/src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services/ai-inference/src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services/docs-core/src"))

from angineer_core import ports  # noqa: E402
from angineer_core.canonical_table_lookup import canonical_table_lookup  # noqa: E402
from docs_core.step09_query import agent_port  # noqa: E402
from docs_core.docs_service import docs_service  # noqa: E402
from engtools.KnowledgeTool import _normalize_doc_title, _title_matches  # noqa: E402
from engtools.TableTool import TableLookupTool  # noqa: E402

# 模板变量 → 典型代入值（按 SOP 里出现过的变量名）
VAR_VALUES = {
    "船型": "杂货船",
    "吨级": "40000",
    "dwt": "40000",
    "掩护情况": "掩护良好",
    "nav_speed_kn": "8",
    "航速": "8",
    "bottom_material": "淤泥",
    "土质": "淤泥",
    "状态": "良好",
}


def substitute(value):
    if isinstance(value, str):
        def repl(m):
            return VAR_VALUES.get(m.group(1), m.group(0))
        return re.sub(r"\$\{([^}]+)\}", repl, value)
    if isinstance(value, dict):
        return {k: substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v) for v in value]
    return value


def resolve_doc_id(file_name: str):
    normalized = _normalize_doc_title(file_name)
    for node in docs_service.list_nodes("default"):
        if getattr(node, "type", "") != "document":
            continue
        if _title_matches(normalized, _normalize_doc_title(node.title)):
            return node.id, node.title
    return None, None


def extract_sop_table_steps():
    steps = []
    for path in glob.glob("data/sops/**/*.json", recursive=True):
        try:
            sop = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(sop, dict):
            continue
        for step in sop.get("steps") or []:
            if isinstance(step, dict) and step.get("tool") == "table_lookup":
                steps.append({
                    "sop": sop.get("name_zh") or sop.get("id"),
                    "step": step.get("id"),
                    "inputs": step.get("inputs") or {},
                })
    return steps


def main():
    ports.register_agent_search(table_blocks=agent_port.table_blocks_provider)
    old_tool = TableLookupTool()
    rows = []
    for item in extract_sop_table_steps():
        inputs = substitute(item["inputs"])
        table_name = inputs.get("table_name")
        conditions = inputs.get("query_conditions")
        file_name = inputs.get("file_name")
        target_column = inputs.get("target_column")
        if isinstance(conditions, list):  # history_records 这类非规范步骤跳过
            rows.append((item["sop"], item["step"], "SKIP", "conditions 为列表（非规范查表）", "", ""))
            continue
        doc_id, doc_title = resolve_doc_id(file_name or "")
        old = old_tool.run(
            table_name=table_name,
            query_conditions=conditions,
            file_name=file_name,
            target_column=target_column,
            use_llm=False,
        )
        if doc_id is None:
            new = {"error": f"file_name 无法解析到文档: {file_name}"}
        else:
            new = canonical_table_lookup(
                table_name=table_name,
                query_conditions=conditions,
                target_column=target_column,
                library_id="default",
                doc_ids=[doc_id],
            )
        old_err = old.get("error") if isinstance(old, dict) else "非dict结果"
        new_err = new.get("error") if isinstance(new, dict) else "非dict结果"
        old_val = old.get("result") if isinstance(old, dict) else old
        new_val = new.get("result") if isinstance(new, dict) else new
        if old_err and new_err:
            verdict = "BOTH_ERR"
        elif old_err or new_err:
            verdict = "MISMATCH(一侧报错)"
        elif old_val == new_val:
            verdict = "MATCH"
        else:
            verdict = "MISMATCH(值不同)"
        rows.append((item["sop"], item["step"], verdict, str(table_name)[:40], json.dumps(old_val, ensure_ascii=False, default=str)[:60], json.dumps(new_val, ensure_ascii=False, default=str)[:60]))

    width = max(len(str(r[0])) for r in rows) if rows else 10
    for sop, step, verdict, tname, ov, nv in rows:
        print(f"{verdict:18} | {str(sop)[:width]} | {step} | {tname} | old={ov} | new={nv}")
    stats = {}
    for r in rows:
        stats[r[2]] = stats.get(r[2], 0) + 1
    print("\n汇总:", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()

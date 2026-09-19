"""续接文本重归属 A/B：同一份代码，只把跨页分支关掉（_prev_page_flow_tail → None）。

用法:
  python scripts/analyze_reattach_ab.py <library_dir>
  python scripts/analyze_reattach_ab.py <library_dir> --state <predictions/state.json>

`--state` 是权威的 page_id → doc_id 映射（评测轮次产物）；不要按 docMeta.fileName 反推——
同一页在 omnidocbench 库里有多份 doc 目录（源页相同、doc_id 不同）。

对每篇文档跑两次结构引擎（use_llm=False），比较：
  - continuation_text_reattaches 计数
  - 产出的 (block_uid, plain_text) 指纹是否变了
  - 变化文档里"被搬动的文本"抽样
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "docs-core" / "src"))
sys.path.insert(0, str(ROOT / "services" / "ai-inference" / "src"))

from docs_core.step04_structure import solo_engine as se  # noqa: E402


def fingerprint(result) -> str:
    payload = "\n".join(f"{n.get('block_uid')}\t{n.get('plain_text')}" for n in result.nodes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_docs(parsed_dirs, disabled: bool):
    orig_tail = se._prev_page_flow_tail
    if disabled:
        se._prev_page_flow_tail = lambda rows: None
    out = {}
    try:
        for parsed in parsed_dirs:
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    result = se.build_structured_from_rawfiles(
                        parsed, parsed.parent.name, options={"use_llm": False}
                    )
            except Exception as exc:  # noqa: BLE001
                out[parsed.parent.name] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            out[parsed.parent.name] = {
                "reattaches": result.stats.get("continuation_text_reattaches"),
                "merges": result.stats.get("continuation_merges"),
                "fp": fingerprint(result),
                "texts": {n.get("block_uid"): (n.get("plain_text") or "") for n in result.nodes},
            }
    finally:
        se._prev_page_flow_tail = orig_tail
    return out


def main() -> None:
    lib = Path(sys.argv[1])
    base = lib / "documents" if (lib / "documents").is_dir() else lib
    parsed_dirs = sorted(p.parents[1] for p in base.glob("*/parsed/mineru_raw/middle.json"))
    if "--state" in sys.argv:
        # 权威映射：评测轮次的 predictions/state.json（page_id → doc_id）。
        # 不能按 docMeta.fileName 反推——同一页在库里有多份 doc 目录（源页相同、doc_id 不同）。
        state = json.loads(Path(sys.argv[sys.argv.index("--state") + 1]).read_text(encoding="utf-8"))
        parsed_dirs = [base / item["doc_id"] / "parsed" for item in state.values()
                       if (base / item["doc_id"] / "parsed").is_dir()]
    print(f"library={lib.name} docs={len(parsed_dirs)}")

    off = run_docs(parsed_dirs, disabled=True)
    on = run_docs(parsed_dirs, disabled=False)

    sum_on = Counter()
    sum_off = Counter()
    changed = []
    for doc, onv in on.items():
        offv = off.get(doc, {})
        sum_on["errors"] += "error" in onv
        sum_off["errors"] += "error" in offv
        if "error" in onv or "error" in offv:
            continue
        sum_on["docs"] += 1
        sum_off["docs"] += 1
        sum_on["reattaches"] += onv["reattaches"] or 0
        sum_off["reattaches"] += offv["reattaches"] or 0
        if onv["fp"] != offv["fp"]:
            changed.append(doc)
            sum_on["changed_docs"] += 1
            if len(changed) <= 3:
                for uid, txt in onv["texts"].items():
                    if offv["texts"].get(uid) != txt:
                        print(f"  [{doc}] {uid}")
                        print(f"      before: {offv['texts'].get(uid)!r}")
                        print(f"      after : {txt!r}")

    print("\n=== A/B (rule off → on) ===")
    print(f"  docs                : {sum_on['docs']}")
    print(f"  reattaches  off/on  : {sum_off['reattaches']} → {sum_on['reattaches']}")
    print(f"  docs with text diff : {sum_on['changed_docs']}")
    print(f"  errors              : {sum_on['errors']}")


if __name__ == "__main__":
    main()

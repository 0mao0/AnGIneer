# -*- coding: utf-8 -*-
"""把公开 gold（content_gold）合入拒答类题集——内容判分常设化的题集前置（2026-10-10）。

用法：
  python scripts/open_ragbench/add_refusal_content_gold.py --check   # 只核对不写盘
  python scripts/open_ragbench/add_refusal_content_gold.py           # 写回 bundle
题集：refusal-v3-39（33 题）+ smoke-v1（3 道拒答题）；gold 源：raw/answers.json（uuid→公开答案）。
按各文件现有缩进风格回写（refusal=1 空格、smoke=2 空格），保证 diff 只含 content_gold 行。
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANSWERS = ROOT / "data/evals/originals/open_ragbench/raw/answers.json"
BUNDLES = [
    (ROOT / "data/evals/datasets/open-ragbench-refusal-v3-39.json", 1),
    (ROOT / "data/evals/datasets/open-ragbench-smoke-v1.json", 2),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="把公开 gold 合入拒答类题集的 content_gold 字段")
    parser.add_argument("--check", action="store_true", help="只核对，不写盘")
    args = parser.parse_args()
    if not ANSWERS.exists():
        print(f"公开 gold 文件不存在: {ANSWERS}")
        return 2
    answers = json.loads(ANSWERS.read_text(encoding="utf-8"))
    total = missing = changed_all = 0
    for path, indent in BUNDLES:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        refusal_n = changed = 0
        for item in bundle.get("items") or []:
            qid = str(item.get("question_id") or "")
            if not qid.startswith("refusal-"):
                continue
            refusal_n += 1
            total += 1
            gold = answers.get(qid[len("refusal-"):])
            if not gold:
                missing += 1
                print(f"  [缺 gold] {path.name}: {qid}")
                continue
            text = gold if isinstance(gold, str) else json.dumps(gold, ensure_ascii=False)
            answer = item.setdefault("answer", {})
            if answer.get("content_gold") != text:
                answer["content_gold"] = text
                changed += 1
        if not args.check and changed:
            path.write_text(json.dumps(bundle, ensure_ascii=False, indent=indent), encoding="utf-8")
        changed_all += changed
        print(f"{path.name}: 拒答题 {refusal_n}，本次更新 {changed}")
    suffix = "（--check 未写盘）" if args.check else ""
    print(f"合计 {total} 题，缺 gold {missing} 题，更新 {changed_all}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

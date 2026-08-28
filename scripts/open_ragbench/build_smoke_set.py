"""冒烟题集构建：从正例子集 + 拒答集抽样小体量门禁题集（默认 20 正例 + 5 拒答）。"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from open_ragbench import common


def build_smoke_bundle(positive_count: int = 20, refusal_count: int = 5, seed: int = 42):
    subset = common.load_json(common.EVAL_DATASET_FILE)
    refusal = common.load_json(common.REFUSAL_DATASET_FILE)

    # 正例按题型（tags[0]）分层抽样
    by_source = {}
    for item in subset.get("items", []):
        source = (item.get("tags") or [""])[0] or "unknown"
        by_source.setdefault(source, []).append(item)
    rnd = random.Random(seed)
    selected = []
    sources = sorted(by_source.keys())
    total = sum(len(v) for v in by_source.values())
    for source in sources:
        items = list(by_source[source])
        rnd.shuffle(items)
        quota = max(1, round(positive_count * len(items) / total)) if total else 0
        selected.extend(items[:quota])
    rnd.shuffle(selected)
    selected = selected[:positive_count]

    refusal_items = list(refusal.get("items", []))
    rnd.shuffle(refusal_items)
    selected.extend(refusal_items[:refusal_count])

    return {
        "dataset": {
            "dataset_id": common.SMOKE_DATASET_ID,
            "title": "Open RAG Benchmark 冒烟门禁集 v1",
            "category": "knowledge",
            "description": "小体量回归门禁：正例 + 拒答混合，防 prompt/权重改动回退",
            "schema_version": "eval.bundle.v2",
            "version": "1.0",
            "library_id": subset.get("dataset", {}).get("library_id", "default"),
        },
        "items": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建冒烟门禁题集")
    parser.add_argument("--positive", type=int, default=20)
    parser.add_argument("--refusal", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    bundle = build_smoke_bundle(args.positive, args.refusal, args.seed)
    common.save_json(common.SMOKE_DATASET_FILE, bundle)
    print("冒烟题集已生成:", common.SMOKE_DATASET_FILE, "题目数:", len(bundle["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

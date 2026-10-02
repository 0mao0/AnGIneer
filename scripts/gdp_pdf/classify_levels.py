"""用生产同款意图分类器给 GDP.pdf 100 题逐题定 L0-L4 层级（回填题集卡层级分布）。

真相源：angineer_core.classifier.IntentClassifier（与 evals intent 评测器、生产 policy_query 同一分类器）。
断点续跑：已写入 data/gdp_pdf/raw/levels.json 的 task_id 跳过。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from dotenv import load_dotenv

load_dotenv(REPO / ".env")

PARQUET = REPO / "data" / "gdp_pdf" / "raw" / "parquet_a.parquet"
OUT = REPO / "data" / "gdp_pdf" / "raw" / "levels.json"


def main() -> int:
    import pandas as pd
    from evals_core.runner._query_helper import _ensure_sop_loader
    from angineer_core.classifier import IntentClassifier

    loader = _ensure_sop_loader()
    sops = loader.load_all() if loader else {}
    clf = IntentClassifier(sops)

    data = {}
    if OUT.exists():
        data = json.loads(OUT.read_text(encoding="utf-8"))

    df = pd.read_parquet(PARQUET)
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows(), 1):
        tid = str(row["task_id"])
        if tid in data and data[tid].get("level"):
            continue
        try:
            r = clf.classify_intent(str(row["prompt"]), mode="instruct")
            level = getattr(r, "intent_level", None)
            mode = getattr(r, "service_mode", None)
            itype = getattr(r, "intent_type", None)
            data[tid] = {"level": str(level) if level else "", "mode": str(mode or ""), "type": str(itype or "")}
        except Exception as exc:  # noqa: BLE001
            data[tid] = {"level": "", "mode": "", "type": "", "error": str(exc)[:150]}
            print(f"[{i}/{total}] {tid[:8]} ERROR {str(exc)[:80]}", flush=True)
            continue
        if i % 10 == 0 or i == total:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{i}/{total}] {data[tid]['level']:3} {data[tid]['type'][:12]:12} {str(row['prompt'])[:48]}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    from collections import Counter
    print("层级分布:", dict(Counter(v.get("level") or "未知" for v in data.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

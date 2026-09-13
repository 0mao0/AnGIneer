"""素材体检（B 层）手动入口：jsonl → canonical/chunk → 向量 的传递性断言。

固化位置：nightly 每晚自动跑（`evals_core/nightly/pipeline.py` 的素材体检步骤，
配置见 `data/evals/nightly_settings.json` 的 parse_health_* 键）；本脚本用于**手动**复查。

用法：
  python scripts/run_material_health.py                                  # 全部库，最近 200 篇
  python scripts/run_material_health.py --libraries lib-b07ed174 --max-docs 50
  python scripts/run_material_health.py --json D:/tmp/health.json        # 另存明细
退出码：0=ok，1=warn/fail（便于接 CI），2=体检本身失败。
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

from evals_core import material_parity  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="素材体检（B 层：jsonl→canonical/chunk→向量）")
    ap.add_argument("--libraries", default="", help="逗号分隔的库 id；留空=全部库")
    ap.add_argument("--max-docs", type=int, default=200, help="按产物修改时间倒序取前 N 篇")
    ap.add_argument("--min-chars", type=int, default=material_parity.DEFAULT_MIN_CHARS)
    ap.add_argument("--json", default="", help="把完整结果另存为 JSON（含每篇缺失清单）")
    args = ap.parse_args()

    libraries = [x.strip() for x in args.libraries.split(",") if x.strip()] or None
    result = material_parity.run_check(libraries=libraries, max_docs=args.max_docs, min_chars=args.min_chars)
    print(material_parity.render_summary(result))
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n明细: {args.json}")
    severity = result.get("severity")
    return 2 if severity == "error" else (0 if severity == "ok" else 1)


if __name__ == "__main__":
    sys.exit(main())

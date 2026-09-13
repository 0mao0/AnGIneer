"""批量提取 MinerU 自己输出的 markdown（用于"MinerU 单独"的对照评测）。

MinerU 的原始 md 就在 `mineru_raw/origin.zip` 的 `<name>/hybrid_auto/<name>.md`；
step03 解压时拷进 `parsed/content.md`，随后被 step04 的 Solo 投影覆盖——所以要看
"MinerU 单独"的表现，必须回到 zip 里取。

用法：
  python scripts/collect_mineru_markdown.py --state data/evals/omnidocbench/predictions_eval200/state.json \
      --out D:/AI/omnidocbench_dl/mineru_only_preds
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_STATE = REPO / "data" / "evals" / "omnidocbench" / "predictions_eval200" / "state.json"
DEFAULT_LIB = REPO / "data" / "knowledge_base" / "libraries" / "omnidocbench" / "documents"


def main() -> int:
    ap = argparse.ArgumentParser(description="提取 MinerU 自带 markdown")
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--library-dir", default=str(DEFAULT_LIB))
    ap.add_argument("--out", required=True, help="输出预测目录（按页命名 <page_id>.md）")
    args = ap.parse_args()

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    lib = Path(args.library_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    done = missing = 0
    versions = {}
    for page_id, meta in state.items():
        doc_id = meta.get("doc_id")
        if not doc_id:
            continue
        raw = lib / doc_id / "parsed" / "mineru_raw"
        zip_path = raw / "origin.zip"
        if not zip_path.exists():
            missing += 1
            continue
        # 版本留痕：middle.json 的 _version_name / _backend
        try:
            middle = json.loads((raw / "middle.json").read_text(encoding="utf-8"))
            key = f"{middle.get('_version_name')}/{middle.get('_backend')}"
            versions[key] = versions.get(key, 0) + 1
        except Exception:  # noqa: BLE001
            pass
        with zipfile.ZipFile(zip_path) as zf:
            md_names = [n for n in zf.namelist() if n.lower().endswith(".md")]
            if not md_names:
                missing += 1
                continue
            markdown = zf.read(md_names[0]).decode("utf-8", errors="replace")
        (out / f"{page_id}.md").write_text(markdown, encoding="utf-8")
        done += 1

    print(f"提取 MinerU markdown: {done} 页（缺失 {missing}）→ {out}")
    print(f"MinerU 版本分布: {versions}")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())

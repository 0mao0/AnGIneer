# -*- coding: utf-8 -*-
"""SOP 链路冒烟 CLI（evals_core.chain_smoke 的薄壳）。

用法（本机开发）：
    python scripts/smoke_sop_chain.py --sop-api-url http://127.0.0.1:8792 \
        --docs-api-url http://127.0.0.1:8790 [--library-id ...] [--doc-id ...] [--query ...]

容器内（服务器）：
    cd docker && docker compose exec aichat-api python /app/scripts/smoke_sop_chain.py

地址缺省与真实客户端同源：SOP_API_URL / ANGINEER_DOCS_API_URL（未配走 compose 服务名）。
退出码：0=ok/warn；1=fail（有硬失败跳）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "evals-core" / "src"))

from evals_core import chain_smoke  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="SOP 链路冒烟（aichat→sop-api→docs-api）")
    ap.add_argument("--sop-api-url", default=None, help="默认读 SOP_API_URL，未配走 http://sop-api:8792")
    ap.add_argument("--docs-api-url", default=None,
                    help="默认读 ANGINEER_DOCS_API_URL，未配走 http://docs-api:8790")
    ap.add_argument("--library-id", default=None, help="配了才打 bundle 一跳（或读 SMOKE_LIBRARY_ID）")
    ap.add_argument("--doc-id", default=None, help="同 --library-id（或读 SMOKE_DOC_ID）")
    ap.add_argument("--query", default=None, help="实体搜索词（或读 SMOKE_QUERY，缺省「设计」）")
    args = ap.parse_args()
    result = chain_smoke.run_smoke(
        sop_api_url=args.sop_api_url, docs_api_url=args.docs_api_url,
        library_id=args.library_id, doc_id=args.doc_id, query=args.query)
    for h in result["hops"]:
        print(f"[{h['status']:<4}] {h['name']}  {h.get('detail') or ''}")
    print(chain_smoke.render_line(result))
    return 1 if result.get("severity") == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

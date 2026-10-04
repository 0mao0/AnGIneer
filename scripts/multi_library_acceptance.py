# -*- coding: utf-8 -*-
"""多库勾选问答线上验收探针（阶段三计划 F4）：检索段 p90 对比（单库 ×1.5 阈值，spec §6）。

用法（部署机宿主机跑，docs-api 只绑 127.0.0.1:8790）：
  python3 scripts/multi_library_acceptance.py --single libA --multi libA,libB
  python3 scripts/multi_library_acceptance.py --single libA --multi libA,libB,libC,libD,libE --runs 20
  python3 scripts/multi_library_acceptance.py --single libA --multi libA,libB --url http://127.0.0.1:8790

验收口径（spec §5.2/§6 定稿，2026-10-04）：
  - 「检索段耗时」求和口径（单/多库 stage_times 键不同，先定义再对比）：
      单库 = dense + sparse + clause + fuse
      多库 = retrieve_fanout + fuse
  - 阈值：多库 p90 ≤ 单库 p90 × 1.5
  - 样本：每组 ≥20 次（≥10 次的 p90≈极值，不可靠）
  - 仅在白天低峰跑，避开 nightly 窗口与晚间网关波动（波动 2 倍不作数）

结果落 data/ops/multi_library_acceptance-<UTC8 时间戳>.json（--out 可覆盖）。
退出码：超阈值或请求失败 → 1；通过 → 0。

端点：POST /api/knowledge/internal/retrieve（docs-core retrieve_knowledge 薄封装，
无鉴权、仅回环；stage_times 键即求和口径的真相源——单/多库键集合不同属预期）。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 求和口径：单库/多库各自参与求和的 stage_times 键（缺键记 0 并在报告中告警）
SINGLE_KEYS = ("dense", "sparse", "clause", "fuse")
MULTI_KEYS = ("retrieve_fanout", "fuse")
THRESHOLD_RATIO = 1.5
MIN_RUNS = 20

_CST = timezone(timedelta(hours=8))  # 面向用户的时间一律北京时间


def _now_cst() -> datetime:
    return datetime.now(_CST)


def _retrieve_once(base_url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _sum_stage(result: dict, keys: tuple) -> tuple[float, list]:
    """stage_times 求和；返回 (求和值, 缺失键清单)。"""
    stage_times = result.get("stage_times") or {}
    missing = [k for k in keys if k not in stage_times]
    return (sum(float(stage_times.get(k) or 0.0) for k in keys), missing)


def _percentile(values: list, q: float) -> float:
    """线性插值分位（q=0.9 → p90）。空清单返回 0.0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _probe_group(base_url: str, payload: dict, runs: int, keys: tuple, timeout: float, label: str) -> dict:
    samples: list = []
    errors: list = []
    for i in range(runs):
        t0 = time.perf_counter()
        try:
            result = _retrieve_once(base_url, payload, timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            errors.append({"run": i + 1, "error": str(exc)})
            continue
        wall = time.perf_counter() - t0
        if "error" in result:
            errors.append({"run": i + 1, "error": str(result["error"]),
                           "detail": result.get("detail")})
            continue
        total, missing = _sum_stage(result, keys)
        samples.append({
            "run": i + 1,
            "stage_sum_s": round(total, 4),
            "wall_s": round(wall, 4),
            "items": int(result.get("total") or 0),
            "missing_keys": missing,
            "stage_times": result.get("stage_times") or {},
        })
        if result.get("partial_errors"):
            samples[-1]["partial_errors"] = result["partial_errors"]
        if (i + 1) % 5 == 0:
            print(f"  [{label}] {i + 1}/{runs} 完成", flush=True)
    sums = [s["stage_sum_s"] for s in samples]
    return {
        "label": label,
        "payload": payload,
        "runs_requested": runs,
        "runs_ok": len(samples),
        "samples": samples,
        "errors": errors,
        "stage_sum_s": {
            "p50": round(_percentile(sums, 0.5), 4),
            "p90": round(_percentile(sums, 0.9), 4),
            "max": round(max(sums), 4) if sums else None,
        },
        "sum_keys": list(keys),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--single", required=True, help="单库基线库名（如 libA）")
    parser.add_argument("--multi", required=True,
                        help="多库集合（逗号分隔，2 或 5 库；须含对照的勾选组合）")
    parser.add_argument("--query", default="混凝土抗压强度试验方法有哪些")
    parser.add_argument("--runs", type=int, default=MIN_RUNS)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--url", default="http://127.0.0.1:8790/api/knowledge/internal/retrieve")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", default="", help="结果 JSON 路径（默认 data/ops/multi_library_acceptance-<ts>.json）")
    args = parser.parse_args()

    multi_libs = [x.strip() for x in args.multi.split(",") if x.strip()]
    if len(multi_libs) < 2:
        print("--multi 至少 2 个库（多库路径 len>1 才触发扇出）")
        return 2
    if args.runs < MIN_RUNS:
        print(f"--runs 最少 {MIN_RUNS}（≥10 次的 p90≈极值，不可靠，spec §6）")
        return 2

    print(f"探针开始 {_now_cst().strftime('%Y-%m-%d %H:%M:%S')}（北京时间）")
    print(f"单库={args.single} 多库={'+'.join(multi_libs)} runs={args.runs} query={args.query!r}")

    started = _now_cst()
    single = _probe_group(
        args.url,
        {"query": args.query, "library_id": args.single, "top_k": args.top_k},
        args.runs, SINGLE_KEYS, args.timeout, f"single:{args.single}",
    )
    multi = _probe_group(
        args.url,
        {"query": args.query, "library_id": multi_libs[0],
         "library_ids": list(multi_libs), "top_k": args.top_k},
        args.runs, MULTI_KEYS, args.timeout, "multi:" + "+".join(multi_libs),
    )

    sp90 = single["stage_sum_s"]["p90"]
    mp90 = multi["stage_sum_s"]["p90"]
    ratio = (mp90 / sp90) if sp90 > 0 else None
    passed = ratio is not None and ratio <= THRESHOLD_RATIO
    ok_runs = single["runs_ok"] >= MIN_RUNS and multi["runs_ok"] >= MIN_RUNS
    passed = passed and ok_runs

    report = {
        "probe": "multi_library_acceptance",
        "spec": "docs/superpowers/specs/2026-10-04-kb-multi-library-qa-design.md §6 验收 3",
        "started_at_cst": started.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "finished_at_cst": _now_cst().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "query": args.query,
        "top_k": args.top_k,
        "threshold_ratio": THRESHOLD_RATIO,
        "single": single,
        "multi": multi,
        "verdict": {
            "single_p90_s": sp90,
            "multi_p90_s": mp90,
            "ratio": round(ratio, 4) if ratio is not None else None,
            "passed": passed,
            "notes": [
                "口径：单库=dense+sparse+clause+fuse；多库=retrieve_fanout+fuse（spec §6 定稿）",
                "前提：两组有效样本均 ≥20；missing_keys 非空说明 stage_times 键漂移，先修口径再信数值",
                "白天低峰窗口之外的结果不作数（晚间网关波动 2 倍）",
            ],
        },
    }

    out_path = Path(args.out) if args.out else (
        Path("data/ops") / f"multi_library_acceptance-{_now_cst().strftime('%Y%m%d-%H%M%S')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"单库 p90={sp90:.3f}s  多库 p90={mp90:.3f}s  "
          f"倍率={('%.2fx' % ratio) if ratio is not None else 'N/A(单库 p90=0)'}  "
          f"阈值≤{THRESHOLD_RATIO}x  判定={'PASS' if passed else 'FAIL'}")
    print(f"样本：单库 {single['runs_ok']}/{args.runs}  多库 {multi['runs_ok']}/{args.runs}  "
          f"错误：{len(single['errors'])}+{len(multi['errors'])}")
    print(f"结果已落盘 {out_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

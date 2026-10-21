"""把「题目已跑完、但流水线判了超时」的 nightly run 从库里补出结论（不重跑评测）。

背景（2026-10-21 生产事故）
--------------------------
3.7G 内存 + 4G 同盘 swap 的部署机，主集 1040 题全部答完后收尾阶段把内存打穿：系统盘
%util 99%、排队 230 深、iowait 73%，整机假死约 5 小时。内核 OOM 杀掉 758MB 的 eval
worker 后系统恢复，pipeline 此时按 420 分钟超时线判 error——但 eval_run / eval_run_detail
里 1040 题的结果是完整的（928 正确，0.8923），只是没有走门禁与报告。

本脚本直接复用 pipeline._compute_and_publish（门禁 + 报告 + 归档），把结论补到该 run
原本的 slot 目录，覆盖掉 error 档的 nightly.json，不产生任何新的评测流量。

用法（仓库根目录；容器内同构路径 python /app/scripts/backfill_nightly_conclusion.py）
------------------------------------------------------------------------------------
  # 先看 run 概况（默认 dry-run，不写任何文件）
  python scripts/backfill_nightly_conclusion.py --run-id run-a65f7718c830

  # 真正补结论（--slot 指定该 run 原本的归档挡，覆盖同日 error 档）
  python scripts/backfill_nightly_conclusion.py --run-id run-a65f7718c830 \
      --slot 0101-f0273e --apply

  # 补完并重发企微（默认不发，避免与当晚已发的超时告警混淆）
  python scripts/backfill_nightly_conclusion.py --run-id ... --slot ... --apply --notify

注意：--date 缺省按 run.started_at 折算北京日期，跨天补算也不会写错目录；
并发写库请在无评测运行时执行（门禁读 1040 条明细则）。
"""
import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BJT = timezone(timedelta(hours=8))


def _run_date(run: dict) -> str:
    """run 归档日期（北京口径），从 started_at 折算；解析失败返回空串。"""
    raw = str(run.get("started_at") or "")
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # evals 库存的是 UTC naive
    return dt.astimezone(BJT).date().isoformat()


def _webhook() -> str:
    """补发通知目标：与 nightly 同一套变量（SYSTEM + OWNER，回退旧契约）。"""
    parts = [w for w in ((os.getenv("WEBHOOK_SYSTEM") or "").strip(),
                         (os.getenv("WEBHOOK_OWNER") or "").strip()) if w]
    if parts:
        return ",".join(parts)
    return (os.getenv("NIGHTLY_WECOM_WEBHOOK") or os.getenv("WEBHOOK") or "").strip()


async def _main(args: argparse.Namespace) -> int:
    from evals_core.nightly import pipeline
    from evals_core.storage import result_store

    result_store.init_db()
    run = result_store.get_run(args.run_id)
    if not run:
        print(f"找不到 run: {args.run_id}")
        return 2
    details = result_store.list_run_details(args.run_id, True) or []
    done = [d for d in details if d.get("status") not in ("pending", "running")]
    correct = sum(1 for d in done if d.get("quality") == "correct")
    date = args.date or _run_date(run)
    print(f"run={args.run_id} dataset={run.get('dataset_id')} status={run.get('status')}")
    print(f"started={run.get('started_at')} completed={run.get('completed_at')} 归档日期={date or '—'}")
    print(f"明细 {len(done)}/{len(details)} 已收口，correct={correct}"
          f"（{correct / len(done):.2%}）" if done else "明细节为空")
    if not done:
        print("没有可用的逐题结果，补结论无意义（请检查 run 是否真的跑过）")
        return 2
    if not args.apply:
        print("dry-run：只读概况，未写任何文件；确认后加 --apply")
        return 0

    print(f"补结论：slot={args.slot or '(新建挡)'} date={date} notify={args.notify}")
    kwargs = {"slot": args.slot}
    # 老镜像里的 _compute_and_publish 还没有 date 参数（按当天归档）；补历史结论时新代码
    # 才需要显式指定日期，这里按签名自适应，避免「脚本比镜像新」直接 TypeError。
    import inspect
    if "date" in inspect.signature(pipeline._compute_and_publish).parameters:
        kwargs["date"] = date
    out = await pipeline._compute_and_publish(
        args.run_id, str(run.get("dataset_id") or ""), args.resamples,
        os.getenv("NIGHTLY_SITE_URL", "").strip(),
        _webhook() if args.notify else "",
        **kwargs,
    )
    print(f"结论已落盘：state={out.get('state')} score={out.get('overall_score')} "
          f"correct={out.get('correct')}/{out.get('total')} detail={out.get('detail') or '—'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="从 evals.sqlite 补出 nightly 主集结论（不重跑）")
    ap.add_argument("--run-id", required=True, help="已跑完但未出结论的 run_id")
    ap.add_argument("--date", default="", help="归档日期 YYYY-MM-DD；缺省按 started_at 折算北京日期")
    ap.add_argument("--slot", default="", help="归档挡（如 0101-f0273e）；缺省新建一挡，不影响原 error 档")
    ap.add_argument("--resamples", type=int, default=1000, help="bootstrap 重采样次数（门禁置信区间）")
    ap.add_argument("--apply", action="store_true", help="真正计算并写结论；缺省 dry-run")
    ap.add_argument("--notify", action="store_true", help="补结论后重发企微（默认不发）")
    return asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

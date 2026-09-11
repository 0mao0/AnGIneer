"""nightly 全内置流水线：评测 → 异常补判 → 门禁 → 落盘结论 → 企微通知。

由 aichat-api 内置调度器到点触发（也可管理页手动触发），与「开始评测」按钮同一套
suite_runner——nightly 不是外部系统，就是产品自己给自己排的定时体检。

不变式：
- 无论成败，当天必有一条结论落盘（失败也要 publish error 条目）；
- 通知三态严格区分，"通过"必须有门禁结论背书；
- 同一时刻至多一条流水线（并发锁在调用方 nightly_control 里）。
"""
import asyncio
import logging
import time
from typing import Callable, Optional

from evals_core.runner import anomaly, suite_runner
from evals_core.storage import result_store

from . import archive, gate, notify, paths, report

logger = logging.getLogger("evals_core.nightly.pipeline")

RUNNING_STATES = ("running", "pending", "queued")
POLL_INTERVAL_S = 10
DEFAULT_TIMEOUT_HOURS = 4.5   # 487 题全量含补判的最坏窗口（01:00 起跑 06:00 前收工）
DEFAULT_RETRY_ROUNDS = 2


class PipelineError(RuntimeError):
    pass


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _await_terminal(run_id: str, deadline: float) -> dict:
    """轮询到 run 终态；超时/失败/取消都按 PipelineError（上层落 error 档结论）。"""
    last_status = ""
    while time.monotonic() < deadline:
        run = await asyncio.to_thread(result_store.get_run, run_id)
        status = (run or {}).get("status", "")
        if status and status != last_status:
            logger.info("nightly run %s 状态: %s (%s/%s)", run_id, status,
                        (run or {}).get("completed_questions"), (run or {}).get("total_questions"))
            last_status = status
        if status not in RUNNING_STATES:
            if status != "completed":
                raise PipelineError(f"评测 run {run_id} 未正常完成（status={status}）")
            return run
        await _sleep(POLL_INTERVAL_S)
    raise PipelineError(f"评测 run {run_id} 超时未完成（超过时限仍未到终态）")


def _stop_run_best_effort(run_id: str) -> None:
    """请求优雅停止评测 run（当前题做完即退出）。失败只记日志——收尾比"停得干净"更重要。"""
    if not run_id:
        return
    try:
        if suite_runner.stop_eval_run(run_id):
            logger.info("nightly 失败收尾：已请求停止 run=%s", run_id)
        else:
            logger.info("nightly 失败收尾：run=%s 已不在运行中，无需停止", run_id)
    except Exception:  # noqa: BLE001
        logger.exception("nightly 失败收尾停止 run 出错（不影响结论落盘）run=%s", run_id)


def _partial_progress(run_id: str) -> Optional[dict]:
    """已跑部分的进度快照 {completed, total, correct, score}，供 error 档展示"跑到哪了"。

    light 查询，不拉 prediction/all_scores 大字段（那是几十 MB 的 JSON）。
    2026-09-12 实踩：05:30 判超时写 error 档，run 自己 05:55 才跑完 526/526，
    437 题结果无人看见——收尾必须把已完成的部分捞出来。"""
    run = result_store.get_run(run_id) or {}
    details = result_store.list_run_details(run_id, True) or []
    done = [d for d in details if d.get("status") not in ("pending", "running")]
    completed = len(done)
    correct = sum(1 for d in done if d.get("quality") == "correct")
    total = int(run.get("total_questions") or len(details) or 0)
    return {
        "completed": completed,
        "total": total,
        "correct": correct,
        "score": round(correct / completed, 4) if completed else None,
    }


async def _auto_retry(run_id: str, dataset_id: str, rounds: int, deadline: float) -> dict:
    """judge_fail 只重判分、exec_error 整题重跑（原地续跑复用同一 run），≤rounds 轮。"""
    for round_no in range(1, max(rounds, 0) + 1):
        details = await asyncio.to_thread(result_store.list_run_details, run_id, True)
        found = anomaly.detect_anomalies(details)
        judge_ids = [q for q in found.get(anomaly.JUDGE_FAIL, [])]
        exec_ids = [q for q in found.get(anomaly.EXEC_ERROR, [])]
        if not judge_ids and not exec_ids:
            return await asyncio.to_thread(result_store.get_run, run_id)
        logger.info("nightly 补判第 %d 轮：%s 题重判、%s 题重跑", round_no, len(judge_ids), len(exec_ids))
        # resume 原地复用同一 run；exec_error 行无分数自动被 pre_done 排除 → 整题重跑
        await asyncio.to_thread(
            lambda: suite_runner.start_eval_run(
                dataset_id=dataset_id, resume_run_id=run_id, rescore_question_ids=judge_ids),
        )
        await _await_terminal(run_id, deadline)
    details = await asyncio.to_thread(result_store.list_run_details, run_id, True)
    found = anomaly.detect_anomalies(details)
    remaining = {k: v for k, v in found.items() if k != anomaly.SLOW and v}
    if remaining:
        raise PipelineError("补判轮数耗尽仍有未清零异常: " + ", ".join(f"{k}={len(v)}" for k, v in remaining.items()))
    return await asyncio.to_thread(result_store.get_run, run_id)


def _dataset_subject(dataset_id: str) -> str:
    """维护内容展示名：题集标题（题数 题）；读取失败退回 id。"""
    try:
        from evals_core.dataset import manager
        ds = manager.get_dataset(dataset_id) or {}
        title = ds.get("title") or dataset_id
        count = ds.get("question_count")
        return f"{title}（{count} 题）" if count else title
    except Exception:  # noqa: BLE001
        return dataset_id


async def _compute_and_publish(run_id: str, dataset_id: str, resamples: int, site_url: str, webhook: str) -> dict:
    """门禁 + 报告 + 落盘 + 通知，全成功返回结论 dict（state=green/red）。"""
    loop_run = await asyncio.to_thread(result_store.get_run, run_id)
    details = await asyncio.to_thread(result_store.list_run_details, run_id)
    manifest = await asyncio.to_thread(_load_json, paths.manifest_path())
    base_run = await asyncio.to_thread(gate.load_baseline)
    new_run = {"run_id": run_id, "dataset_id": dataset_id, "details": details}
    gate_res = await asyncio.to_thread(
        gate.compare_runs, base_run, gate.normalize_run(new_run), manifest or {"questions": []}, resamples)
    summary = await asyncio.to_thread(
        report.group_and_summarize, details, manifest or {"questions": []})
    report_md = report.render_markdown(summary)

    state = "red" if gate_res.get("gate_red") else "green"
    q_texts = archive.load_question_texts(paths.dataset_json_path(dataset_id))
    entry = archive.build_entry(
        gate_res, loop_run.get("summary_scores") or {}, q_texts,
        dataset_id, paths.today_bjt(), run_id=run_id, state=state,
        subject=_dataset_subject(dataset_id),
        started_at=str(loop_run.get("started_at") or ""))
    archive.publish_day(entry, report_md)

    raw_for_card = {k: loop_run.get(k) for k in ("started_at", "completed_at")}
    raw_for_card["summary_scores"] = loop_run.get("summary_scores") or {}
    text = notify.append_links(
        notify.build_message(raw_for_card, gate_res, state), site_url)
    await _notify_best_effort(webhook, text)
    return {"state": state, "ok": state == "green", "run_id": run_id,
            "overall_score": entry.get("overall_score"), "correct": entry.get("correct"),
            "total": entry.get("total"), "detail": "；".join(gate_res.get("gate_reasons") or [])[:300]}


def _load_json(path):
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def _notify_best_effort(webhook: str, text: str) -> None:
    """逐群尽力推送：支持逗号/分号/空白分隔的多群；单群失败只告警，不阻断其余、不翻转结论。"""
    targets = notify.split_webhooks(webhook)
    if not targets:
        logger.info("未配置企微 webhook，跳过通知")
        return
    for url in targets:
        try:
            await asyncio.to_thread(notify.send, url, text)
            logger.info("企微通知已送达: %s", notify.target_label(url))
        except Exception as exc:  # noqa: BLE001 通知失败不翻转评测结论
            logger.warning("企微通知失败（不影响结论）target=%s: %s", notify.target_label(url), exc)


async def run_nightly(*, dataset_id: str,
                      timeout_hours: float = DEFAULT_TIMEOUT_HOURS,
                      retry_rounds: int = DEFAULT_RETRY_ROUNDS,
                      resamples: int = 1000,
                      site_url: str = "",
                      webhook: str = "",
                      on_run_started: Optional[Callable[[str], None]] = None,
                      should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """执行整条流水线并保证"当天必有结论"。返回 {state, ok, run_id, detail, ...}。

    on_run_started：run 一开跑即上报 run_id（供上层暴露进度/停止目标），回调异常不拖垮流水线。
    should_stop：人为停止意图轮询——起跑间隙置位则起跑后立即收尾；正常完成不因它丢结论。"""
    date = paths.today_bjt()
    deadline = time.monotonic() + timeout_hours * 3600
    run_id = ""
    try:
        started = await asyncio.to_thread(
            lambda: suite_runner.start_eval_run(dataset_id=dataset_id))
        run_id = str(started.get("run_id") or "")
        if not run_id:
            raise PipelineError("start_eval_run 未返回 run_id")
        if on_run_started:
            try:
                on_run_started(run_id)
            except Exception:  # noqa: BLE001 进度上报失败不影响评测本身
                logger.exception("nightly on_run_started 回调异常（run=%s）", run_id)
        logger.info("nightly 流水线启动：dataset=%s run=%s", dataset_id, run_id)
        # 起跑间隙停止：run_id 上报前 stop_pipeline 无从下手，这里拿到 id 立即补停闭环
        if should_stop and should_stop():
            await asyncio.to_thread(suite_runner.stop_eval_run, run_id)
        await _await_terminal(run_id, deadline)
        await _auto_retry(run_id, dataset_id, retry_rounds, deadline)
        return await _compute_and_publish(run_id, dataset_id, resamples, site_url, webhook)
    except Exception as exc:  # noqa: BLE001 任何异常都收口，绝不让历史断档
        # 人为停止：should_stop 置位且 run 未正常完成 → "stopped" 档（不落 error 结论、不发企微，
        # 与「删除同步停止」语义一致：干净消失，不污染门禁历史）
        if should_stop and should_stop():
            status = await asyncio.to_thread(
                lambda: (result_store.get_run(run_id) or {}).get("status") if run_id else "")
            if status != "completed":
                logger.info("nightly 流水线被手动停止（run=%s）", run_id)
                return {"state": "stopped", "ok": False, "run_id": run_id,
                        "detail": "已被手动停止，未生成结论"}
        # 先停后写：超时/异常后 run 往往还在跑（2026-09-12 实踩：05:30 判超时，
        # run 自己 05:55 才收工，此后算力全是白烧），这里立即请求优雅停止。
        await asyncio.to_thread(_stop_run_best_effort, run_id)
        logger.exception("nightly 流水线失败（run=%s）", run_id)
        note = f"{type(exc).__name__}: {str(exc)[:280]}"
        err_started = ""
        progress = None
        if run_id:
            try:  # 起跑后失败（run 已建档）尽量带上开跑时间与已跑进度；起跑前异常则无从取、留空
                err_started = str((await asyncio.to_thread(result_store.get_run, run_id) or {}).get("started_at") or "")
                progress = await asyncio.to_thread(_partial_progress, run_id)
            except Exception:  # noqa: BLE001
                pass
        progress_text = ""
        if progress and progress.get("completed"):
            score = progress.get("score")
            progress_text = f"；已跑 {progress['completed']}/{progress.get('total') or '?'}"
            if score is not None:
                progress_text += f"（答对 {progress['correct']}，部分正确率 {score:.2%}）"
        try:
            archive.publish_day(archive.build_error_entry(
                dataset_id, date, note, subject=_dataset_subject(dataset_id),
                started_at=err_started, progress=progress), None)
            await _notify_best_effort(webhook, notify.build_message(
                None, None, notify.STATE_ERROR, note + progress_text))
        except Exception:  # noqa: BLE001 兜底路径再失败只留日志
            logger.exception("nightly error 档结论落盘/通知也失败")
        return {"state": "error", "ok": False, "run_id": run_id,
                "detail": (note + progress_text)[:300]}

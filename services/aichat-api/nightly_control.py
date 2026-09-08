"""夜间维护调度控制：Web 端配置 + 内置调度器直接跑流水线（全内置，不经过 GitHub）。

时间口径为北京时间；配置持久化在 data/evals/nightly_settings.json（改配置 1 分钟内
生效，零部署）。到点执行的是 evals_core.nightly.pipeline.run_nightly —— 与「开始
评测」按钮同一套 suite_runner。服务器 .env 配 NIGHTLY_SCHEDULER=1 启用定时器；
「立即运行」在任何环境都可用（本地跑小集合验证用）。
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from evals_core.nightly import paths, pipeline
from evals_core.runner import suite_runner
from evals_core.storage import result_store

logger = logging.getLogger("nightly_control")

BJT = paths.BJT
DEFAULT_SETTINGS = {
    # 每晚定时执行是默认选择（01:00 北京时间）；关闭需要显式保存一次
    "enabled": True,
    "hour": 1,
    "minute": 0,
    "dataset_id": paths.DATASET_DEFAULT,
    "timeout_minutes": 270,       # 487 题全量含补判最坏 4.5h
    "retry_rounds": 2,
}
HOURLY_WINDOW = (0, 23)
MINUTE_WINDOW = (0, 59)
TIMEOUT_WINDOW = (10, 1440)
RETRY_WINDOW = (0, 3)


def normalize_settings(raw: dict) -> dict:
    """校验+归一（PUT 入参）；非法抛 ValueError（路由层转 400）。"""
    if not isinstance(raw, dict):
        raise ValueError("请求体必须是对象")
    enabled = raw.get("enabled", DEFAULT_SETTINGS["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔")

    def _int(key: str, default: int, low: int, high: int) -> int:
        try:
            val = int(raw.get(key, default))
        except (TypeError, ValueError):
            raise ValueError(f"{key} 必须是整数")
        if not low <= val <= high:
            raise ValueError(f"{key} 需在 {low}-{high}")
        return val

    if "dataset_id" in raw:
        dataset_id = str(raw.get("dataset_id") or "").strip()
        if not dataset_id or any(c in dataset_id for c in "/\\.."):
            raise ValueError("dataset_id 不合法")
    else:
        dataset_id = DEFAULT_SETTINGS["dataset_id"]
    return {
        "enabled": enabled,
        "hour": _int("hour", DEFAULT_SETTINGS["hour"], *HOURLY_WINDOW),
        "minute": _int("minute", DEFAULT_SETTINGS["minute"], *MINUTE_WINDOW),
        "dataset_id": dataset_id,
        "timeout_minutes": _int("timeout_minutes", DEFAULT_SETTINGS["timeout_minutes"], *TIMEOUT_WINDOW),
        "retry_rounds": _int("retry_rounds", DEFAULT_SETTINGS["retry_rounds"], *RETRY_WINDOW),
    }


def load_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    last_dispatch = None
    try:
        data = json.loads(paths.settings_file().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg.update(normalize_settings(data))
            ld = data.get("last_dispatch")
            if isinstance(ld, dict):
                last_dispatch = ld
    except (OSError, ValueError):
        pass  # 文件缺失/损坏 → 默认值（每晚定时执行=默认选择），接口仍可用
    cfg["last_dispatch"] = last_dispatch
    return cfg


def save_settings(cfg: dict) -> None:
    path = paths.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: cfg[k] for k in DEFAULT_SETTINGS}
    if cfg.get("last_dispatch"):
        payload["last_dispatch"] = cfg["last_dispatch"]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def next_fire_at(cfg: dict, now: datetime) -> Optional[datetime]:
    """下一次应触发的绝对时刻（Asia/Shanghai）。未启用返回 None。"""
    if not cfg.get("enabled"):
        return None
    local = now.astimezone(BJT)
    candidate = local.replace(hour=cfg["hour"], minute=cfg["minute"], second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def slot_of(cfg: dict, now: datetime) -> str:
    """"当天该时段"幂等键：北京日期 + 配置时刻。"""
    return f"{now.astimezone(BJT).date().isoformat()} {cfg['hour']:02d}:{cfg['minute']:02d}"


def due(cfg: dict, now: datetime) -> bool:
    """启用、且已到今日时段 → 该跑；当日时段后已有任何派发（调度器或「立即运行」）
    即视为当天已跑完，不再补跑。2026-09-07 实踩：manual 派发的 slot 键带 "manual:" 前缀，
    旧判定只比对 slot 字符串完全相等，容器重启后调度器误判当日未跑，自动重跑了一轮幽灵评测。"""
    if not cfg.get("enabled"):
        return False
    local = now.astimezone(BJT)
    slot_dt = local.replace(hour=cfg["hour"], minute=cfg["minute"], second=0, microsecond=0)
    if local < slot_dt:
        return False
    last = cfg.get("last_dispatch") or {}
    if last.get("slot") == slot_of(cfg, now):
        return False
    at = last.get("at")
    if not at:
        return True
    try:
        at_dt = datetime.fromisoformat(str(at))
    except ValueError:
        return True
    if at_dt.tzinfo is None:
        at_dt = at_dt.replace(tzinfo=BJT)
    return at_dt < slot_dt


def run_plan() -> dict:
    """「立即运行」确认弹框的预览：跑哪个集、答题/评判模型、并发（只出配置名，绝无密钥）。"""
    from evals_core.dataset import manager
    from evals_core.runner import answer_eval
    cfg = load_settings()
    ds = manager.get_dataset(cfg["dataset_id"]) or {}
    ordered: list = []
    try:
        from ai_inference.llm_config import load_llm_models_from_env
        ordered = [m.name for m in load_llm_models_from_env()]
    except Exception:  # noqa: BLE001 模型清单读取失败不阻塞预览
        logger.warning("LLM_CONFIGS 模型清单读取失败", exc_info=True)
    judge_names = []
    for candidate in answer_eval._judge_candidates():
        judge_names.append(candidate or "兜底=作答模型")
    return {
        "dataset": {"id": cfg["dataset_id"], "title": ds.get("title") or cfg["dataset_id"],
                    "question_count": ds.get("question_count")},
        "answer_model": ordered[0] if ordered else "默认模型（LLM_CONFIGS 首个可用端点）",
        "judge_models": judge_names or ["兜底=作答模型"],
        "concurrency": int(os.getenv("EVAL_CONCURRENCY", "3") or 3),
        "timeout_minutes": cfg["timeout_minutes"],
        "retry_rounds": cfg["retry_rounds"],
    }


# ── 流水线触发（进程内唯一，天然替代 GH 的 concurrency 锁）──

_active: Optional[asyncio.Task] = None
# 运行中流水线的 run 视图：_current_run_id 供列表虚拟行/停止目标；_stop_requested 是
# 人为停止意图（pipeline 收到后走 stopped 收口：不落 error 结论、不发企微）
_current_run_id: str = ""
_stop_requested: bool = False


def is_running() -> bool:
    return _active is not None and not _active.done()


def _on_run_started(run_id: str) -> None:
    global _current_run_id
    _current_run_id = run_id


def running_entry() -> Optional[dict]:
    """列表虚拟运行行：流水线在跑就有行——起跑间隙（run 尚未建档/上报）给"启动中"种子行，
    点「立即运行」后立即可见；已进终态（收口毫秒间隙）返回 None。

    evals 库 started_at 为 UTC naive（容器 UTC），展示统一转北京 +08 带偏移，
    与归档条目 generated_at 同口径，前端 fmtTime 直接解析。"""
    if not is_running():
        return None
    run = result_store.get_run(_current_run_id) if _current_run_id else None
    status = (run or {}).get("status")
    if run is not None and status not in (None, "", "running", "pending", "queued"):
        return None
    cfg = load_settings()
    subject = pipeline._dataset_subject(cfg["dataset_id"])
    started = str((run or {}).get("started_at") or "")
    generated = ""
    if started:
        try:
            dt = datetime.fromisoformat(started)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            generated = dt.astimezone(BJT).isoformat(timespec="seconds")
        except ValueError:
            generated = started
    if not started:
        generated = datetime.now(BJT).isoformat(timespec="seconds")  # 种子行时间=按下时刻
    return {
        "date": "running", "running": True, "state": "running",
        "generated_at": generated, "run_id": _current_run_id,
        "dataset_id": cfg["dataset_id"], "subject": subject,
        "correct": (run or {}).get("completed_questions"),
        "total": (run or {}).get("total_questions"),
        "verdict": "评测进行中，完成后出结论" if run else "评测启动中…",
    }


def stop_pipeline() -> dict:
    """请求停止当前流水线（管理员操作）。优雅停止：当前题做完收尾标 cancelled，
    流水线轮询最迟 ~10s 后经 stopped 路径收口；当天该 slot 已记录，不会自动重跑。"""
    global _stop_requested
    if not is_running():
        return {"ok": False, "detail": "当前没有流水线在运行"}
    _stop_requested = True
    run_id = _current_run_id
    if run_id:
        try:
            suite_runner.stop_eval_run(run_id)
        except Exception:  # noqa: BLE001 停止评测失败也要收口（should_stop 兜底判定）
            logger.exception("stop_eval_run 异常（run=%s），流水线仍按停止收口", run_id)
    return {"ok": True, "run_id": run_id,
            "detail": "已请求停止：当前题目完成后退出，不落结论、不发通知"}


def _record(cfg: dict, now: datetime, source: str, slot: Optional[str], result: dict) -> None:
    cfg = dict(cfg)
    cfg["last_dispatch"] = {
        "slot": slot if source == "scheduler" else f"manual:{now.astimezone(BJT).isoformat(timespec='minutes')}",
        "source": source,
        "at": now.astimezone(BJT).isoformat(timespec="seconds"),
        "ok": bool(result.get("ok")),
        "state": result.get("state") or ("error" if not result.get("ok") else "green"),
        "run_id": result.get("run_id") or "",
        "detail": str(result.get("detail") or "")[:300],
    }
    try:
        save_settings(cfg)
    except OSError:
        logger.exception("nightly 运行结果落盘失败")


def _resolve_webhook() -> str:
    """夜间评测通知目标：系统群 WEBHOOK_SYSTEM + 业主群 WEBHOOK_OWNER（逗号拼接后由
    pipeline 逐群尽力推送，各变量自身支持逗号/分号分隔多群）。
    两者皆未配置时回退旧部署契约 NIGHTLY_WECOM_WEBHOOK / WEBHOOK——nightly 内置化时
    变量名迁移过一轮，部署机 .env 没跟着改就会静默「未配置 webhook 跳过通知」（09-09 晨实踩）。"""
    webhooks = [w for w in (
        (os.getenv("WEBHOOK_SYSTEM") or "").strip(),
        (os.getenv("WEBHOOK_OWNER") or "").strip(),
    ) if w]
    if webhooks:
        return ",".join(webhooks)
    return (os.getenv("NIGHTLY_WECOM_WEBHOOK") or os.getenv("WEBHOOK") or "").strip()


async def _execute(cfg: dict, source: str, slot: Optional[str]) -> dict:
    global _stop_requested, _current_run_id
    _stop_requested = False
    _current_run_id = ""
    t0 = time.monotonic()
    webhook = _resolve_webhook()
    site_url = (os.getenv("NIGHTLY_SITE_URL") or "https://angineer.cn/admin/evals?view=nightly").strip()
    logger.info("nightly 流水线开始（source=%s, dataset=%s）", source, cfg["dataset_id"])
    try:
        result = await pipeline.run_nightly(
            dataset_id=cfg["dataset_id"],
            timeout_hours=cfg["timeout_minutes"] / 60.0,
            retry_rounds=cfg["retry_rounds"],
            site_url=site_url,
            webhook=webhook,
            on_run_started=_on_run_started,
            should_stop=lambda: _stop_requested,
        )
    finally:
        _current_run_id = ""
    logger.info("nightly 流水线结束（source=%s）: state=%s 用时 %.1f min",
                source, result.get("state"), (time.monotonic() - t0) / 60.0)
    _record(cfg, datetime.now(BJT), source, slot, result)
    return result


async def launch(source: str = "manual", slot: Optional[str] = None) -> dict:
    """后台启动流水线；已在跑则拒绝（返回 ok=False）。返回启动状态（非评测结果）。"""
    global _active, _stop_requested
    if is_running():
        return {"ok": False, "detail": "已有一条夜间流水线在运行，请等待其完成"}
    _stop_requested = False
    cfg = load_settings()
    _active = asyncio.create_task(_execute(cfg, source, slot))
    return {"ok": True, "started_at": datetime.now(BJT).isoformat(timespec="seconds"),
            "detail": "流水线已在后台启动，预计数十分钟至数小时，完成看企微与本页历史"}


async def scheduler_loop() -> None:
    """轻量轮询：睡到下一个检查点（≤1h，配置变更 1 分钟内生效），到点直接跑流水线。"""
    logger.info("nightly 调度器已启动（时区 Asia/Shanghai，全内置流水线）")
    while True:
        try:
            now = datetime.now(BJT)
            cfg = load_settings()
            wait = 60.0
            nxt = next_fire_at(cfg, now)
            if nxt is not None:
                wait = min(max((nxt - now).total_seconds(), 5.0), 3600.0)
            await asyncio.sleep(wait)
            now = datetime.now(BJT)
            cfg = load_settings()
            if not due(cfg, now) or is_running():
                continue
            await _execute(cfg, "scheduler", slot_of(cfg, now))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 调度循环永不因单次失败退出
            logger.exception("nightly 调度迭代异常，60s 后继续")
            await asyncio.sleep(60)

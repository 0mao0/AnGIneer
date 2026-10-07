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
from evals_core.storage import retention, result_store

logger = logging.getLogger("nightly_control")

BJT = paths.BJT
DEFAULT_SETTINGS = {
    # 每晚定时执行是默认选择（01:00 北京时间）；关闭需要显式保存一次
    "enabled": True,
    "hour": 1,
    "minute": 0,
    "dataset_id": paths.DATASET_DEFAULT,
    # 附加门禁/观察集（2026-10-07）：主集跑完后顺序各跑一轮完整流水线（各自门禁+基线+企微）。
    # 选配逻辑＝按改动面对照：refusal-39 盯拒答校准、intent-router 盯路由漂移、clause-probe
    # 盯条款直达、financebench-150 盯数值/计算（v0.2.92 书名号闸回归只有手工补跑的 refusal-39
    # 抓到——覆盖面不能只靠主集）。
    "extra_dataset_ids": [],
    "timeout_minutes": 270,       # 487 题全量含补判最坏 4.5h
    "retry_rounds": 2,
    # 素材检查（B 层：jsonl→canonical/chunk→向量 的传递性断言，见 docs/parse-struct-eval.md）
    "parse_health_enabled": True,
    "parse_health_libraries": [],   # 空 = 全部库；也可指定 ["lib-b07ed174"]
    "parse_health_max_docs": 200,   # 按产物修改时间倒序取前 N 篇
}
HOURLY_WINDOW = (0, 23)
MINUTE_WINDOW = (0, 59)
TIMEOUT_WINDOW = (10, 1440)
RETRY_WINDOW = (0, 3)
PARSE_HEALTH_DOCS_WINDOW = (1, 2000)


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

    def _bool(key: str, default: bool) -> bool:
        val = raw.get(key, default)
        if not isinstance(val, bool):
            raise ValueError(f"{key} 必须是布尔")
        return val

    def _str_list(key: str, default: list) -> list:
        val = raw.get(key, default)
        if val in (None, ""):
            return []
        if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
            raise ValueError(f"{key} 必须是字符串数组")
        return [x.strip() for x in val if x.strip()]

    if "dataset_id" in raw:
        dataset_id = str(raw.get("dataset_id") or "").strip()
        # 防路径穿越（id 会拼成 datasets/<id>.json）：拒 /、\、..，放行单点号。
        # 旧写法 any(c in dataset_id for c in "/\\..") 是对该字符串**逐字符**迭代
        # （'/'、'\'、'.'、'.'），把任何点号都判非法——v4.1 这类带点题集永远选不上。
        # 09-28 实踩：手改 JSON 塞 v4.1 → 旧代码静默回默认 v3 → 幽灵跑一轮。
        if not dataset_id or "/" in dataset_id or "\\" in dataset_id or ".." in dataset_id:
            raise ValueError("dataset_id 不合法")
    else:
        dataset_id = DEFAULT_SETTINGS["dataset_id"]
    extra_ids = []
    for x in _str_list("extra_dataset_ids", DEFAULT_SETTINGS["extra_dataset_ids"]):
        if "/" in x or "\\" in x or ".." in x:
            raise ValueError(f"extra_dataset_ids 含不合法 id: {x}")
        if x != dataset_id and x not in extra_ids:
            extra_ids.append(x)
    return {
        "enabled": enabled,
        "hour": _int("hour", DEFAULT_SETTINGS["hour"], *HOURLY_WINDOW),
        "minute": _int("minute", DEFAULT_SETTINGS["minute"], *MINUTE_WINDOW),
        "dataset_id": dataset_id,
        "extra_dataset_ids": extra_ids,
        "timeout_minutes": _int("timeout_minutes", DEFAULT_SETTINGS["timeout_minutes"], *TIMEOUT_WINDOW),
        "retry_rounds": _int("retry_rounds", DEFAULT_SETTINGS["retry_rounds"], *RETRY_WINDOW),
        "parse_health_enabled": _bool("parse_health_enabled", DEFAULT_SETTINGS["parse_health_enabled"]),
        "parse_health_libraries": _str_list("parse_health_libraries", DEFAULT_SETTINGS["parse_health_libraries"]),
        "parse_health_max_docs": _int("parse_health_max_docs", DEFAULT_SETTINGS["parse_health_max_docs"],
                                      *PARSE_HEALTH_DOCS_WINDOW),
    }


def load_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    last_dispatch = None
    load_error = ""
    try:
        data = json.loads(paths.settings_file().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("nightly_settings.json 顶层必须是对象")
        cfg.update(normalize_settings(data))
        ld = data.get("last_dispatch")
        if isinstance(ld, dict):
            last_dispatch = ld
    except FileNotFoundError:
        pass  # 首装无文件 → 默认值（每晚定时执行=默认选择），调度正常接管
    except (OSError, ValueError) as exc:
        # fail-closed：文件在但读坏（半截 JSON/非法字段）不再静默拿默认值跑——
        # 09-28 实踩：默认值恰好可跑（v3/01:00/启用/无派发记录）→ 调度器补跑一轮
        # 幽灵评测，收口还把默认配置覆写回盘。读坏 = 拒跑等人工修（due() 判定处），
        # 界面仍按默认值渲染，管理员改一次配置即恢复。
        load_error = f"{type(exc).__name__}: {exc}"
        logger.error("nightly_settings 读取失败，调度器将拒跑等待人工修复：%s", exc)
    cfg["last_dispatch"] = last_dispatch
    cfg["load_error"] = load_error
    return cfg


def save_settings(cfg: dict) -> None:
    path = paths.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: cfg[k] for k in DEFAULT_SETTINGS}
    if cfg.get("last_dispatch"):
        payload["last_dispatch"] = cfg["last_dispatch"]
    # 原子写：先写同目录临时文件再 os.replace。就地截断重写一旦被打断（容器被杀/崩溃），
    # 盘上会留半截 JSON——09-28 幽灵跑的物理起点（读坏→静默回默认→多跑一轮）
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


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
    旧判定只比对 slot 字符串完全相等，容器重启后调度器误判当日未跑，自动重跑了一轮幽灵评测。
    fail-closed：配置读坏（load_error，见 load_settings）时宁可不跑等人工修，
    也不拿默认值补跑（09-28 幽灵跑的第二道洞——读坏静默回默认）。"""
    if cfg.get("load_error"):
        return False
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
    plan = {
        "dataset": {"id": cfg["dataset_id"], "title": ds.get("title") or cfg["dataset_id"],
                    "question_count": ds.get("question_count")},
        "answer_model": ordered[0] if ordered else "默认模型（LLM_CONFIGS 首个可用端点）",
        "judge_models": judge_names or ["兜底=作答模型"],
        "concurrency": int(os.getenv("EVAL_CONCURRENCY", "3") or 3),
        "timeout_minutes": cfg["timeout_minutes"],
        "retry_rounds": cfg["retry_rounds"],
    }
    # 断点续跑预览（req-nightly-interrupt-resume §2-B3）：10h 窗口内有带章中断 run 时
    # 弹框明示「本次将断点续跑」。只读探测，判据与 pipeline._find_resume_candidate
    # 同一函数（不改派发行为）；无候选不出现该字段（不添噪）
    try:
        resume_id = pipeline._find_resume_candidate(cfg["dataset_id"])
        if resume_id:
            run = result_store.get_run(resume_id) or {}
            plan["resume"] = {
                "run_id": resume_id,
                "completed": int(run.get("completed_questions") or 0),
                "total": int(run.get("total_questions") or 0),
            }
    except Exception:  # noqa: BLE001 预览探测失败不阻塞弹框
        logger.warning("run_plan 续跑候选探测失败", exc_info=True)
    return plan


# ── 流水线触发（进程内唯一，天然替代 GH 的 concurrency 锁）──

_active: Optional[asyncio.Task] = None
# 运行中流水线的 run 视图：_current_run_id 供列表虚拟行/停止目标；_stop_requested 是
# 人为停止意图（pipeline 收到后走 stopped 收口：不落 error 结论、不发企微）
_current_run_id: str = ""
_stop_requested: bool = False
# 断点续跑提示（req-nightly-interrupt-resume §2-B3）：launch 派发前探测命中即写入，
# 种子行据此显示「续跑中」而非与全新起跑无差别。一次性消费——真实 run 行出现即不再
# 参与渲染；_execute finally 兜底清空，防探测落空后残留误导下次全新起跑。
_resume_hint: Optional[dict] = None


def is_running() -> bool:
    return _active is not None and not _active.done()


def attach_active(task: "asyncio.Task") -> None:
    """登记当前流水线 task（launch 内部调用；单活跃位语义不变，与派发同事件循环）。"""
    global _active
    _active = task


async def resume_on_startup(cfg: dict) -> bool:
    """启动自动续跑（req-nightly-interrupt-resume §2-B1）：部署/重启砸掉带中断章的
    run 后自动续跑，与手动派发共用 launch 入口。

    2026-10-05 实踩教训：旧实现是路由 startup 里裸 create_task(_execute)，绕过 launch
    → _active 不登记 → is_running 恒假 → 运行中徽章失明、stop_pipeline 无从下手、
    当晚 04:00 调度器可能双派发。此函数把续跑拉回唯一入口：is_running 守卫
    （launch 内）＋派发落盘（_mark_dispatch）＋内存登记一并生效，杜绝再分叉。
    返回是否真的发起了续跑。"""
    try:
        resume_id = await asyncio.to_thread(
            pipeline._find_resume_candidate, cfg["dataset_id"])
    except Exception:  # noqa: BLE001 探测失败=不续跑，绝不拖垮启动
        logger.exception("启动续跑探测失败（跳过本轮）")
        return False
    if not resume_id:
        return False
    logger.info("nightly 启动自动续跑：发现中断 run %s（窗口内，带启动清扫章）", resume_id)
    result = await launch("resume")
    if not result.get("ok"):
        logger.warning("nightly 启动续跑被拒：%s", result.get("detail"))
    return bool(result.get("ok"))


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
    verdict = "评测进行中，完成后出结论" if run else "评测启动中…"
    entry = {
        "date": "running", "running": True, "state": "running",
        "generated_at": generated, "run_id": _current_run_id,
        "dataset_id": cfg["dataset_id"], "subject": subject,
        "correct": (run or {}).get("completed_questions"),
        "total": (run or {}).get("total_questions"),
    }
    # 种子行 + 续跑 hint：起跑间隙就可见「续跑中（已完成 N/总）」，与全新起跑可区分；
    # hint 只是提示语（派发探测与 pipeline 内部探测是两次独立调用，以实际派发为准）
    if run is None and _resume_hint:
        verdict = f"断点续跑中（已完成 {_resume_hint['already_done']}/{_resume_hint['total'] or '?'}）"
        entry["resuming_from"] = _resume_hint["run_id"]
        entry["correct"] = _resume_hint["already_done"]
        entry["total"] = _resume_hint["total"] or None
    entry["verdict"] = verdict
    return entry


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


def _slot_key(source: str, slot: Optional[str], now: datetime) -> str:
    """派发记录的 slot 键三档（due 据此判「当日已跑」）：
    - scheduler：当日排班时段（幂等键，due 认它算已跑）；
    - manual：裸时刻（无 manual: 前缀）——手动跑完当晚定时不再重复烧一整轮；
      旧带前缀行为=当晚 04:00 双跑，10-05 用户实测后定版改裸（幽灵评测的旧事故
      根因是「读坏静默回默认」而非 manual 形态，fail-closed 三洞堵死后此改动安全）；
    - resume 等其它：带前缀（启动续跑不占排班档，当晚 04:00 定时仍能跑——
      续跑是故障补救，不是当晚评测）。"""
    if source == "scheduler":
        return slot or ""
    if source == "manual":
        return now.astimezone(BJT).isoformat(timespec="minutes")
    return f"{source}:{now.astimezone(BJT).isoformat(timespec='minutes')}"


def _record(cfg: dict, now: datetime, source: str, slot: Optional[str], result: dict) -> None:
    cfg = dict(cfg)
    cfg["last_dispatch"] = {
        "slot": _slot_key(source, slot, now),
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


def _mark_dispatch(cfg: dict, now: datetime, source: str, slot: Optional[str]) -> None:
    """派发即落盘（state=dispatched）：旧实现收口才写 slot，一跑数小时里盘上没有
    「当日已派发」记录，判定全靠进程内存的 is_running()——进程重启/多调度实例落在
    跑中窗口就重复派发（09-07 容器重启、09-28 配置读坏两次幽灵跑同根）。
    先写后跑，最坏「少跑不补」而非「多跑覆写结论」。"""
    _record(cfg, now, source, slot,
            {"ok": True, "state": "dispatched", "run_id": "", "detail": ""})


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


async def _probe_resume_hint(cfg: dict) -> None:
    """派发前探测断点续跑候选，命中留 hint 给种子行（起跑间隙即显示「续跑中」）。

    与 pipeline 内部探测（pipeline.py:426）是两次独立调用，窗口边界上可能不一致
    （种子说续跑、实际全新跑）——hint 只是提示语，不构成行为契约。探测失败按全新
    起跑显示，绝不影响派发本身。"""
    global _resume_hint
    _resume_hint = None
    try:
        resume_id = await asyncio.to_thread(pipeline._find_resume_candidate, cfg["dataset_id"])
        if not resume_id:
            return
        run = await asyncio.to_thread(result_store.get_run, resume_id) or {}
        _resume_hint = {
            "run_id": resume_id,
            "already_done": int(run.get("completed_questions") or 0),
            "total": int(run.get("total_questions") or 0),
        }
    except Exception:  # noqa: BLE001
        logger.exception("续跑提示探测失败（按全新起跑显示）")
        _resume_hint = None


async def _execute(cfg: dict, source: str, slot: Optional[str]) -> dict:
    global _stop_requested, _current_run_id, _resume_hint
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
            parse_health_enabled=cfg.get("parse_health_enabled", True),
            parse_health_libraries=cfg.get("parse_health_libraries") or None,
            parse_health_max_docs=cfg.get("parse_health_max_docs", 200),
        )
    finally:
        _current_run_id = ""
        _resume_hint = None  # 一次性消费兜底：无论成败，hint 不活到下次派发
    logger.info("nightly 流水线结束（source=%s）: state=%s 用时 %.1f min",
                source, result.get("state"), (time.monotonic() - t0) / 60.0)
    # 附加集：主集收口后顺序各跑一轮完整流水线（门禁/基线/企微各自独立，2026-10-07）。
    # 单集失败只记日志不拖垮后续集；停止意图沿用同一开关（stop_pipeline 停当前 run，
    # 下一起跑间隙 should_stop 置位即收尾）。
    extras = cfg.get("extra_dataset_ids") or []
    for extra_id in extras:
        if _stop_requested:
            logger.info("nightly 附加集跳过（收到停止意图）: %s", extra_id)
            break
        t1 = time.monotonic()
        try:
            extra_result = await pipeline.run_nightly(
                dataset_id=extra_id,
                timeout_hours=cfg["timeout_minutes"] / 60.0,
                retry_rounds=cfg["retry_rounds"],
                site_url=site_url,
                webhook=webhook,
                on_run_started=_on_run_started,
                should_stop=lambda: _stop_requested,
                parse_health_enabled=False,  # 素材检查主集已跑，附加集不重复
            )
            logger.info("nightly 附加集 %s 收口: state=%s 用时 %.1f min",
                        extra_id, extra_result.get("state"), (time.monotonic() - t1) / 60.0)
        except Exception:  # noqa: BLE001
            logger.exception("nightly 附加集 %s 失败（继续后续集）", extra_id)
        finally:
            _current_run_id = ""
    _record(cfg, datetime.now(BJT), source, slot, result)
    # 全表补裁：suite_runner 只在"自己的 run 收尾时"调 enforce，而刚收尾的 run 都在
    # 3 天窗内不动。若此后几天没有别的评测收尾，滑出窗口的全量 run 就没人裁（10-02
    # 实踩：4 个 450MB run 堆到 2G）。nightly 每晚必跑，这里补一次全表扫描兜住日界。
    # best-effort：失败只留日志，下晚再试（同 suite_runner:742 的容错口径）。
    try:
        retention_stats = retention.enforce_after_run()
        if retention_stats["compacted_runs"] or retention_stats["deleted_runs"]:
            logger.info("nightly 日终保留策略: %s", {k: v for k, v in retention_stats.items() if v})
    except Exception:  # noqa: BLE001
        logger.exception("nightly 日终保留策略失败（下晚再试）")
    # 素材检查/门禁计算也会吃堆内存；评测段归还点在 suite_runner 线程 finally
    try:
        suite_runner.release_native_memory()
    except Exception:  # noqa: BLE001
        logger.exception("归还内存失败（无害，下轮再试）")
    return result


async def launch(source: str = "manual", slot: Optional[str] = None) -> dict:
    """后台启动流水线；已在跑则拒绝（返回 ok=False）。返回启动状态（非评测结果）。"""
    global _active, _stop_requested
    if is_running():
        return {"ok": False, "detail": "已有一条夜间流水线在运行，请等待其完成"}
    _stop_requested = False
    cfg = load_settings()
    await _probe_resume_hint(cfg)
    _mark_dispatch(cfg, datetime.now(BJT), source, slot)
    attach_active(asyncio.create_task(_execute(cfg, source, slot)))
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
            _mark_dispatch(cfg, now, "scheduler", slot_of(cfg, now))
            await _execute(cfg, "scheduler", slot_of(cfg, now))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 调度循环永不因单次失败退出
            logger.exception("nightly 调度迭代异常，60s 后继续")
            await asyncio.sleep(60)

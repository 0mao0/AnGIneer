"""Evals API 路由。"""
import asyncio
import json
import os
import re as _re
import shutil
from datetime import datetime as _dt, timezone as _tz
from typing import Any, Dict, Optional

import nightly_control

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File as FastAPIFile

from chat_auth import resolve_session_principal
from evals_core.contracts import (
    AddQuestionRequest,
    CompareResult,
    CreateDatasetRequest,
    CreateFolderRequest,
    EvalRunProgress,
    MoveDatasetRequest,
    StartEvalRunRequest,
    UpdateFolderRequest,
    UpdateQuestionRequest,
)
from evals_core.dataset import manager
from angineer_core.prompts.evals_routes import (
    COMPARE_ANALYSIS_SYSTEM_PROMPT,
    COMPARE_ANALYSIS_USER_TEMPLATE,
)
from evals_core.runner import suite_runner
from evals_core.storage import result_store

evals_router = APIRouter()


@evals_router.on_event("startup")
async def _startup():
    """应用启动时初始化数据库，并清扫上次进程被杀留下的僵尸 running run。"""
    import logging
    result_store.init_db()
    swept = suite_runner.sweep_interrupted_runs()
    if swept:
        logging.getLogger("evals").warning("启动清扫：%d 个中断评测已标记为已取消（可断点续跑）", swept)


# --- 题集管理 ---


@evals_router.get("/datasets")
async def get_datasets():
    """列出所有测试集。"""
    datasets = manager.list_datasets()
    return {"datasets": datasets}


@evals_router.post("/datasets")
async def create_dataset(req: CreateDatasetRequest):
    """创建空测试集。"""
    dataset = manager.create_dataset(req.model_dump())
    return dataset


@evals_router.post("/datasets/import")
async def import_dataset(file: UploadFile = FastAPIFile(...)):
    """导入 JSON 题集文件。"""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="仅支持 .json 文件")
    content = await file.read()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {exc}")
    try:
        dataset = manager.import_bundle(payload, source_file=file.filename)
        return dataset
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"题集格式错误: {exc}")


@evals_router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    """获取测试集详情。"""
    dataset = manager.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return dataset


@evals_router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    """删除测试集。"""
    success = manager.delete_dataset(dataset_id)
    if not success:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return {"status": "deleted"}


@evals_router.patch("/datasets/{dataset_id}")
async def update_dataset(dataset_id: str, body: Dict[str, Any] = None):
    """更新测试集元信息（如标题）。"""
    if not body:
        raise HTTPException(status_code=400, detail="无更新内容")
    dataset = manager.update_dataset(dataset_id, body)
    if not dataset:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return dataset


@evals_router.get("/datasets/{dataset_id}/questions")
async def get_questions(dataset_id: str):
    """获取测试集题目列表。"""
    questions = manager.list_questions(dataset_id)
    return {"questions": questions}


@evals_router.post("/datasets/{dataset_id}/questions")
async def add_question(dataset_id: str, req: AddQuestionRequest):
    """向测试集添加单题。"""
    question = manager.add_question(dataset_id, req.model_dump())
    return question


@evals_router.put("/datasets/{dataset_id}/questions/{question_id}")
async def update_question(dataset_id: str, question_id: str, req: UpdateQuestionRequest):
    """编辑题目。"""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")
    question = manager.update_question(dataset_id, question_id, updates)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


@evals_router.delete("/datasets/{dataset_id}/questions/{question_id}")
async def delete_question(dataset_id: str, question_id: str):
    """删除题目。"""
    success = manager.delete_question(dataset_id, question_id)
    if not success:
        raise HTTPException(status_code=404, detail="题目不存在")
    return {"status": "deleted"}


@evals_router.get("/datasets/{dataset_id}/export")
async def export_dataset(dataset_id: str):
    """导出测试集为规范 JSON。"""
    data = manager.export_dataset(dataset_id)
    if not data:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return data


# --- 文件夹管理 ---


@evals_router.get("/folders")
async def get_folders():
    """列出所有文件夹。"""
    folders = manager.list_folders()
    return {"folders": folders}


@evals_router.post("/folders")
async def create_folder(req: CreateFolderRequest):
    """创建文件夹。"""
    folder = manager.create_folder(req.model_dump())
    return folder


@evals_router.patch("/folders/{folder_id}")
async def update_folder(folder_id: str, req: UpdateFolderRequest):
    """更新文件夹信息。"""
    updates = {}
    for field in req.model_fields_set:
        value = getattr(req, field)
        if value is not None or field == 'parent_folder_id':
            updates[field] = value
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")
    folder = manager.update_folder(folder_id, updates)
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return folder


@evals_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str):
    """删除文件夹。"""
    success = manager.delete_folder(folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return {"status": "deleted"}


@evals_router.patch("/datasets/{dataset_id}/move")
async def move_dataset(dataset_id: str, req: MoveDatasetRequest):
    """移动数据集到指定文件夹。"""
    dataset = manager.move_dataset(dataset_id, req.folder_id, req.sort_order)
    if not dataset:
        raise HTTPException(status_code=404, detail="测试集不存在")
    return dataset


# --- 评测运行 ---


@evals_router.post("/runs")
async def start_run(req: StartEvalRunRequest):
    """启动评测运行（异步），可指定单题。"""
    try:
        loop = asyncio.get_event_loop()
        run_data = await loop.run_in_executor(
            None,
            lambda: suite_runner.start_eval_run(
                dataset_id=req.dataset_id, question_id=req.question_id, save=req.save,
                override_doc_ids=req.doc_ids, resume_run_id=req.resume_run_id,
                config_name=req.config_name, rescore_question_ids=req.rescore_question_ids,
                judge_config_name=req.judge_config_name, restart_run_id=req.restart_run_id,
            ),
        )
        return run_data
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@evals_router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    """删除评测运行记录。"""
    success = suite_runner.delete_eval_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="评测记录不存在")
    return {"status": "deleted"}


@evals_router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str):
    """停止正在运行的评测任务。"""
    success = suite_runner.stop_eval_run(run_id)
    if not success:
        raise HTTPException(status_code=404, detail="未找到运行中的任务或任务已结束")
    return {"status": "stopping", "run_id": run_id}


@evals_router.get("/runs/{run_id}")
async def get_run(run_id: str, light: bool = Query(False)):
    """查询运行进度/结果。

    light=true 时裁剪 prediction/all_scores/all_predictions 等大字段，
    用于列表与轮询场景；展开单题时走 /runs/{run_id}/questions/{question_id} 获取完整详情。
    """
    run = suite_runner.get_eval_run(run_id, light=light)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@evals_router.get("/runs/{run_id}/questions/{question_id}")
async def get_run_question_detail(run_id: str, question_id: str):
    """获取单道题目的完整运行详情（含过程 trace、分项分数等）。"""
    detail = suite_runner.get_eval_run_detail(run_id, question_id)
    if not detail:
        raise HTTPException(status_code=404, detail="题目运行详情不存在")
    return detail


@evals_router.get("/runs")
async def list_runs(dataset_id: Optional[str] = None):
    """列出历史运行记录。"""
    runs = suite_runner.list_eval_runs(dataset_id)
    return {"runs": runs}


@evals_router.get("/compare")
async def compare_runs(run_id_a: str, run_id_b: str):
    """对比两次运行结果。"""
    result = suite_runner.compare_runs(run_id_a, run_id_b)
    if not result:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return result


@evals_router.post("/compare/analyze")
async def analyze_compare(body: Dict[str, Any] = None):
    """使用 LLM 分析两次评测结果的差异。"""
    if not body:
        raise HTTPException(status_code=400, detail="无请求内容")
    run_id_a = body.get("run_id_a")
    run_id_b = body.get("run_id_b")
    question_id = body.get("question_id")
    if not run_id_a or not run_id_b or not question_id:
        raise HTTPException(status_code=400, detail="缺少 run_id_a、run_id_b 或 question_id")

    from ai_inference.llm_client import get_llm_client

    run_a = suite_runner.get_eval_run(run_id_a)
    run_b = suite_runner.get_eval_run(run_id_b)
    if not run_a or not run_b:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    details_a = {d["question_id"]: d for d in run_a.get("details", [])}
    details_b = {d["question_id"]: d for d in run_b.get("details", [])}
    detail_a = details_a.get(question_id, {})
    detail_b = details_b.get(question_id, {})

    quality_a = detail_a.get("quality") or detail_a.get("status", "missing")
    quality_b = detail_b.get("quality") or detail_b.get("status", "missing")

    scores_a = detail_a.get("scores") or {}
    scores_b = detail_b.get("scores") or {}
    prediction_a = detail_a.get("prediction") or {}
    prediction_b = detail_b.get("prediction") or {}

    prompt = COMPARE_ANALYSIS_USER_TEMPLATE.format(
        question_id=question_id,
        run_id_a=run_id_a[:12],
        quality_a=quality_a,
        scores_a=scores_a,
        prediction_a=prediction_a,
        run_id_b=run_id_b[:12],
        quality_b=quality_b,
        scores_b=scores_b,
        prediction_b=prediction_b,
    )

    try:
        loop = asyncio.get_event_loop()
        client = get_llm_client()
        analysis = await loop.run_in_executor(
            None,
            lambda: client.chat(
                messages=[
                    {"role": "system", "content": COMPARE_ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                mode="instruct",
            ),
        )
        return {"question_id": question_id, "analysis": analysis}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM 分析失败: {exc}")


# --- 解析回归（A 层只读看板）---
# 与夜间维护同一套模式：读服务器上的归档目录，不触发任何执行。
# 为什么只能看不能跑：A① 要 18GB 官方评测镜像，只装在开发机（部署机根分区装不下，
# AGENTS.md 已否决），所以数据由本机 `run_parse_regression.py --publish` 同步上来。

async def require_admin_session(request: Request) -> None:
    """只读视图（解析回归 / 夜间维护）的管理员会话校验：Bearer session + is_admin。

    定义在这里（两个只读视图共用），不能放在任一段落内部——模块级装饰器在导入时求值。
    """
    if not resolve_session_principal(request):
        raise HTTPException(status_code=401, detail="需要登录会话")
    if not getattr(request.state.session_user, "is_admin", False):
        raise HTTPException(status_code=403, detail="仅管理员可查看")


_PARSE_REG_RUN_RE = _re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _parse_regression_root() -> str:
    """与 evals.sqlite 同口径的 data/evals 根下 `parse_regression/`，不新增配置项。"""
    return os.path.join(os.path.dirname(result_store._DB_PATH), "parse_regression")


def _read_publish(run_dir: str, run_id: str) -> Dict[str, Any]:
    """读一次 run 的 publish.json（本机算好的结论层载荷）。

    两种情况分开记（前端文案不同）：文件还没生成 = pending（本机在跑或跑完没 --publish）；
    文件在但读不出来 = corrupt（真坏了）。都用目录名兜底当 run_id，列表不因此炸。
    """
    path = os.path.join(run_dir, "publish.json")
    if not os.path.exists(path):
        return {"run_id": run_id, "state": "pending"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("publish.json 不是对象")
        data.setdefault("run_id", run_id)
        return data
    except (OSError, ValueError):
        return {"run_id": run_id, "state": "corrupt"}


_DATE_IN_TEXT_RE = _re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")


def _run_sort_key(entry: Dict[str, Any]) -> str:
    """排序键统一成 `YYYY-MM-DD`：run_date → ts → run_id/目录名里的日期。

    三种键格式不同会排乱（"2026-09-17" 与 "20260918-0100" 逐字符比，'-' 比数字小），
    所以先归一化；损坏条目没有 run_date，就用目录名兜底（仍能按日期排）。
    """
    for raw in (entry.get("run_date"), entry.get("ts"), entry.get("run_id")):
        match = _DATE_IN_TEXT_RE.search(str(raw or ""))
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def _read_text_or_empty(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


@evals_router.get("/parse-regression", dependencies=[Depends(require_admin_session)])
async def list_parse_regression_runs():
    """解析回归 run 列表（倒序）。本机跑完 `--publish` 落 data/evals/parse_regression/<run_id>/。"""
    root = _parse_regression_root()
    if not os.path.isdir(root):
        return {"runs": [], "root_exists": False}
    runs = [
        _read_publish(os.path.join(root, name), name)
        for name in sorted(os.listdir(root))
        if _PARSE_REG_RUN_RE.match(name) and os.path.isdir(os.path.join(root, name))
    ]
    # 按"结果日期"倒序（不按目录名：baseline-* 会被字典序排到 2026* 前面，看起来像最新）
    runs.sort(key=lambda r: _run_sort_key(r), reverse=True)
    return {"runs": runs, "root_exists": True}


# 注意：/parse-regression/{run_id} 注册在列表路由之后（FastAPI 按声明顺序匹配，前缀不同不冲突）
@evals_router.get("/parse-regression/{run_id}", dependencies=[Depends(require_admin_session)])
async def get_parse_regression_run(run_id: str):
    """单次 run 详情：结论载荷 + summary.md 原文 + A② 逐类目报告。run_id 严格校验防路径穿越。"""
    if not _PARSE_REG_RUN_RE.match(run_id):
        raise HTTPException(status_code=404, detail="run_id 不合法")
    run_dir = os.path.join(_parse_regression_root(), run_id)
    if not os.path.isdir(run_dir):
        raise HTTPException(status_code=404, detail="该次解析回归归档不存在")
    return {
        "run": _read_publish(run_dir, run_id),
        "summary_md": _read_text_or_empty(os.path.join(run_dir, "summary.md")),
        "struct_report_md": _read_text_or_empty(os.path.join(run_dir, "struct_chain_report.md")),
    }


# --- 夜间维护（nightly 门禁产物只读视图）---
# 仅这两个路由要求管理员会话（require_admin_session）；存量 /api/evals/* 鉴权治理另行处理。

_NIGHTLY_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _nightly_root() -> str:
    """产物目录与 evals.sqlite 同口径（result_store 的 data/evals 根），不新增配置项。"""
    return os.path.join(os.path.dirname(result_store._DB_PATH), "nightly")


def _read_nightly_day(day_dir: str, date: str) -> Dict[str, Any]:
    """读单日 nightly.json；缺失/损坏降级为 corrupt，不炸整个列表。"""
    try:
        with open(os.path.join(day_dir, "nightly.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("nightly.json 不是对象")
        data["date"] = date
        return data
    except (OSError, ValueError):
        return {"date": date, "state": "corrupt"}


@evals_router.get("/nightly", dependencies=[Depends(require_admin_session)])
async def list_nightly_days():
    """夜间维护历史列表（倒序）。workflow Publish 步骤逐日落 data/evals/nightly/<date>/。"""
    root = _nightly_root()
    if not os.path.isdir(root):
        return {"days": []}
    days = [
        _read_nightly_day(os.path.join(root, name), name)
        for name in sorted(os.listdir(root), reverse=True)
        if _NIGHTLY_DATE_RE.match(name) and os.path.isdir(os.path.join(root, name))
    ]
    entry = nightly_control.running_entry()
    if entry:
        days.insert(0, entry)
    return {"days": days}


# 注意路由顺序：/nightly/settings 必须注册在 /nightly/{date} 之前，否则被日期路由吞成 404


@evals_router.get("/nightly/settings", dependencies=[Depends(require_admin_session)])
async def get_nightly_settings():
    """夜间维护调度配置 + 下次触发时间（北京时间）+ 流水线是否在跑。"""
    cfg = nightly_control.load_settings()
    nxt = nightly_control.next_fire_at(cfg, _dt.now(_tz.utc))
    return {**cfg, "running": nightly_control.is_running(),
            "next_fire_at": nxt.isoformat(timespec="minutes") if nxt else None}


@evals_router.get("/nightly/run-plan", dependencies=[Depends(require_admin_session)])
async def get_nightly_run_plan():
    """「立即运行」确认弹框预览：测试集/作答模型/评判模型链/并发（仅配置名，无密钥）。"""
    return nightly_control.run_plan()


@evals_router.put("/nightly/settings", dependencies=[Depends(require_admin_session)])
async def put_nightly_settings(payload: Dict[str, Any]):
    """保存每晚执行时间（北京时间）与启用开关；调度器 1 分钟内生效。
    与现有配置合并：UI 只传展示字段，dataset/超时等高级项不被重置。"""
    try:
        cfg = nightly_control.normalize_settings({**nightly_control.load_settings(), **payload})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    cfg["last_dispatch"] = nightly_control.load_settings().get("last_dispatch")
    nightly_control.save_settings(cfg)
    return await get_nightly_settings()


@evals_router.post("/nightly/stop", dependencies=[Depends(require_admin_session)])
async def post_nightly_stop():
    """停止运行中的流水线（当前题完成后收尾）：不落 error 档结论、不发企微通知。"""
    r = nightly_control.stop_pipeline()
    if not r.get("ok"):
        raise HTTPException(status_code=409, detail=r.get("detail") or "当前没有流水线在运行")
    return r


@evals_router.delete("/nightly/{date}", dependencies=[Depends(require_admin_session)])
async def delete_nightly_day(date: str):
    """删除一条夜间维护结论：连带删除对应评测 run（日常测试的逐题结果一并消失，不可恢复）；
    run 若仍在运行先停再删（与「停止」同语义）。"""
    if not _NIGHTLY_DATE_RE.match(date):
        raise HTTPException(status_code=404, detail="日期格式不合法")
    day_dir = os.path.join(_nightly_root(), date)
    if not os.path.isdir(day_dir):
        raise HTTPException(status_code=404, detail="该日期无夜间维护记录")
    entry: Dict[str, Any] = {}
    try:
        with open(os.path.join(day_dir, "nightly.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            entry = data
    except (OSError, ValueError):
        pass  # 损坏条目照样可删，只是无从连带删 run
    stopped_run = deleted_run = False
    run_id = str(entry.get("run_id") or "")
    if run_id:
        run = result_store.get_run(run_id) or {}
        if run.get("status") in ("running", "pending", "queued"):
            suite_runner.stop_eval_run(run_id)
            stopped_run = True
        deleted_run = suite_runner.delete_eval_run(run_id)
    shutil.rmtree(day_dir, ignore_errors=True)
    return {"status": "deleted", "date": date, "stopped_run": stopped_run, "deleted_run": deleted_run}


@evals_router.get("/nightly/{date}", dependencies=[Depends(require_admin_session)])
async def get_nightly_day(date: str):
    """单日详情：结论 json + report.md 原文。date 严格校验防路径穿越。"""
    if not _NIGHTLY_DATE_RE.match(date):
        raise HTTPException(status_code=404, detail="日期格式不合法")
    day_dir = os.path.join(_nightly_root(), date)
    if not os.path.isdir(day_dir):
        raise HTTPException(status_code=404, detail="该日期无夜间维护记录")
    entry = _read_nightly_day(day_dir, date)
    report_md = ""
    report_path = os.path.join(day_dir, "report.md")
    try:
        with open(report_path, "r", encoding="utf-8") as fh:
            report_md = fh.read()
    except OSError:
        pass
    return {"nightly": entry, "report_md": report_md}


@evals_router.post("/nightly/run-now", dependencies=[Depends(require_admin_session)])
async def post_nightly_run_now():
    """立即后台跑一轮全内置流水线（评测→补判→门禁→落盘结论→企微），结果异步出。"""
    started = await nightly_control.launch("manual")
    return {
        "ok": bool(started.get("ok")),
        "detail": str(started.get("detail") or ""),
        "at": started.get("started_at") or "",
    }


_nightly_scheduler_task = None


@evals_router.on_event("startup")
async def _nightly_scheduler_startup():
    """服务器（.env NIGHTLY_SCHEDULER=1）才启用内置调度；本地 dev 默认关，不误触发 CI。"""
    global _nightly_scheduler_task
    if os.getenv("NIGHTLY_SCHEDULER", "").strip().lower() not in ("1", "true", "on"):
        return
    if _nightly_scheduler_task is None or _nightly_scheduler_task.done():
        _nightly_scheduler_task = asyncio.create_task(nightly_control.scheduler_loop())

"""Dream Cycle API 路由。

提供报告查看、手动触发和审核确认接口。
"""

import os
import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

dream_cycle_router = APIRouter()


def _get_reports_dir() -> str:
    """获取报告存储目录。"""
    project_root = os.environ.get("ANGINEER_PROJECT_ROOT", "")
    if not project_root:
        current = os.path.dirname(os.path.abspath(__file__))
        while current and not os.path.isdir(os.path.join(current, "services")):
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        project_root = current
    data_dir = os.environ.get(
        "DREAM_CYCLE_DATA_DIR",
        os.path.join(project_root, "data", "dream_cycle"),
    )
    return os.path.join(data_dir, "reports")


@dream_cycle_router.get("/reports")
async def list_reports(limit: int = Query(default=30, ge=1, le=365)):
    """获取历史报告列表（按日期倒序）。"""
    reports_dir = _get_reports_dir()
    if not os.path.isdir(reports_dir):
        return {"reports": [], "total": 0}

    files = sorted(
        [f for f in os.listdir(reports_dir) if f.endswith(".json")],
        reverse=True,
    )[:limit]

    reports = []
    for f in files:
        file_path = os.path.join(reports_dir, f)
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            reports.append({
                "date": f.replace(".json", ""),
                "total_findings": data.get("total_findings", 0),
                "total_auto_fixed": data.get("total_auto_fixed", 0),
                "run_duration_seconds": data.get("run_duration_seconds", 0),
                "task_count": len(data.get("task_results", [])),
            })
        except Exception:
            reports.append({"date": f.replace(".json", ""), "error": "报告读取失败"})

    return {"reports": reports, "total": len(reports)}


@dream_cycle_router.get("/reports/{date}")
async def get_report(date: str):
    """获取指定日期的完整报告。"""
    reports_dir = _get_reports_dir()
    file_path = os.path.join(reports_dir, f"{date}.json")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"报告不存在: {date}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="报告文件损坏")


@dream_cycle_router.post("/run")
async def trigger_run():
    """手动触发一次 Dream Cycle 运行（后台执行）。"""
    def _run_in_background():
        try:
            from docs_core.maintain.cycle.runner import DreamCycleRunner
            runner = DreamCycleRunner()
            runner.run()
        except Exception as e:
            import traceback
            traceback.print_exc()

    thread = threading.Thread(target=_run_in_background, daemon=True)
    thread.start()
    return {
        "status": "started",
        "message": "Dream Cycle 已在后台启动，请稍后查看报告。",
        "timestamp": datetime.now().isoformat(),
    }


@dream_cycle_router.post("/tasks/dedup/confirm/{entity_a_id}/{entity_b_id}")
async def confirm_dedup_merge(
    entity_a_id: str,
    entity_b_id: str,
    canonical_name: Optional[str] = Query(default=None),
):
    """确认合并两个疑似重复实体。"""
    try:
        from docs_core.maintain.cycle.config import get_config
        from docs_core.maintain.cycle.runner import DreamCycleRunner

        cfg = get_config()
        runner = DreamCycleRunner(cfg)
        conn = runner._connect_graph_db()
        if not conn:
            raise HTTPException(status_code=500, detail="无法连接知识图谱数据库")

        try:
            name = canonical_name or entity_a_id
            runner._merge_entities(conn, entity_a_id, entity_b_id, name)
            return {
                "status": "merged",
                "message": f"实体 {entity_b_id} 已合并到 {entity_a_id}",
            }
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@dream_cycle_router.post("/tasks/dedup/dismiss/{entity_a_id}/{entity_b_id}")
async def dismiss_dedup_candidate(entity_a_id: str, entity_b_id: str):
    """驳回一个去重建议（记录为误报）。"""
    try:
        from docs_core.maintain.cycle.config import get_config
        from docs_core.maintain.cycle.runner import DreamCycleRunner

        cfg = get_config()
        runner = DreamCycleRunner(cfg)
        runner._write_audit("dedup_dismissed", {
            "timestamp": datetime.now().isoformat(),
            "entity_a_id": entity_a_id,
            "entity_b_id": entity_b_id,
            "action": "dismissed",
        })
        return {
            "status": "dismissed",
            "message": f"已记录误报反馈: {entity_a_id} 与 {entity_b_id} 不重复",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@dream_cycle_router.post("/tasks/orphan/keep/{entity_id}")
async def orphan_keep(entity_id: str):
    """保留孤立实体（标记为非孤立）。"""
    try:
        from docs_core.maintain.cycle.config import get_config
        cfg = get_config()
        conn = sqlite3.connect(cfg.graph_db_path)
        conn.execute(
            "UPDATE graph_entities SET description = COALESCE(description||' ','') || '[DREAM_CYCLE: 人工保留，非孤立实体]' WHERE entity_id = ?",
            (entity_id,),
        )
        conn.commit()
        conn.close()
        return {"status": "kept", "message": f"实体 {entity_id} 已标记为保留"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@dream_cycle_router.post("/tasks/orphan/delete/{entity_id}")
async def orphan_delete(entity_id: str):
    """确认清理孤立实体（标记为 inactive）。"""
    try:
        from docs_core.maintain.cycle.config import get_config
        cfg = get_config()
        conn = sqlite3.connect(cfg.graph_db_path)
        conn.execute(
            "UPDATE graph_entities SET description = COALESCE(description||' ','') || '[DREAM_CYCLE: 人工确认，标记为不活跃]' WHERE entity_id = ?",
            (entity_id,),
        )
        conn.commit()
        conn.close()
        return {"status": "deleted", "message": f"实体 {entity_id} 已标记为不活跃"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@dream_cycle_router.get("/health")
async def health_check():
    """检查 Dream Cycle 状态。"""
    reports_dir = _get_reports_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    today_report = os.path.join(reports_dir, f"{today}.json")

    # 检查最近一次报告
    last_run = None
    if os.path.isdir(reports_dir):
        files = sorted(
            [f for f in os.listdir(reports_dir) if f.endswith(".json")],
            reverse=True,
        )
        if files:
            last_run = files[0].replace(".json", "")

    return {
        "enabled": os.environ.get("DREAM_CYCLE_ENABLED", "true").lower() == "true",
        "last_run": last_run,
        "today_completed": os.path.exists(today_report),
        "reports_dir": reports_dir,
        "reports_count": len([
            f for f in os.listdir(reports_dir) if f.endswith(".json")
        ]) if os.path.isdir(reports_dir) else 0,
    }

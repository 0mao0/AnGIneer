"""迁移审计：data/ops/kb_migration_audit.jsonl 单文件追加（设计 D11）。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docs_core.library_registry import resolve_data_root


def audit_path() -> Path:
    """审计 jsonl 路径：``<数据根>/ops/kb_migration_audit.jsonl``。

    延迟解析（2026-10-07 独立发版）：此前是模块级常量，``import docs_core`` 就会解析数据根——
    独立安装（wheel）里没有仓库树、数据根通常来自环境变量，import 期解析会让"还没配环境"
    直接变成 import 崩溃（发布后 PyPI 实装验收抓到）。改到真正读写审计时才解析。
    """
    return resolve_data_root() / "ops" / "kb_migration_audit.jsonl"


def write_audit(*, operator: str, action: str, params: Dict[str, Any],
                preview_digest: Optional[str] = None, verify_digest: Optional[str] = None,
                result: Optional[str] = None, error: Optional[str] = None) -> None:
    entry = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "operator": operator,
        "action": action,  # preview|submit|switch|rollback|cancel|resume|verify
        "params": params,
        "preview_digest": preview_digest,
        "verify_digest": verify_digest,
        "result": result,
        "error": error,
    }
    path = audit_path()
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_audit(offset: int = 0, limit: int = 100) -> Tuple[List[Dict[str, Any]], int]:
    """按写入时序返回（审计流水给人按 preview→submit→switch 顺读，任务抽屉按 task 过滤展示）。

    计划实现稿此处曾 reverse()（最新在前），与计划自带测试断言矛盾——测试为准（v3.1 施工勘误）。
    """
    path = audit_path()
    if not path.exists():
        return [], 0
    entries: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    total = len(entries)
    return entries[offset:offset + limit], total

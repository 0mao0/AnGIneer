"""运维观测落盘：按日 JSONL 追加，容器重建不丢（需求 §4 修正——验收观测不能只依赖 docker logs）。

形态：data/ops/<kind>-<YYYYMMDD>.jsonl，每行一个 JSON 对象（ts_iso 用 UTC，另有 ts_bj 北京墙钟便于人读）。
调用方仅限「一行 append」语义的打点（TTFT、分类耗时），不做聚合——聚合交给读侧脚本。

开关与健壮性：全程 best-effort，任何 IO 异常吞掉（观测失败绝不能影响主链路）；
``ANGINEER_OPS_DIR`` 覆盖目录；``ANGINEER_OPS_DISABLE=1`` 整体停用。
"""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_BJ_TZ = timezone(timedelta(hours=8))


def _repo_root() -> Path:
    """仓库根探测（同 services/shared/paths.py 的标记：同时含 services/ 与 apps/）。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "services").is_dir() and (parent / "apps").is_dir():
            return parent
    return Path.cwd()


def ops_dir() -> str:
    override = (os.getenv("ANGINEER_OPS_DIR", "") or "").strip()
    if override:
        return override
    return str(_repo_root() / "data" / "ops")


def ops_enabled() -> bool:
    return (os.getenv("ANGINEER_OPS_DISABLE", "") or "").strip() not in ("1", "true", "yes", "on")


def record_event(kind: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """追加一条观测到 data/ops/<kind>-<当日>.jsonl；失败静默（打点永不影响业务）。"""
    if not kind or not ops_enabled():
        return
    try:
        now = datetime.now(timezone.utc)
        day = now.astimezone(_BJ_TZ).strftime("%Y%m%d")
        line = json.dumps(
            {
                "ts_utc": now.isoformat(timespec="milliseconds"),
                "ts_bj": now.astimezone(_BJ_TZ).isoformat(timespec="seconds"),
                "kind": kind,
                **(payload or {}),
            },
            ensure_ascii=False,
        )
        directory = Path(ops_dir())
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{kind}-{day}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        logger.debug("ops record_event(%s) 落盘失败（忽略）", kind, exc_info=True)

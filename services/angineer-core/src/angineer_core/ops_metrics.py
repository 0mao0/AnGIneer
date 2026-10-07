"""运维观测落盘：按日 JSONL 追加，容器重建不丢（需求 §4 修正——验收观测不能只依赖 docker logs）。

形态：data/ops/<kind>-<YYYYMMDD>.jsonl，每行一个 JSON 对象（ts_iso 用 UTC，另有 ts_bj 北京墙钟便于人读）。
调用方仅限「一行 append」语义的打点（TTFT、分类耗时），不做聚合——聚合交给读侧脚本。

开关与健壮性：全程 best-effort，任何 IO 异常吞掉（观测失败绝不能影响主链路）；
``ANGINEER_OPS_DIR`` 覆盖目录；``ANGINEER_OPS_DISABLE=1`` 整体停用。

落盘目录口径（2026-10-07 独立发版自审）：主仓库树内默认 ``<仓库根>/data/ops``；
树外（第三方 pip 装到 site-packages）未显式配置 ``ANGINEER_OPS_DIR`` 时**不落盘**——
库不往宿主工作目录写文件，需要落盘必须显式给目录。
"""
import contextvars
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_BJ_TZ = timezone(timedelta(hours=8))

# 当前 run 的关联键：agent_loop 开跑时 set，本包内 record_event 自动附带——
# 让深层打点（如 agent_tools 的检索分段）无需层层透传 run_id；不跨包暴露。
_current_run_id: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("ops_current_run_id", default=None)


def set_run_id(run_id: Optional[str]) -> None:
    """绑定当前上下文的 run_id（agent_loop 开跑处调用），供 record_event 自动附带。"""
    _current_run_id.set(run_id)


def current_run_id() -> Optional[str]:
    return _current_run_id.get()


def _repo_root() -> Optional[Path]:
    """仓库根探测（同 services/shared/paths.py 的标记：同时含 services/ 与 apps/）。

    找不到标记说明代码不是从主仓库树里跑的（第三方 pip 安装、单包分发）：
    返回 None，由调用方按「不落盘」处理——**不回落当前工作目录**。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "services").is_dir() and (parent / "apps").is_dir():
            return parent
    return None


def ops_dir() -> str:
    """观测落盘目录；返回空字符串＝不落盘（不在主仓库树里且未显式配置）。"""
    override = (os.getenv("ANGINEER_OPS_DIR", "") or "").strip()
    if override:
        return override
    root = _repo_root()
    if root is None:
        return ""
    return str(root / "data" / "ops")


def ops_enabled() -> bool:
    return (os.getenv("ANGINEER_OPS_DISABLE", "") or "").strip() not in ("1", "true", "yes", "on")


def record_event(kind: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """追加一条观测到 data/ops/<kind>-<当日>.jsonl；失败静默（打点永不影响业务）。

    payload 未显式带 run_id 时自动附加上下文绑定的 run_id（见 set_run_id）；
    显式值优先，上下文无绑定则不落该键。

    没地方落（不在主仓库树里且没配 ``ANGINEER_OPS_DIR``）时静默跳过。"""
    if not kind or not ops_enabled():
        return
    directory = ops_dir()
    if not directory:
        return
    try:
        now = datetime.now(timezone.utc)
        day = now.astimezone(_BJ_TZ).strftime("%Y%m%d")
        fields = dict(payload or {})
        if fields.get("run_id") is None:
            ctx_run_id = _current_run_id.get()
            if ctx_run_id:
                fields["run_id"] = ctx_run_id
        line = json.dumps(
            {
                "ts_utc": now.isoformat(timespec="milliseconds"),
                "ts_bj": now.astimezone(_BJ_TZ).isoformat(timespec="seconds"),
                "kind": kind,
                **fields,
            },
            ensure_ascii=False,
        )
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{kind}-{day}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        logger.debug("ops record_event(%s) 落盘失败（忽略）", kind, exc_info=True)

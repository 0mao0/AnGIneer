"""游客设置（docs/design-guest-settings.md）：免登录访客的开放开关 / 轮数上限 / 可用知识库。

存储 data/platform/guest_settings.json（原子写，同 nightly_control.py 模式）；
优先级：文件 > env(ANGINEER_GUEST_ROUNDS) > 30；文件缺失 = 默认值（今天的行为）；
文件存在但读坏 → fail-closed（enabled=false + load_error 上报，后台展示、保存一次即恢复）。
每请求直读不缓存：docs-api 写 / aichat-api 读跨容器经 data/ 卷即时同步。
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from shared.paths import resolve_data_file

logger = logging.getLogger("shared.guest_settings")

SETTINGS_ENV = "GUEST_SETTINGS_FILE"
ENV_ROUNDS = "ANGINEER_GUEST_ROUNDS"
DEFAULT_ROUNDS = 30
ROUNDS_MIN, ROUNDS_MAX = 1, 1000
DEFAULT_LIBRARY_IDS = ["default"]


def settings_path() -> Path:
    return Path(resolve_data_file(SETTINGS_ENV, "platform/guest_settings.json"))


def _env_rounds() -> int:
    try:
        return max(ROUNDS_MIN, int(os.getenv(ENV_ROUNDS, str(DEFAULT_ROUNDS)) or DEFAULT_ROUNDS))
    except ValueError:
        return DEFAULT_ROUNDS


def normalize_guest_settings(raw: Any) -> Dict[str, Any]:
    """规范化三键（保存与读取共用）；结构/类型/范围非法即 ValueError（PUT 转 400）。"""
    if not isinstance(raw, dict):
        raise ValueError("guest_settings 顶层必须是 JSON 对象")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")
    rounds = raw.get("rounds", DEFAULT_ROUNDS)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not (ROUNDS_MIN <= rounds <= ROUNDS_MAX):
        raise ValueError(f"rounds 必须是 {ROUNDS_MIN}–{ROUNDS_MAX} 的整数")
    libs_raw = raw.get("library_ids", list(DEFAULT_LIBRARY_IDS))
    if not isinstance(libs_raw, list):
        raise ValueError("library_ids 必须是数组")
    libs = [str(x).strip() for x in libs_raw if str(x).strip()]
    if not libs:
        raise ValueError("library_ids 至少需要 1 个知识库")
    return {"enabled": enabled, "rounds": rounds, "library_ids": libs}


def _fail_closed_defaults(reason: str) -> Dict[str, Any]:
    logger.error("guest_settings 不可用，按 fail-closed 关闭游客: %s", reason)
    return {
        "enabled": False,
        "rounds": _env_rounds(),
        "library_ids": list(DEFAULT_LIBRARY_IDS),
        "load_error": reason,
    }


def load_guest_settings() -> Dict[str, Any]:
    """读取生效设置（含 load_error）。文件缺失 → 默认；读坏/内容非法 → fail-closed。"""
    path = settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "enabled": True,
            "rounds": _env_rounds(),
            "library_ids": list(DEFAULT_LIBRARY_IDS),
            "load_error": "",
        }
    except (OSError, ValueError) as exc:
        return _fail_closed_defaults(f"{type(exc).__name__}: {exc}")
    try:
        cfg = normalize_guest_settings(raw)
    except ValueError as exc:
        return _fail_closed_defaults(str(exc))
    cfg["load_error"] = ""
    return cfg


def save_guest_settings(cfg: Any) -> Dict[str, Any]:
    """规范化 + 原子写（同目录 .tmp + os.replace，同 nightly 模式）；返回落盘设置。"""
    normalized = normalize_guest_settings(cfg)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return {**normalized, "load_error": ""}


def guest_enabled() -> bool:
    return bool(load_guest_settings().get("enabled"))


def effective_rounds() -> int:
    return int(load_guest_settings().get("rounds") or DEFAULT_ROUNDS)


def guest_library_ids() -> List[str]:
    return list(load_guest_settings().get("library_ids") or DEFAULT_LIBRARY_IDS)

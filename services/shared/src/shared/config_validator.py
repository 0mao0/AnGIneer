"""*.env 与 *_CONFIGS 一致性校验：启动时检查配置漂移。

服务始终正常启动。校验失败时：
- stderr 打印 ERROR 详细信息（docker logs 可见）
- 发送企微 webhook 通知运维
- 内部状态可通过 get_config_errors() 查询
- health 端点返回 503 反映配置异常
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from shared.notify import send as _notify_send, split_webhooks as _split_webhooks

load_dotenv()

# 所有预期的 *_CONFIGS 键及其校验规则
CONFIGS_SCHEMA: Dict[str, Dict] = {
    "LLM_CONFIGS": {
        "required_fields": ["name"],
        "url_fields": ["base_url"],
        "optional": False,
        "desc": "LLM 模型列表（回答模型）",
    },
    "MINERU_CONFIGS": {
        "required_fields": ["name", "url", "api_key"],
        "url_fields": ["url"],
        "optional": False,
        "desc": "MinerU 解析端点列表",
    },
    "POPO_CONFIGS": {
        "required_fields": ["name", "url", "api_key", "model"],
        "url_fields": ["url"],
        "optional": False,
        "desc": "PoPo 推理端点列表",
    },
    "EMBEDDING_CONFIGS": {
        "required_fields": ["name", "model", "api_key", "api_url"],
        "url_fields": ["api_url"],
        "optional": True,
        "desc": "Embedding 端点列表（可回退 hash）",
    },
    "RERANKER_CONFIGS": {
        "required_fields": ["url"],
        "url_fields": ["url"],
        "optional": True,
        "desc": "Reranker 端点列表（可降级链）",
    },
}

_URL_RE = re.compile(r"^https?://")

# 模块级状态：校验结果，供其他模块查询
_CONFIG_ERRORS: List[str] = []
_CONFIG_WARNINGS: List[str] = []
_CONFIG_CHECKED: bool = False


def _env_file_path() -> Path:
    """定位 .env 文件路径（从当前工作目录往上找）。"""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".env").exists():
            return parent / ".env"
    return cwd / ".env"


def validate_env() -> Tuple[List[str], List[str]]:
    """校验 .env 中的 *_CONFIGS 是否合法。

    Returns:
        (errors, warnings): errors 为致命错误（非可选配置缺失/非法），
        warnings 为可选配置问题。
    """
    errors: List[str] = []
    warnings: List[str] = []

    env_file = _env_file_path()
    if not env_file.exists():
        # 配置真相源是进程环境：docker 部署由 compose env_file 注入，容器内本就没有
        # .env 文件。文件缺失不单独致命（旧逻辑在此早退，既在每次启动/部署误报
        # [MISSING] 轰炸运维群，又让真正的 *_CONFIGS 漂移在容器里永远查不到）；
        # 只有连一个 *_CONFIGS 都没有（真空配置）才判缺失。
        if not any((os.getenv(k) or "").strip() for k in CONFIGS_SCHEMA):
            errors.append(
                f"[MISSING] .env file not found and no *_CONFIGS set in environment: {env_file}"
            )
            return errors, warnings

    for key, schema in CONFIGS_SCHEMA.items():
        value = os.getenv(key, "").strip()

        if not value:
            if not schema["optional"]:
                errors.append(
                    f"配置漂移: {key} 未设置（{schema['desc']}，必填项）"
                )
            else:
                warnings.append(
                    f"配置漂移: {key} 未设置（{schema['desc']}，可选，回退兜底）"
                )
            continue

        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            errors.append(
                f"配置漂移: {key} JSON 解析失败: {e}（{schema['desc']}）"
            )
            continue

        if not isinstance(data, list):
            errors.append(
                f"配置漂移: {key} 应为 JSON 数组，实际为 {type(data).__name__}"
            )
            continue

        if not data:
            if not schema["optional"]:
                errors.append(
                    f"配置漂移: {key} 为空数组（{schema['desc']}，至少需要一个端点）"
                )
            continue

        for i, item in enumerate(data):
            if not isinstance(item, dict):
                errors.append(f"配置漂移: {key}[{i}] 应为对象")
                continue

            for field in schema["required_fields"]:
                val = item.get(field)
                if val is None or str(val).strip() == "":
                    errors.append(
                        f"配置漂移: {key}[{i}] 缺少必填字段 '{field}'"
                    )

            for field in schema["url_fields"]:
                if field in item and item[field]:
                    if not _URL_RE.match(str(item[field])):
                        errors.append(
                            f"配置漂移: {key}[{i}].{field} 不是有效 URL: {item[field]}"
                        )

    return errors, warnings


def _send_webhook_notification(errors: List[str], warnings: List[str]) -> None:
    """校验失败时发送企微 webhook 通知（系统维护群）。"""
    webhook = os.environ.get("WEBHOOK_SYSTEM", "").strip()
    if not webhook:
        print("[config-validator] WEBHOOK_SYSTEM 未配置，跳过通知")
        return

    lines = []
    if errors:
        lines.append("### [ERROR] AnGIneer 服务配置异常")
        for e in errors:
            lines.append(f"- {e}")
    if warnings:
        lines.append("### [WARNING] 配置漂移")
        for w in warnings:
            lines.append(f"- {w}")
    lines.append("---")
    lines.append(f"服务: {os.getenv('ANGINEER_SERVICE_NAME', 'docs-api/aichat-api')}")
    lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    text = "\n".join(lines)

    try:
        _notify_send(webhook, text, quiet=True)
        print(f"[config-validator] webhook 已通知 ({len(_split_webhooks(webhook))} 个目标)")
    except Exception as exc:
        print(f"[config-validator] webhook 推送失败: {exc}")


def ensure_env() -> None:
    """启动时校验配置一致性。

    校验失败时不退出进程，而是：
    1. 打印 ERROR 到 stderr（docker logs 可见）
    2. 发送企微 webhook 通知
    3. 存储错误状态供 health 端点和其他业务逻辑查询
    """
    global _CONFIG_ERRORS, _CONFIG_WARNINGS, _CONFIG_CHECKED

    errors, warnings = validate_env()
    _CONFIG_ERRORS = errors
    _CONFIG_WARNINGS = warnings
    _CONFIG_CHECKED = True

    for w in warnings:
        print(f"[config-validator] WARNING: {w}")

    if errors:
        for e in errors:
            print(f"[config-validator] ERROR: {e}", flush=True)
        print(
            f"[config-validator] 共 {len(errors)} 个配置错误，"
            f"服务仍启动但相关业务将不可用。请检查 .env。",
            flush=True,
        )
        _send_webhook_notification(errors, warnings)
    else:
        print(f"[config-validator] OK config validated ({len(CONFIGS_SCHEMA)} *_CONFIGS)")


def get_config_errors() -> List[str]:
    """返回最近一次校验的错误列表。无错误时返回空列表。"""
    return list(_CONFIG_ERRORS)


def get_config_warnings() -> List[str]:
    """返回最近一次校验的警告列表。"""
    return list(_CONFIG_WARNINGS)


def is_config_ok() -> bool:
    """配置校验是否通过（无错误）。"""
    return len(_CONFIG_ERRORS) == 0


def config_status_response() -> dict:
    """返回适合 JSON 响应的配置状态。"""
    return {
        "config_ok": is_config_ok(),
        "errors": _CONFIG_ERRORS,
        "warnings": _CONFIG_WARNINGS,
        "checked": _CONFIG_CHECKED,
    }


if __name__ == "__main__":
    ensure_env()

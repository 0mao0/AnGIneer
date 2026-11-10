"""解析面配置校验（shared.config_validator 的包内内联版）。

为什么内联（DredgeAI docs-api 进包需求 3.3-e）：`angineer-shared` 未上 PyPI，`[api]` extra
直接依赖会让 pip 安装必败（先例见 pyproject 内 popo-client 注释）。等价校验逻辑就地收进包，
并做两点裁剪：
- 去企微 webhook 通知（shared.notify 不在包依赖里），错误只落 stderr 日志；
- 档位按解析面实际消费裁剪：`MINERU_CONFIGS` 必填（raw_parse 硬阶段），
  `POPO_CONFIGS` / `EMBEDDING_CONFIGS` / `RERANKER_CONFIGS` 可选（软阶段/降级链），
  `LLM_CONFIGS` 不属于解析面（宿主 aichat 诉求），不校验。

语义与宿主一致：服务始终正常启动；失败时 health 端点 `status=degraded` + `config_errors`。
"""
import json
import os
import re
from typing import Dict, List, Tuple

# 解析面消费的 *_CONFIGS 键及校验规则（字段要求与 shared.config_validator 同口径）
CONFIGS_SCHEMA: Dict[str, Dict] = {
    "MINERU_CONFIGS": {
        "required_fields": ["name", "url", "api_key"],
        "url_fields": ["url"],
        "optional": False,
        "desc": "MinerU 解析端点列表",
    },
    "POPO_CONFIGS": {
        "required_fields": ["name", "url", "api_key", "model"],
        "url_fields": ["url"],
        "optional": True,
        "desc": "PoPo 视觉结构强化端点列表（软阶段，可缺省降级）",
    },
    "EMBEDDING_CONFIGS": {
        "required_fields": ["name", "model", "api_key", "api_url"],
        "url_fields": ["api_url"],
        "optional": True,
        "desc": "Embedding 端点列表（vectors 阶段消费，可回退 hash）",
    },
    "RERANKER_CONFIGS": {
        "required_fields": ["url"],
        "url_fields": ["url"],
        "optional": True,
        "desc": "Reranker 端点列表（检索面消费，解析面仅透传校验）",
    },
}

_URL_RE = re.compile(r"^https?://")

# 模块级状态：校验结果，供 /health 查询
_CONFIG_ERRORS: List[str] = []
_CONFIG_WARNINGS: List[str] = []
_CONFIG_CHECKED: bool = False


def validate_env() -> Tuple[List[str], List[str]]:
    """校验进程环境中的 *_CONFIGS 是否合法（与宿主同规则，缺 .env 不单独致命）。"""
    errors: List[str] = []
    warnings: List[str] = []

    # 配置真相源是进程环境（docker/compose 由 env_file 注入）。真空配置才判缺失。
    if not any((os.getenv(k) or "").strip() for k in CONFIGS_SCHEMA):
        errors.append(
            "[MISSING] no *_CONFIGS set in environment（解析面至少需要 MINERU_CONFIGS）"
        )
        return errors, warnings

    for key, schema in CONFIGS_SCHEMA.items():
        value = os.getenv(key, "").strip()

        if not value:
            if not schema["optional"]:
                errors.append(f"配置漂移: {key} 未设置（{schema['desc']}，必填项）")
            else:
                warnings.append(f"配置漂移: {key} 未设置（{schema['desc']}，可选，回退兜底）")
            continue

        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            errors.append(f"配置漂移: {key} JSON 解析失败: {e}（{schema['desc']}）")
            continue

        if not isinstance(data, list):
            errors.append(f"配置漂移: {key} 应为 JSON 数组，实际为 {type(data).__name__}")
            continue

        if not data:
            if not schema["optional"]:
                errors.append(f"配置漂移: {key} 为空数组（{schema['desc']}，至少需要一个端点）")
            continue

        for i, item in enumerate(data):
            if not isinstance(item, dict):
                errors.append(f"配置漂移: {key}[{i}] 应为对象")
                continue
            for field in schema["required_fields"]:
                val = item.get(field)
                if val is None or str(val).strip() == "":
                    errors.append(f"配置漂移: {key}[{i}] 缺少必填字段 '{field}'")
            for field in schema["url_fields"]:
                if field in item and item[field]:
                    if not _URL_RE.match(str(item[field])):
                        errors.append(
                            f"配置漂移: {key}[{i}].{field} 不是有效 URL: {item[field]}"
                        )

    return errors, warnings


def ensure_env() -> None:
    """启动时校验配置一致性（不退出进程，错误进 /health）。"""
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
            f"[config-validator] 共 {len(errors)} 个配置错误，服务仍启动但相关业务不可用。",
            flush=True,
        )
    else:
        print(f"[config-validator] OK config validated ({len(CONFIGS_SCHEMA)} *_CONFIGS)")


def is_config_ok() -> bool:
    return len(_CONFIG_ERRORS) == 0


def config_status_response() -> dict:
    """返回适合 /health 组装的状态 dict。"""
    return {
        "config_ok": is_config_ok(),
        "errors": list(_CONFIG_ERRORS),
        "warnings": list(_CONFIG_WARNINGS),
        "checked": _CONFIG_CHECKED,
    }

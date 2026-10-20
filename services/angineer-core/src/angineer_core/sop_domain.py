"""SOP 领域知识包（domain pack）加载。

领域知识（SOP 参数释义、工具输出别名、calculator 领域提示）一律住数据文件，
引擎代码保持零领域内容：不启用时按通用行为执行。宿主经环境变量
``ANGINEER_SOP_DOMAIN_PACK`` 显式启用，值为内置包名（如 ``harbor``）或
任意 JSON 文件路径；读取时机为调用期（惰性），不在 import 期产生副作用。

JSON 契约（字段均可缺省）::

    {
      "name": "harbor",
      "description": "海港/码头工程（JTS 规范族）参数释义与输出别名",
      "param_descriptions": {"H": "波高（m）..."},
      "output_aliases": {"dwl_basic": ["design_high_water_level", "..."]},
      "table_column_aliases": {"吨级": ["载重吨DWT(t)", "DWT", "船舶吨级"]},
      "calculator_hint": "For K1 (wave coefficient): ..."
    }

加载失败（内置名不存在/文件缺失/JSON 损坏）按空包降级并告警——领域包只是
路由与智能执行的提示辅助，不能因数据文件问题挡住 SOP 执行。
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from angineer_core.base_logger import get_logger

logger = get_logger(__name__)

DOMAIN_PACK_ENV = "ANGINEER_SOP_DOMAIN_PACK"

_BUILTIN_PACKS_DIR = "domain_packs"


@dataclass
class DomainHints:
    """领域提示与参数规则集合；各字段互相独立，宿主按需提供。"""

    param_descriptions: Dict[str, str] = field(default_factory=dict)
    output_aliases: Dict[str, List[str]] = field(default_factory=dict)
    # 表头别名：参数名 → 可匹配的表头片段（如 吨级 → 载重吨DWT(t)）；表引擎行过滤/取列消费。
    table_column_aliases: Dict[str, List[str]] = field(default_factory=dict)
    calculator_hint: str = ""
    # 参数规则段（domain_arg_rules 消费；2026-10-12 classifier 深层逻辑外置）
    arg_rules: Dict[str, Any] = field(default_factory=dict)
    arg_computes: List[Dict[str, Any]] = field(default_factory=list)
    arg_defaults: Dict[str, str] = field(default_factory=dict)
    ship_type_rules: List[Dict[str, Any]] = field(default_factory=list)
    stop_markers: List[str] = field(default_factory=list)
    clean_rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # 缺参引导（2026-10-13 业主定纪律）：参数名 → {recommend, unit, rationale, source}。
    # 缺参时只报缺 + 给推荐值供用户确认，系统绝不代填（如实报缺是产品红线）。
    param_recommendations: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(
            self.param_descriptions or self.output_aliases or self.table_column_aliases
            or self.calculator_hint
            or self.arg_rules or self.arg_computes or self.arg_defaults
            or self.ship_type_rules or self.stop_markers or self.clean_rules
            or self.param_recommendations
        )


EMPTY_HINTS = DomainHints()

_cache: Dict[str, DomainHints] = {}


def _read_builtin(name: str) -> str:
    from importlib.resources import files

    resource = files("angineer_core") / _BUILTIN_PACKS_DIR / f"{name}.json"
    return resource.read_text(encoding="utf-8")


def _parse_pack(text: str) -> DomainHints:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("domain pack 根节点必须为对象")
    params = data.get("param_descriptions")
    aliases = data.get("output_aliases")
    column_aliases = data.get("table_column_aliases")
    hint = data.get("calculator_hint")
    def _dict_of_dicts(raw: Any) -> Dict[str, Dict[str, Any]]:
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def _list_of_dicts(raw: Any) -> List[Dict[str, Any]]:
        return [v for v in raw if isinstance(v, dict)] if isinstance(raw, list) else []

    return DomainHints(
        param_descriptions={str(k): str(v) for k, v in params.items()} if isinstance(params, dict) else {},
        output_aliases={
            str(k): [str(a) for a in v] if isinstance(v, list) else [str(v)]
            for k, v in aliases.items()
        } if isinstance(aliases, dict) else {},
        table_column_aliases={
            str(k): [str(a) for a in v] if isinstance(v, list) else [str(v)]
            for k, v in column_aliases.items()
        } if isinstance(column_aliases, dict) else {},
        calculator_hint=str(hint) if hint else "",
        arg_rules=_dict_of_dicts(data.get("arg_rules")),
        arg_computes=_list_of_dicts(data.get("arg_computes")),
        arg_defaults={str(k): str(v) for k, v in (data.get("arg_defaults") or {}).items()} if isinstance(data.get("arg_defaults"), dict) else {},
        ship_type_rules=_list_of_dicts(data.get("ship_type_rules")),
        stop_markers=[str(m) for m in (data.get("stop_markers") or []) if m is not None] if isinstance(data.get("stop_markers"), list) else [],
        clean_rules=_dict_of_dicts(data.get("clean_rules")),
        param_recommendations=_dict_of_dicts(data.get("param_recommendations")),
    )


def load_domain_pack(ref: Optional[str]) -> DomainHints:
    """按内置包名或 JSON 文件路径加载领域包；空值/失败一律返回空包。"""
    if ref is None:
        return EMPTY_HINTS
    ref = str(ref).strip()
    if not ref:
        return EMPTY_HINTS
    if ref in _cache:
        return _cache[ref]

    hints = EMPTY_HINTS
    try:
        if ref.endswith(".json") or os.path.exists(ref):
            with open(ref, "r", encoding="utf-8") as f:
                hints = _parse_pack(f.read())
        else:
            hints = _parse_pack(_read_builtin(ref))
    except Exception as exc:  # noqa: BLE001
        logger.warning("领域知识包加载失败，按空包降级（ref=%s）: %s", ref, exc)

    _cache[ref] = hints
    return hints


def load_domain_pack_from_env(env_name: str = DOMAIN_PACK_ENV) -> DomainHints:
    """从环境变量解析领域包引用并加载；未设置返回空包。"""
    return load_domain_pack(os.getenv(env_name))

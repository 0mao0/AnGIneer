"""领域参数规则应用器：把「题面 → SOP 参数」的提取/清洗规则从数据包执行。

plan：classifier 深层港口逻辑外置（2026-10-12，plan-sop-l4-synth 排期项）。

引擎只提供匹配原语与计算算子，具体规则（K1/掩护/船型/Hnav…）全部住领域包 JSON：
- 规则段：``arg_rules``（required 相位=按 SOP required 提参；always 相位=无条件派生），
  ``arg_computes``（算子：subtract / numeric_flag / compass_angle / pick_ts_water /
  fallback_regexes），``arg_defaults``，``ship_type_rules``，``stop_markers``，``clean_rules``。
- 不启用领域包 → 全部规则为空 → 行为=通用（不注入任何领域参数，仅做通用清洗）。

提取语义（与原 classifier 逐字节对齐，对拍测试锁死）：
1. required 相位：对每个 required 参数，先 regexes 顺序取首个捕获，再 markers 自然语言兜底；
   命中则清洗后写入。
2. args 全键通用清洗一遍（含 base_args 传入值）。
3. 船型推断按 ship_type_rules 补 required 缺键；设计船型↔船型互填。
4. always 相位派生（只补未设置键）：keywords_value → regex_value → regexes；
   随后 computes（按声明顺序）→ defaults。
"""
import re
from typing import Any, Dict, List, Optional, Tuple


def _extract_by_patterns(query: str, patterns: List[str]) -> Optional[str]:
    """按候选正则顺序提取参数值（取首个命中模式的第一个非空捕获组）。"""
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            value = next((group for group in match.groups() if group), "")
            value = str(value or "").strip(" ，。；;:：")
            if value:
                return value
    return None


def _extract_after_markers(query: str, markers: List[str]) -> Optional[str]:
    """按「字段名 + 为/取/=」的自然语言表达提取后续片段。"""
    text = str(query or "")
    separators = ("为", "取", ":", "：", "=")
    stop_chars = "，。；;,\n"
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        tail = text[idx + len(marker):].lstrip()
        if not tail:
            continue
        if tail[0] in separators:
            tail = tail[1:].lstrip()
        collected = []
        for char in tail:
            if char in stop_chars:
                break
            collected.append(char)
        value = "".join(collected).strip(" ，。；;:：")
        if value:
            return value
    return None


def _trim_tail(value: str, stop_markers: List[str]) -> str:
    """裁剪抽取片段尾部的领域描述噪声（停用词表由领域包提供；空表则不裁剪）。"""
    cleaned = str(value or "").strip(" ，。；;:：")
    for marker in stop_markers or []:
        idx = cleaned.find(marker)
        if idx > 0:
            cleaned = cleaned[:idx].strip(" ，。；;:：")
    return cleaned


def infer_ship_types(query: str, ship_type_rules: List[Dict[str, Any]]) -> Dict[str, str]:
    """按领域包规则从题面货种/船型语义推断可复用的船型字段。"""
    text = str(query or "")
    for rule in ship_type_rules or []:
        keywords = rule.get("keywords") or []
        if any(str(kw).lower() in text.lower() for kw in keywords):
            out = {}
            if rule.get("船型"):
                out["船型"] = rule["船型"]
            if rule.get("设计船型"):
                out["设计船型"] = rule["设计船型"]
            if out:
                return out
    return {}


def clean_arg(param_name: str, value: Any, query: str, hints: Any) -> Any:
    """清洗抽取结果（通用尾裁 + 领域包 clean_rules 指定算子）。"""
    if value in (None, ""):
        return value
    stop_markers = getattr(hints, "stop_markers", None) or []
    clean_rules = getattr(hints, "clean_rules", None) or {}
    cleaned = _trim_tail(str(value), stop_markers)

    rule = clean_rules.get(param_name) or {}
    op = str(rule.get("op") or "")
    if op == "first_number":
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        return match.group(0) if match else cleaned
    if op == "remove_substrings":
        for sub in rule.get("substrings") or []:
            cleaned = cleaned.replace(str(sub), "")
        strip_chars = str(rule.get("strip") or "")
        if strip_chars:
            cleaned = cleaned.strip(strip_chars)
        return _trim_tail(cleaned, stop_markers)
    if op == "ship_type":
        if "码头" in cleaned and "船" not in cleaned:
            cleaned = cleaned.split("码头", 1)[0]
        cleaned = re.sub(r"^\d+(?:\.\d+)?\s*吨级", "", cleaned).strip()
        cleaned = cleaned.strip(" 的")
        inferred = infer_ship_types(query, getattr(hints, "ship_type_rules", None) or [])
        if not cleaned or cleaned in {"码头", "泊位"}:
            return inferred.get(param_name, cleaned)
        if "船" not in cleaned and inferred.get(param_name):
            return inferred[param_name]
        return cleaned
    # 通用：取前导数（"1.5m"→"1.5"）
    num_match = re.match(r'^([-+]?\d+(?:\.\d+)?)', cleaned)
    if num_match:
        return num_match.group(1)
    return cleaned


def _required_phase_extract(query: str, param_name: str, hints: Any) -> Optional[str]:
    """required 相位：regexes 优先，markers 兜底。"""
    rule = (getattr(hints, "arg_rules", None) or {}).get(param_name) or {}
    req = rule.get("required") or {}
    extracted = _extract_by_patterns(query, req.get("regexes") or [])
    if not extracted and req.get("markers"):
        extracted = _extract_after_markers(query, req["markers"])
    return extracted


def _always_phase_rules(query: str, hints: Any) -> Dict[str, Any]:
    """always 相位：按参数声明顺序做 keywords_value → regex_value → regexes。"""
    out: Dict[str, Any] = {}
    for param, rule in (getattr(hints, "arg_rules", None) or {}).items():
        phase = rule.get("always") or {}
        value = None
        for keyword, fixed in phase.get("keywords_value") or []:
            if str(keyword) in query:
                value = fixed
                break
        if value is None:
            for pattern, fixed in phase.get("regex_value") or []:
                if re.search(pattern, query):
                    value = fixed
                    break
        if value is None and phase.get("regexes"):
            value = _extract_by_patterns(query, phase["regexes"])
        if value not in (None, ""):
            out[param] = value
    return out


def _apply_computes(query: str, args: Dict[str, Any], hints: Any) -> None:
    """计算算子（按声明顺序执行，只补未设置键）。"""
    for spec in getattr(hints, "arg_computes", None) or []:
        param = str(spec.get("param") or "")
        if not param or args.get(param) not in (None, ""):
            continue
        op = str(spec.get("op") or "")
        try:
            if op == "numeric_flag":
                source = str(spec.get("source") or "")
                raw = args.get(source)
                if raw is None:
                    continue
                numeric = float(re.search(r"[-+]?\d+(?:\.\d+)?", str(raw)).group(0))
                args[param] = spec.get("true", "有") if numeric > float(spec.get("gt", 0)) else spec.get("false", "无")
            elif op == "subtract":
                minuend = _extract_by_patterns(query, spec.get("minuend_regexes") or [])
                subtrahend = _extract_by_patterns(query, spec.get("subtrahend_regexes") or [])
                if minuend and subtrahend:
                    a = float(re.search(r"[-+]?\d+(?:\.\d+)?", minuend).group(0))
                    b = float(re.search(r"[-+]?\d+(?:\.\d+)?", subtrahend).group(0))
                    args[param] = str(round(a - b, int(spec.get("round", 2))))
            elif op == "compass_angle":
                flow = re.search(spec.get("flow_regex", r"流向\s*([NSEW])\s*(\d+)\s*[°°]"), query)
                channel = re.search(spec.get("channel_regex", r"航道(?:轴线)?方位(?:为|是)?\s*(\d+)\s*[°°]\s*[~～]\s*(\d+)\s*[°°]"), query)
                if flow and channel:
                    flow_dir, flow_deg = flow.group(1), float(flow.group(2))
                    ch_mid = (float(channel.group(1)) + float(channel.group(2))) / 2.0
                    bearing = {"N": flow_deg, "S": 180.0 + flow_deg, "E": 90.0, "W": 270.0}.get(flow_dir, flow_deg)
                    angle = abs(ch_mid - bearing)
                    if angle > 180:
                        angle = 360 - angle
                    if angle > 90:
                        angle = 180 - angle
                    args[param] = str(round(angle, 1))
            elif op == "pick_ts_water":
                # 乘潮水位：优先「频率∈[90,95] 的水位对」，其次单一「乘潮水位 X」表述
                lo, hi = (spec.get("freq_range") or [90, 95])[:2]
                value = None
                for m in re.finditer(r"([\d.]+)\s*%\s*[^0-9]{0,16}?([\-\d.]+)\s*m", query):
                    freq = float(m.group(1))
                    if lo <= freq <= hi:
                        value = m.group(2)
                        break
                if value is None:
                    for m in re.finditer(r"([\-\d.]+)\s*m\s*[^0-9]{0,16}?([\d.]+)\s*%", query):
                        freq = float(m.group(2))
                        if lo <= freq <= hi:
                            value = m.group(1)
                            break
                if value is None:
                    value = _extract_by_patterns(query, spec.get("single_regexes") or [])
                if value:
                    args[param] = value
            elif op == "fallback_regexes":
                value = _extract_by_patterns(query, spec.get("regexes") or [])
                if value:
                    args[param] = value
        except Exception:  # noqa: BLE001
            continue


def derive_extra(query: str, hints: Any) -> Dict[str, Any]:
    """无条件派生（原 _derive_extra_args_from_query 的领域包版）。"""
    args: Dict[str, Any] = {}
    args.update(_always_phase_rules(query, hints))
    _apply_computes(query, args, hints)
    for param, value in (getattr(hints, "arg_defaults", None) or {}).items():
        if args.get(param) is None:
            args[param] = value
    return args


def supplement_args(
    query: str,
    required_params: List[str],
    base_args: Dict[str, Any],
    hints: Any,
) -> Dict[str, Any]:
    """required 相位提参 + 全键清洗 + 船型互填 + always 相位派生（流水线与原实现对齐）。"""
    args: Dict[str, Any] = dict(base_args or {})
    normalized_required = {str(item) for item in (required_params or [])}

    for param_name in normalized_required:
        if args.get(param_name) not in (None, ""):
            continue
        extracted = _required_phase_extract(query, param_name, hints)
        if extracted:
            args[param_name] = clean_arg(param_name, extracted, query, hints)

    for key, value in list(args.items()):
        args[key] = clean_arg(key, value, query, hints)

    inferred = infer_ship_types(query, getattr(hints, "ship_type_rules", None) or [])
    for key, value in inferred.items():
        if key in normalized_required and not args.get(key):
            args[key] = value
    if "设计船型" in normalized_required and not args.get("船型") and args.get("设计船型"):
        args["船型"] = args["设计船型"]
    if "船型" in normalized_required and not args.get("设计船型") and args.get("船型"):
        args["设计船型"] = args["船型"]

    args.update({
        k: v for k, v in derive_extra(query, hints).items()
        if v not in (None, "") and not args.get(k)
    })
    return args

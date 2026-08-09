"""SOP 结构校验器（P1.2）。

`validate_sop_data` / `validate_sop` 返回问题列表，空列表表示通过。
用于生成侧落盘前与 API 创建/更新/发布前的统一闸门。
"""
import re
from typing import Any, Dict, List

from angineer_core.base_contracts import SOP, Step
from sop_core.sop_loader import _is_known_tool


def _prepare_step_dict(step: Any) -> Dict[str, Any]:
    """把步骤字典归一化为 Step 可接受的结构，同时保留原始 tool 供校验。"""
    if not isinstance(step, dict):
        raise ValueError("步骤必须是对象")
    prepared = dict(step)
    execution = prepared.get("execution")
    if isinstance(execution, dict):
        prepared.setdefault("tool", execution.get("tool"))
        prepared.setdefault("inputs", execution.get("inputs"))
        prepared.setdefault("outputs", execution.get("outputs"))
    description = prepared.get("description")
    if isinstance(description, str):
        prepared["description"] = {"content": description, "citations": []}
    elif not isinstance(description, dict):
        prepared["description"] = {"content": "", "citations": []}
    return prepared


def build_sop_model(data: Dict[str, Any]) -> SOP:
    """将 SOP 字典（含 execution 嵌套格式）构建为 SOP 模型。"""
    steps_data = data.get("steps") or []
    steps = [Step(**_prepare_step_dict(s)) for s in steps_data]
    return SOP(
        id=data.get("id", ""),
        name_zh=data.get("name_zh"),
        name_en=data.get("name_en"),
        description=data.get("description"),
        description_zh=data.get("description_zh"),
        description_en=data.get("description_en"),
        steps=steps,
        blackboard=data.get("blackboard"),
        status=data.get("status", "draft"),
        confidence=data.get("confidence", 0.0),
        source=data.get("source") or {},
        review=data.get("review") or {},
        stats=data.get("stats") or {},
    )


def _collect_placeholder_refs(value: Any) -> List[str]:
    """递归收集字符串中的 ${var} 占位符引用。"""
    refs: List[str] = []
    if isinstance(value, str):
        refs.extend(re.findall(r"\$\{([^}]+)\}", value))
    elif isinstance(value, dict):
        for v in value.values():
            refs.extend(_collect_placeholder_refs(v))
    elif isinstance(value, list):
        for v in value:
            refs.extend(_collect_placeholder_refs(v))
    return refs


def _validate_step_graph(steps: List[Step], problems: List[str]) -> None:
    """规则 2：next_step_id 指向存在且沿链无环。"""
    by_id = {step.id: step for step in steps}

    def find_cycle(start_id: str) -> bool:
        seen = set()
        current = start_id
        while current:
            if current in seen:
                return True
            seen.add(current)
            step = by_id.get(current)
            if step is None:
                return False
            current = step.next_step_id
        return False

    for step in steps:
        nxt = step.next_step_id
        if nxt is None:
            continue
        if nxt not in by_id:
            problems.append(f"步骤 {step.id} 的 next_step_id 指向不存在的步骤: {nxt}")
        elif find_cycle(step.id):
            problems.append(f"步骤 {step.id} 的 next_step_id 链存在环")


def validate_sop(sop: SOP) -> List[str]:
    """校验 SOP 模型，返回问题列表（空 = 通过）。"""
    problems: List[str] = []
    steps = list(sop.steps or [])

    # 规则 1：steps 非空、id 全局唯一
    if not steps:
        problems.append("steps 不能为空")
    seen_ids = set()
    for step in steps:
        if step.id in seen_ids:
            problems.append(f"步骤 id 重复: {step.id}")
        seen_ids.add(step.id)

    # 规则 2：next_step_id 引用与环
    _validate_step_graph(steps, problems)

    # 规则 3：tool 必须可执行；auto 仅允许未分析步骤
    for step in steps:
        tool = str(step.tool or "").strip().lower()
        if tool == "auto":
            if str(step.analysis_status or "").lower() == "analyzed":
                problems.append(f"步骤 {step.id} 已分析(analyzed)但工具仍为 auto，请选择具体工具")
        elif tool and not _is_known_tool(tool):
            problems.append(f"步骤 {step.id} 的工具未注册: {step.tool}")

    # 规则 4：inputs/outputs 为 dict；blackboard.required 闭包检查
    produced = set()
    referenced = set()
    for step in steps:
        if not isinstance(step.inputs, dict):
            problems.append(f"步骤 {step.id} 的 inputs 必须为对象")
        else:
            referenced.update(_collect_placeholder_refs(step.inputs))
        if not isinstance(step.outputs, dict):
            problems.append(f"步骤 {step.id} 的 outputs 必须为对象")
        else:
            produced.update(step.outputs.keys())

    if sop.blackboard is not None:
        if not isinstance(sop.blackboard, dict):
            problems.append("blackboard 必须为对象")
        else:
            required = sop.blackboard.get("required")
            if required is not None and not isinstance(required, list):
                problems.append("blackboard.required 必须为数组")
            elif required:
                for key in required:
                    if not isinstance(key, str) or not key:
                        continue
                    if key == "user_query" or key in produced or key in referenced:
                        continue
                    problems.append(
                        f"blackboard.required 的键无法由初始上下文或任何步骤提供: {key}"
                    )

    # 规则 5：description.content 非空
    for step in steps:
        description = step.description
        content = getattr(description, "content", None)
        if content is None and isinstance(description, dict):
            content = description.get("content") or ""
        elif content is None:
            content = description or ""
        if not str(content).strip():
            problems.append(f"步骤 {step.id} 的 description.content 不能为空")

    return problems


def validate_sop_data(data: Dict[str, Any]) -> List[str]:
    """校验 SOP 字典（兼容 execution 嵌套格式），模型解析失败也作为问题返回。"""
    try:
        sop = build_sop_model(data)
    except Exception as exc:
        return [f"SOP 数据无法通过模型校验: {exc}"]
    return validate_sop(sop)

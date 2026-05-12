"""单题严格追踪工具，定位评测链路中的真实失败点。"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional


def _get_root_dir() -> str:
    """返回仓库根目录绝对路径。"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))


def _ensure_backend_paths() -> str:
    """为脚本/测试注入后端服务源码路径，保证跨服务导入可用。"""
    root_dir = _get_root_dir()
    service_src_dirs = [
        os.path.join(root_dir, "services", "angineer-core", "src"),
        os.path.join(root_dir, "services", "sop-core", "src"),
        os.path.join(root_dir, "services", "ai-inference", "src"),
        os.path.join(root_dir, "services", "docs-core", "src"),
        os.path.join(root_dir, "services", "engtools", "src"),
        os.path.join(root_dir, "services", "tree-core", "src"),
        os.path.join(root_dir, "services", "evals-core", "src"),
    ]
    for path in reversed(service_src_dirs):
        if path not in sys.path:
            sys.path.insert(0, path)
    return root_dir


def _register_runtime_tools() -> None:
    """导入工具模块，通过副作用完成 ToolRegistry 注册。"""
    import engtools.TableTool  # noqa: F401
    import engtools.CalculatorTool  # noqa: F401
    import engtools.UserInputTool  # noqa: F401
    import engtools.CommonTool  # noqa: F401
    import engtools.ConditionalTool  # noqa: F401
    import engtools.KnowledgeTool  # noqa: F401


def _to_json_safe(data: Any) -> Any:
    """把任意对象转成可 JSON 序列化的数据。"""
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def _build_answer_check(answer: str, answer_gold: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """按评测题中的 correctness_checks 规则做轻量答案校验。"""
    extracted_option = _extract_explicit_option(answer)
    if not answer_gold:
        return {
            "available": False,
            "passed": None,
            "checks": [],
            "extracted_option": extracted_option,
        }

    checks_result: List[Dict[str, Any]] = []
    overall_passed: Optional[bool] = True
    for check in answer_gold.get("correctness_checks") or []:
        check_type = str(check.get("type") or "")
        if check_type == "contains_any":
            keywords = [str(keyword) for keyword in (check.get("keywords") or []) if str(keyword).strip()]
            matched_keywords = [keyword for keyword in keywords if keyword in answer]
            passed = bool(matched_keywords)
            checks_result.append({
                "type": check_type,
                "passed": passed,
                "matched_keywords": matched_keywords,
                "expected_keywords": keywords,
            })
            overall_passed = bool(overall_passed and passed)
            continue

        checks_result.append({
            "type": check_type or "unknown",
            "passed": None,
            "detail": "未实现的检查类型，仅保留原始信息。",
            "raw": check,
        })
        overall_passed = None if overall_passed else overall_passed

    return {
        "available": True,
        "passed": overall_passed,
        "gold_answer": answer_gold.get("gold_answer"),
        "semantic_threshold": answer_gold.get("semantic_threshold"),
        "checks": checks_result,
        "extracted_option": extracted_option,
    }


def _extract_explicit_option(answer: str) -> Optional[str]:
    """从长答案中提取显式声明的最终选项。"""
    patterns = [
        r"最终答案[是为：:\s]*[\*\(（\s]*([A-D])",
        r"正确答案[是为：:\s]*[\*\(（\s]*([A-D])",
        r"答案[是为：:\s]*[\*\(（\s]*([A-D])",
        r"故选[：:\s]*[\*\(（\s]*([A-D])",
        r"对应选项[：:\s]*[\*\(（\s]*([A-D])",
        r"选项[：:\s]*[\*\(（\s]*([A-D])",
    ]
    for pattern in patterns:
        match = re.search(pattern, answer, re.IGNORECASE)
        if match:
            return str(match.group(1)).upper()
    return None


def _collect_step_findings(step_trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """扫描 SOP 步骤追踪，提取工具契约错误和隐性失败。"""
    step_errors: List[Dict[str, Any]] = []
    contract_mismatch_steps: List[str] = []
    hidden_error_steps: List[str] = []

    for step in step_trace:
        outputs = step.get("outputs") or {}
        inputs = step.get("inputs") or {}
        error_message = ""
        if isinstance(outputs, dict):
            error_message = str(outputs.get("error") or "")

        if error_message:
            step_errors.append({
                "step_id": step.get("step_id"),
                "tool": step.get("tool"),
                "error": error_message,
            })

        if (
            step.get("tool") == "calculator"
            and isinstance(inputs, dict)
            and "expressions" in inputs
            and error_message == "表达式不能为空"
        ):
            contract_mismatch_steps.append(str(step.get("step_id") or ""))

        if error_message and str(step.get("status") or "") == "success":
            hidden_error_steps.append(str(step.get("step_id") or ""))

    return {
        "step_errors": step_errors,
        "contract_mismatch_steps": [step_id for step_id in contract_mismatch_steps if step_id],
        "hidden_error_steps": [step_id for step_id in hidden_error_steps if step_id],
    }


def _build_issue_list(
    question: Dict[str, Any],
    intent_payload: Dict[str, Any],
    route_payload: Dict[str, Any],
    dispatch_payload: Dict[str, Any],
    isolated_payload: Dict[str, Any],
    answer_check: Dict[str, Any],
    sop_catalog: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """根据追踪结果生成诊断问题列表。"""
    issues: List[Dict[str, Any]] = []

    expected_intent = str(question.get("intent_level") or "")
    actual_intent = str(intent_payload.get("intent_level") or "")
    if expected_intent and actual_intent and expected_intent != actual_intent:
        issues.append({
            "code": "intent_level_mismatch",
            "message": f"题目标注为 {expected_intent}，实际识别为 {actual_intent}。",
        })

    if str(intent_payload.get("service_mode") or "") != "standard_sop":
        issues.append({
            "code": "service_mode_not_standard_sop",
            "message": f"当前 service_mode 为 {intent_payload.get('service_mode')}，未走标准 SOP 路径。",
        })

    matched_sop_id = str(route_payload.get("matched_sop_id") or "")
    if not matched_sop_id:
        issues.append({
            "code": "route_no_match",
            "message": "SOP 路由没有命中候选结果。",
        })

    if dispatch_payload.get("fallback_used"):
        issues.append({
            "code": "dispatch_fallback_used",
            "message": "Dispatcher 在执行中发生回退，没有稳定停留在 SOP 主链。",
        })

    step_findings = isolated_payload.get("step_findings") or {}
    if step_findings.get("step_errors"):
        issues.append({
            "code": "sop_step_error",
            "message": "SOP 执行步骤中存在显式错误输出。",
            "steps": step_findings.get("step_errors"),
        })

    if step_findings.get("contract_mismatch_steps"):
        issues.append({
            "code": "calculator_input_contract_mismatch",
            "message": "LLM 生成了 calculator 的 expressions 列表输入，但 CalculatorTool 只接受 expression 单字符串。",
            "steps": step_findings.get("contract_mismatch_steps"),
        })

    if step_findings.get("hidden_error_steps"):
        issues.append({
            "code": "step_error_hidden_by_success_status",
            "message": "步骤输出已包含 error，但 trace/status 仍被记录为 success，失败未被及时升级。",
            "steps": step_findings.get("hidden_error_steps"),
        })

    if answer_check.get("available") and answer_check.get("passed") is False:
        issues.append({
            "code": "answer_gold_mismatch",
            "message": "最终答案未通过题目 gold_answer 的关键字校验，存在结果错误或幻觉风险。",
            "check": answer_check,
        })

    extracted_option = answer_check.get("extracted_option")
    gold_option = str(answer_check.get("gold_answer") or "").strip().upper()
    if extracted_option and gold_option and extracted_option != gold_option:
        issues.append({
            "code": "explicit_final_option_mismatch",
            "message": f"答案中显式给出的最终选项为 {extracted_option}，但 gold_answer 为 {gold_option}。",
            "check": answer_check,
        })

    unloaded_sops = sop_catalog.get("unloaded_sop_ids") or []
    if unloaded_sops:
        issues.append({
            "code": "sop_catalog_parse_gap",
            "message": "SOP 目录中存在无法通过当前 Step 契约加载的 JSON，候选池不是完整状态。",
            "count": len(unloaded_sops),
            "sop_ids": unloaded_sops,
        })

    return issues


def _build_summary(issues: List[Dict[str, Any]], route_payload: Dict[str, Any]) -> str:
    """根据问题列表生成单句诊断结论。"""
    issue_codes = {issue["code"] for issue in issues}
    if "calculator_input_contract_mismatch" in issue_codes:
        return (
            "当前样例已正确进入 L3 + SOP 主链，但 analyzed step 生成的 calculator 输入契约不匹配，"
            "导致关键计算步骤输出 error 后仍继续执行，最终答案退化为 LLM 推断。"
        )
    if "route_no_match" in issue_codes:
        return "当前样例没有稳定命中 SOP，优先排查 SOP 召回、精排和参数抽取。"
    matched_sop_id = str(route_payload.get("matched_sop_id") or "")
    if matched_sop_id:
        return f"当前样例已命中 SOP `{matched_sop_id}`，链路结构完整，可继续细看步骤级计算正确性。"
    return "当前样例诊断已完成，但未形成明确主结论，请结合详细 trace 继续分析。"


def run_eval_case_trace(
    dataset_id: str,
    question_id: str,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Dict[str, Any]:
    """运行单题严格追踪，输出从取题到最终回答的完整诊断结果。"""
    root_dir = _ensure_backend_paths()
    _register_runtime_tools()

    from evals_core.storage import result_store
    from sop_core.sop_loader import SopLoader
    from angineer_core.classifier import IntentClassifier
    from angineer_core.dispatcher import Dispatcher

    result_store.init_db()
    question = result_store.get_question(dataset_id, question_id)
    if not question:
        raise ValueError(f"题目不存在: dataset_id={dataset_id}, question_id={question_id}")

    sop_base_dir = os.path.join(root_dir, "data", "sops")
    sop_json_dir = os.path.join(sop_base_dir, "json")
    sop_loader = SopLoader(sop_base_dir)
    sops = sop_loader.load_all()
    loaded_sop_ids = [sop.id for sop in sops]
    all_sop_json_ids = []
    if os.path.isdir(sop_json_dir):
        all_sop_json_ids = sorted(
            os.path.splitext(file_name)[0]
            for file_name in os.listdir(sop_json_dir)
            if file_name.endswith(".json")
        )
    unloaded_sop_ids = [sop_id for sop_id in all_sop_json_ids if sop_id not in loaded_sop_ids]

    classifier = IntentClassifier(sops)
    intent_result = classifier.classify_intent(
        question["question"], config_name=config_name, mode=mode
    )
    route_result = classifier.route(
        question["question"], config_name=config_name, mode=mode
    )

    matched_sop = route_result.sop
    matched_sop_id = matched_sop.id if matched_sop else None
    analyzed_sop = None
    isolated_payload: Dict[str, Any] = {
        "matched_sop_id": matched_sop_id,
        "required_args": [],
        "missing_required_args": [],
        "initial_context": {},
        "final_context": {},
        "history": [],
        "trace": [],
        "step_findings": {
            "step_errors": [],
            "contract_mismatch_steps": [],
            "hidden_error_steps": [],
        },
    }

    if matched_sop:
        analyzed_sop = sop_loader.analyze_sop(matched_sop.id, prefer_llm=False)
        required_args = list(((analyzed_sop.blackboard or {}).get("required") or []))
        initial_context = {"user_query": question["question"]}
        initial_context.update(route_result.args or {})
        isolated_dispatcher = Dispatcher(config_name=config_name, mode=mode)
        final_context = isolated_dispatcher.run_sop(analyzed_sop, initial_context)
        isolated_trace = Dispatcher._build_sop_trace(isolated_dispatcher, analyzed_sop)

        isolated_payload = {
            "matched_sop_id": matched_sop.id,
            "required_args": required_args,
            "missing_required_args": [
                key for key in required_args if key not in (route_result.args or {})
            ],
            "initial_context": _to_json_safe(initial_context),
            "final_context": _to_json_safe(final_context),
            "history": _to_json_safe([
                record.model_dump(mode="json")
                for record in isolated_dispatcher.memory.history
            ]),
            "trace": _to_json_safe(isolated_trace),
            "step_findings": _collect_step_findings(isolated_trace),
        }

    dispatch_result = Dispatcher(config_name=config_name, mode=mode).dispatch(
        query=question["question"],
        library_id=question.get("library_id", "default"),
        doc_ids=question.get("doc_ids") or [],
        sop_loader=sop_loader,
    )
    dispatch_payload = {
        "intent": _to_json_safe(dispatch_result.get("intent") or {}),
        "answer": str(dispatch_result.get("answer") or ""),
        "fallback_used": bool(dispatch_result.get("fallback_used")),
        "strategy": str(dispatch_result.get("strategy") or ""),
        "stage_timings": _to_json_safe(dispatch_result.get("stage_timings") or {}),
        "sop_trace": _to_json_safe(dispatch_result.get("sop_trace") or []),
        "citations": _to_json_safe(dispatch_result.get("citations") or []),
        "retrieved_items": _to_json_safe(dispatch_result.get("retrieved_items") or []),
    }

    answer_check = _build_answer_check(
        dispatch_payload["answer"], question.get("answer_gold")
    )
    route_payload = {
        "matched_sop_id": matched_sop_id,
        "confidence": route_result.confidence,
        "reason": route_result.reason,
        "args": _to_json_safe(route_result.args or {}),
        "candidates": _to_json_safe(route_result.candidates or []),
    }
    intent_payload = _to_json_safe(intent_result.model_dump(mode="json"))
    sop_catalog = {
        "json_sop_count": len(all_sop_json_ids),
        "loaded_sop_count": len(loaded_sop_ids),
        "unloaded_sop_ids": unloaded_sop_ids,
    }

    issues = _build_issue_list(
        question=question,
        intent_payload=intent_payload,
        route_payload=route_payload,
        dispatch_payload=dispatch_payload,
        isolated_payload=isolated_payload,
        answer_check=answer_check,
        sop_catalog=sop_catalog,
    )

    return {
        "case": {
            "dataset_id": dataset_id,
            "question_id": question_id,
            "question": question["question"],
            "task_type": question.get("task_type"),
            "expected_intent_level": question.get("intent_level"),
            "library_id": question.get("library_id"),
            "doc_ids": question.get("doc_ids") or [],
            "answer_gold": _to_json_safe(question.get("answer_gold")),
            "sop_gold": _to_json_safe(question.get("sop_gold")),
        },
        "sop_catalog": sop_catalog,
        "classifier": {
            "intent": intent_payload,
            "route": route_payload,
        },
        "isolated_sop_run": isolated_payload,
        "dispatch": dispatch_payload,
        "answer_check": answer_check,
        "issues": issues,
        "summary": _build_summary(issues, route_payload),
    }


def write_case_trace_report(trace_payload: Dict[str, Any], output_path: str) -> str:
    """把诊断结果写入 JSON 文件，便于人工审阅和前端复用。"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file_handle:
        json.dump(trace_payload, file_handle, ensure_ascii=False, indent=2)
    return output_path

"""评测题库数据加载模块。"""
import json
from pathlib import Path
from typing import Any, Dict, List


# 解析 docs-core 评测样本目录。
def resolve_eval_data_dir() -> Path:
    current_file = Path(__file__).resolve()
    return current_file.parents[5] / "data" / "evals" / "datasets"


# 返回目录下全部单文件题库，按文件名稳定排序。
def list_eval_bundle_files(base_dir: Path) -> List[Path]:
    return sorted(
        file_path
        for file_path in base_dir.glob("*.json")
        if file_path.is_file()
    )


# 返回空的统一题库视图，便于按题库合并。
def create_empty_eval_dataset() -> Dict[str, Any]:
    return {
        "datasets": [],
        "questions": [],
        "retrieval": [],
        "answers": [],
        "sql": [],
    }


# 校验题库元信息，确保后续可稳定展示与合并。
def validate_dataset_meta(bundle_path: Path, dataset_meta: Dict[str, Any]) -> Dict[str, Any]:
    dataset_id = str(dataset_meta.get("dataset_id") or bundle_path.stem).strip()
    title = str(dataset_meta.get("title") or bundle_path.stem).strip()
    schema_version = str(dataset_meta.get("schema_version") or "eval.bundle.v1").strip()
    if not dataset_id:
        raise ValueError(f"题库缺少 dataset_id: {bundle_path}")
    if not title:
        raise ValueError(f"题库缺少 title: {bundle_path}")
    return {
        **dataset_meta,
        "dataset_id": dataset_id,
        "title": title,
        "schema_version": schema_version,
    }


# 读取单个题库文件的原始 json 对象。
def load_eval_bundle_payload(bundle_path: Path) -> Dict[str, Any]:
    with open(bundle_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"题库根节点必须是对象: {bundle_path}")
    return payload


# 校验单题最小必填字段，避免题库静默混入非法数据。
def validate_eval_item(bundle_path: Path, item: Dict[str, Any]) -> Dict[str, Any]:
    question_id = str(item.get("question_id") or "").strip()
    question = str(item.get("question") or "").strip()
    library_id = str(item.get("library_id") or "").strip()
    if not question_id:
        raise ValueError(f"题库题目缺少 question_id: {bundle_path}")
    if not question:
        raise ValueError(f"题库题目缺少 question: {bundle_path}#{question_id}")
    if not library_id:
        raise ValueError(f"题库题目缺少 library_id: {bundle_path}#{question_id}")
    return item


# 统计题库题目数量，便于前端展示。
def summarize_dataset_items(dataset_meta: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    question_count = 0
    sql_question_count = 0
    visible_question_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "").strip()
        if not question_id:
            continue
        question_count += 1
        task_type = str(item.get("task_type") or "").strip()
        if task_type == "analytic_sql":
            sql_question_count += 1
        else:
            visible_question_count += 1
    return {
        **dataset_meta,
        "question_count": question_count,
        "visible_question_count": visible_question_count,
        "sql_question_count": sql_question_count,
    }


# 把单个题目条目拆成 question / retrieval / answer / sql 四类视图。
def normalize_eval_item(
    item: Dict[str, Any],
    dataset_meta: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    question_id = str(item.get("question_id") or "").strip()
    if not question_id:
        return {}
    question = {
        key: value
        for key, value in item.items()
        if key not in {"retrieval", "answer", "sql"}
    }
    question["dataset_id"] = str(dataset_meta.get("dataset_id") or "")
    question["dataset_title"] = str(dataset_meta.get("title") or "")

    retrieval = dict(item.get("retrieval") or {})
    retrieval["question_id"] = question_id
    answer = dict(item.get("answer") or {})
    answer["question_id"] = question_id
    sql = dict(item.get("sql") or {})
    sql["question_id"] = question_id
    return {
        "question": question,
        "retrieval": retrieval,
        "answer": answer,
        "sql": sql,
    }


# 读取单个 json 题库文件并拆成统一数据结构。
def load_eval_bundle(bundle_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    payload = load_eval_bundle_payload(bundle_path)
    dataset_meta = validate_dataset_meta(bundle_path, dict(payload.get("dataset") or {}))
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise ValueError(f"题库 items 必须是数组: {bundle_path}")
    normalized = {
        "datasets": [summarize_dataset_items(dataset_meta, items)],
        "questions": [],
        "retrieval": [],
        "answers": [],
        "sql": [],
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        validated_item = validate_eval_item(bundle_path, item)
        item_views = normalize_eval_item(validated_item, dataset_meta)
        if not item_views:
            continue
        normalized["questions"].append(item_views["question"])
        if any(key != "question_id" for key in item_views["retrieval"].keys()):
            normalized["retrieval"].append(item_views["retrieval"])
        if any(key != "question_id" for key in item_views["answer"].keys()):
            normalized["answers"].append(item_views["answer"])
        if any(key != "question_id" for key in item_views["sql"].keys()):
            normalized["sql"].append(item_views["sql"])
    return normalized


# 列出当前目录下所有题库元信息。
def list_eval_datasets(base_dir: Path | None = None) -> List[Dict[str, Any]]:
    resolved_base_dir = base_dir or resolve_eval_data_dir()
    dataset_metas: List[Dict[str, Any]] = []
    for bundle_file in list_eval_bundle_files(resolved_base_dir):
        payload = load_eval_bundle_payload(bundle_file)
        dataset_meta = validate_dataset_meta(bundle_file, dict(payload.get("dataset") or {}))
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise ValueError(f"题库 items 必须是数组: {bundle_file}")
        dataset_metas.append(summarize_dataset_items(dataset_meta, items))
    return dataset_metas


# 读取当前目录下单个或多个题库，并合并成统一题库视图。
def load_eval_dataset(base_dir: Path | None = None, dataset_id: str | None = None) -> Dict[str, List[Dict[str, Any]]]:
    resolved_base_dir = base_dir or resolve_eval_data_dir()
    bundle_files = list_eval_bundle_files(resolved_base_dir)
    if not bundle_files:
        raise FileNotFoundError(f"未找到评测题库 json 文件: {resolved_base_dir}")
    merged = create_empty_eval_dataset()
    target_dataset_id = str(dataset_id or "").strip()
    matched_dataset_ids: List[str] = []
    for bundle_file in bundle_files:
        bundle = load_eval_bundle(bundle_file)
        bundle_dataset_meta = list(bundle.get("datasets") or [])
        bundle_dataset_id = str((bundle_dataset_meta[0] or {}).get("dataset_id") or "").strip() if bundle_dataset_meta else ""
        if target_dataset_id and bundle_dataset_id != target_dataset_id:
            continue
        if bundle_dataset_id:
            matched_dataset_ids.append(bundle_dataset_id)
        for key in merged:
            merged[key].extend(bundle[key])
    if target_dataset_id and not matched_dataset_ids:
        raise FileNotFoundError(f"未找到指定评测题库: {target_dataset_id}")
    return merged


# 返回当前评测题库中的问题列表。
def load_eval_questions(base_dir: Path | None = None, dataset_id: str | None = None) -> List[Dict[str, Any]]:
    return load_eval_dataset(base_dir, dataset_id=dataset_id).get("questions", [])


# 返回当前评测题库中的检索 gold 列表。
def load_eval_retrieval_rows(base_dir: Path | None = None, dataset_id: str | None = None) -> List[Dict[str, Any]]:
    return load_eval_dataset(base_dir, dataset_id=dataset_id).get("retrieval", [])


# 返回当前评测题库中的回答 gold 列表。
def load_eval_answer_rows(base_dir: Path | None = None, dataset_id: str | None = None) -> List[Dict[str, Any]]:
    return load_eval_dataset(base_dir, dataset_id=dataset_id).get("answers", [])


# 返回当前评测题库中的 SQL gold 列表。
def load_eval_sql_rows(base_dir: Path | None = None, dataset_id: str | None = None) -> List[Dict[str, Any]]:
    return load_eval_dataset(base_dir, dataset_id=dataset_id).get("sql", [])


__all__ = [
    "list_eval_datasets",
    "load_eval_answer_rows",
    "load_eval_bundle",
    "load_eval_dataset",
    "load_eval_questions",
    "load_eval_retrieval_rows",
    "load_eval_sql_rows",
    "resolve_eval_data_dir",
]

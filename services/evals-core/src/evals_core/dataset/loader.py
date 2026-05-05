"""JSON 题集加载与校验。"""
import json
from pathlib import Path
from typing import Any, Dict, List

from evals_core.dataset.schema import EvalBundleV2, EvalQuestionItem

TASK_TYPE_TO_INTENT_LEVEL = {
    "definition": "L1",
    "content_qa": "L1",
    "locate": "L1",
    "locate_qa": "L1",
    "table_explain": "L2",
    "table_qa": "L2",
    "table_lookup": "L2",
    "schema_qa": "L2",
    "analytic_sql": "L3",
    "sql": "L3",
    "exam_case": "L4",
    "mixed": "L4",
    "auto": "L1",
}


def _migrate_v1_to_v2(payload: Dict[str, Any]) -> Dict[str, Any]:
    """将 eval.bundle.v1 格式迁移为 v2。"""
    dataset = payload.get("dataset", {})
    dataset["schema_version"] = "eval.bundle.v2"
    if "category" not in dataset:
        dataset["category"] = "knowledge"

    migrated_items = []
    for item in payload.get("items", []):
        task_type = item.get("task_type", "definition")
        if "intent_level" not in item:
            item["intent_level"] = TASK_TYPE_TO_INTENT_LEVEL.get(task_type, "L1")
        if "doc_ids" not in item:
            doc_ids = []
            for tag in item.get("tags", []):
                if tag.startswith("doc-"):
                    doc_ids.append(tag)
            item["doc_ids"] = doc_ids

        retrieval = item.get("retrieval")
        if retrieval and "gold_doc_ids" not in retrieval:
            retrieval["gold_doc_ids"] = retrieval.pop("gold_table_ids", [])

        answer = item.get("answer")
        if answer:
            answer.pop("allow_abstractive", None)

        item.pop("expected_route", None)
        item.pop("thought_process", None)
        item.pop("year", None)
        item.pop("exam_name", None)
        item.pop("exam_type", None)
        item.pop("question_no", None)
        item.pop("source_file", None)

        migrated_items.append(item)

    payload["dataset"] = dataset
    payload["items"] = migrated_items
    return payload


def load_bundle_from_file(file_path: str) -> EvalBundleV2:
    """从 JSON 文件加载题集并校验。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"题集文件不存在: {file_path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return load_bundle_from_dict(payload)


def load_bundle_from_dict(payload: Dict[str, Any]) -> EvalBundleV2:
    """从字典加载题集并校验，自动处理 v1→v2 迁移。"""
    schema_version = payload.get("dataset", {}).get("schema_version", "")
    if schema_version == "eval.bundle.v1":
        payload = _migrate_v1_to_v2(payload)
    return EvalBundleV2.model_validate(payload)


def list_bundle_files(directory: str) -> List[str]:
    """列出目录下所有 JSON 题集文件。"""
    base_dir = Path(directory)
    if not base_dir.exists():
        return []
    return sorted(
        str(file_path)
        for file_path in base_dir.glob("*.json")
        if file_path.is_file()
    )


def export_bundle_to_dict(bundle: EvalBundleV2) -> Dict[str, Any]:
    """将题集导出为规范 JSON 字典。"""
    return bundle.model_dump(exclude_none=True)

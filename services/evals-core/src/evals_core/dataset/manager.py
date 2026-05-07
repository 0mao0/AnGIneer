"""题集 CRUD 管理器。"""
import json
import os
from typing import Any, Dict, List, Optional

from evals_core.dataset.loader import export_bundle_to_dict, load_bundle_from_dict
from evals_core.dataset.schema import EvalBundleV2
from evals_core.storage import result_store

_DATASETS_DIR = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../..")),
    "data", "evals", "datasets",
)


def create_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
    """创建空测试集。"""
    return result_store.insert_dataset(data)


def import_bundle(payload: Dict[str, Any], source_file: str = "") -> Dict[str, Any]:
    """导入 JSON 题集到数据库，并保存原始 JSON 到 data/evals/datasets/。"""
    bundle = load_bundle_from_dict(payload)
    dataset_meta = bundle.dataset
    dataset_data = {
        "dataset_id": dataset_meta.dataset_id,
        "title": dataset_meta.title,
        "category": dataset_meta.category,
        "description": dataset_meta.description,
        "schema_version": dataset_meta.schema_version,
        "version": dataset_meta.version,
        "library_id": dataset_meta.library_id,
        "question_count": len(bundle.items),
        "source_file": source_file,
    }
    result_store.insert_dataset(dataset_data)
    for index, item in enumerate(bundle.items):
        question_data = _item_to_question_row(item, dataset_meta.dataset_id, index)
        result_store.insert_question(question_data)
    result_store.update_dataset_question_count(dataset_meta.dataset_id, len(bundle.items))
    os.makedirs(_DATASETS_DIR, exist_ok=True)
    json_path = os.path.join(_DATASETS_DIR, f"{dataset_meta.dataset_id}.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return result_store.get_dataset(dataset_meta.dataset_id)


def get_dataset(dataset_id: str) -> Optional[Dict[str, Any]]:
    """获取测试集详情。"""
    return result_store.get_dataset(dataset_id)


def list_datasets() -> List[Dict[str, Any]]:
    """列出所有测试集。"""
    return result_store.list_datasets()


def delete_dataset(dataset_id: str) -> bool:
    """删除测试集。"""
    return result_store.delete_dataset(dataset_id)


def update_dataset(dataset_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新测试集元信息（如标题）。"""
    return result_store.update_dataset(dataset_id, updates)


def add_question(dataset_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """向测试集添加单题。"""
    question_data = {
        "question_id": data["question_id"],
        "dataset_id": dataset_id,
        "question": data.get("question", ""),
        "task_type": data.get("task_type", "definition"),
        "intent_level": data.get("intent_level", "L1"),
        "difficulty": data.get("difficulty", "easy"),
        "tags": data.get("tags", []),
        "library_id": data.get("library_id", "default"),
        "doc_ids": data.get("doc_ids", []),
        "retrieval_gold": data.get("retrieval"),
        "answer_gold": data.get("answer"),
        "sql_gold": data.get("sql"),
        "sop_gold": data.get("sop"),
    }
    result = result_store.insert_question(question_data)
    questions = result_store.list_questions(dataset_id)
    result_store.update_dataset_question_count(dataset_id, len(questions))
    return result


def update_question(dataset_id: str, question_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """编辑题目。"""
    field_mapping = {
        "retrieval": "retrieval_gold",
        "answer": "answer_gold",
        "sql": "sql_gold",
        "sop": "sop_gold",
    }
    db_updates = {}
    for key, value in updates.items():
        db_key = field_mapping.get(key, key)
        db_updates[db_key] = value
    return result_store.update_question(dataset_id, question_id, db_updates)


def delete_question(dataset_id: str, question_id: str) -> bool:
    """删除题目。"""
    success = result_store.delete_question(dataset_id, question_id)
    if success:
        questions = result_store.list_questions(dataset_id)
        result_store.update_dataset_question_count(dataset_id, len(questions))
    return success


def list_questions(dataset_id: str) -> List[Dict[str, Any]]:
    """列出测试集题目。"""
    return result_store.list_questions(dataset_id)


def export_dataset(dataset_id: str) -> Optional[Dict[str, Any]]:
    """导出测试集为规范 JSON。"""
    dataset = result_store.get_dataset(dataset_id)
    if not dataset:
        return None
    questions = result_store.list_questions(dataset_id)
    items = [_question_row_to_item(q) for q in questions]
    bundle = EvalBundleV2(
        dataset={
            "dataset_id": dataset["dataset_id"],
            "title": dataset["title"],
            "category": dataset["category"],
            "description": dataset["description"],
            "schema_version": dataset["schema_version"],
            "version": dataset["version"],
            "library_id": dataset["library_id"],
        },
        items=items,
    )
    return export_bundle_to_dict(bundle)


def _item_to_question_row(item: Any, dataset_id: str, sort_order: int = 0) -> Dict[str, Any]:
    """将 EvalQuestionItem 转为数据库行格式。"""
    return {
        "question_id": item.question_id,
        "dataset_id": dataset_id,
        "question": item.question,
        "task_type": item.task_type,
        "intent_level": item.intent_level,
        "difficulty": item.difficulty,
        "tags": item.tags,
        "library_id": item.library_id,
        "doc_ids": item.doc_ids,
        "retrieval_gold": item.retrieval.model_dump(exclude_none=True) if item.retrieval else None,
        "answer_gold": item.answer.model_dump(exclude_none=True) if item.answer else None,
        "sql_gold": item.sql.model_dump(exclude_none=True) if item.sql else None,
        "sop_gold": item.sop.model_dump(exclude_none=True) if item.sop else None,
        "sort_order": sort_order,
    }


def _question_row_to_item(row: Dict[str, Any]) -> Dict[str, Any]:
    """将数据库行转为 JSON item 格式。"""
    item: Dict[str, Any] = {
        "question_id": row["question_id"],
        "question": row["question"],
        "task_type": row.get("task_type", "definition"),
        "intent_level": row.get("intent_level", "L1"),
        "library_id": row.get("library_id", "default"),
        "doc_ids": row.get("doc_ids", []),
        "difficulty": row.get("difficulty", "easy"),
        "tags": row.get("tags", []),
    }
    if row.get("retrieval_gold"):
        item["retrieval"] = row["retrieval_gold"]
    if row.get("answer_gold"):
        item["answer"] = row["answer_gold"]
    if row.get("sql_gold"):
        item["sql"] = row["sql_gold"]
    if row.get("sop_gold"):
        item["sop"] = row["sop_gold"]
    return item


# --- 文件夹管理 ---


def list_folders() -> List[Dict[str, Any]]:
    """列出所有文件夹。"""
    return result_store.list_folders()


def create_folder(data: Dict[str, Any]) -> Dict[str, Any]:
    """创建文件夹。"""
    return result_store.insert_folder(data)


def update_folder(folder_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新文件夹信息。"""
    return result_store.update_folder(folder_id, updates)


def delete_folder(folder_id: str) -> bool:
    """删除文件夹。"""
    return result_store.delete_folder(folder_id)


def move_dataset(dataset_id: str, folder_id: str, sort_order: int = 0) -> Optional[Dict[str, Any]]:
    """移动数据集到指定文件夹。"""
    return result_store.update_dataset(dataset_id, {"folder_id": folder_id, "sort_order": sort_order})

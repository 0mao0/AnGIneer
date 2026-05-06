"""JSON 题集加载与校验。"""
import json
from pathlib import Path
from typing import Any, Dict, List

from evals_core.dataset.schema import EvalBundleV2


def load_bundle_from_file(file_path: str) -> EvalBundleV2:
    """从 JSON 文件加载题集并校验。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"题集文件不存在: {file_path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return load_bundle_from_dict(payload)


def load_bundle_from_dict(payload: Dict[str, Any]) -> EvalBundleV2:
    """从字典加载题集并校验。"""
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

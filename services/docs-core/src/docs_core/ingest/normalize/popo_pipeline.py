"""PoPo 本地 pipeline 封装，通过子进程调用 PoPo 的三个阶段。"""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PoPoPipelineRunner:
    """封装 PoPo 本地 pipeline 调用。"""

    def __init__(self, popo_repo_path: Optional[str] = None):
        self.popo_repo_path = Path(popo_repo_path or os.environ.get("POPO_REPO_PATH", ""))

    def _popo_script(self, relative_path: str) -> Path:
        return self.popo_repo_path / relative_path

    def run_full_pipeline(
        self, content_list_path: str, layout_path: str, output_dir: str
    ) -> Dict[str, Any]:
        """Run PoPo: label normalization -> inference (cloud 4B) -> build tree.

        Returns: {"enriched_blocks_path": str, "document_tree_path": str}
        """
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="popo-")

        # Step 1: Label Normalization
        normalize_script = self._popo_script("post_processing/label_normalization.py")
        normalized_path = os.path.join(tmp_dir, "normalized.json")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.popo_repo_path) + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.run(
            [sys.executable, str(normalize_script),
             "--content_list", content_list_path,
             "--layout", layout_path,
             "--output", normalized_path],
            env=env, check=True, timeout=60, capture_output=True, text=True,
        )

        # Step 2: Inference (cloud 4B API via vLLM)
        inference_script = self._popo_script("post_processing/inference.py")
        enriched_path = os.path.join(tmp_dir, "enriched.json")
        subprocess.run(
            [sys.executable, str(inference_script),
             "--input", normalized_path,
             "--output", enriched_path],
            env=env, check=True, timeout=120, capture_output=True, text=True,
        )

        # Step 3: Build document tree
        tree_script = self._popo_script("post_processing/get_json_tree.py")
        tree_path = os.path.join(tmp_dir, "tree.json")
        subprocess.run(
            [sys.executable, str(tree_script),
             "--input", enriched_path,
             "--output", tree_path],
            env=env, check=True, timeout=60, capture_output=True, text=True,
        )

        import shutil
        final_enriched = os.path.join(output_dir, "enriched_blocks.json")
        final_tree = os.path.join(output_dir, "document_tree.json")
        shutil.copy2(enriched_path, final_enriched)
        shutil.copy2(tree_path, final_tree)
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return {"enriched_blocks_path": final_enriched, "document_tree_path": final_tree}


_pipeline: Optional[PoPoPipelineRunner] = None


def get_popo_pipeline() -> PoPoPipelineRunner:
    global _pipeline
    if _pipeline is None:
        _pipeline = PoPoPipelineRunner()
    return _pipeline

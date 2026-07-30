"""PoPo 本地 pipeline 封装，通过子进程调用 PoPo 的三个阶段。"""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DOC_ID = "doc"


class PoPoPipelineRunner:
    """封装 PoPo 本地 pipeline 调用。"""

    def __init__(self, popo_repo_path: Optional[str] = None):
        if popo_repo_path:
            self.popo_repo_path = Path(popo_repo_path)
        else:
            env_path = os.environ.get("POPO_REPO_PATH", "").strip()
            if env_path and Path(env_path).exists():
                self.popo_repo_path = Path(env_path)
            else:
                self.popo_repo_path = Path(__file__).resolve().parent.parent.parent.parent / "popo"

    def _popo_script(self, relative_path: str) -> Path:
        return self.popo_repo_path / relative_path

    def _copy_model_json_normalized(self, src_path: str, dest_path: str) -> None:
        """Copy model.json, remapping bbox from page-pixel coords to 1000-scale.

        Company API model.json stores bbox in output page pixel coordinates
        (e.g. page_width=1654, bbox_x=271).  PoPo label_normalization always
        normalizes with ``assumed_scale=1000``, so we remap every bbox to
        1000-scale here so that the final normalized value is correct [0,1].
        """
        data = json.loads(Path(src_path).read_text(encoding="utf-8"))
        pages = data if isinstance(data, list) else [data]
        out_pages = []
        for page in pages:
            if not isinstance(page, dict):
                out_pages.append(page)
                continue
            info = page.get("page_info") or {}
            w = float(info.get("width") or 1)
            h = float(info.get("height") or 1)

            remapped = dict(page)
            layout_dets = remapped.get("layout_dets")
            if isinstance(layout_dets, list):
                new_dets = []
                for det in layout_dets:
                    if isinstance(det, dict) and isinstance(det.get("bbox"), list) and len(det["bbox"]) == 4:
                        x0, y0, x1, y1 = det["bbox"]
                        new_det = dict(det)
                        new_det["bbox"] = [
                            x0 * 1000.0 / w,
                            y0 * 1000.0 / h,
                            x1 * 1000.0 / w,
                            y1 * 1000.0 / h,
                        ]
                        new_dets.append(new_det)
                    else:
                        new_dets.append(det)
                remapped["layout_dets"] = new_dets
            out_pages.append(remapped)

        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(dest_path).write_text(json.dumps(out_pages, ensure_ascii=False), encoding="utf-8")

    def run_full_pipeline(
        self, mineru_raw_dir: str, output_dir: str, doc_id: str = DOC_ID,
        source_pdf_path: str = "",
    ) -> Dict[str, Any]:
        """Run PoPo: label normalization -> inference (cloud 4B) -> build tree.

        Returns: {"enriched_blocks_path": str, "document_tree_path": str}
        """
        tmp_dir = tempfile.mkdtemp(prefix="popo-")
        try:
            return self._run_stages(mineru_raw_dir, output_dir, tmp_dir, doc_id, source_pdf_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _run_stages(
        self, mineru_raw_dir: str, output_dir: str, tmp_dir: str, doc_id: str,
        source_pdf_path: str = "",
    ) -> Dict[str, Any]:
        mineru_raw = Path(mineru_raw_dir)
        tmp = Path(tmp_dir)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.popo_repo_path) + os.pathsep + env.get("PYTHONPATH", "")

        # ---- Step 1: Label Normalization ----
        # MineruReader prefers model.json (1st), but company API model.json
        # layout_dets have no "content"/"text" field, so all blocks are skipped.
        # Use middle.json instead: para_blocks contain text AND page_size gives
        # correct bbox normalization without the 1000-scale assumption.
        #   Directory: <input>/<doc_id>/vlm/<doc_id>_middle.json
        middle_src = mineru_raw / "middle.json"
        vlm_dir = tmp / "input" / doc_id / "vlm"
        vlm_dir.mkdir(parents=True, exist_ok=True)

        if middle_src.exists():
            shutil.copy2(str(middle_src), str(vlm_dir / f"{doc_id}_middle.json"))
        else:
            content_list_src = mineru_raw / "content_list.json"
            if content_list_src.exists():
                shutil.copy2(str(content_list_src), str(vlm_dir / f"{doc_id}_content_list.json"))

        normalized_out = tmp / "normalized"
        label_norm_script = self._popo_script("post_processing/label_normalization.py")
        subprocess.run(
            [sys.executable, str(label_norm_script),
             "--model", "mineru",
             "--input-dir", str(tmp / "input"),
             "--output-dir", str(normalized_out),
             "--doc-id", doc_id,
             ],
            env=env, check=True, timeout=60, capture_output=True, text=True,
        )

        # Patch input_label in normalized output so inference can find the PDF
        norm_files = list(normalized_out.rglob(f"{doc_id}*.json"))
        if not norm_files:
            norm_files = list(normalized_out.rglob("*.json"))
        if norm_files:
            # Find a usable PDF for page image extraction
            pdf_candidates = []
            if source_pdf_path:
                pdf_candidates.append(Path(source_pdf_path))
            parsed_parent = mineru_raw.parent  # parsed_dir
            pdf_candidates.append(parsed_parent / "mineru_render.pdf")
            for base_dir in [parsed_parent, mineru_raw]:
                try:
                    pdf_candidates.extend(sorted(base_dir.rglob("*.pdf")))
                except OSError:
                    pass
            resolved_pdf = ""
            for c in pdf_candidates:
                if c.exists() and c.is_file():
                    resolved_pdf = str(c)
                    break
            if not resolved_pdf:
                logger.warning("PoPo: no PDF found for inference page extraction, candidates: %s",
                               [str(c) for c in pdf_candidates[:5]])
            else:
                pdf_staging = tmp / "input" / "pdfs"
                pdf_staging.mkdir(parents=True, exist_ok=True)
                target_pdf = pdf_staging / f"{doc_id}.pdf"
                if not target_pdf.exists():
                    shutil.copy2(resolved_pdf, str(target_pdf))
                for nf in norm_files:
                    data = json.loads(nf.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        for item in data:
                            if item.get("doc_id") == doc_id:
                                item["input_label"] = str(target_pdf)
                    elif isinstance(data, dict):
                        if data.get("doc_id") == doc_id:
                            data["input_label"] = str(target_pdf)
                    nf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                logger.info("PoPo: patched input_label in %d normalized files -> %s",
                            len(norm_files), target_pdf)

        # ---- Step 2: Inference (cloud 4B API via vLLM) ----
        enriched_out = tmp / "enriched"
        inference_script = self._popo_script("post_processing/run_inference.py")
        try:
            subprocess.run(
                [sys.executable, str(inference_script),
                 "--model", "mineru",
                 "--input-dir", str(normalized_out),
                 "--output-dir", str(enriched_out),
                 "--limit", "0",
                 ],
                env=env, check=True, timeout=300, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("PoPo inference failed.\nSTDERR:\n%s\nSTDOUT:\n%s", exc.stderr, exc.stdout)
            raise

        # ---- Step 3: Build document tree ----
        tree_out = tmp / "tree"
        txt_out = tmp / "tree_txt"
        tree_script = self._popo_script("post_processing/get_json_tree.py")
        try:
            subprocess.run(
                [sys.executable, str(tree_script),
                 "--input-dir", str(enriched_out),
                 "--output-dir", str(tree_out),
                 "--txt-dir", str(txt_out),
                 ],
                env=env, check=True, timeout=60, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("PoPo tree build failed.\nSTDERR:\n%s\nSTDOUT:\n%s", exc.stderr, exc.stdout)
            raise

        final_enriched = str(out / "enriched_blocks.json")
        final_tree = str(out / "document_tree.json")

        enriched_files = list(enriched_out.glob("*.json"))
        if enriched_files:
            shutil.copy2(str(enriched_files[0]), final_enriched)

        tree_files = list(tree_out.glob("*.json"))
        if tree_files:
            shutil.copy2(str(tree_files[0]), final_tree)

        return {
            "enriched_blocks_path": final_enriched if Path(final_enriched).exists() else "",
            "document_tree_path": final_tree if Path(final_tree).exists() else "",
        }


_pipeline: Optional[PoPoPipelineRunner] = None


def get_popo_pipeline() -> PoPoPipelineRunner:
    global _pipeline
    if _pipeline is None:
        _pipeline = PoPoPipelineRunner()
    return _pipeline

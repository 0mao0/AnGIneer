"""PoPo 本地 pipeline 封装，通过子进程调用 PoPo 的三个阶段。"""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DOC_ID = "doc"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("PoPo: invalid %s=%r, using default %d", name, raw, default)
        return default


def _decode_output(data: Optional[bytes]) -> str:
    """解码子进程输出，避免 Windows 下编码不一致导致崩溃。"""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _emit_on_step(
    on_step: Optional[Callable[[str, str, str], None]],
    step: str,
    status: str = "done",
    detail: str = "",
) -> None:
    if on_step is not None:
        try:
            on_step(step, status, detail)
        except Exception:
            logger.warning("PoPo 步骤回调失败 step=%s", step, exc_info=True)


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
                # 本文件位于 src/docs_core/step03_mineru_parse/ 下，向上 3 层即 src/
                src_root = Path(__file__).resolve().parent.parent.parent
                candidates = [
                    src_root / "popo",
                    src_root / "docs_core" / "popo",
                ]
                self.popo_repo_path = next(
                    (c for c in candidates if (c / "post_processing" / "label_normalization.py").exists()),
                    candidates[0],
                )

    def _popo_script(self, relative_path: str) -> Path:
        return self.popo_repo_path / relative_path

    def _run_script(
        self, args: List[str], *, env: Dict[str, str], timeout: int, stage: str
    ) -> None:
        """统一执行 PoPo 子脚本：按字节捕获输出并宽松解码，统一错误日志。"""
        try:
            subprocess.run(
                args, env=env, check=True, timeout=timeout, capture_output=True
            )
        except subprocess.CalledProcessError as exc:
            stderr = _decode_output(exc.stderr)
            stdout = _decode_output(exc.stdout)
            logger.error(
                "PoPo %s failed.\nSTDERR:\n%s\nSTDOUT:\n%s", stage, stderr, stdout
            )
            raise subprocess.CalledProcessError(
                exc.returncode, exc.cmd, output=stdout, stderr=stderr
            ) from exc
        except subprocess.TimeoutExpired as exc:
            stderr = _decode_output(exc.stderr)
            stdout = _decode_output(exc.stdout)
            logger.error(
                "PoPo %s timed out after %ds.\nSTDERR:\n%s\nSTDOUT:\n%s",
                stage, timeout, stderr, stdout,
            )
            raise

    def run_full_pipeline(
        self, mineru_raw_dir: str, output_dir: str, doc_id: str = DOC_ID,
        source_pdf_path: str = "",
        source_dir: Optional[str] = None,
        on_step: Optional[Callable[[str, str, str], None]] = None,
    ) -> Dict[str, Any]:
        """Run PoPo: label normalization -> inference (cloud 4B) -> build tree.

        Args:
            mineru_raw_dir: MinerU 原始产物目录（middle.json / content_list.json）。
            output_dir: PoPo 产物输出目录（enriched_blocks.json + document_tree.json）。
            source_pdf_path: 可直接使用的 PDF 源路径（优先）。
            source_dir: 文档 source 目录（PDF 候选，兜底扫描）。

        Returns: {"enriched_blocks_path": str, "document_tree_path": str}
        """
        tmp_dir = tempfile.mkdtemp(prefix="popo-")
        try:
            return self._run_stages(
                mineru_raw_dir, output_dir, tmp_dir, doc_id,
                source_pdf_path, source_dir, on_step,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _run_stages(
        self, mineru_raw_dir: str, output_dir: str, tmp_dir: str, doc_id: str,
        source_pdf_path: str = "",
        source_dir: Optional[str] = None,
        on_step: Optional[Callable[[str, str, str], None]] = None,
    ) -> Dict[str, Any]:
        mineru_raw = Path(mineru_raw_dir)
        tmp = Path(tmp_dir)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.popo_repo_path) + os.pathsep + env.get("PYTHONPATH", "")

        # ---- Step 1: Label Normalization ----
        # MineruReader 官方优先读 model.json，但公司 API 的 model.json layout_dets
        # 缺 content/text 字段会导致全部 block 被跳过，因此这里只喂 middle.json：
        # para_blocks 带文本，page_size 能给出正确的 bbox 归一化（不依赖 1000 比例）。
        #   目录约定: <input>/<doc_id>/vlm/<doc_id>_middle.json
        middle_src = mineru_raw / "middle.json"
        content_list_src = mineru_raw / "content_list.json"
        if not middle_src.exists() and not content_list_src.exists():
            _emit_on_step(on_step, "PoPo 输入准备", "failed", "缺少 middle.json / content_list.json")
            raise FileNotFoundError(
                f"PoPo: 输入目录缺少 middle.json / content_list.json: {mineru_raw}"
            )

        vlm_dir = tmp / "input" / doc_id / "vlm"
        vlm_dir.mkdir(parents=True, exist_ok=True)
        if middle_src.exists():
            shutil.copy2(str(middle_src), str(vlm_dir / f"{doc_id}_middle.json"))
        else:
            shutil.copy2(str(content_list_src), str(vlm_dir / f"{doc_id}_content_list.json"))
        _emit_on_step(on_step, "PoPo 输入准备", "done", str(mineru_raw))

        normalized_out = tmp / "normalized"
        try:
            self._run_script(
                [sys.executable, str(self._popo_script("post_processing/label_normalization.py")),
                 "--model", "mineru",
                 "--input-dir", str(tmp / "input"),
                 "--output-dir", str(normalized_out),
                 "--doc-id", doc_id,
                 ],
                env=env,
                timeout=_env_int("POPO_LABEL_NORM_TIMEOUT", 60),
                stage="label normalization",
            )
        except Exception as exc:
            _emit_on_step(on_step, "label 归一化", "failed", f"{type(exc).__name__}: {str(exc)[:160]}")
            raise
        _emit_on_step(on_step, "label 归一化", "done", "")

        # Patch input_label in normalized output so inference can find the PDF
        norm_files = list(normalized_out.rglob(f"{doc_id}.json"))
        if not norm_files:
            raise RuntimeError(f"PoPo: 归一化未产出 {doc_id}.json（{normalized_out}）")

        # 原始 PDF 在 source 目录（转换后的 PDF 或上传的 PDF），不再扫描 parsed/mineru_render.pdf
        pdf_candidates = []
        if source_pdf_path:
            pdf_candidates.append(Path(source_pdf_path))
        if source_dir:
            try:
                pdf_candidates.extend(sorted(Path(source_dir).rglob("*.pdf")))
            except OSError:
                pass
        resolved_pdf = next(
            (str(c) for c in pdf_candidates if c.exists() and c.is_file()), ""
        )
        if not resolved_pdf:
            raise RuntimeError(
                f"PoPo: 未找到 PDF 源文件（source_pdf_path={source_pdf_path!r}, "
                f"source_dir={source_dir!r}）"
            )
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
        try:
            self._run_script(
                [sys.executable, str(self._popo_script("post_processing/run_inference.py")),
                 "--model", "mineru",
                 "--input-dir", str(normalized_out),
                 "--output-dir", str(enriched_out),
                 "--limit", "0",
                 ],
                env=env,
                timeout=_env_int("POPO_INFERENCE_TIMEOUT", 1800),
                stage="inference",
            )
        except Exception as exc:
            _emit_on_step(on_step, "PoPo 4B 推理", "failed", f"{type(exc).__name__}: {str(exc)[:160]}")
            raise
        _emit_on_step(on_step, "PoPo 4B 推理", "done", "")

        # ---- Step 3: Build document tree ----
        tree_out = tmp / "tree"
        txt_out = tmp / "tree_txt"
        try:
            self._run_script(
                [sys.executable, str(self._popo_script("post_processing/get_json_tree.py")),
                 "--input-dir", str(enriched_out),
                 "--output-dir", str(tree_out),
                 "--txt-dir", str(txt_out),
                 ],
                env=env,
                timeout=_env_int("POPO_TREE_TIMEOUT", 60),
                stage="tree build",
            )
        except Exception as exc:
            _emit_on_step(on_step, "document tree 构建", "failed", f"{type(exc).__name__}: {str(exc)[:160]}")
            raise
        _emit_on_step(on_step, "document tree 构建", "done", "")

        final_enriched = str(out / "enriched_blocks.json")
        final_tree = str(out / "document_tree.json")

        enriched_file = enriched_out / f"{doc_id}.json"
        if enriched_file.exists():
            shutil.copy2(str(enriched_file), final_enriched)
        else:
            enriched_files = list(enriched_out.glob("*.json"))
            if enriched_files:
                shutil.copy2(str(enriched_files[0]), final_enriched)

        tree_file = tree_out / f"{doc_id}.json"
        if tree_file.exists():
            shutil.copy2(str(tree_file), final_tree)
        else:
            tree_files = list(tree_out.glob("*.json"))
            if tree_files:
                shutil.copy2(str(tree_files[0]), final_tree)

        _emit_on_step(
            on_step,
            "enriched_blocks.json 落盘",
            "done" if Path(final_enriched).exists() else "failed",
            final_enriched,
        )
        _emit_on_step(
            on_step,
            "document_tree.json 落盘",
            "done" if Path(final_tree).exists() else "failed",
            final_tree,
        )
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

"""PoPo 本地 pipeline 封装，通过子进程调用 PoPo 的三个阶段。"""
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


class PopoEndpointUnavailableError(RuntimeError):
    """PoPo 推理端点全部失败（瞬时抖动或持续不可用）。

    单独建类型是为了让 `parse_pipeline._is_transient_popo_failure` 能把它认成瞬时失败、
    走既有的重试（`POPO_INFERENCE_RETRIES`）——用裸 RuntimeError 会被判成永久失败，
    直接回滚产物、白丢这一篇的判定。
    """


_POPO_ENDPOINT_FAILURE_RE = re.compile(r"POPO endpoint\s+(\S+)\s+failed", re.IGNORECASE)


def _popo_endpoint_failures(text: str) -> List[str]:
    """从子进程输出里捞出端点级失败（返回失败的端点地址列表）。

    `model_utils.popo_generate` 在**所有端点都失败**时只 `return ""`、不抛异常，子进程退出码
    因此仍是 0——阶段会被记成 done，而产物里一个判定都没有（2026-09-20 实测：1,890 篇里
    contd 有 245 篇是"问了却回空"）。它唯一的痕迹就是那行 `print`，必须显式捞出来。
    """
    return _POPO_ENDPOINT_FAILURE_RE.findall(text or "")


def _pick_weighted_popo_configs() -> str:
    """按 POPO_ENDPOINT_WEIGHTS 抽一个端点，返回单条 POPO_CONFIGS JSON 列表。

    2026-10-26 M5 切 popo-client（公开库）后加权轮询的宿主（dgx-spark-popo 计划 §2/F1）：
    库内只保留顺序 failover，配比在调用方实现——每文档按权重抽一次端点。
    旧 vendored 实现是子进程内请求级游标，粒度更细；对 dgx:1,company:3 这类
    比例，文档级抽样与请求级配比在聚合上收敛一致，且不把权重逻辑带进公开库。
    权重缺失/非法时原样透传 POPO_CONFIGS（多端点顺序 failover，库默认行为）。
    """
    raw_configs = os.environ.get("POPO_CONFIGS", "").strip()
    raw_weights = os.environ.get("POPO_ENDPOINT_WEIGHTS", "").strip()
    if not raw_configs or not raw_weights:
        return raw_configs
    try:
        configs = json.loads(raw_configs)
        if not isinstance(configs, list) or not configs:
            return raw_configs
        table = {}
        for part in raw_weights.split(","):
            if ":" in part:
                k, _, v = part.partition(":")
                table[k.strip()] = max(1, int(v))
        if not table:
            return raw_configs
        weights = [table.get(c.get("name", ""), 1) for c in configs]
        picked = random.choices(configs, weights=weights, k=1)[0]
        return json.dumps([picked], ensure_ascii=False)
    except Exception:
        return raw_configs


def _count_popo_verdicts(enriched_dir: Path, doc_id: str) -> Dict[str, int]:
    """统计 enriched 产物里模型真给出的判定数（contd/level/image 非负计数）。

    用于区分"无候选（模型没被问）"与"问了却没产出"——只有计数才能真正反映这一步的成效。
    """
    counts = {"blocks": 0, "contd": 0, "level": 0, "image": 0}
    path = enriched_dir / f"{doc_id}.json"
    if not path.is_file():
        cands = sorted(enriched_dir.glob("*.json"))
        if not cands:
            return counts
        path = cands[0]
    try:
        blocks = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return counts
    if isinstance(blocks, dict):
        blocks = blocks.get("blocks") or []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        counts["blocks"] += 1
        for key in ("contd", "level", "image"):
            try:
                if int(block.get(key, -1)) >= 0:
                    counts[key] += 1
            except (TypeError, ValueError):
                continue
    return counts


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
        except Exception as exc:
            # 取消异常必须向上传播（on_step 兼作取消点），其余回调失败仅告警
            if type(exc).__name__ == "ParseTaskCancelledError":
                raise
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
                # 已安装的 popo 包（pip 装的 popo-client，容器内无 .env 时的主路径）
                try:
                    import popo as _popo_pkg
                    candidates.insert(0, Path(list(_popo_pkg.__path__)[0]))
                except ImportError:
                    pass
                self.popo_repo_path = next(
                    (c for c in candidates if (c / "post_processing" / "label_normalization.py").exists()),
                    None,
                )

    def is_available(self) -> bool:
        """PoPo 子模块是否可用（子进程脚本齐全）。缺失时上层应优雅跳过而非报错。"""
        return bool(
            self.popo_repo_path
            and (self.popo_repo_path / "post_processing" / "label_normalization.py").is_file()
        )

    def _popo_script(self, relative_path: str) -> Path:
        if self.popo_repo_path is None:
            raise FileNotFoundError("PoPo 子模块未安装（缺少 post_processing/label_normalization.py）")
        return self.popo_repo_path / relative_path

    def _run_script(
        self, args: List[str], *, env: Dict[str, str], timeout: int, stage: str,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> str:
        """统一执行 PoPo 子脚本：按字节捕获输出并宽松解码，统一错误日志。

        返回 `stdout\\nstderr` 合并文本——子脚本会把"端点失败"打成 print 而不是异常
        （见 `_popo_endpoint_failures`），退出码为 0 时这些内容只能靠调用方检查。

        cancel_check：可选取消检查回调（自身抛取消异常），运行期间每 0.5s 轮询一次；
        触发取消时先 kill 子进程再向上传播。
        """
        # Windows 下把子进程放进独立进程组，避免控制台 Ctrl+C / 热重载终止
        # 父进程时连带杀死 PoPo 子进程（表现为 0xC000013A）。
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        if cancel_check is not None:
            proc = subprocess.Popen(
                args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            try:
                deadline = time.monotonic() + timeout if timeout else None
                while proc.poll() is None:
                    cancel_check()  # 抛取消异常时进入 except 分支 kill 子进程
                    if deadline is not None and time.monotonic() > deadline:
                        proc.kill()
                        stdout, stderr = proc.communicate()
                        raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
                    try:
                        proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        continue
                stdout, stderr = proc.communicate()
                if proc.returncode != 0:
                    err = subprocess.CalledProcessError(
                        proc.returncode, args, output=stdout, stderr=stderr
                    )
                    logger.error(
                        "PoPo %s failed.\nSTDERR:\n%s\nSTDOUT:\n%s",
                        stage, _decode_output(stderr), _decode_output(stdout),
                    )
                    raise err
                return _decode_output(stdout) + "\n" + _decode_output(stderr)
            except BaseException:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                raise
        try:
            done = subprocess.run(
                args, env=env, check=True, timeout=timeout, capture_output=True,
                creationflags=creationflags,
            )
            return _decode_output(done.stdout) + "\n" + _decode_output(done.stderr)
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
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """Run PoPo: label normalization -> inference (cloud 4B) -> build tree.

        Args:
            mineru_raw_dir: MinerU 原始产物目录（middle.json / content_list.json）。
            output_dir: PoPo 产物输出目录（enriched_blocks.json + document_tree.json）。
            source_pdf_path: 可直接使用的 PDF 源路径（优先）。
            source_dir: 文档 source 目录（PDF 候选，兜底扫描）。
            cancel_check: 可选取消检查回调（自身抛取消异常），子进程运行期间轮询。

        Returns: {"enriched_blocks_path": str, "document_tree_path": str}
        """
        tmp_dir = tempfile.mkdtemp(prefix="popo-")
        try:
            doc_api_url = os.environ.get("POPO_DOC_API_URL", "").strip()
            if doc_api_url:
                return self._run_doc_api(
                    doc_api_url, mineru_raw_dir, output_dir, doc_id,
                    source_pdf_path, source_dir, on_step,
                )
            return self._run_stages(
                mineru_raw_dir, output_dir, tmp_dir, doc_id,
                source_pdf_path, source_dir, on_step, cancel_check,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _run_doc_api(
        self, base_url: str, mineru_raw_dir: str, output_dir: str, doc_id: str,
        source_pdf_path: str, source_dir: Optional[str],
        on_step: Optional[Callable[[str, str, str], None]],
    ) -> Dict[str, Any]:
        """文档级 API 模式（dgx-spark-popo server/，2026-10-26 起）：一次 HTTP 拿判定+树。

        链路（归一化→推理→构树）整体在服务端跑；本侧只剩编排与落盘。
        未设 POPO_DOC_API_URL 时回落子进程链模式（wheel），两条路产物同构。
        注意：cancel_check 在本模式不生效（requests 阻塞等待），超时由 POPO_DOC_TIMEOUT 控制。
        """
        import requests

        api_key = os.environ.get("POPO_DOC_API_KEY", "").strip()
        timeout = int(os.environ.get("POPO_DOC_TIMEOUT", "1800"))

        raw = Path(mineru_raw_dir)
        middle = raw / "middle.json"
        if not middle.is_file():
            middle = raw / "content_list.json"
        if not middle.is_file():
            _emit_on_step(on_step, "PoPo 输入准备", "failed", "缺少 middle.json / content_list.json")
            raise FileNotFoundError(f"no middle.json under {raw}")

        pdf = self._resolve_pdf(source_pdf_path, source_dir)
        if pdf is None:
            _emit_on_step(on_step, "PoPo 输入准备", "failed", "未找到源 PDF")
            raise FileNotFoundError("no source pdf")
        _emit_on_step(on_step, "PoPo 输入准备", "done", str(pdf))

        try:
            with open(pdf, "rb") as f_pdf, open(middle, "rb") as f_mid:
                resp = requests.post(
                    f"{base_url.rstrip('/')}/v1/enhance",
                    files={"pdf": (pdf.name, f_pdf, "application/pdf"),
                           "middle": (middle.name, f_mid, "application/json")},
                    data={"doc_id": doc_id},
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    timeout=timeout,
                )
        except requests.RequestException as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:160]}"
            _emit_on_step(on_step, "PoPo 4B 推理", "failed", detail)
            raise PopoEndpointUnavailableError(f"PoPo 文档级 API 不可达（{detail}）") from exc
        if resp.status_code == 401:
            _emit_on_step(on_step, "PoPo 4B 推理", "failed", "401 鉴权失败")
            raise PopoEndpointUnavailableError("PoPo 文档级 API 鉴权失败（检查 POPO_DOC_API_KEY）")
        if resp.status_code != 200:
            detail = resp.text[:200]
            _emit_on_step(on_step, "PoPo 4B 推理", "failed", f"HTTP {resp.status_code}")
            raise PopoEndpointUnavailableError(f"PoPo 文档级 API 返回 {resp.status_code}: {detail}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise PopoEndpointUnavailableError("PoPo 文档级 API 返回非 JSON") from exc

        blocks = payload.get("enriched_blocks") or []
        verdicts = {
            "blocks": len(blocks),
            "contd": sum(1 for b in blocks if b.get("contd", -1) >= 0),
            "level": sum(1 for b in blocks if b.get("level", -1) >= 0),
            "image": sum(1 for b in blocks if b.get("image", -1) >= 0),
        }
        if verdicts["blocks"] == 0:
            raise PopoEndpointUnavailableError("PoPo 文档级 API 返回零判定块")
        _emit_on_step(on_step, "PoPo 4B 推理", "done",
                      f"判定 contd {verdicts['contd']} / level {verdicts['level']} / "
                      f"image {verdicts['image']}（{verdicts['blocks']} 块，服务端 {payload.get('seconds')}s）")
        _emit_on_step(on_step, "document tree 构建", "done", "")

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        final_enriched = str(out / "enriched_blocks.json")
        final_tree = str(out / "document_tree.json")
        Path(final_enriched).write_text(
            json.dumps(payload.get("enriched_blocks"), ensure_ascii=False), encoding="utf-8")
        Path(final_tree).write_text(
            json.dumps(payload.get("document_tree"), ensure_ascii=False), encoding="utf-8")
        _emit_on_step(on_step, "enriched_blocks.json 落盘", "done", final_enriched)
        return {
            "enriched_blocks_path": final_enriched,
            "document_tree_path": final_tree,
        }

    def _resolve_pdf(self, source_pdf_path: str, source_dir: Optional[str]) -> Optional[Path]:
        candidates = []
        if source_pdf_path:
            candidates.append(Path(source_pdf_path))
        if source_dir:
            candidates.extend(sorted(Path(source_dir).glob("*.pdf")))
        return next((c for c in candidates if c.is_file()), None)

    def _run_stages(
        self, mineru_raw_dir: str, output_dir: str, tmp_dir: str, doc_id: str,
        source_pdf_path: str = "",
        source_dir: Optional[str] = None,
        on_step: Optional[Callable[[str, str, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        mineru_raw = Path(mineru_raw_dir)
        tmp = Path(tmp_dir)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.popo_repo_path) + os.pathsep + env.get("PYTHONPATH", "")
        # F1 宿主迁移：公开库只做顺序 failover，端点配比在此按文档粒度选定
        env["POPO_CONFIGS"] = _pick_weighted_popo_configs()

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
                cancel_check=cancel_check,
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
            infer_output = self._run_script(
                [sys.executable, str(self._popo_script("post_processing/run_inference.py")),
                 "--model", "mineru",
                 "--input-dir", str(normalized_out),
                 "--output-dir", str(enriched_out),
                 "--limit", "0",
                 ],
                env=env,
                timeout=_env_int("POPO_INFERENCE_TIMEOUT", 1800),
                stage="inference",
                cancel_check=cancel_check,
            )
        except Exception as exc:
            _emit_on_step(on_step, "PoPo 4B 推理", "failed", f"{type(exc).__name__}: {str(exc)[:160]}")
            raise
        # 非空校验：端点全挂时 popo_generate 只 return ""、退出码仍是 0，阶段会被记成 done
        # 而产物里一个判定都没有。这里把它变成显式失败（popo 是 soft 阶段，不影响后续解析）。
        # 2026-10-16 修正：旧版只要 stdout 出现一条 "POPO endpoint X failed" 就判失败——
        # 多端点容错下会误杀（company 连不上、DGX 成功产出判定，整篇仍被标 failed，当天 PoPo
        # 零产出 12h 的真因）。改为先数产物：有判定=成功（端点失败只是容错噪音）；零判定才失败。
        verdicts = _count_popo_verdicts(enriched_out, doc_id)
        failed_endpoints = _popo_endpoint_failures(infer_output)
        if failed_endpoints and verdicts["blocks"] == 0:
            detail = f"端点失败 {len(failed_endpoints)} 次：{failed_endpoints[0]}"
            _emit_on_step(on_step, "PoPo 4B 推理", "failed", detail)
            raise PopoEndpointUnavailableError(
                f"PoPo 推理端点全部失败，本文档没有可用判定（{detail}）"
                "；历史行为是静默返回空串、阶段记 done，故此前一直不可见"
            )
        logger.info("PoPo 判定产出: %s", verdicts)
        _emit_on_step(
            on_step,
            "PoPo 4B 推理",
            "done",
            f"判定 contd {verdicts['contd']} / level {verdicts['level']} / image {verdicts['image']}"
            f"（{verdicts['blocks']} 块）",
        )

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
                cancel_check=cancel_check,
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

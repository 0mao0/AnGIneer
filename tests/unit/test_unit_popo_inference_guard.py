"""PoPo 推理非空校验：端点全挂时必须显式失败，而不是静默产出空判定。

背景（2026-09-20 实测）：`popo/model_utils.popo_generate` 在所有端点都失败时只 `return ""`
、不抛异常，子进程退出码仍是 0 → 阶段记 done、产物判定全为 -1。1,890 篇历史产物里
contd 有 245 篇是"问了却回空"，而管线没有任何地方察觉。本用例钉住这条校验。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

from docs_core.step03_mineru_parse.popo_enhance import (  # noqa: E402
    PoPoPipelineRunner,
    _count_popo_verdicts,
    _popo_endpoint_failures,
)

FAIL_LINE = (
    "POPO endpoint https://angineer.cn/api/popo/v1 failed: "
    "ConnectionError: HTTPSConnectionPool(host='angineer.cn', port=443): Read timed out."
)


class TestEndpointFailureScan:
    def test_detects_failure_line(self):
        assert _popo_endpoint_failures(FAIL_LINE) == ["https://angineer.cn/api/popo/v1"]

    def test_detects_multiple_endpoints(self):
        text = FAIL_LINE + "\nPOPO endpoint http://localhost:8003/v1 failed: refused"
        assert len(_popo_endpoint_failures(text)) == 2

    def test_ignores_normal_output_and_responses(self):
        assert _popo_endpoint_failures("") == []
        assert _popo_endpoint_failures("<|src_id|>45<|tgt_id|>47\n") == []
        assert _popo_endpoint_failures("INFO 处理完成，无端点错误") == []


class TestVerdictCounts:
    def _write(self, tmp_path: Path, blocks) -> Path:
        d = tmp_path / "enriched"
        d.mkdir(parents=True, exist_ok=True)
        (d / "doc-x.json").write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
        return d

    def test_counts_non_negative_verdicts(self, tmp_path):
        d = self._write(tmp_path, [
            {"contd": 47, "level": -1, "image": -1},
            {"contd": -1, "level": 2, "image": 23},
            {"contd": -1, "level": -1, "image": -1},
        ])
        assert _count_popo_verdicts(d, "doc-x") == {"blocks": 3, "contd": 1, "level": 1, "image": 1}

    def test_all_empty_is_zero(self, tmp_path):
        """模型没给出任何判定（含端点静默失败）——计数必须如实为 0。"""
        d = self._write(tmp_path, [{"contd": -1, "level": -1, "image": -1}])
        assert _count_popo_verdicts(d, "doc-x") == {"blocks": 1, "contd": 0, "level": 0, "image": 0}

    def test_missing_dir_is_zero(self, tmp_path):
        assert _count_popo_verdicts(tmp_path / "nope", "doc-x")["blocks"] == 0


def _prepare_doc(tmp_path: Path) -> tuple[Path, Path]:
    """构造跑 _run_stages 的最小输入：mineru_raw/middle.json + 一个占位 PDF。"""
    raw = tmp_path / "mineru_raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "middle.json").write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    src = tmp_path / "source"
    src.mkdir(parents=True, exist_ok=True)
    pdf = src / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")
    out = tmp_path / "popo_out"
    return raw, pdf


def _runner_with_stub(monkeypatch, infer_output: str, verdict_blocks) -> PoPoPipelineRunner:
    """把三个子脚本调用短路：label 归一化产文件、推理返回给定输出、树构建产产物。"""
    runner = PoPoPipelineRunner()

    def fake_run_script(args, *, env, timeout, stage, cancel_check=None):
        text = " ".join(str(a) for a in args)
        if "label_normalization" in text:
            norm = Path(args[args.index("--output-dir") + 1])
            (norm / "doc-x.json").parent.mkdir(parents=True, exist_ok=True)
            (norm / "doc-x.json").write_text("{}", encoding="utf-8")
        elif "run_inference" in text:
            out = Path(args[args.index("--output-dir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "doc-x.json").write_text(json.dumps(verdict_blocks), encoding="utf-8")
            return infer_output
        elif "get_json_tree" in text:
            out = Path(args[args.index("--output-dir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "doc-x.json").write_text("{}", encoding="utf-8")
        return ""

    monkeypatch.setattr(runner, "_run_script", fake_run_script)
    monkeypatch.setattr(runner, "_popo_script", lambda rel: Path("/tmp") / rel)
    return runner


def _run(runner, raw: Path, pdf: Path, out: Path, steps: list):
    return runner.run_full_pipeline(
        mineru_raw_dir=str(raw),
        output_dir=str(out),
        doc_id="doc-x",
        source_pdf_path=str(pdf),
        on_step=lambda s, st, d: steps.append((s, st, d)),
    )


class TestStageGuard:
    def test_stage_fails_on_endpoint_failure(self, monkeypatch, tmp_path):
        """端点失败必须让阶段显式失败，而不是产出空判定还报 done。"""
        raw, pdf = _prepare_doc(tmp_path)
        runner = _runner_with_stub(monkeypatch, FAIL_LINE, [{"contd": -1, "level": -1, "image": -1}])
        steps: list = []
        try:
            _run(runner, raw, pdf, tmp_path / "o1", steps)
            raised = False
        except RuntimeError as exc:
            raised = "端点全部失败" in str(exc)
        assert raised, "端点失败没有被提升为阶段失败"
        assert any(s[0] == "PoPo 4B 推理" and s[1] == "failed" for s in steps), steps

    def test_stage_passes_and_reports_verdicts(self, monkeypatch, tmp_path):
        """正常返回时必须通过，并把判定计数写进步骤详情（可观测性）。"""
        raw, pdf = _prepare_doc(tmp_path)
        blocks = [{"contd": 47, "level": -1, "image": -1}, {"contd": -1, "level": 2, "image": 23}]
        runner = _runner_with_stub(monkeypatch, "<|src_id|>45<|tgt_id|>47\n", blocks)
        steps: list = []
        _run(runner, raw, pdf, tmp_path / "o2", steps)
        done = [s for s in steps if s[0] == "PoPo 4B 推理"]
        assert done and done[0][1] == "done", steps
        assert "contd 1" in done[0][2] and "level 1" in done[0][2] and "image 1" in done[0][2], done


class TestTransientClassification:
    """校验抛的错必须被判为「瞬时」，否则一次抖动就白丢该篇的 PoPo 判定（绕过重试）。"""

    def test_endpoint_error_is_transient(self):
        from docs_core.parse_pipeline import _is_transient_popo_failure
        from docs_core.step03_mineru_parse.popo_enhance import PopoEndpointUnavailableError

        exc = PopoEndpointUnavailableError("PoPo 推理端点全部失败，端点失败 1 次：https://x/v1")
        assert _is_transient_popo_failure(exc) is True

    def test_plain_runtime_error_is_not_transient(self):
        """裸 RuntimeError 不该被当成瞬时——避免把永久故障也拖进重试。"""
        from docs_core.parse_pipeline import _is_transient_popo_failure

        assert _is_transient_popo_failure(RuntimeError("子模块缺失")) is False

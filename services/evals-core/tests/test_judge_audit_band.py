"""边界双判（judge_audit band）：band 解析与首票门控语义。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "shared" / "src"))

from evals_core.runner import judge_audit  # noqa: E402


def test_default_band(monkeypatch):
    monkeypatch.delenv(judge_audit.ENV_BAND, raising=False)
    assert judge_audit.rejudge_band() == (0.4, 0.7)
    assert judge_audit.in_rejudge_band(0.45) is True
    assert judge_audit.in_rejudge_band(0.9) is False
    assert judge_audit.in_rejudge_band(0.1) is False
    # 边界：左闭右开
    assert judge_audit.in_rejudge_band(0.4) is True
    assert judge_audit.in_rejudge_band(0.7) is False


def test_empty_band_means_full_rejudge(monkeypatch):
    monkeypatch.setenv(judge_audit.ENV_BAND, "")
    assert judge_audit.rejudge_band() is None
    for s in (0.0, 0.45, 1.0, None):
        assert judge_audit.in_rejudge_band(s) is True


def test_custom_and_invalid_band(monkeypatch):
    monkeypatch.setenv(judge_audit.ENV_BAND, "0.3,0.6")
    assert judge_audit.rejudge_band() == (0.3, 0.6)
    assert judge_audit.in_rejudge_band(0.35) is True
    # 非法配置（反序/乱写）按无带处理 = 保守全量复核
    monkeypatch.setenv(judge_audit.ENV_BAND, "0.7,0.4")
    assert judge_audit.rejudge_band() is None
    monkeypatch.setenv(judge_audit.ENV_BAND, "abc")
    assert judge_audit.rejudge_band() is None
    assert judge_audit.in_rejudge_band(0.99) is True

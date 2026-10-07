# -*- coding: utf-8 -*-
"""ops_metrics 落盘边界回归（2026-10-07 独立发版自审）：

- 主仓库树内：默认目录 = <仓库根>/data/ops；
- 树外（第三方 pip 装到 site-packages）且未配 ANGINEER_OPS_DIR：**不落盘**，
  绝不回落到当前工作目录（库不往宿主目录写文件）；
- ANGINEER_OPS_DIR / ANGINEER_OPS_DISABLE 两个开关的优先级不变。
"""
import json

import pytest

from angineer_core import ops_metrics


def _clear_ops_env(monkeypatch):
    monkeypatch.delenv("ANGINEER_OPS_DIR", raising=False)
    monkeypatch.delenv("ANGINEER_OPS_DISABLE", raising=False)


class TestSinkBoundary:
    def test_outside_repo_tree_does_not_write_cwd(self, tmp_path, monkeypatch):
        """无仓库标记 + 无 ANGINEER_OPS_DIR：静默不落盘，cwd 不留任何文件。"""
        _clear_ops_env(monkeypatch)
        monkeypatch.setattr(ops_metrics, "_repo_root", lambda: None)
        monkeypatch.chdir(tmp_path)

        assert ops_metrics.ops_dir() == ""
        ops_metrics.record_event("probe", {"a": 1})
        assert list(tmp_path.rglob("*.jsonl")) == []
        assert not (tmp_path / "data").exists()

    def test_env_dir_overrides_and_writes(self, tmp_path, monkeypatch):
        """显式给 ANGINEER_OPS_DIR 后照常落盘（树外也能开观测）。"""
        _clear_ops_env(monkeypatch)
        monkeypatch.setattr(ops_metrics, "_repo_root", lambda: None)
        monkeypatch.setenv("ANGINEER_OPS_DIR", str(tmp_path / "ops"))

        ops_metrics.record_event("probe", {"a": 1})
        files = list((tmp_path / "ops").glob("probe-*.jsonl"))
        assert len(files) == 1
        row = json.loads(files[0].read_text(encoding="utf-8").strip())
        assert row["kind"] == "probe" and row["a"] == 1

    def test_repo_tree_keeps_default_dir(self, tmp_path, monkeypatch):
        """树内默认目录不变：<仓库根>/data/ops。"""
        _clear_ops_env(monkeypatch)
        monkeypatch.setattr(ops_metrics, "_repo_root", lambda: tmp_path)
        assert ops_metrics.ops_dir() == str(tmp_path / "data" / "ops")

    def test_disable_switch_still_wins(self, tmp_path, monkeypatch):
        """ANGINEER_OPS_DISABLE 优先级最高：目录配了也不落盘。"""
        _clear_ops_env(monkeypatch)
        monkeypatch.setenv("ANGINEER_OPS_DIR", str(tmp_path / "ops"))
        monkeypatch.setenv("ANGINEER_OPS_DISABLE", "1")

        ops_metrics.record_event("probe", {"a": 1})
        assert not (tmp_path / "ops").exists()

    def test_run_id_attached_from_context(self, tmp_path, monkeypatch):
        """既有行为回归：上下文 run_id 自动随打点落库。"""
        _clear_ops_env(monkeypatch)
        monkeypatch.setenv("ANGINEER_OPS_DIR", str(tmp_path / "ops"))
        ops_metrics.set_run_id("run-probe")
        try:
            ops_metrics.record_event("probe")
        finally:
            ops_metrics.set_run_id(None)
        row = json.loads(
            next((tmp_path / "ops").glob("probe-*.jsonl")).read_text(encoding="utf-8").strip()
        )
        assert row["run_id"] == "run-probe"


def test_monorepo_marker_detected_when_present():
    """主仓库树内必须命中标记（独立仓 / site-packages 环境无标记，自动跳过）。"""
    root = ops_metrics._repo_root()
    if root is None:
        pytest.skip("不在主仓库树内（独立仓或 pip 安装）")
    assert (root / "services").is_dir() and (root / "apps").is_dir()

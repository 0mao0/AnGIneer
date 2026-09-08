"""tests/test_startup_guard.py"""
import pytest
from unittest.mock import patch
from docs_core.startup_guard import run_vector_startup_guard, VectorGuardReport


def test_empty_store_skips_probe():
    with patch("docs_core.startup_guard._check_vector_store", return_value={
        "total_rows": 0, "zero_dimension_rows": 0, "expected_dimension": 0, "dimension_distribution": {}
    }), patch("docs_core.startup_guard._probe_embedding_dimension", return_value=(0, "should not be called")):
        report = run_vector_startup_guard()
        assert report.ok is True
        assert len(report.warnings) == 1
        assert "空" in report.warnings[0]


def test_dimension_mismatch_is_error():
    with patch("docs_core.startup_guard._check_vector_store", return_value={
        "total_rows": 100, "zero_dimension_rows": 0, "expected_dimension": 1024, "dimension_distribution": {1024: 100}
    }), patch("docs_core.startup_guard._probe_embedding_dimension", return_value=(768, None)):
        report = run_vector_startup_guard()
        assert report.ok is False
        assert any("不匹配" in e for e in report.errors)


def test_dimension_match_is_ok():
    with patch("docs_core.startup_guard._check_vector_store", return_value={
        "total_rows": 100, "zero_dimension_rows": 0, "expected_dimension": 1024, "dimension_distribution": {1024: 100}
    }), patch("docs_core.startup_guard._probe_embedding_dimension", return_value=(1024, None)):
        report = run_vector_startup_guard()
        assert report.ok is True
        assert len(report.errors) == 0


def test_zero_dim_rows_are_warning():
    with patch("docs_core.startup_guard._check_vector_store", return_value={
        "total_rows": 100, "zero_dimension_rows": 5, "expected_dimension": 1024, "dimension_distribution": {1024: 95}
    }), patch("docs_core.startup_guard._probe_embedding_dimension", return_value=(1024, None)):
        report = run_vector_startup_guard()
        assert report.ok is True
        assert any("脏数据" in w for w in report.warnings)


def test_heterogeneous_dims_are_warning():
    with patch("docs_core.startup_guard._check_vector_store", return_value={
        "total_rows": 100, "zero_dimension_rows": 0, "expected_dimension": 1024, "dimension_distribution": {1024: 80, 768: 20}
    }), patch("docs_core.startup_guard._probe_embedding_dimension", return_value=(1024, None)):
        report = run_vector_startup_guard()
        assert any("异构" in w for w in report.warnings)


def test_embedding_probe_failure_is_error():
    with patch("docs_core.startup_guard._check_vector_store", return_value={
        "total_rows": 100, "zero_dimension_rows": 0, "expected_dimension": 1024, "dimension_distribution": {1024: 100}
    }), patch("docs_core.startup_guard._probe_embedding_dimension", return_value=(0, "连接超时")):
        report = run_vector_startup_guard()
        assert report.ok is False
        assert any("连接超时" in e for e in report.errors)


def test_store_unaccessible_is_warning():
    with patch("docs_core.startup_guard._check_vector_store", return_value={
        "error": "database locked", "total_rows": 0, "zero_dimension_rows": 0, "expected_dimension": 0, "dimension_distribution": {}
    }):
        report = run_vector_startup_guard()
        assert report.ok is True  # warning, not error
        assert any("不可访问" in w for w in report.warnings)


def test_report_to_dict_serializable():
    report = VectorGuardReport(ok=False, errors=["test error"], warnings=["test warning"], details={"key": "value"})
    from docs_core.startup_guard import report_to_dict
    d = report_to_dict(report)
    assert d["ok"] is False
    assert d["errors"] == ["test error"]
    assert d["warnings"] == ["test warning"]
    assert d["details"] == {"key": "value"}


def test_get_retrieve_warning_returns_none_when_ok():
    import docs_core.startup_guard as mod
    mod._last_report = VectorGuardReport(ok=True)
    assert mod.get_retrieve_warning() is None


def test_get_retrieve_warning_returns_text_when_not_ok():
    import docs_core.startup_guard as mod
    mod._last_report = VectorGuardReport(ok=False, errors=["维度不匹配"])
    warning = mod.get_retrieve_warning()
    assert warning is not None
    assert "维度不匹配" in warning


def test_get_retrieve_warning_returns_none_when_no_report():
    import docs_core.startup_guard as mod
    mod._last_report = None
    assert mod.get_retrieve_warning() is None

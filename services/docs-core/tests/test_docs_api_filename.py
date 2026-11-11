"""上传文件名净化单测（0.1.8，DredgeAI 接入验收·问题二）。

背景：.NET 客户端对非 ASCII 文件名按 RFC 2047 编码 encoded-word，python-multipart
0.0.33 不解码；Windows 文件名禁 ``?`` → open() OSError [Errno 22]。
"""
import base64

import pytest

from docs_core.docs_api._filename import (
    decode_rfc2047,
    normalize_upload_filename,
    sanitize_filename,
)


def _encoded(name: str) -> str:
    return "=?utf-8?B?" + base64.b64encode(name.encode("utf-8")).decode() + "?="


def test_encoded_word_decoded():
    raw = _encoded("混凝土强度检测报告.pdf")
    assert decode_rfc2047(raw) == "混凝土强度检测报告.pdf"
    assert normalize_upload_filename(raw) == "混凝土强度检测报告.pdf"


def test_plain_chinese_name_untouched():
    """未编码的普通中文文件名（multipart 直传 str）不能被 decode_header 弄坏。"""
    name = "普通中文报告.pdf"
    assert normalize_upload_filename(name) == name


def test_windows_illegal_chars_replaced():
    assert sanitize_filename('a<b>c:"d/e\\f|g?h*i') == "a_b_c__d_e_f_g_h_i"
    assert sanitize_filename("name with trailing dots... ") == "name with trailing dots"


def test_reserved_device_name_prefixed():
    assert normalize_upload_filename("CON.pdf") == "_CON.pdf"
    assert normalize_upload_filename("com1") == "_com1"
    assert normalize_upload_filename("NUL") == "_NUL"


def test_path_injection_flattened():
    """encoded-word 解码产物若含路径分隔符，压成扁平文件名（防目录穿越）。"""
    raw = _encoded("../..\\evil报告.pdf")
    out = normalize_upload_filename(raw)
    assert "/" not in out and "\\" not in out
    assert "evil报告.pdf" in out
    # 全点特殊名（. / ..）被尾部点清洗成空 → 走兜底名，不产生特殊目录项
    assert normalize_upload_filename(_encoded("..")) == "upload.bin"


def test_empty_falls_back():
    assert normalize_upload_filename("", fallback="upload.bin") == "upload.bin"
    assert normalize_upload_filename("???") == "___"


def test_mixed_encoded_and_plain_segments():
    """多段 encoded-word + 明文拼接（.NET 长文件名分行编码形态）。"""
    raw = _encoded("报告第") + "1部分" + _encoded(".pdf")
    assert normalize_upload_filename(raw) == "报告第1部分.pdf"

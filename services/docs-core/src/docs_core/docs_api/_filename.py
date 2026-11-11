"""上传文件名净化：RFC 2047 encoded-word 解码 + Windows 非法字符清洗。

为什么在包内（DredgeAI 0.1.7 接入验收反馈·问题二）：.NET 客户端对非 ASCII 文件名按
RFC 2047 编码为 encoded-word（``=?utf-8?B?...?=``），python-multipart（0.0.33）不解码、
原样作文件名；Windows 文件名禁止 ``?``，``open()`` 直接 OSError [Errno 22]——凡是含中文
文件名的上传，解析在 source_prep 前就崩。宿主时代未暴露是因为宿主环境 python-multipart
为 0.0.22。服务端不依赖客户端自行处理（消费方客户端侧 ASCII 化会丢中文原名，已回退）。

独立小模块（不 import app 装配），宿主 v1 路由可单独导入同款逻辑保持两侧一致。
"""
import re
from pathlib import PurePosixPath, PureWindowsPath

# Windows 保留字符 + 控制字符（文件名部分；路径分隔符不在此处理——只收单文件名）
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# RFC 2047 encoded-word 整体形态（逐个解码；明文段不动）
_ENCODED_WORD_RE = re.compile(r"=\?[^?\s]*\?[bBqQ]\?[^?\s]*\?=")


def decode_rfc2047(value: str) -> str:
    """解 RFC 2047 encoded-word（``=?charset?B/Q?...?=``）；无 ``=?`` 时原样返回。

    逐个 encoded-word 独立解码、明文段原样保留——不用 ``email.header.decode_header``
    整串处理：它会把 encoded-word 之间的明文非 ASCII 段二次编码（实测「部分」被写成
    ``_u90e8_u5206``）。.NET 长文件名常按行拆多段 encoded-word + 明文交错。
    """
    raw = value or ""
    if "=?" not in raw:
        return raw

    def _decode_one(match: re.Match) -> str:
        import email.header

        try:
            parts = email.header.decode_header(match.group(0))
            out = []
            for data, charset in parts:
                if isinstance(data, bytes):
                    out.append(data.decode(charset or "utf-8", "replace"))
                else:
                    out.append(data)
            return "".join(out)
        except Exception:  # noqa: BLE001 — 单段解码失败保留原样（错误留给落盘层报）
            return match.group(0)

    return _ENCODED_WORD_RE.sub(_decode_one, raw)


def sanitize_filename(value: str) -> str:
    """清洗单文件名：Windows/POSIX 保留字符与控制字符替换为 ``_``，去尾部空格点。"""
    cleaned = _INVALID_NAME_CHARS.sub("_", value or "").strip()
    # Windows 目录项不能以空格或点结尾（点保留给扩展名内部）
    cleaned = cleaned.rstrip(" .")
    return cleaned


def normalize_upload_filename(raw: str, fallback: str = "upload.bin") -> str:
    """上传文件名净化入口：解码 encoded-word → 清洗非法字符 → 空名兜底。"""
    name = sanitize_filename(decode_rfc2047(raw))
    if not name:
        return fallback
    # 防 Windows 保留设备名（CON/PRN/AUX/NUL/COM1..9/LPT1..9，含带扩展名形态）
    stem = PureWindowsPath(name).stem.upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or (
        len(stem) > 3 and stem[:3] in {"COM", "LPT"} and stem[3:].isdigit()
    ):
        name = f"_{name}"
    # 净化后必须仍是纯文件名（encoded-word 里被塞入路径分隔符的兜底）
    if PureWindowsPath(name).name != name or PurePosixPath(name).name != name:
        name = re.sub(r"[\\/]+", "_", name)
    if name in {".", ".."}:  # Windows 目录项特殊名不可作文件名
        name = "_" + name
    return name or fallback

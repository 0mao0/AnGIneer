"""通过 LibreOffice headless 将常见办公文档转换为 PDF。"""
import subprocess
import os
import shutil
from pathlib import Path
from typing import Optional


def find_libreoffice() -> Optional[str]:
    """查找 LibreOffice 可执行路径。"""
    names = [
        "soffice",
        "libreoffice",
    ]
    for name in names:
        path = shutil.which(name)
        if path:
            return path

    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


def convert_to_pdf(input_path: str, output_dir: str) -> Optional[str]:
    """将常见办公文档转换为 PDF，返回生成的 PDF 路径，失败返回 None。

    支持格式：doc, docx, ppt, pptx, xls, xlsx, odt, odp, ods, rtf, txt 等。
    对已经是 PDF 的文件直接返回原路径。
    """
    input_path = os.path.abspath(input_path)
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    ext = Path(input_path).suffix.lower()
    if ext == '.pdf':
        return input_path

    lo_path = find_libreoffice()
    if not lo_path:
        raise RuntimeError(
            "未找到 LibreOffice。请安装后设置环境变量或放入标准路径。"
            "Docker 部署时 apt-get install libreoffice-core libreoffice-writer"
        )

    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    env = os.environ.copy()
    env['HOME'] = env.get('HOME', '/tmp')

    cmd = [
        lo_path,
        '--headless',
        '--convert-to', 'pdf',
        '--outdir', output_dir,
        input_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice 转换失败 (exit={result.returncode}): "
            f"stderr={result.stderr[:500]}"
        )

    basename = Path(input_path).stem
    output_pdf = os.path.join(output_dir, f"{basename}.pdf")
    if os.path.isfile(output_pdf):
        return output_pdf

    raise RuntimeError(f"转换后 PDF 未生成: {output_pdf}")

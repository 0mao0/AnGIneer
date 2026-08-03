"""通过 LibreOffice headless 将常见办公文档转换为 PDF。"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional


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


def _kill_stale_soffice() -> None:
    """清理残留 soffice 进程（Windows taskkill / Unix pkill），避免 profile 锁冲突。"""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/IM", "soffice.bin", "/F"],
                capture_output=True, timeout=10,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "soffice"],
                capture_output=True, timeout=10,
            )
    except Exception:
        pass


def prepare_source(library_id: str, doc_id: str, file_path: str) -> str:
    """确保源文件位于规范 source 目录，返回规范路径（docx 或 pdf）。

    供解析管线 source_prep/convert 阶段调用；文件复制等物理操作委托 file_storage。
    """
    from docs_core.write.store.assets_file_store import file_storage

    source_path = file_storage.ensure_doc_source_file(library_id, doc_id, file_path=file_path)
    if not source_path:
        raise RuntimeError("源文件不存在或无法复制到规范目录")
    return source_path


def convert_to_pdf(
    input_path: str,
    output_dir: str,
    cancel_check: Optional[Callable[[], None]] = None,
) -> Optional[str]:
    """将常见办公文档转换为 PDF，返回生成的 PDF 路径，失败返回 None。

    支持格式：doc, docx, ppt, pptx, xls, xlsx, odt, odp, ods, rtf, txt 等。
    对已经是 PDF 的文件直接返回原路径。
    cancel_check：可选取消检查回调，转换期间每 0.3s 调用一次；
    若抛出异常（如取消异常）则终止 soffice 子进程并向外传播该异常。
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

    # 独立 UserInstallation profile，避免与其它 soffice 实例争用锁导致挂起
    profile_dir = tempfile.mkdtemp(prefix="lo-profile-")
    user_install = f"file:///{profile_dir.replace(os.sep, '/')}"

    cmd = [
        lo_path,
        '--headless',
        '-env:UserInstallation=' + user_install,
        '--convert-to', 'pdf',
        '--outdir', output_dir,
        input_path,
    ]

    # stdout/stderr 重定向到文件，避免管道缓冲（64KB）填满导致死锁
    stdout_path = os.path.join(profile_dir, "lo_stdout.log")
    stderr_path = os.path.join(profile_dir, "lo_stderr.log")
    try:
        with open(stdout_path, "w", encoding="utf-8", errors="replace") as fout, \
             open(stderr_path, "w", encoding="utf-8", errors="replace") as ferr:
            # Popen + 轮询：转换期间每 0.3s 检查一次取消回调，可随时终止子进程
            proc = subprocess.Popen(cmd, stdout=fout, stderr=ferr, env=env)
            deadline = time.time() + 180
            try:
                while True:
                    if cancel_check is not None:
                        cancel_check()
                    if proc.poll() is not None:
                        break
                    if time.time() > deadline:
                        raise TimeoutError()
                    time.sleep(0.3)
            except TimeoutError:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                _kill_stale_soffice()
                raise RuntimeError(
                    f"LibreOffice 转换超时（180s）: {Path(input_path).name}，"
                    f"已清理 soffice 进程，请重试。"
                )
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
            result = proc
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    if result.returncode != 0:
        stderr_tail = ""
        try:
            with open(stderr_path, "r", encoding="utf-8", errors="replace") as ferr:
                stderr_tail = ferr.read()[-500:]
        except Exception:
            pass
        raise RuntimeError(
            f"LibreOffice 转换失败 (exit={result.returncode}): {stderr_tail}"
        )

    basename = Path(input_path).stem
    output_pdf = os.path.join(output_dir, f"{basename}.pdf")
    if os.path.isfile(output_pdf):
        return output_pdf

    raise RuntimeError(f"转换后 PDF 未生成: {output_pdf}")

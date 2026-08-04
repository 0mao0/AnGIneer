"""步骤二：通过 LibreOffice headless 将常见办公文档转换为 PDF。"""

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional


def find_libreoffice() -> Optional[str]:
    """查找 LibreOffice 可执行路径。

    查找顺序：LIBREOFFICE_BIN 环境变量 > PATH（soffice / libreoffice）> Windows 常见安装路径。
    服务器场景：安装后设置 LIBREOFFICE_BIN，或确保 soffice 在 PATH 中。
    """
    env_path = os.environ.get("LIBREOFFICE_BIN", "").strip()
    if env_path:
        # 显式指定时不再回退，避免配置错误被静默掩盖
        return env_path if os.path.isfile(env_path) else None

    for name in ("soffice", "libreoffice"):
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


def _force_kill_process(pid: Optional[int]) -> None:
    """强制结束单个 soffice 进程及其子进程（按 PID，不影响其他实例）。"""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=10,
            )
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def convert_to_pdf(
    input_path: str,
    output_dir: str,
    cancel_check: Optional[Callable[[], None]] = None,
) -> str:
    """将常见办公文档转换为 PDF，返回生成的 PDF 路径；失败抛出 RuntimeError。

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
            "未找到 LibreOffice。请安装后设置环境变量 LIBREOFFICE_BIN，"
            "或将 soffice 加入 PATH；"
            "Docker 部署时 apt-get install libreoffice-core libreoffice-writer"
        )

    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # 先清除旧产物，避免本次转换静默失败时误判为成功（返回过期 PDF）
    basename = Path(input_path).stem
    output_pdf = os.path.join(output_dir, f"{basename}.pdf")
    try:
        os.remove(output_pdf)
    except FileNotFoundError:
        pass

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
    stderr_tail = ""
    result = None
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
                    _force_kill_process(proc.pid)
                raise RuntimeError(
                    f"LibreOffice 转换超时（180s）: {Path(input_path).name}，"
                    "已清理 soffice 进程，请重试。"
                )
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        _force_kill_process(proc.pid)
            result = proc
    finally:
        # 先读 stderr 再清理临时目录，否则日志被删后错误信息恒为空
        try:
            with open(stderr_path, "r", encoding="utf-8", errors="replace") as ferr:
                stderr_tail = ferr.read()[-500:]
        except Exception:
            pass
        shutil.rmtree(profile_dir, ignore_errors=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice 转换失败 (exit={result.returncode}): {stderr_tail}"
        )

    if os.path.isfile(output_pdf):
        return output_pdf

    raise RuntimeError(f"转换后 PDF 未生成: {output_pdf}")


__all__ = ["convert_to_pdf", "find_libreoffice"]

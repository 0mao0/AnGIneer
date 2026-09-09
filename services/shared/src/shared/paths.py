"""共享数据文件路径解析：env 优先 > 仓库根探测 > cwd/data。

供 shared 内的模型模块使用（user_model / api_key_model）。
仓库根探测标记：同时含 services/ 与 apps/ 的目录（本地仓库根与容器 /app 均满足）。
"""
import os
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "services").is_dir() and (parent / "apps").is_dir():
            return parent
    return Path.cwd()


def resolve_data_file(env_key: str, filename: str) -> str:
    """解析 data 目录下的文件路径；env_key 非空时优先用其值。"""
    override = (os.environ.get(env_key, "") or "").strip()
    if override:
        return override
    return str(_repo_root() / "data" / filename)

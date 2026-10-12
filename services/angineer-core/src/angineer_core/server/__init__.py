"""angineer-core [server] 薄壳包：chat-api 宿主入口（agent 编排 SSE + health）。

依赖 ``[server]`` extra（fastapi/uvicorn）：``pip install 'angineer-core[server]'``。
纯库消费者不受影响——不安装 extra 时本子包不可用，包其余部分行为不变。

启动：``uvicorn angineer_core.server:app --host 127.0.0.1 --port 8311``

惰性导出（2026-10-12）：``app``/``create_app`` 按需加载——``http_ports`` 等纯逻辑
模块可被独立导入（未装 fastapi 的环境也不报错）。
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from angineer_core.server.app import app, create_app

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    if name in ("app", "create_app"):
        # 必须 importlib.import_module 直接导子模块：`from angineer_core.server import app`
        # 会先走本 __getattr__（attr 查找优先于子模块回落）→ 无限递归（2026-10-12 实踩）。
        import importlib

        _app_module = importlib.import_module(f"{__name__}.app")
        value = getattr(_app_module, name)
        globals()[name] = value  # 缓存：后续访问不再走 __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | {"app", "create_app"})

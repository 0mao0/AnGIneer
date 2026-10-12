"""docs-core [server] 薄壳包：retrieval-api 宿主入口（检索 / 库册清单 / 原文回源 + health）。

依赖 ``[server]`` extra（fastapi/uvicorn）：``pip install 'angineer-docs-core[server]'``。
纯库消费者不受影响——不安装 extra 时本子包不可用，包其余部分行为不变。

启动：``uvicorn docs_core.server:app --host 127.0.0.1 --port 8310``
"""
from docs_core.server.app import app, create_app

__all__ = ["app", "create_app"]

"""angineer-core [server] 薄壳包：chat-api 宿主入口（agent 编排 SSE + health）。

依赖 ``[server]`` extra（fastapi/uvicorn）：``pip install 'angineer-core[server]'``。
纯库消费者不受影响——不安装 extra 时本子包不可用，包其余部分行为不变。

启动：``uvicorn angineer_core.server:app --host 127.0.0.1 --port 8311``
"""
from angineer_core.server.app import app, create_app

__all__ = ["app", "create_app"]

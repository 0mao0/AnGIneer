"""可选启动入口：``python -m docs_core.docs_api``（带单实例守卫）。

主入口仍是 ``uvicorn docs_core.docs_api:app --port 8312``（端口由 uvicorn 参数决定，
不读 ports.json——需求 R1/c）。本入口只服务于想要「守卫 + 固定 env 端口」的调用方：
- ``DOCS_API_PORT``：监听端口（默认 8312）；
- ``DOCS_API_SINGLE_INSTANCE_GUARD``：``1`` 时启动前探 /health 拒绝重复启动（默认关，
  进程唯一性由消费方启动器保证）。
"""
import os

if __name__ == "__main__":
    import uvicorn

    from docs_core.docs_api.app import assert_single_instance

    port = int(os.getenv("DOCS_API_PORT", "8312"))
    if (os.getenv("DOCS_API_SINGLE_INSTANCE_GUARD") or "").strip() == "1":
        assert_single_instance(port)
    uvicorn.run(
        "docs_core.docs_api.app:app",
        host=os.getenv("DOCS_API_HOST", "0.0.0.0"),
        port=port,
        # DredgeAI 以 5s 间隔轮询 /status，默认 keep-alive 超时（5s）会导致复用
        # 已被服务端关闭的连接而收到 RST（SocketException 10053），调大以规避。
        timeout_keep_alive=int(os.getenv("UVICORN_KEEP_ALIVE_TIMEOUT", "30")),
    )

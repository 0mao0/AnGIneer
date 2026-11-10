"""docs_core.docs_api — 解析面薄壳（[api] extra）。

入口 ``docs_core.docs_api:app``（uvicorn 直起），见 app.py 模块文档。
"""
from docs_core.docs_api.app import app, assert_single_instance, create_app

__all__ = ["app", "create_app", "assert_single_instance"]

"""chat-history 包内测试的路径注入（与根 tests/aichat-api 同惯例，收敛到单处）。

chat_history / angineer_core / shared 均为 src-layout 源码分发（未 pip 安装），
conftest 先于测试模块被 pytest 导入，在此统一注入三个 src 目录。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _src in ("../src", "../../angineer-core/src", "../../shared/src"):
    _p = os.path.abspath(os.path.join(_HERE, _src))
    if _p not in sys.path:
        sys.path.insert(0, _p)

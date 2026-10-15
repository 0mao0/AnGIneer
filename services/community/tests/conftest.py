"""community 包内测试的路径注入（照 chat-history/tests/conftest.py 惯例）。

community / tree_core / shared 均为 src-layout 源码分发（未 pip 安装），
conftest 先于测试模块被 pytest 导入，在此统一注入 src 目录。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _src in ("../src", "../../tree-core/src", "../../shared/src"):
    _p = os.path.abspath(os.path.join(_HERE, _src))
    if _p not in sys.path:
        sys.path.insert(0, _p)

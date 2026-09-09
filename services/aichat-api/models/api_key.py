"""models.api_key 已收敛到 shared.api_key_model（单一真相源，2026-09-09）。

本模块为别名兼容层：模块替换（sys.modules 换名）使既有导入与 patch 语义不变。
"""
import sys as _sys

try:
    import shared.api_key_model as _impl
except ImportError:  # 裸环境兜底：挂上 monorepo 的 shared/src
    import os as _os

    _sys.path.insert(
        0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "shared", "src"))
    )
    import shared.api_key_model as _impl

_sys.modules[__name__] = _impl

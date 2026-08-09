"""P5 Prompt 资产化：统一注册表 + ``load(name, version)`` 薄加载器。

约定：
- 每个 prompt 一个常量 + 头部注释（用途 / 语言 / 版本 / 最后变更）；
- 常量在模块底部 ``register()`` 登记，经 ``load(name, version)`` 加载；
- 改动 prompt 必须递增版本号（``v1`` → ``v2`` ...）；
- 中英策略：结构化提取 / 评测判分沿用英文（图谱 E1-E5 与 VERIFY 已验证），
  面向用户生成用中文（dispatcher system prompt、QA/COMPLEX 档等）。
"""
from typing import Dict

_REGISTRY: Dict[str, Dict[str, str]] = {}


def register(name: str, version: str, text: str) -> None:
    """注册一条 prompt；同名同版本内容不一致时拒绝覆盖。"""
    if name not in _REGISTRY:
        _REGISTRY[name] = {}
    existed = _REGISTRY[name].get(version)
    if existed is not None and existed != text:
        raise ValueError(f"prompt {name}@{version} 重复注册且内容不一致")
    _REGISTRY[name][version] = text


def load(name: str, version: str = "latest") -> str:
    """按名称加载 prompt；version 默认取最新注册版本。"""
    entry = _REGISTRY.get(name)
    if not entry:
        raise KeyError(f"未注册的 prompt: {name}")
    if version == "latest":
        version = max(entry.keys())
    if version not in entry:
        raise KeyError(f"prompt {name} 无版本 {version}，可用: {sorted(entry)}")
    return entry[version]


def versions() -> Dict[str, str]:
    """返回 {name: latest_version} 注册表，供 evals prediction 持久化。"""
    return {name: max(entry.keys()) for name, entry in _REGISTRY.items()}


from . import agent_configs, answer_eval, classifier, dispatcher, evals_routes, sop_routes  # noqa: E402,F401

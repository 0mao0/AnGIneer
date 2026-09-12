"""端点级 enable_thinking 开关（LLM_CONFIGS 字段）：显式 > 环境变量 > 隐式 URL/模型名规则。

背景：隐式规则只认 dashscope/aliyun、angineer.cn、模型名含 qwen3.6，直连 vLLM/DGX 的
思考模型一条都不命中 → 思考全量输出（53 题全灭事故触发面）。直连端点现可显式声明
"enable_thinking": true/false。
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import helpers

from ai_inference.llm_client import LLMClient
from ai_inference.llm_config import (
    LLMClientConfig,
    LLMModelConfig,
    RetryConfig,
    load_llm_models_from_env,
)


def _client(model_cfg: LLMModelConfig) -> LLMClient:
    return LLMClient(LLMClientConfig(
        models=[model_cfg], default_model=model_cfg.name, retry=RetryConfig(max_retries=0),
    ))


_UNSET = object()


def _extra_body_for(model_cfg: LLMModelConfig, env=_UNSET):
    """env 省略 = 变量未设置；env="" = 键在但值为空串（缺陷 B 的触发态）。"""
    client = _client(model_cfg)
    completions = helpers.FakeCompletions()
    env_patch = {} if env is _UNSET else {"ANGINEER_CHAT_TEMPLATE_KWARGS": env}
    with mock.patch("ai_inference.llm_client.OpenAI", helpers.make_sync_factory(completions)):
        with mock.patch.dict(os.environ, env_patch, clear=False):
            if env is _UNSET:
                os.environ.pop("ANGINEER_CHAT_TEMPLATE_KWARGS", None)
            client.chat([{"role": "user", "content": "hi"}])
    return completions.calls[-1].get("extra_body")


def _cfg(**kw) -> LLMModelConfig:
    base = dict(name="m", model="m-model", api_key="k", base_url="https://dgx-direct.cccc/v1", enabled=True, priority=10)
    base.update(kw)
    return LLMModelConfig(**base)


class TestExplicitSwitch(unittest.TestCase):
    def test_explicit_false_on_direct_endpoint(self):
        body = _extra_body_for(_cfg(enable_thinking=False))
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": False}})

    def test_explicit_true_overrides_implicit_dashscope_rule(self):
        # dashscope 隐式规则会发顶层 enable_thinking:False——显式 True 必须压过它
        body = _extra_body_for(_cfg(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", enable_thinking=True))
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": True}})

    def test_explicit_overrides_env_kwargs(self):
        body = _extra_body_for(_cfg(enable_thinking=True), env='{"other": 1}')
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": True}})


class TestBackwardCompat(unittest.TestCase):
    def test_none_keeps_implicit_angineer_rule(self):
        body = _extra_body_for(_cfg(base_url="https://angineer.cn/api/llm", enable_thinking=None))
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": False}})

    def test_none_direct_endpoint_sends_nothing(self):
        # 未声明时行为与旧版一致：直连不发任何 thinking 相关参数
        body = _extra_body_for(_cfg())
        self.assertIn(body, (None, {}))

    def test_none_honors_env_kwargs(self):
        body = _extra_body_for(_cfg(), env='{"enable_thinking": false}')
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": False}})


class TestLoaderEnableThinking(unittest.TestCase):
    """LLM_CONFIGS 里的 enable_thinking 必须真的落到配置对象上（缺陷 A 回归，2026-09-12）。

    缺陷 A 漏到今天的原因：此前没有任何测试走 load_llm_models_from_env()，全是手工构造
    LLMModelConfig，正好绕过「构造时漏传 enable_thinking」的那一行。
    """

    def _load(self, models):
        with mock.patch.dict(os.environ, {"LLM_CONFIGS": json.dumps(models)}, clear=False):
            return {m.name: m for m in load_llm_models_from_env()}

    def test_declared_false_true_and_absent(self):
        loaded = self._load([
            {"name": "off", "model": "qwen3.8-flash-next", "base_url": "http://dgx:8888/v1", "enable_thinking": False},
            {"name": "on", "model": "qwen3.8-flash-next", "base_url": "http://dgx:8888/v1", "enable_thinking": True},
            {"name": "absent", "model": "qwen3.8-flash-next", "base_url": "http://dgx:8888/v1"},
        ])
        self.assertIs(loaded["off"].enable_thinking, False)
        self.assertIs(loaded["on"].enable_thinking, True)
        self.assertIsNone(loaded["absent"].enable_thinking)

    def test_string_forms_normalized(self):
        loaded = self._load([
            {"name": "s1", "model": "m", "base_url": "http://x:8888/v1", "enable_thinking": "false"},
            {"name": "s2", "model": "m", "base_url": "http://x:8888/v1", "enable_thinking": "true"},
            {"name": "s3", "model": "m", "base_url": "http://x:8888/v1", "enable_thinking": "YES"},
        ])
        self.assertIs(loaded["s1"].enable_thinking, False)
        self.assertIs(loaded["s2"].enable_thinking, True)
        self.assertIs(loaded["s3"].enable_thinking, True)

    def test_unrecognized_value_degrades_to_none_without_raising(self):
        loaded = self._load([
            {"name": "bad", "model": "m", "base_url": "http://x:8888/v1", "enable_thinking": "nope"},
        ])
        self.assertIsNone(loaded["bad"].enable_thinking)

    def test_declared_switch_reaches_extra_body(self):
        # 端到端：loader 声明 → extra_body（直连端点，隐式规则一条都不命中）
        loaded = self._load([{
            "name": "dgx-direct", "model": "qwen3.8-flash-next", "api_key": "k",
            "base_url": "http://dgx:8888/v1", "enable_thinking": False,
        }])
        body = _extra_body_for(loaded["dgx-direct"])
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": False}})


class TestEnvKwargsTolerance(unittest.TestCase):
    """ANGINEER_CHAT_TEMPLATE_KWARGS 空值/非法 JSON 不得打挂请求（缺陷 B 回归）。"""

    def test_empty_string_treated_as_unset_and_falls_through(self):
        # 空串：不能抛异常；落到隐式规则（angineer.cn → false）
        body = _extra_body_for(_cfg(base_url="https://angineer.cn/api/llm"), env="")
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": False}})

    def test_whitespace_only_treated_as_unset(self):
        body = _extra_body_for(_cfg(), env="   ")
        self.assertIn(body, (None, {}))

    def test_invalid_json_degrades_without_raising(self):
        body = _extra_body_for(_cfg(), env="not-json")
        self.assertIn(body, (None, {}))

    def test_valid_json_still_honored(self):
        body = _extra_body_for(_cfg(), env='{"enable_thinking": false}')
        self.assertEqual(body, {"chat_template_kwargs": {"enable_thinking": False}})


if __name__ == "__main__":
    unittest.main()

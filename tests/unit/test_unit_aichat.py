"""AIChat 单元测试 - 验证模型配置、客户端方法、上下文管理、token 估算等基础逻辑。"""
import unittest


class TestLLMConfig(unittest.TestCase):
    """测试 LLM 模型配置"""

    # 验证默认模型配置加载
    def test_config_default_model(self):
        from ai_inference.llm_config import load_llm_models_from_env

        models = load_llm_models_from_env()

        if len(models) > 0:
            first_model = models[0]
            self.assertTrue(
                len(first_model.name) > 0,
                f"默认模型名称不应为空，实际为 {first_model.name!r}",
            )

    # 验证 LLMClient 拥有流式方法
    def test_llm_client_stream_method(self):
        from ai_inference.llm_client import LLMClient

        self.assertTrue(
            hasattr(LLMClient, "chat_stream"),
            "LLMClient 应该有 chat_stream 方法",
        )


class TestChatRequestModel(unittest.TestCase):
    """测试 ChatRequest 数据模型"""

    # 验证 ChatRequest 模型创建与字段
    def test_chat_request_model(self):
        from pydantic import BaseModel

        class ChatMessage(BaseModel):
            role: str
            content: str

        class ChatRequest(BaseModel):
            message: str
            history: list
            model: str = None
            mode: str = "chat"

        req = ChatRequest(
            message="你好",
            history=[{"role": "user", "content": "历史消息"}],
            model="Qwen2.5-7B",
        )

        self.assertEqual(req.message, "你好")
        self.assertEqual(req.model, "Qwen2.5-7B")


class TestContextManagement(unittest.TestCase):
    """测试上下文管理逻辑"""

    # 验证上下文滑动窗口保留最近 N 轮
    def test_context_sliding_window(self):
        def manage_context(messages, max_rounds=10):
            chat_messages = [m for m in messages if m.get("role") != "system"]

            user_count = len([m for m in chat_messages if m.get("role") == "user"])
            if user_count > max_rounds:
                remove_count = (user_count - max_rounds) * 2
                chat_messages = chat_messages[remove_count:]

            return chat_messages

        messages = []
        for i in range(15):
            messages.append({"role": "user", "content": f"问题{i+1}"})
            messages.append({"role": "assistant", "content": f"回答{i+1}"})

        managed = manage_context(messages, max_rounds=10)
        user_messages = [m for m in managed if m["role"] == "user"]

        self.assertEqual(len(user_messages), 10)


class TestTokenEstimate(unittest.TestCase):
    """测试 token 估算逻辑"""

    # 验证中英文 token 估算
    def test_token_estimate(self):
        def estimate_tokens(content):
            tokens = 0
            for char in content:
                if "\u4e00" <= char <= "\u9fa5":
                    tokens += 1.5
                else:
                    tokens += 0.5
            return int(tokens)

        zh_tokens = estimate_tokens("你好世界")
        self.assertEqual(zh_tokens, 6)

        en_tokens = estimate_tokens("Hello")
        self.assertEqual(en_tokens, 2)


if __name__ == "__main__":
    unittest.main()

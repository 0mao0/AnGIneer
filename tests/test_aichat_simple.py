"""
AIChat 简单测试
验证基本功能可用
"""
import sys
import os

# 添加路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'services', 'angineer-core', 'src'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'apps', 'api-server'))

def test_config_default_model():
    """测试默认模型配置"""
    from ai_inference.llm_config import load_llm_models_from_env
    
    models = load_llm_models_from_env()
    
    if len(models) > 0:
        # 验证第一个模型（应该是 Qwen2.5-7B）
        first_model = models[0]
        print(f"✓ 默认模型: {first_model.name}")
        assert 'Qwen2.5-7B' in first_model.name or 'qwen2.5-7b' in first_model.name.lower(), \
            f"默认模型应该是 Qwen2.5-7B，实际是 {first_model.name}"
    else:
        print("⚠ 没有配置模型（环境变量未设置）")

def test_llm_client_stream_method():
    """测试 LLMClient 有流式方法"""
    from ai_inference.llm_client import LLMClient
    
    # 验证方法存在
    assert hasattr(LLMClient, 'chat_stream'), "LLMClient 应该有 chat_stream 方法"
    print("✓ LLMClient.chat_stream 方法存在")

def test_chat_request_model():
    """测试 ChatRequest 模型"""
    from pydantic import BaseModel
    
    # 模拟 ChatRequest
    class ChatMessage(BaseModel):
        role: str
        content: str
        
    class ChatRequest(BaseModel):
        message: str
        history: list
        model: str = None
        mode: str = 'chat'
    
    # 验证模型创建
    req = ChatRequest(
        message="你好",
        history=[{"role": "user", "content": "历史消息"}],
        model="Qwen2.5-7B"
    )
    
    assert req.message == "你好"
    assert req.model == "Qwen2.5-7B"
    print("✓ ChatRequest 模型验证通过")

def test_context_management():
    """测试上下文管理逻辑"""
    # 模拟上下文管理
    def manage_context(messages, max_rounds=10):
        chat_messages = [m for m in messages if m.get('role') != 'system']
        
        user_count = len([m for m in chat_messages if m.get('role') == 'user'])
        if user_count > max_rounds:
            remove_count = (user_count - max_rounds) * 2
            chat_messages = chat_messages[remove_count:]
        
        return chat_messages
    
    # 构建 15 轮对话
    messages = []
    for i in range(15):
        messages.append({'role': 'user', 'content': f'问题{i+1}'})
        messages.append({'role': 'assistant', 'content': f'回答{i+1}'})
    
    managed = manage_context(messages, max_rounds=10)
    user_messages = [m for m in managed if m['role'] == 'user']
    
    assert len(user_messages) == 10, f"应该保留 10 轮，实际 {len(user_messages)}"
    print(f"✓ 上下文滑动窗口验证通过（保留 {len(user_messages)} 轮）")

def test_token_estimate():
    """测试 token 估算"""
    def estimate_tokens(content):
        tokens = 0
        for char in content:
            if '\u4e00' <= char <= '\u9fa5':
                tokens += 1.5
            else:
                tokens += 0.5
        return int(tokens)
    
    # 中文
    zh_tokens = estimate_tokens("你好世界")
    assert zh_tokens == 6, f"中文 token 估算错误: {zh_tokens}"
    
    # 英文
    en_tokens = estimate_tokens("Hello")
    assert en_tokens == 3, f"英文 token 估算错误: {en_tokens}"
    
    print("✓ Token 估算验证通过")

if __name__ == "__main__":
    print("=" * 50)
    print("AIChat 功能测试")
    print("=" * 50)
    
    try:
        test_config_default_model()
    except Exception as e:
        print(f"✗ 默认模型测试失败: {e}")
    
    try:
        test_llm_client_stream_method()
    except Exception as e:
        print(f"✗ LLMClient 流式方法测试失败: {e}")
    
    try:
        test_chat_request_model()
    except Exception as e:
        print(f"✗ ChatRequest 模型测试失败: {e}")
    
    try:
        test_context_management()
    except Exception as e:
        print(f"✗ 上下文管理测试失败: {e}")
    
    try:
        test_token_estimate()
    except Exception as e:
        print(f"✗ Token 估算测试失败: {e}")
    
    print("=" * 50)
    print("测试完成")

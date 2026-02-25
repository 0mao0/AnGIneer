"""
测试数据加载工具。

支持：
- 从 JSON 文件加载测试数据
- 快速确定性测试（fixture 数据）
- 集成测试（真实 LLM，需 API Key）
- 用户交互模式（用户输入或 LLM 生成）
"""
import json
import os
from typing import Dict, List, Any, Optional
from enum import Enum


class TestMode(Enum):
    """测试模式枚举。"""
    FIXTURE = "fixture"
    INTEGRATION = "integration"
    INTERACTIVE = "interactive"


class FixtureLoader:
    """测试数据加载器。"""
    
    def __init__(self, fixtures_dir: Optional[str] = None):
        """
        初始化加载器。
        
        Args:
            fixtures_dir: fixtures 目录路径，默认为 tests/fixtures
        """
        if fixtures_dir is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            fixtures_dir = os.path.join(os.path.dirname(current_dir), "fixtures")
        self.fixtures_dir = fixtures_dir
    
    def load_json(self, filename: str) -> Dict[str, Any]:
        """
        加载 JSON 文件。
        
        Args:
            filename: JSON 文件名
        
        Returns:
            解析后的字典
        
        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON 解析失败
        """
        filepath = os.path.join(self.fixtures_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def get_samples(self, filename: str) -> List[Dict[str, Any]]:
        """
        获取样本列表。
        
        Args:
            filename: JSON 文件名
        
        Returns:
            样本列表
        """
        data = self.load_json(filename)
        return data.get("samples", [])
    
    def get_sample_by_id(self, filename: str, sample_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取特定样本。
        
        Args:
            filename: JSON 文件名
            sample_id: 样本 ID
        
        Returns:
            样本字典，未找到返回 None
        """
        samples = self.get_samples(filename)
        for sample in samples:
            if sample.get("id") == sample_id:
                return sample
        return None
    
    def get_intent_response(self, sample_id: str) -> Optional[Dict[str, Any]]:
        """获取意图分类响应样本。"""
        return self.get_sample_by_id("intent_responses.json", sample_id)
    
    def get_action_response(self, sample_id: str) -> Optional[Dict[str, Any]]:
        """获取步骤执行动作响应样本。"""
        return self.get_sample_by_id("action_responses.json", sample_id)
    
    def get_args_extract_response(self, sample_id: str) -> Optional[Dict[str, Any]]:
        """获取参数提取响应样本。"""
        return self.get_sample_by_id("args_extract_responses.json", sample_id)


class MockLLMClient:
    """Mock LLM 客户端，用于确定性测试。"""
    
    def __init__(self, responses: Dict[str, Any]):
        """
        初始化 Mock 客户端。
        
        Args:
            responses: 预设响应字典，key 为 prompt hash 或调用顺序
        """
        self.responses = responses
        self.call_count = 0
        self.call_history: List[Dict[str, Any]] = []
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        mode: str = "instruct",
        config_name: str = None,
        **kwargs
    ) -> str:
        """
        模拟 chat 调用。
        
        Args:
            messages: 消息列表
            mode: 运行模式
            config_name: 配置名称
        
        Returns:
            预设的响应字符串
        """
        self.call_count += 1
        self.call_history.append({
            "messages": messages,
            "mode": mode,
            "config_name": config_name,
            "kwargs": kwargs
        })
        
        key = str(self.call_count)
        if key in self.responses:
            response = self.responses[key]
            if isinstance(response, dict):
                return json.dumps(response, ensure_ascii=False)
            return response
        
        if "default" in self.responses:
            response = self.responses["default"]
            if isinstance(response, dict):
                return json.dumps(response, ensure_ascii=False)
            return response
        
        return json.dumps({})
    
    def reset(self):
        """重置调用计数和历史。"""
        self.call_count = 0
        self.call_history = []


def create_fixture_loader() -> FixtureLoader:
    """创建 FixtureLoader 实例。"""
    return FixtureLoader()


def create_mock_llm_client(responses: Dict[str, Any]) -> MockLLMClient:
    """
    创建 Mock LLM 客户端。
    
    Args:
        responses: 响应字典，key 为调用顺序号或 "default"
    
    Returns:
        MockLLMClient 实例
    
    Example:
        >>> client = create_mock_llm_client({
        ...     "1": {"sop_id": "math_sop", "reason": "数学计算"},
        ...     "2": {"args": {"expression": "25 * 4"}},
        ...     "default": {}
        ... })
    """
    return MockLLMClient(responses)

"""
交互式测试工具，支持用户选择测试数据来源。

使用方法:
    python tests/interactive_test.py [--mode MODE] [--fixture FIXTURE]

参数:
    --mode: 测试模式
        - fixture: 使用预设的 fixture 数据（快速、确定性）
        - live: 调用真实 LLM（需要 API Key）
        - interactive: 用户交互模式，用户可输入或让 LLM 生成
    --fixture: 指定 fixture 文件名（默认使用默认 fixture）
"""
import os
import sys
import json
import argparse
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/engtools/src")))

from angineer_core.core import IntentClassifier, Dispatcher, Memory
from angineer_core.standard import SOP, Step
from angineer_core.infra import get_logger, extract_json_from_text, ParseError
from sop_core.sop_loader import SopLoader

logger = get_logger(__name__)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class FixtureManager:
    """Fixture 数据管理器。"""
    
    def __init__(self, fixtures_dir: str = FIXTURES_DIR):
        self.fixtures_dir = fixtures_dir
        self._ensure_fixtures_dir()
    
    def _ensure_fixtures_dir(self):
        """确保 fixture 目录存在。"""
        if not os.path.exists(self.fixtures_dir):
            os.makedirs(self.fixtures_dir)
    
    def list_fixtures(self) -> List[str]:
        """列出所有可用的 fixture 文件。"""
        if not os.path.exists(self.fixtures_dir):
            return []
        return [f for f in os.listdir(self.fixtures_dir) if f.endswith('.json')]
    
    def load_fixture(self, name: str) -> Dict[str, Any]:
        """加载指定的 fixture 文件。"""
        if not name.endswith('.json'):
            name += '.json'
        
        path = os.path.join(self.fixtures_dir, name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Fixture 文件不存在: {path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save_fixture(self, name: str, data: Dict[str, Any]):
        """保存数据到 fixture 文件。"""
        if not name.endswith('.json'):
            name += '.json'
        
        path = os.path.join(self.fixtures_dir, name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Fixture 已保存: {path}")


class MockLLMClient:
    """模拟 LLM 客户端，使用 fixture 数据。"""
    
    def __init__(self, fixture_data: Dict[str, Any]):
        self.fixture_data = fixture_data
        self.call_count = 0
    
    def chat(self, messages: list, **kwargs) -> str:
        """返回 fixture 中的响应。"""
        self.call_count += 1
        
        if 'responses' in self.fixture_data:
            responses = self.fixture_data['responses']
            if self.call_count <= len(responses):
                return responses[self.call_count - 1]
        
        if 'default_response' in self.fixture_data:
            return self.fixture_data['default_response']
        
        return '{"error": "no fixture response available"}'


class InteractiveTestRunner:
    """交互式测试运行器。"""
    
    def __init__(self, mode: str = "fixture", fixture_name: str = "default"):
        self.mode = mode
        self.fixture_name = fixture_name
        self.fixture_manager = FixtureManager()
        self.sop_loader = None
    
    def setup(self):
        """初始化测试环境。"""
        sop_dir = os.path.join(os.path.dirname(__file__), "../data/sops/raw")
        self.sop_loader = SopLoader(sop_dir)
        logger.info(f"测试环境初始化完成，模式: {self.mode}")
    
    def run_intent_classification_test(self, user_query: str) -> Dict[str, Any]:
        """
        运行意图分类测试。
        
        Args:
            user_query: 用户查询
        
        Returns:
            测试结果
        """
        sops = self.sop_loader.load_all()
        
        if self.mode == "fixture":
            fixture_data = self.fixture_manager.load_fixture(self.fixture_name)
            mock_client = MockLLMClient(fixture_data)
            classifier = IntentClassifier(sops, llm_client=mock_client)
        else:
            from angineer_core.infra import get_llm_client
            classifier = IntentClassifier(sops, llm_client=get_llm_client())
        
        sop, args, reason = classifier.route(user_query)
        
        return {
            "query": user_query,
            "matched_sop": sop.id if sop else None,
            "extracted_args": args,
            "reason": reason
        }
    
    def run_memory_test(self, test_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        运行内存解析测试。
        
        Args:
            test_data: 测试数据，包含 blackboard 和要解析的值
        
        Returns:
            测试结果
        """
        memory = Memory()
        memory.update_context(test_data.get("blackboard", {}))
        
        results = {}
        for key, value in test_data.get("test_values", {}).items():
            try:
                resolved = memory.resolve_value(value)
                results[key] = {
                    "input": value,
                    "output": resolved,
                    "status": "success"
                }
            except Exception as e:
                results[key] = {
                    "input": value,
                    "output": None,
                    "status": "error",
                    "error": str(e)
                }
        
        return results
    
    def interactive_mode(self):
        """交互式测试模式。"""
        print("\n" + "=" * 60)
        print("AnGIneer 交互式测试工具")
        print("=" * 60)
        print(f"当前模式: {self.mode}")
        print(f"Fixture: {self.fixture_name}")
        print("-" * 60)
        
        while True:
            print("\n选择测试类型:")
            print("1. 意图分类测试")
            print("2. 内存解析测试")
            print("3. 查看可用 Fixture")
            print("4. 切换测试模式")
            print("5. 退出")
            
            choice = input("\n请输入选项 (1-5): ").strip()
            
            if choice == "1":
                query = input("请输入用户查询: ").strip()
                if query:
                    result = self.run_intent_classification_test(query)
                    print("\n测试结果:")
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                    
                    if self.mode == "live":
                        save = input("\n是否保存为 Fixture? (y/n): ").strip().lower()
                        if save == 'y':
                            name = input("请输入 Fixture 名称: ").strip()
                            if name:
                                self.fixture_manager.save_fixture(name, {
                                    "query": query,
                                    "result": result
                                })
            
            elif choice == "2":
                print("\n输入黑板数据 (JSON 格式，空行结束):")
                lines = []
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
                
                try:
                    blackboard = json.loads('\n'.join(lines)) if lines else {}
                except json.JSONDecodeError:
                    print("JSON 解析错误，使用空黑板")
                    blackboard = {}
                
                print("\n输入要解析的值 (JSON 格式):")
                try:
                    test_values = json.loads(input())
                except json.JSONDecodeError:
                    print("JSON 解析错误，使用默认测试值")
                    test_values = {"test": "${user_query}"}
                
                result = self.run_memory_test({
                    "blackboard": blackboard,
                    "test_values": test_values
                })
                print("\n测试结果:")
                print(json.dumps(result, ensure_ascii=False, indent=2))
            
            elif choice == "3":
                fixtures = self.fixture_manager.list_fixtures()
                print("\n可用的 Fixture:")
                for f in fixtures:
                    print(f"  - {f}")
                if not fixtures:
                    print("  (无)")
            
            elif choice == "4":
                print("\n选择模式:")
                print("1. fixture - 使用预设数据")
                print("2. live - 调用真实 LLM")
                mode_choice = input("请输入选项 (1-2): ").strip()
                if mode_choice == "1":
                    self.mode = "fixture"
                    name = input("请输入 Fixture 名称 (默认: default): ").strip()
                    self.fixture_name = name or "default"
                elif mode_choice == "2":
                    self.mode = "live"
                print(f"已切换到模式: {self.mode}")
            
            elif choice == "5":
                print("退出测试工具")
                break
            
            else:
                print("无效选项，请重新输入")


def create_default_fixtures():
    """创建默认的 fixture 文件。"""
    fixture_manager = FixtureManager()
    
    default_fixture = {
        "description": "默认测试 fixture",
        "responses": [
            json.dumps({"sop_id": "math_sop", "reason": "用户想要进行数学计算"}, ensure_ascii=False),
            json.dumps({"args": {"expression": "25 * 4"}}, ensure_ascii=False)
        ],
        "default_response": '{"sop_id": null, "reason": "无法识别意图"}'
    }
    fixture_manager.save_fixture("default", default_fixture)
    
    intent_fixture = {
        "description": "意图分类测试 fixture",
        "responses": [
            json.dumps({"sop_id": "航道通航底高程", "reason": "用户询问航道通航底高程计算"}, ensure_ascii=False),
            json.dumps({"args": {"船型": "油船", "吨级": "100000", "土质": "岩石"}}, ensure_ascii=False)
        ]
    }
    fixture_manager.save_fixture("intent_navigation", intent_fixture)
    
    print("默认 fixture 文件已创建")


def main():
    parser = argparse.ArgumentParser(description="AnGIneer 交互式测试工具")
    parser.add_argument(
        "--mode",
        choices=["fixture", "live", "interactive"],
        default="interactive",
        help="测试模式"
    )
    parser.add_argument(
        "--fixture",
        default="default",
        help="Fixture 文件名"
    )
    parser.add_argument(
        "--create-fixtures",
        action="store_true",
        help="创建默认 fixture 文件"
    )
    
    args = parser.parse_args()
    
    if args.create_fixtures:
        create_default_fixtures()
        return
    
    runner = InteractiveTestRunner(mode=args.mode, fixture_name=args.fixture)
    runner.setup()
    
    if args.mode == "interactive":
        runner.interactive_mode()
    else:
        print(f"\n运行模式: {args.mode}")
        print("请使用 --mode interactive 进入交互模式")


if __name__ == "__main__":
    main()

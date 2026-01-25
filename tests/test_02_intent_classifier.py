import unittest
import os
import sys
import json

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.agents import IntentClassifier
from src.core.sop_loader import SopLoader
from src.tools import ToolRegistry

# 定义 5 个典型测试案例，包含预期结果
SAMPLE_QUERIES = [
    {
        "id": "case_1",
        "label": "代码审查 (典型)", 
        "query": "我需要对这段 Python 代码进行审查，看看有没有潜在的 Bug：\n\ndef add(a, b): return a + b",
        "expected_sop": "code_review"
    },
    {
        "id": "case_2",
        "label": "市场调研 (典型)", 
        "query": "我想了解 2025 年全球 AI 算力芯片的市场趋势和主要竞争对手",
        "expected_sop": "market_research"
    },
    {
        "id": "case_3",
        "label": "数学计算 (SOP)", 
        "query": "计算一个半径为 5.5 的圆的面积",
        "expected_sop": "math_sop",
        "expected_args_key": "expression" # 预期提取的参数 key
    },
    {
        "id": "case_4",
        "label": "跨领域指令 (高难度)", 
        "query": "帮我分析一下这个项目的源代码安全性，顺便写一份调研报告发给老板",
        "expected_sop": "code_review" # 或者是 market_research，取决于 LLM 判断，这里假设优先代码审查
    },
    {
        "id": "case_5",
        "label": "闲聊 (不触发 SOP)", 
        "query": "今天心情不错，给我讲个笑话吧",
        "expected_sop": None # 应该返回 None 或闲聊处理
    },
    {
        "id": "case_all",
        "label": "执行全部路由测试",
        "query": "all"
    }
]

class TestIntentClassifier(unittest.TestCase):
    def setUp(self):
        self.sop_dir = os.path.join(os.path.dirname(__file__), "../backend/sops")
        self.loader = SopLoader(self.sop_dir)
        # IntentClassifier expects a list of SOPs
        self.sops = self.loader.load_all()
        self.classifier = IntentClassifier(self.sops)

    def test_01_sop_loading_validation(self):
        """测试 1: SOP 加载与元数据验证"""
        print("\n[测试 02-1] SOP 加载与元数据验证")
        
        # 1. 验证 SOP 目录是否存在
        if not os.path.exists(self.sop_dir):
            self.fail(f"SOP 目录不存在: {self.sop_dir}")
        
        # 2. 验证是否加载了 SOP
        print(f"  -> 已加载 SOP 总数: {len(self.sops)}")
        self.assertGreater(len(self.sops), 0, "没有加载到任何 SOP，请检查 index.json 或 SOP 目录")
        
        # 3. 打印所有加载的 SOP
        print("\n  >>> 已加载 SOP 清单:")
        for sop in self.sops:
            print(f"  - ID: {sop.id}")
            print(f"    Name: {sop.name_zh} / {sop.name_en}")
            print(f"    Desc: {sop.description[:60]}...")
            
            # 基本元数据检查
            if not sop.name_zh and not sop.name_en:
                print(f"    [WARNING] SOP {sop.id} 缺少名称")
            if not sop.description:
                print(f"    [WARNING] SOP {sop.id} 缺少描述")
        
        # 4. 验证关键 SOP 是否存在
        required_sops = ["math_sop", "code_review", "market_research"]
        found_ids = [s.id for s in self.sops]
        missing = [rid for rid in required_sops if rid not in found_ids]
        
        if missing:
            print(f"\n  [WARNING] 缺少核心 SOP: {missing}")
        else:
            print("\n  [SUCCESS] 核心 SOP 全部加载。")

    def test_02_intent_routing(self):
        """测试 2: 意图识别与路由"""
        print("\n[测试 02-2] 意图识别路由测试")
        
        # 优先使用环境变量传入的 query
        env_query = os.environ.get("TEST_LLM_QUERY")
        
        if env_query and env_query != "all":
            # 如果是具体查询，尝试从 SAMPLE_QUERIES 找对应期望值
            matched_case = next((c for c in SAMPLE_QUERIES if c['query'] == env_query), None)
            expected = matched_case['expected_sop'] if matched_case else "unknown"
            
            test_cases = [{
                "id": "manual", 
                "label": "Manual Query", 
                "query": env_query, 
                "expected_sop": expected
            }]
        else:
            # 过滤掉 query="all" 的那个控制项
            test_cases = [c for c in SAMPLE_QUERIES if c['query'] != "all"]

        for case in test_cases:
            print(f"\n  --------------------------------------------------")
            print(f"  测试用例: {case['label']}")
            print(f"  Query: {case['query']}")
            
            # 执行路由
            sop, args, reason = self.classifier.route(case['query'])
            
            # 结果展示
            sop_id = sop.id if sop else "None"
            print(f"  -> 路由结果 SOP: {sop_id}")
            print(f"  -> 提取参数 Args: {json.dumps(args, ensure_ascii=False)}")
            print(f"  -> 路由原因 Reason: {reason}")
            
            # 为了兼容前端正则捕获
            if sop_id != "None":
                print(f"[AI 匹配成功] Match Success")
                print(f"匹配 SOP ID: {sop_id} | SOP_ID: {sop_id}")
                print(f"提取参数: {json.dumps(args, ensure_ascii=False)} | ARGS: {json.dumps(args, ensure_ascii=False)}")
            else:
                 print(f"未匹配到 SOP")

            # 验证逻辑
            if "expected_sop" in case and case["expected_sop"] != "unknown":
                expected = case["expected_sop"]
                if expected is None:
                    if sop is not None:
                        print(f"  [FAILURE] 预期不触发 SOP，但触发了 {sop_id}")
                    else:
                        print(f"  [SUCCESS] 正确处理为空/闲聊")
                else:
                    if sop is None:
                         print(f"  [FAILURE] 预期触发 {expected}，但未识别出 SOP")
                    elif sop.id != expected:
                        # 允许一定的歧义
                        if case.get('id') == "case_4":
                            print(f"  [NOTE] 跨领域指令路由到 {sop_id} (预期 {expected}) - 可接受")
                        else:
                            print(f"  [FAILURE] SOP ID 不匹配: 预期 {expected}, 实际 {sop_id}")
                    else:
                        print(f"  [SUCCESS] 路由正确: {expected}")

            # 特殊验证：数学计算参数
            if case.get("expected_args_key"):
                key = case["expected_args_key"]
                if key in args:
                    print(f"  [SUCCESS] 参数 {key} 提取成功: {args[key]}")
                else:
                    print(f"  [FAILURE] 缺少预期参数: {key}")

if __name__ == "__main__":
    unittest.main()

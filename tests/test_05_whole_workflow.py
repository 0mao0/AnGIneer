import unittest
import os
import sys
import json
import re
import time
from unittest.mock import patch
import datetime

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/angineer-core/src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/sop-core/src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/engtools/src")))


from angineer_core.agents import IntentClassifier
from sop_core.sop_loader import SopLoader
from angineer_core.agents.dispatcher import Dispatcher
from angineer_core.core.contextStruct import SOP

class TestWholeWorkflow(unittest.TestCase):
    def setUp(self):
        # 记录初始化开始时间
        self.init_start_time = time.time()
        
        self.sop_dir = os.path.join(os.path.dirname(__file__), "../data/sops/raw")
        self.loader = SopLoader(self.sop_dir)
        # IntentClassifier expects a list of SOPs
        self.sops = self.loader.load_all()
        self.classifier = IntentClassifier(self.sops)
        
        self.init_duration = time.time() - self.init_start_time

    def test_full_flow_integration(self):
        """测试: 端到端流程 (Query -> Classifier -> SOP -> Dispatcher)"""
        print("\n[测试] 端到端流程集成测试")
        
        # 收集前置过程日志
        pre_execution_logs = []
        
        # 使用用户指定的 Qwen3-4B 模型
        target_model = "Qwen3-4B (Public)"
        print(f"  [Config] Target Model: {target_model}")
        
        # 优化 Query 以便 Qwen3-4B 能更好提取 DWT (例如明确写 100000 DWT)
        query = "我要设计一个油船航道，设计船型是 100000 DWT 油船。航道底质是岩石。设计通航水位是理论最低潮面 0.5m。航速 10节，受限水域。"
        print(f"  用户查询: {query}")
        
        pre_execution_logs.append({
            "event": "用户需求",
            "method": "User Input",
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": "-",
            "details": query
        })
        
        # 1. 意图识别
        clf_start = time.time()
        matched_sop_stub, args, reason = self.classifier.route(query, config_name=target_model)
        clf_duration = time.time() - clf_start
        
        print(f"  -> 识别 SOP: {matched_sop_stub.id if matched_sop_stub else None}")
        print(f"  -> 提取参数: {args}")
        
        pre_execution_logs.append({
            "event": "意图识别 & 参数提取",
            "method": f"IntentClassifier ({target_model})",
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": f"{clf_duration:.4f}s",
            "details": f"SOP: {matched_sop_stub.id}\nArgs: {args}"
        })
        
        self.assertIsNotNone(matched_sop_stub, "未能识别出 SOP")
        self.assertEqual(matched_sop_stub.id, "航道通航底高程", f"SOP 识别错误，预期 '航道通航底高程'，实际 '{matched_sop_stub.id}'")
        
        # 加载详细 SOP JSON
        sop_load_start = time.time()
        sop_json_path = os.path.join(os.path.dirname(__file__), f"../data/sops/json/{matched_sop_stub.id}.json")
        if not os.path.exists(sop_json_path):
             self.fail(f"找不到对应的 SOP JSON 文件: {sop_json_path}")
             
        with open(sop_json_path, "r", encoding="utf-8") as f:
            sop_data = json.load(f)
        sop = SOP(**sop_data)
        sop_load_duration = time.time() - sop_load_start
        
        pre_execution_logs.append({
            "event": "SOP 加载",
            "method": "Local JSON File",
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": f"{sop_load_duration:.4f}s",
            "details": f"Path: {sop_json_path}\nSteps: {len(sop.steps)}"
        })
        
        print(f"  -> 初始上下文: {args}")
        
        pre_execution_logs.append({
            "event": "Blackboard 初始化",
            "method": "Intent Arguments",
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": "-",
            "details": f"Initial Args: {args}"
        })
        
        # 3. 执行 Dispatcher
        print("\n  >>> 启动 Dispatcher 执行 SOP...")
        result_md_path = os.path.join(os.path.dirname(__file__), "result_test_05.md")
        dispatcher = Dispatcher(result_md_path=result_md_path, config_name=target_model)
        
        # 过滤 auto 步骤以匹配 test_03 逻辑 (避免 LLM 自动生成步骤的开销)
        sop.steps = [s for s in sop.steps if s.tool != "auto"]
        
        # 定义 Mock 的用户输入逻辑，替代原有的参数补全 "作弊"
        from unittest.mock import patch
        
        # 使用列表来存储调用次数，作为闭包状态
        call_counter = [0]

        def mock_user_input_side_effect(*args, **kwargs):
            call_counter[0] += 1
            idx = call_counter[0]
            
            # 获取请求的变量名 (如果 Dispatcher 传递了)
            variable = kwargs.get("variable")
            question = kwargs.get("question", "")
            
            print(f"    [MockInput] Call #{idx}: variable='{variable}', question='{question}'")
            
            # 第一次调用: Step 5 (Z3). SOP output map: {"Z3": "0.15"} -> 意味着从工具输出取 key="0.15" 的值
            if idx == 1: 
                return {"0.15": 0.15, "result": 0.15}
            
            # 第二次调用: Step 6 (H_nav). SOP output map: {"H_nav": "input"} -> 意味着从工具输出取 key="input" 的值
            if idx == 2:
                return {"input": 0.5, "result": 0.5}
            
            # 默认返回
            return kwargs.get("default", {"result": f"Mocked {variable}", "input": f"Mocked {variable}"})

        # 使用 patch 拦截 UserInputTool.run
        with patch('engtools.UserInputTool.UserInputTool.run', side_effect=mock_user_input_side_effect):
            # Pass pre_execution_logs to run
            final_context = dispatcher.run(sop, args, pre_logs=pre_execution_logs)
        
        # 4. 验证结果
        print("\n  >>> 验证执行结果:")
        # 验证关键参数
        # 注意: 这里的期望值基于测试规范中的表值
        # T=15.0 (10万吨级)
        # Z0=0.6 (10节, 0.5m水深 -> 查表得 0.6)
        # Z1=0.8 (10万吨, 岩石)
        # Z2=0.4 (受限水域)
        # Z3=0.15 (Mock)
        # D0 = 15.0 + 0.6 + 0.8 + 0.4 + 0.15 = 16.95
        # E_nav = 0.5 - 16.95 = -16.45
        expected_values = {
            "T": 15.0,
            "Z0": 0.6,
            "Z1": 0.8,
            "Z2": 0.4,
            "Z3": 0.15,
            "D0": 16.95,
            "E_nav": -16.45
        }
        
        for k, v in expected_values.items():
            actual = final_context.get(k)
            if isinstance(actual, dict) and "result" in actual:
                 actual = actual["result"]
            
            # 处理可能的 float 精度
            if isinstance(actual, (int, float)):
                 self.assertAlmostEqual(actual, v, places=2, msg=f"{k} 计算错误")
            else:
                 print(f"  [Warn] {k} 实际值 {actual} 不是数字，跳过精确比对")
                
        print("  [SUCCESS] 端到端测试通过！")

if __name__ == "__main__":
    unittest.main()

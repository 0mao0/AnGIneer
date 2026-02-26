import unittest
import os
import sys
import json
import re
import time
from unittest.mock import patch
import datetime

# Add backend to path - 注意：angineer-core 必须在 engtools 之前，因为 engtools 依赖它
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/sop-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 先导入 ToolRegistry 确保 Dispatcher 能正确获取它
try:
    from engtools.BaseTool import ToolRegistry
except ImportError:
    pass

from angineer_core.core import IntentClassifier
from sop_core.sop_loader import SopLoader
from angineer_core.core import Dispatcher
from angineer_core.standard.context_models import SOP
from regression_report import build_report, emit_report

class TestWholeWorkflow(unittest.TestCase):
    def setUp(self):
        # 记录初始化开始时间
        self.init_start_time = time.time()
        
        self.sop_dir = os.path.join(os.path.dirname(__file__), "../../data/sops/raw")
        self.loader = SopLoader(self.sop_dir)
        # IntentClassifier expects a list of SOPs
        self.sops = self.loader.load_all()
        self.classifier = IntentClassifier(self.sops)
        
        self.init_duration = time.time() - self.init_start_time

    def test_full_flow_integration(self):
        """测试: 端到端流程 (Query -> Classifier -> SOP -> Dispatcher)"""
        print("\n[测试] 端到端流程集成测试")
        start_time = time.perf_counter()
        
        # 使用用户指定的 Qwen3-4B 模型
        target_model = "Qwen3-4B (Public)"
        print(f"  [Config] Target Model: {target_model}")
        
        query = "我要设计一个油船航道，设计船型是 100000 DWT 油船。航道底质是岩石。设计通航水位是理论最低潮面 0.5m。航速 10节，受限水域。水深 15m。"
        print(f"  用户查询: {query}")
        
        # 1. 意图识别
        clf_start = time.time()
        matched_sop_stub, args, reason = self.classifier.route(query, config_name=target_model)
        clf_duration = time.time() - clf_start
        
        print(f"  -> 识别 SOP: {matched_sop_stub.id if matched_sop_stub else None}")
        print(f"  -> 提取参数: {args}")
        
        self.assertIsNotNone(matched_sop_stub, "未能识别出 SOP")
        self.assertEqual(matched_sop_stub.id, "航道通航底高程", f"SOP 识别错误，预期 '航道通航底高程'，实际 '{matched_sop_stub.id}'")
        
        # 加载详细 SOP JSON
        sop_load_start = time.time()
        sop_json_path = os.path.join(os.path.dirname(__file__), f"../../data/sops/json/{matched_sop_stub.id}.json")
        if not os.path.exists(sop_json_path):
             self.fail(f"找不到对应的 SOP JSON 文件: {sop_json_path}")
             
        with open(sop_json_path, "r", encoding="utf-8") as f:
            sop_data = json.load(f)
        sop = SOP(**sop_data)
        sop_load_duration = time.time() - sop_load_start
        
        print(f"  -> 初始上下文: {args}")
        required_keys = (sop.blackboard or {}).get("required") or []
        missing_keys = [k for k in required_keys if k not in args]
        self.assertFalse(missing_keys, f"缺少必要参数: {missing_keys}")
        
        # 3. 执行 Dispatcher
        print("\n  >>> 启动 Dispatcher 执行 SOP...")
        result_md_path = os.path.join(os.path.dirname(__file__), "result_test_05.md")
        dispatcher = Dispatcher(result_md_path=result_md_path, config_name=target_model)
        
        # 过滤 auto 步骤以匹配 test_03 逻辑 (避免 LLM 自动生成步骤的开销)
        sop.steps = [s for s in sop.steps if s.tool != "auto"]
        
        call_counter = [0]

        def mock_user_input_side_effect(*args, **kwargs):
            call_counter[0] += 1
            idx = call_counter[0]
            
            # 获取请求的变量名 (如果 Dispatcher 传递了)
            variable = kwargs.get("variable")
            question = kwargs.get("question", "")
            
            print(f"    [MockInput] Call #{idx}: variable='{variable}', question='{question}'")
            
            # 只 mock H_nav 的用户输入
            if variable == "H_nav" or "通航水位" in question:
                h_nav = kwargs.get("H_nav", 0.5)
                return {"input": h_nav, "result": h_nav}
            
            return kwargs.get("default", {"result": f"Mocked {variable}", "input": f"Mocked {variable}"})

        # 使用 patch 拦截 UserInputTool.run
        with patch('engtools.UserInputTool.UserInputTool.run', side_effect=mock_user_input_side_effect):
            final_context = dispatcher.run(sop, args)
        
        # 4. 打印结果供人工判断
        print("\n  >>> 执行结果:")
        for k, v in final_context.items():
            print(f"    {k}: {v}")
                
        print("  [SUCCESS] 端到端测试执行完成！")
        case_status = "ok"
        report_cases = [{
            "id": "full_flow",
            "label": "端到端流程",
            "status": case_status,
            "details": {
                "query": query,
                "matched_sop": matched_sop_stub.id if matched_sop_stub else None,
                "final_context": final_context
            }
        }]
        summary = {
            "cases": len(report_cases),
            "failures": len([c for c in report_cases if c["status"] == "fail"]),
            "duration": round(time.perf_counter() - start_time, 4)
        }
        emit_report(build_report("test_05_whole_workflow", report_cases, summary=summary))

if __name__ == "__main__":
    unittest.main()

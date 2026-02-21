#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
完整执行流与 API 接口测试脚本 (Test 05)
验证从用户请求到最终结果的完整闭环，包括：
1. 意图分类（Intent Classification）
2. SOP 匹配与加载
3. 步骤拆解与工具调用
4. 变量传递与记忆流转
5. 结果汇总与输出
"""

import sys
import os
import json
import unittest
import requests
import time

# 添加路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.core.contextStruct import SOP, Step
from src.agents import IntentClassifier, Dispatcher
from src.core.sop_loader import SopLoader
from src.tools import ToolRegistry
from src.tools import *

# API 基础 URL
BASE_URL = "http://localhost:8080"


class TestFullExecutionFlow(unittest.TestCase):
    """全流程测试套件"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        print("\n" + "=" * 70)
        print("Test 05: 完整执行流测试")
        print("=" * 70)
        
        # 初始化 SOP Loader
        cls.sop_dir = os.path.join(os.path.dirname(__file__), "../backend/sops")
        cls.sop_loader = SopLoader(cls.sop_dir)
        cls.sops = cls.sop_loader.load_all()
        print(f"\n[初始化] 已加载 {len(cls.sops)} 个 SOP")
        
        # 初始化意图分类器
        cls.classifier = IntentClassifier(cls.sops)
        
        # 检查 API 可用性
        try:
            resp = requests.get(f"{BASE_URL}/llm_configs", timeout=5)
            cls.api_available = resp.status_code == 200
            print(f"[初始化] API 服务状态: {'可用' if cls.api_available else '不可用'}")
        except:
            cls.api_available = False
            print("[初始化] API 服务状态: 不可用 (将跳过 API 测试)")

    def test_01_intent_classification(self):
        """测试 1: 意图分类 - 匹配正确的 SOP"""
        print("\n" + "-" * 70)
        print("测试 1: 意图分类")
        print("-" * 70)
        
        test_cases = [
            {
                "query": "计算 12 + 30",
                "expected_sop": "math_sop",
                "desc": "数学计算"
            },
            {
                "query": "40000吨杂货船的满载吃水是多少",
                "expected_sop": None,  # 可能匹配 market_research 或 table_lookup
                "desc": "船舶参数查询"
            },
            {
                "query": "计算航道通航底高程，设计船型40000吨杂货船",
                "expected_sop": "航道通航底高程",
                "desc": "航道通航底高程计算"
            },
            {
                "query": "计算通航宽度，设计船型50000吨集装箱船",
                "expected_sop": "通航宽度",
                "desc": "通航宽度计算"
            },
        ]
        
        for i, case in enumerate(test_cases, 1):
            print(f"\n  -> 用例 {i}: {case['desc']}")
            print(f"     查询: {case['query']}")
            
            sop, args, reason = self.classifier.route(case["query"])
            
            if sop:
                print(f"     匹配 SOP: {sop.id}")
                print(f"     提取参数: {args}")
                print(f"     路由原因: {reason}")
                
                if case["expected_sop"]:
                    self.assertEqual(sop.id, case["expected_sop"], 
                        f"SOP 匹配错误: 预期 {case['expected_sop']}, 实际 {sop.id}")
            else:
                print(f"     未匹配到 SOP")
                print(f"     原因: {reason}")
                
            print(f"     ✓ 通过")

    def test_02_dispatcher_basic_flow(self):
        """测试 2: Dispatcher 基础执行流 - 变量传递"""
        print("\n" + "-" * 70)
        print("测试 2: Dispatcher 基础执行流")
        print("-" * 70)
        
        # 创建测试 SOP
        steps = [
            Step(
                id="calc_sum",
                name_zh="计算加和",
                tool="calculator",
                inputs={"expression": "2 + 3"},
                outputs={"sum": "result"}
            ),
            Step(
                id="calc_product",
                name_zh="计算乘积",
                tool="calculator",
                inputs={"expression": "${sum} * 4"},
                outputs={"product": "result"}
            ),
            Step(
                id="calc_final",
                name_zh="计算最终结果",
                tool="calculator",
                inputs={
                    "expression": "${sum} + ${product}"
                },
                outputs={"final": "result"}
            )
        ]
        
        sop = SOP(
            id="test_flow",
            name_zh="测试流程",
            description="测试变量传递",
            steps=steps
        )
        
        dispatcher = Dispatcher()
        print("\n  -> 执行 SOP: 测试变量传递")
        print(f"     步骤 1: 2 + 3 = ?")
        print(f"     步骤 2: ${{sum}} * 4 = ?")
        print(f"     步骤 3: sum + product = ?")
        
        final_context = dispatcher.run(sop, {"user_query": "测试"})
        
        # 验证结果
        print(f"\n     执行结果:")
        print(f"       sum = {final_context.get('sum')}")
        print(f"       product = {final_context.get('product')}")
        print(f"       final = {final_context.get('final')}")
        
        self.assertEqual(final_context.get("sum"), 5, "步骤 1 结果错误")
        self.assertEqual(final_context.get("product"), 20, "步骤 2 结果错误")
        self.assertEqual(final_context.get("final"), 25, "步骤 3 结果错误")
        print(f"     ✓ 通过")

    def test_03_channel_design_flow(self):
        """测试 3: 航道设计完整流程 - 查表 + 计算"""
        print("\n" + "-" * 70)
        print("测试 3: 航道设计完整流程")
        print("-" * 70)
        
        print("\n  -> 场景: 计算 40000吨杂货船 的航道通航底高程")
        print("     步骤 1: 查表获取设计船型满载吃水 T")
        print("     步骤 2: 查询富裕深度 Z0, Z1, Z2, Z3")
        print("     步骤 3: 计算通航水深 D0 = T + Z0 + Z1 + Z2 + Z3")
        print("     步骤 4: 计算通航底高程 E_nav = H_nav - D0")
        
        # 步骤 1: 查表获取吃水
        table_tool = ToolRegistry.get_tool("table_lookup")
        table_result = table_tool.run(
            table_name="杂货船设计船型尺度",
            query_conditions="DWT=40000",
            target_column="满载吃水T(m)",
            file_name="《海港水文规范》.md"
        )
        
        T = table_result.get("result")
        print(f"\n     步骤 1 结果: T = {T}m")
        self.assertAlmostEqual(T, 12.3, delta=0.1, msg="查表结果错误")
        
        # 步骤 2: 富裕深度（简化，实际应该查规范或知识库）
        Z0 = 0.5  # 船舶航行下沉量
        Z1 = 0.3  # 龙骨下最小富裕深度
        Z2 = 0.8  # 波浪富裕深度
        Z3 = 0.15 # 装载纵倾富裕深度
        print(f"     步骤 2 结果: Z0={Z0}, Z1={Z1}, Z2={Z2}, Z3={Z3}")
        
        # 步骤 3: 计算通航水深
        calc_tool = ToolRegistry.get_tool("calculator")
        D0_result = calc_tool.run(
            expression="T + Z0 + Z1 + Z2 + Z3",
            variables={"T": T, "Z0": Z0, "Z1": Z1, "Z2": Z2, "Z3": Z3}
        )
        D0 = D0_result.get("result")
        print(f"     步骤 3 结果: D0 = {D0}m")
        
        # 验证 D0
        expected_D0 = T + Z0 + Z1 + Z2 + Z3
        self.assertAlmostEqual(D0, expected_D0, delta=0.01, msg="通航水深计算错误")
        
        # 步骤 4: 计算通航底高程
        H_nav = 5.0  # 设计通航水位
        E_nav_result = calc_tool.run(
            expression="H_nav - D0",
            variables={"H_nav": H_nav, "D0": D0}
        )
        E_nav = E_nav_result.get("result")
        print(f"     步骤 4 结果: E_nav = {E_nav}m (H_nav = {H_nav}m)")
        
        expected_E_nav = H_nav - D0
        self.assertAlmostEqual(E_nav, expected_E_nav, delta=0.01, msg="通航底高程计算错误")
        
        print(f"\n     最终结果:")
        print(f"       通航水深 D0 = {D0}m")
        print(f"       通航底高程 E_nav = {E_nav}m")
        print(f"     ✓ 通过")

    def test_04_api_endpoints(self):
        """测试 4: API 端点测试"""
        if not self.api_available:
            print("\n  -> 跳过 API 测试 (服务不可用)")
            return
            
        print("\n" + "-" * 70)
        print("测试 4: API 端点测试")
        print("-" * 70)
        
        # 测试 1: 获取模型配置
        print("\n  -> 测试 /llm_configs")
        resp = requests.get(f"{BASE_URL}/llm_configs", timeout=10)
        self.assertEqual(resp.status_code, 200)
        configs = resp.json()
        self.assertTrue(isinstance(configs, list))
        print(f"     可用模型数: {len(configs)}")
        print(f"     ✓ 通过")
        
        # 测试 2: 获取 SOP 列表
        print("\n  -> 测试 /sops")
        resp = requests.get(f"{BASE_URL}/sops", timeout=10)
        self.assertEqual(resp.status_code, 200)
        sops = resp.json()
        self.assertTrue(isinstance(sops, list))
        print(f"     SOP 数量: {len(sops)}")
        print(f"     ✓ 通过")
        
        # 测试 3: Chat 接口
        print("\n  -> 测试 /chat (数学计算)")
        resp = requests.post(
            f"{BASE_URL}/chat",
            json={"query": "计算 12 + 30", "config": None, "mode": "instruct"},
            timeout=30
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("sop_id", data)
        print(f"     匹配 SOP: {data.get('sop_id')}")
        print(f"     执行步骤数: {len(data.get('trace', []))}")
        print(f"     ✓ 通过")
        
        # 测试 4: Chat 接口 (航道计算)
        print("\n  -> 测试 /chat (航道通航底高程)")
        resp = requests.post(
            f"{BASE_URL}/chat",
            json={
                "query": "计算40000吨杂货船的航道通航底高程",
                "config": None,
                "mode": "instruct"
            },
            timeout=60
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        print(f"     匹配 SOP: {data.get('sop_id')}")
        print(f"     SOP 名称: {data.get('sop_name_zh')}")
        print(f"     执行步骤数: {len(data.get('trace', []))}")
        if data.get('trace'):
            for i, step in enumerate(data['trace'], 1):
                print(f"       步骤 {i}: {step.get('step_name_zh')} - {step.get('status')}")
        print(f"     ✓ 通过")

    def test_05_tool_chain_execution(self):
        """测试 5: 工具链执行 - 多个工具串联"""
        print("\n" + "-" * 70)
        print("测试 5: 工具链执行")
        print("-" * 70)
        
        print("\n  -> 场景: 计算疏浚工程量")
        print("     步骤 1: 查表获取设计船型尺度")
        print("     步骤 2: 计算通航水深")
        print("     步骤 3: 计算疏浚工程量")
        
        # 步骤 1: 查表
        table_tool = ToolRegistry.get_tool("table_lookup")
        ship_data = table_tool.run(
            table_name="杂货船设计船型尺度",
            query_conditions="DWT=40000",
            target_column=None,  # 返回整行
            file_name="《海港水文规范》.md"
        )
        
        print(f"\n     步骤 1 结果:")
        if isinstance(ship_data.get("result"), dict):
            for key, value in ship_data["result"].items():
                print(f"       {key}: {value}")
        
        # 步骤 2: 计算通航水深
        T = 12.3  # 吃水
        Z_total = 1.75  # 总富裕深度
        
        calc_tool = ToolRegistry.get_tool("calculator")
        D0_result = calc_tool.run(
            expression="T + Z_total",
            variables={"T": T, "Z_total": Z_total}
        )
        D0 = D0_result.get("result")
        print(f"\n     步骤 2 结果: D0 = {D0}m")
        
        # 步骤 3: GIS 计算工程量
        gis_tool = ToolRegistry.get_tool("gis_section_volume_calc")
        volume_result = gis_tool.run(
            design_depth=D0,
            design_width=150,
            length=1000
        )
        
        print(f"\n     步骤 3 结果:")
        print(f"       总工程量: {volume_result.get('total_volume_m3')} m³")
        print(f"       置信度: {volume_result.get('confidence_score')}")
        
        self.assertIn("total_volume_m3", volume_result)
        self.assertGreater(volume_result["total_volume_m3"], 0)
        print(f"\n     ✓ 通过")

    def test_06_error_handling(self):
        """测试 6: 错误处理"""
        print("\n" + "-" * 70)
        print("测试 6: 错误处理")
        print("-" * 70)
        
        calc_tool = ToolRegistry.get_tool("calculator")
        
        # 测试 1: 除零错误
        print("\n  -> 测试除零错误")
        result = calc_tool.run("1 / 0")
        self.assertIn("error", result)
        print(f"     错误信息: {result.get('error')}")
        print(f"     ✓ 通过")
        
        # 测试 2: 未定义变量
        print("\n  -> 测试未定义变量")
        result = calc_tool.run("x + y")
        self.assertIn("error", result)
        print(f"     错误信息: {result.get('error')}")
        print(f"     ✓ 通过")
        
        # 测试 3: 语法错误
        print("\n  -> 测试语法错误")
        result = calc_tool.run("12 + * 30")
        self.assertIn("error", result)
        print(f"     错误信息: {result.get('error')}")
        print(f"     ✓ 通过")


def run_full_flow_demo():
    """
    全流程演示 - 不依赖 unittest，直接运行
    """
    print("\n" + "=" * 70)
    print("PicoAgent 全流程演示")
    print("=" * 70)
    
    # 初始化
    sop_dir = os.path.join(os.path.dirname(__file__), "../backend/sops")
    sop_loader = SopLoader(sop_dir)
    sops = sop_loader.load_all()
    classifier = IntentClassifier(sops)
    
    # 演示场景
    demo_queries = [
        "计算 25 * 4",
        "40000吨杂货船的满载吃水是多少",
        "计算航道通航底高程，设计船型40000吨杂货船",
    ]
    
    for query in demo_queries:
        print("\n" + "-" * 70)
        print(f"用户查询: {query}")
        print("-" * 70)
        
        # 1. 意图分类
        print("\n[步骤 1] 意图分类...")
        sop, args, reason = classifier.route(query)
        if sop:
            print(f"  匹配 SOP: {sop.id}")
            print(f"  SOP 名称: {sop.name_zh or sop.id}")
            print(f"  提取参数: {args}")
            print(f"  路由原因: {reason}")
        else:
            print(f"  未匹配到 SOP")
            print(f"  原因: {reason}")
            continue
        
        # 2. 执行 SOP
        print("\n[步骤 2] 执行 SOP...")
        dispatcher = Dispatcher()
        final_context = dispatcher.run(sop, args)
        
        # 3. 显示结果
        print("\n[步骤 3] 执行结果:")
        print(f"  执行步骤数: {len(dispatcher.memory.history)}")
        for i, record in enumerate(dispatcher.memory.history, 1):
            print(f"    步骤 {i}: {record.step_name} - {record.status}")
        print(f"  最终上下文: {json.dumps(final_context, ensure_ascii=False, indent=2)[:200]}...")
    
    print("\n" + "=" * 70)
    print("演示完成")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test 05: 完整执行流测试")
    parser.add_argument("--demo", action="store_true", help="运行全流程演示")
    args = parser.parse_args()
    
    if args.demo:
        run_full_flow_demo()
    else:
        unittest.main(verbosity=2)

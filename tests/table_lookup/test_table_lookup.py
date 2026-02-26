import pytest
import sys
import os
import time
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../services/engtools/src")))

from engtools.TableTool import TableLookupTool

# 知识库目录
KB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data/knowledge_base"))

# 初始化工具
tool = TableLookupTool(knowledge_dir=KB_DIR)

# 测试用例：每个表格一个或多个测试查询
TEST_CASES = [
    # 表A.0.2-2 散货船设计船型尺度
    {
        "name": "散货船吃水查询",
        "table": "表A.0.2-2",
        "query": {"吨级": "50000"},
        "target": "满载吃水T",
        "expected_range": (12, 15),  # 期望值范围
    },
    # 表A.0.2-3 油船设计船型尺度
    {
        "name": "油船吃水查询",
        "table": "表A.0.2-3",
        "query": {"吨级": "100000"},
        "target": "满载吃水T",
        "expected_range": (14, 16),
    },
    # 表A.0.2-4 集装箱船设计船型尺度
    {
        "name": "集装箱船吃水查询",
        "table": "表A.0.2-4",
        "query": {"吨级": "100000"},
        "target": "满载吃水T",
        "expected_range": (12, 16),
    },
    # 表A.0.2-9 化学品船设计船型尺度
    {
        "name": "化学品船吃水查询",
        "table": "表A.0.2-9",
        "query": {"吨级": "50000"},
        "target": "满载吃水T",
        "expected_range": (10, 14),
    },
    # 表6.4.2-1 船舶与航道底边线间的富裕宽度
    {
        "name": "富裕宽度查询-散货船",
        "table": "表6.4.2-1",
        "query": {"船舶吨级": "100000", "船型": "散货船"},
        "target": "富裕宽度c",
    },
    # 表6.4.5-1 航行时龙骨下最小富裕深度
    {
        "name": "龙骨下富裕深度-岩石",
        "table": "表6.4.5-1",
        "query": {"吨级": "100000", "土质": "岩石"},
        "target": "龙骨下最小富裕深度 Z1",
        "expected_range": (0.6, 1.0),
    },
    # 图6.4.5 船舶航行时船体下沉值曲线
    {
        "name": "航行下沉量-10节",
        "table": "图6.4.5",
        "query": {"吨级": "100000", "航速": "10"},
        "target": "航行下沉量 Z0",
        "expected_range": (1.0, 2.0),
    },
]

class TestTableLookup:
    """表格查询单元测试"""
    
    @pytest.mark.parametrize("case", TEST_CASES, ids=lambda c: c["name"])
    def test_table_lookup(self, case):
        print(f"\n{'='*60}")
        print(f"测试: {case['name']}")
        print(f"表格: {case['table']}")
        print(f"查询条件: {case['query']}")
        print(f"目标列: {case['target']}")
        
        start = time.perf_counter()
        
        result = tool.run(
            table_name=case["table"],
            query_conditions=case["query"],
            file_name="markdown/海港总体设计规范_JTS_165-2025.md",
            target_column=case["target"]
        )
        
        elapsed = time.perf_counter() - start
        
        print(f"耗时: {elapsed:.3f}s")
        print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
        
        # 检查是否有错误
        if isinstance(result, dict):
            if "error" in result:
                print(f"❌ 错误: {result.get('error')}")
                # 检查 trace
                trace = result.get("_trace", [])
                for t in trace[-5:]:
                    print(f"   {t}")
                pytest.fail(f"查询失败: {result.get('error')}")
        
        # 如果有期望范围，检查结果
        if "expected_range" in case and isinstance(result, dict):
            # 尝试提取数值
            for key, value in result.items():
                if isinstance(value, (int, float)):
                    if case["expected_range"][0] <= value <= case["expected_range"][1]:
                        print(f"✅ 结果 {value} 在期望范围内 {case['expected_range']}")
                        return
            print(f"⚠️  结果不在期望范围内: {case['expected_range']}")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

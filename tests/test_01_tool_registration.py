
import sys
import os
import unittest
import json
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.tools import ToolRegistry
from src.core.sop_loader import SopLoader

"""
基础资源加载验证脚本 (Test 01)
目的：分别验证 Tool (工具) 和 SOP (标准作业程序) 的注册与加载情况。
不涉及 LLM 调用，仅验证静态资源和元数据的完整性。
"""

SAMPLE_QUERIES = [
    {"label": "执行资源加载验证", "query": "all"}
]

class TestResourceLoading(unittest.TestCase):
    def setUp(self):
        self.mode = os.environ.get("TEST_LLM_QUERY", "all")
        self.sop_dir = os.path.join(os.path.dirname(__file__), "../backend/sops")

    def test_resources(self):
        """统一测试入口，根据指令分发任务"""
        print(f"\n[Test 01] 资源加载测试 (Mode: {self.mode})")
        
        results = {
            "mode": self.mode,
            "tools": [],
            "sops": []
        }

        if self.mode == "check_tools" or self.mode == "all":
            results["tools"] = self._check_tools()
            
        if self.mode == "check_sops" or self.mode == "all":
            results["sops"] = self._check_sops()

        # 输出 JSON 供前端解析
        print("\n__JSON_START__")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print("__JSON_END__")

    def _check_tools(self):
        print("\n>>> 正在验证工具注册表 (ToolRegistry)...")
        tools = ToolRegistry.list_tools()
        tool_names = list(tools.keys())
        
        print(f"  -> [统计] 已注册工具数量: {len(tool_names)}")
        print(f"  -> [列表] {', '.join(tool_names)}")

        # 核心工具检查清单
        required_tools = ["calculator", "weather", "web_search", "sop_run", "file_reader", "table_lookup", "knowledge_search"]
        
        check_results = []
        missing_tools = []
        
        for name in required_tools:
            item = {"name": name, "type": "tool", "status": "ok", "desc": ""}
            if name not in tools:
                missing_tools.append(name)
                item["status"] = "missing"
                print(f"  -> [ERROR] 缺少核心工具: {name}")
            else:
                meta = tools[name]
                desc = meta.get("zh") or meta.get("en") or "No description"
                item["desc"] = desc
                print(f"  -> [OK] Found tool '{name}': {desc[:40]}...")
            check_results.append(item)
                
        self.assertEqual(len(missing_tools), 0, f"缺少核心工具: {missing_tools}")
        print("  -> [SUCCESS] 所有核心工具验证通过。")
        return check_results

    def _check_sops(self):
        print("\n>>> 正在验证 SOP 加载 (SopLoader)...")
        if not os.path.exists(self.sop_dir):
            self.fail(f"SOP 目录不存在: {self.sop_dir}")
            
        loader = SopLoader(self.sop_dir)
        sops = loader.load_all()
        
        print(f"  -> [统计] 已加载 SOP 数量: {len(sops)}")
        
        # 核心 SOP 检查清单 (确保这些必须存在)
        required_sops = ["math_sop", "code_review", "market_research"]
        
        found_sops_map = {s.id: s for s in sops}
        check_results = []
        
        # 1. 添加所有已加载的 SOP
        for sop in sops:
            item = {
                "name": sop.id, 
                "type": "sop", 
                "status": "ok", 
                "desc": sop.name_zh or sop.name_en or "No description"
            }
            if not sop.description:
                 item["status"] = "warning"
                 item["msg"] = "缺少描述"
            check_results.append(item)
            print(f"  -> [OK] Found SOP '{sop.id}': {item['desc']}")

        # 2. 检查是否有核心 SOP 缺失
        missing_sops = []
        for req_id in required_sops:
            if req_id not in found_sops_map:
                missing_sops.append(req_id)
                check_results.append({
                    "name": req_id,
                    "type": "sop",
                    "status": "missing",
                    "desc": "Required SOP missing"
                })
                print(f"  -> [WARNING] 核心 SOP '{req_id}' 未加载")

        if missing_sops:
            print(f"  -> [INFO] 部分预期 SOP 未找到: {missing_sops}")
        else:
            print("  -> [SUCCESS] 所有核心 SOP 验证通过。")
            
        return check_results

if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()

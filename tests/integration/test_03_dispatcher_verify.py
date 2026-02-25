import sys
import os
import json
from typing import Dict, Any

# Setup paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
# Add engtools to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))

from angineer_core.core import Dispatcher
from angineer_core.standard.context_models import SOP

from engtools.UserInputTool import UserInputTool
from engtools.CalculatorTool import Calculator
from engtools.TableTool import TableLookupTool
from engtools.CommonTool import Echo, WeatherTool

SOP_JSON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../..", "data", "sops", "json", "航道通航底高程.json"))
RESULT_MD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "result_test_03.md"))

def run_test():
    print(f"Loading SOP from: {SOP_JSON_PATH}")
    if not os.path.exists(SOP_JSON_PATH):
        print("Error: SOP file not found.")
        return

    with open(SOP_JSON_PATH, "r", encoding="utf-8") as f:
        sop_data = json.load(f)
    
    # Filter out 'auto' steps to avoid LLM calls in this test
    # The original test handled 'auto' by just printing a summary and skipping tool execution.
    # Dispatcher tries to use LLM for 'auto', which we want to avoid here for a simple tool test.
    sop_data["steps"] = [s for s in sop_data["steps"] if s.get("tool") != "auto"]
    
    try:
        sop = SOP(**sop_data)
    except Exception as e:
        print(f"Error parsing SOP: {e}")
        # Fallback for debugging if Pydantic validation fails
        import traceback
        traceback.print_exc()
        return

    # 题目输入
    # “我要设计一个油船航道，设计船型是 10万吨级油船。航道底质是岩石。设计通航水位是理论最低潮面 0.5m。航速 10节，受限水域。”
    initial_context = {
        "船型": "油船",
        "吨级": 100000,
        "DWT": 100000,
        "土质": "岩石",
        "H_nav": 0.5,
        "航速": 10,
        "水域条件": "受限水域",
        # 补充缺失的必要参数，避免 Dispatcher 报错或陷入死循环
        # 注意：Step 2 需要“水深”来查“Z0”。题目未给，这里给一个合理假设值。
        "水深": 22.0 
    }

    print("Initializing Dispatcher...")
    # Initialize dispatcher with the result markdown path
    dispatcher = Dispatcher(result_md_path=RESULT_MD_PATH, config_name="Qwen3-4B (Public)")
    
    print("Running SOP...")
    final_context = dispatcher.run(sop, initial_context)
    
    print("\nExecution Completed.")
    print("Final Blackboard State:")
    for k, v in final_context.items():
        print(f"{k}: {v}")
    
    print(f"\nResult log written to: {RESULT_MD_PATH}")

if __name__ == "__main__":
    run_test()

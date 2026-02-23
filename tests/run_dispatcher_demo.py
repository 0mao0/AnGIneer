import sys
import os
import json

# Ensure src can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

# Import tools to ensure registration
import src.tools

from src.core.sop_loader import SopLoader
from src.agents.dispatcher import Dispatcher

def main():
    # 1. Paths
    sop_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "sops"))
    result_md_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "result.md"))
    
    # 2. Load SOP
    print(f"Loading SOP from {sop_dir}...")
    loader = SopLoader(sop_dir)
    # Force refresh to ensure we get the latest parsing logic (LLM based)
    try:
        sop = loader.analyze_sop(
            "航道通航底高程", 
            force_refresh=True,
            config_name="Qwen3VL-30B-A3B (Private)"
        )
    except Exception as e:
        print(f"Error loading SOP: {e}")
        return

    print(f"Loaded SOP: {sop.id} with {len(sop.steps)} steps.")

    print("\n[Debug] Analyzed SOP Steps:")
    for step in sop.steps:
        print(f"  Step {step.id}: {step.name}")
        print(f"    Tool: {step.tool}")
        print(f"    Inputs: {step.inputs}")
        print(f"    Outputs: {step.outputs}")

    # 3. Initial Context
    # User input: 10万吨级油船, 岩石底质, 0.5m理论最低潮面, 10节航速, 受限水域
    initial_context = {
        "船型": "油船",
        "dwt": 100000,
        "bottom_material": "岩石",
        "nav_speed_kn": 10,
        "navigation_area": "受限水域",
        "H_nav": 0.5,  # 理论最低潮面 0.5m
        "water_depth": 20.0 # 假设水深足够
    }

    # 4. Initialize Dispatcher
    print("Initializing Dispatcher...")
    dispatcher = Dispatcher(result_md_path=result_md_path)

    # 5. Run
    print("Running Dispatcher...")
    final_context = dispatcher.run(sop, initial_context)
    
    print("Execution finished.")
    print("Final Blackboard Snapshot:")
    print(json.dumps(final_context, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

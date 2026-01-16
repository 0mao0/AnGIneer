import os
import json
import glob
from src.core.models import SOP
from src.agents import IntentRouter, Dispatcher
from src.tools import * # Load tools

def load_sops():
    sops = []
    sop_files = glob.glob("sops/*.json")
    for fpath in sop_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                sops.append(SOP(**data))
        except Exception as e:
            print(f"Error loading SOP {fpath}: {e}")
    return sops

def main():
    print("Initializing PicoAgent...")
    sops = load_sops()
    print(f"Loaded {len(sops)} SOPs: {[s.id for s in sops]}")
    
    router = IntentRouter(sops)
    dispatcher = Dispatcher()
    
    # Simulate user interaction
    queries = [
        "Please calculate 50 + 100",
        "Do a market research on AI Agents",
        "Review the code in file src/code.py",
        "I need a dredging design for a 50000 ton container ship. The channel length is 5km and the soil is mostly sand.",
        "What is the weather in Beijing?" # Should fail
    ]
    
    for query in queries:
        print("\n" + "="*50)
        print(f"User Query: {query}")
        
        # 1. Route
        sop, args = router.route(query)
        
        if not sop:
            print("No suitable SOP found.")
            continue
            
        print(f"Selected SOP: {sop.id}")
        print(f"Extracted Args: {args}")
        
        # 2. Dispatch
        final_context = dispatcher.run(sop, args)
        
        print("-" * 20)
        print("Final Context State (All keys):")
        for k, v in final_context.items():
            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()

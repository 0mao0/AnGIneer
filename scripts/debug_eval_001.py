import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "services", "angineer-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "services", "sop-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "services", "ai-inference", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "services", "docs-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "services", "engtools", "src"))

import engtools.TableTool
import engtools.CalculatorTool
import engtools.UserInputTool
import engtools.CommonTool
import engtools.ConditionalTool
import engtools.KnowledgeTool

from engtools.BaseTool import ToolRegistry
print(f"Registered tools: {list(ToolRegistry._registry.keys())}")

question_text = "某海港在部分掩护水域拟建100000 吨级矿石码头,采用东西向布置，码头 结构为沉箱结构型式，设计低水位为0.5m,极端低水位为-1.35m,波浪为ENE 向,允许停泊波 高 H4% 为 1.5m,平均周期6s,底质为含砂块状土,备淤富裕深度取0.4m。计算该码头前沿底 高程应为:(取小数点后1 位)(A)-14.9m(B)-15.0m(C)-15.4m(D)-15.7m"

print("=" * 60)
print("Step 1: Load SOP Loader")
print("=" * 60)
t0 = time.time()
from sop_core.sop_loader import SopLoader
sop_base_dir = r"d:\AI\AnGIneer\data\sops"
sop_loader = SopLoader(sop_base_dir)
sops = sop_loader.load_all()
print(f"Loaded {len(sops)} SOPs in {time.time()-t0:.2f}s")

print("\n" + "=" * 60)
print("Step 2: Intent Classification")
print("=" * 60)
t1 = time.time()
from angineer_core.classifier import IntentClassifier
classifier = IntentClassifier(sops)
intent_result = classifier.classify_intent(question_text)
print(f"Intent: level={intent_result.intent_level}, mode={intent_result.service_mode}, reason={intent_result.reason}")

print("\n" + "=" * 60)
print("Step 3: SOP Route")
print("=" * 60)
t2 = time.time()
route_result = classifier.route(question_text)
print(f"Route: sop={route_result.sop.id if route_result.sop else None}, confidence={route_result.confidence}, reason={route_result.reason}")

if route_result.sop and route_result.confidence >= 0.6:
    print("\n" + "=" * 60)
    print("Step 4: Analyze SOP")
    print("=" * 60)
    t3 = time.time()
    sop_full = sop_loader.analyze_sop(route_result.sop.id, prefer_llm=False)
    print(f"SOP: {len(sop_full.steps)} steps")

    print("\n" + "=" * 60)
    print("Step 5: Execute SOP (run_sop)")
    print("=" * 60)
    t4 = time.time()
    from angineer_core.dispatcher import Dispatcher
    sop_dispatcher = Dispatcher()
    initial_context = {"user_query": question_text}
    initial_context.update(route_result.args)
    final_context = sop_dispatcher.run_sop(sop_full, initial_context)
    elapsed = time.time() - t4
    print(f"SOP execution done in {elapsed:.2f}s")
    print(f"Final context:")
    for k, v in final_context.items():
        print(f"  {k} = {v}")
    answer = final_context.get("answer", final_context.get("E_bed", ""))
    print(f"\nANSWER: {str(answer)[:500]}")

print(f"\nTOTAL TIME: {time.time()-t0:.2f}s")


import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.sop_loader import SopLoader
from backend.src.agents import IntentClassifier, Dispatcher
from backend.src.tools import ToolRegistry

# Mock the LLM client to prevent network timeouts and usage
@patch("backend.src.core.llm.llm_client")
class TestPicoAgentAll(unittest.TestCase):
    """
    Comprehensive Test Suite for PicoAgent.
    Covers: SOP Loading, Routing, Dispatching, Hybrid Execution, and Tool Usage.
    """
    
    @classmethod
    def setUpClass(cls):
        print("\n>>> [Test] Initializing Full System Test Environment...")
        cls.sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        cls.loader = SopLoader(cls.sop_dir)
        cls.sops = cls.loader.load_all()
        print(f">>> [Loader] Loaded {len(cls.sops)} SOPs from index.")
        
    def test_01_tool_registration(self, mock_llm):
        """Verify all critical tools are registered."""
        print("\n[Test 01] Verifying Tool Registration...")
        tools = ToolRegistry.list_tools()
        self.assertIn("table_lookup", tools)
        self.assertIn("knowledge_search", tools)
        self.assertIn("calculator", tools)
        print("  -> All core tools (TableLookup, KnowledgeSearch, Calculator) found.")
        
    def test_02_intent_classifier(self, mock_llm):
        """Test if Classifier can correctly identify SOP from user query."""
        print("\n[Test 02] Testing Intent Classifier...")
        
        # Mock Classifier LLM response
        mock_llm.chat.return_value = '{"sop_id": "航道通航底高程", "args": {"DWT": "50000", "ship_type": "oil_tanker"}}'
        
        classifier = IntentClassifier(self.sops)
        query = "计算5万吨级油轮的航道通航底高程"
        sop, args = classifier.route(query)
        
        self.assertIsNotNone(sop)
        self.assertEqual(sop.id, "航道通航底高程")
        # args might vary slightly depending on LLM, but should contain '50000' or similar
        print(f"  -> Routed to: {sop.id}")
        print(f"  -> Extracted Args: {args}")
        
    def test_03_sop_analysis(self, mock_llm):
        """Test Hybrid Analysis of SOP (converting MD to Structured Steps)."""
        print("\n[Test 03] Testing SOP Hybrid Analysis...")
        
        # Mock Analysis Response
        mock_response = """
        ```json
        {
            "steps": [
                {
                    "id": "step1",
                    "name": "确定设计船型尺度",
                    "tool": "table_lookup",
                    "inputs": {"table_name": "油船设计船型尺度", "query_conditions": "DWT=50000"},
                    "notes": "需查询《海港水文规范》附录A"
                },
                {
                    "id": "step2",
                    "name": "计算通航水深",
                    "tool": "calculator",
                    "inputs": {"expression": "T + Z0 + Z1"},
                    "notes": "Z0需根据航速计算"
                }
            ]
        }
        ```
        """
        mock_llm.chat.return_value = mock_response
        
        sop_id = "航道通航底高程"
        analyzed_sop = self.loader.analyze_sop(sop_id)
        
        self.assertGreater(len(analyzed_sop.steps), 0)
        first_step = analyzed_sop.steps[0]
        self.assertIsNotNone(first_step.name)
        # Check if 'notes' are extracted (feature of hybrid loader)
        has_notes = any(step.notes for step in analyzed_sop.steps)
        self.assertTrue(has_notes, "SOP Analysis failed to extract Notes.")
        print(f"  -> Analyzed {len(analyzed_sop.steps)} steps. Notes extracted: {has_notes}")
        
    def test_04_full_execution_flow(self, mock_llm):
        """
        Simulate a full execution flow:
        1. Load SOP
        2. Provide partial context
        3. Dispatcher runs (triggers TableLookup and KnowledgeSearch via Hybrid logic)
        """
        print("\n[Test 04] Testing Full Execution Flow (Hybrid Dispatch)...")
        
        # Mock Analysis Response (Same as above)
        mock_response = """
        ```json
        {
            "steps": [
                {
                    "id": "step1",
                    "name": "确定设计船型尺度",
                    "tool": "table_lookup",
                    "inputs": {"table_name": "油船设计船型尺度", "query_conditions": "DWT=50000"},
                    "notes": "需查询《海港水文规范》附录A"
                }
            ]
        }
        ```
        """
        # Set up a sequence of return values for subsequent calls
        # 1. Analyze SOP -> returns JSON above
        # 2. Dispatcher Hybrid Check (Smart Execution) -> returns Action JSON
        # 3. TableLookup Tool -> returns Table Data (MOCKED via LLM inside tool)
        
        # We need to be careful. Dispatcher calls LLM. TableLookup calls LLM.
        # Let's verify logic without relying on precise LLM chain.
        # We can mock the side effects.
        
        mock_llm.chat.side_effect = [
            mock_response, # 1. Analyze SOP
            '{"action": "table_lookup", "table_name": "油船设计船型尺度", "conditions": "DWT=50000"}', # 2. Dispatcher decision
            '{"result": {"DWT": 50000, "T": 12.8}}' # 3. TableLookup Tool extraction
        ]
        
        sop_id = "航道通航底高程"
        analyzed_sop = self.loader.analyze_sop(sop_id)
        dispatcher = Dispatcher()
        
        initial_context = {
            "user_query": "计算50000吨级油轮的航道通航底高程，设计水深15米",
        }
        
        try:
            final_context = dispatcher.run(analyzed_sop, initial_context)
            print("  -> Execution completed without errors.")
            print(f"  -> Final Context Keys: {list(final_context.keys())}")
            
        except Exception as e:
            self.fail(f"Dispatcher execution failed with error: {e}")

    def test_05_table_lookup_tool_direct(self, mock_llm):
        """Directly test the TableLookupTool to ensure it works."""
        print("\n[Test 05] Testing TableLookupTool Direct Call...")
        
        # Mock LLM extraction
        mock_llm.chat.return_value = '{"result": 12.8}'
        
        tool = ToolRegistry.get_tool("table_lookup")
        result = tool.run(table_name="油船设计船型尺度", query_conditions="船舶吨级DWT=50000", target_column="满载吃水T(m)")
        print(f"  -> Lookup Result: {result}")
        
        self.assertTrue(isinstance(result, dict))


if __name__ == "__main__":
    unittest.main()

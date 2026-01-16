import json
import os
import glob
from typing import Any, Dict, List, Optional

class KnowledgeManager:
    _instance = None
    _knowledge_data: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(KnowledgeManager, cls).__new__(cls)
            cls._instance._load_knowledge()
        return cls._instance

    def _load_knowledge(self):
        """
        Load all JSON files from the knowledge directory.
        """
        knowledge_dir = "knowledge"
        if not os.path.exists(knowledge_dir):
            return

        json_files = glob.glob(os.path.join(knowledge_dir, "*.json"))
        for fpath in json_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Merge data into the central store
                    if isinstance(data, dict):
                        self._knowledge_data.update(data)
            except Exception as e:
                print(f"Error loading knowledge file {fpath}: {e}")

    def query(self, table_name: str, query_params: Dict[str, Any]) -> Optional[Any]:
        """
        Query the knowledge base for a specific table and parameters.
        """
        if table_name not in self._knowledge_data:
            return None

        data = self._knowledge_data[table_name]
        if not isinstance(data, list):
            return data

        # Simple matching logic (same as previously in the tool)
        results = []
        for item in data:
            match = True
            for k, v in query_params.items():
                # Specialized handling for tonnage ranges
                if k == "tonnage":
                    try:
                        v_num = float(v)
                        min_t = float(item.get("min_tonnage", 0))
                        max_t = float(item.get("max_tonnage", 999999))
                        if not (min_t <= v_num <= max_t):
                            match = False
                    except:
                        match = False
                elif k == "ship_type" and k in item:
                    v_str = str(v).lower()
                    item_str = str(item[k]).lower()
                    if v_str not in item_str and item_str not in v_str:
                        match = False
                elif k in item and item[k] != v:
                    match = False
            
            if match:
                results.append(item)

        return results[0] if results else data[0]

knowledge_manager = KnowledgeManager()

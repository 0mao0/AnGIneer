from typing import Any, Dict, List
import json
from src.tools.base import BaseTool, register_tool
from src.core.knowledge import knowledge_manager

@register_tool
class StandardDataLookupTool(BaseTool):
    """
    通用查表工具：模拟从客观知识库中查询固定数据。
    """
    name = "standard_data_lookup"
    description = "Lookup design standards or chart data from Knowledge Base. Inputs: table_name (str), query_params (dict)"
    
    def run(self, table_name: str, query_params: Dict[str, Any], **kwargs) -> Any:
        # 清理查询参数中的数值 (保持鲁棒性)
        clean_params = {}
        for k, v in query_params.items():
            if isinstance(v, str) and k.lower() in ["tonnage", "length", "depth", "width", "channel_length"]:
                try:
                    clean_params[k] = float(''.join(filter(lambda x: x.isdigit() or x == '.', v)))
                except:
                    clean_params[k] = v
            elif isinstance(v, (int, float)):
                clean_params[k] = float(v)
            else:
                clean_params[k] = v

        # 从知识库管理器查询数据
        result = knowledge_manager.query(table_name, clean_params)
        
        if result is None:
            return {"error": f"Table '{table_name}' not found in knowledge base."}
            
        return result

@register_tool
class GISSectionVolumeTool(BaseTool):
    """
    重型计算工具：处理 LLM 无法完成的 CAD/GIS 几何运算。
    例如根据地形切片计算断面面积和总体积。
    """
    name = "gis_section_volume_calc"
    description = "Professional GIS calculation for dredging sections. Inputs: design_depth (float), design_width (float), length (float), terrain_data_id (str)"
    
    def run(self, design_depth: Any, design_width: Any, length: Any, terrain_data_id: str = "default_survey", **kwargs) -> Any:
        # Robust parsing
        try:
            d_depth = 0.0
            d_width = 0.0
            d_length = 0.0
            
            if isinstance(design_depth, (int, float)): d_depth = float(design_depth)
            elif isinstance(design_depth, str): d_depth = float(''.join(filter(lambda x: x.isdigit() or x == '.', design_depth)))
            
            if isinstance(design_width, (int, float)): d_width = float(design_width)
            elif isinstance(design_width, str): d_width = float(''.join(filter(lambda x: x.isdigit() or x == '.', design_width)))
            
            if isinstance(length, (int, float)): d_length = float(length)
            elif isinstance(length, str): d_length = float(''.join(filter(lambda x: x.isdigit() or x == '.', length)))
            
            if d_depth == 0 or d_width == 0 or d_length == 0:
                return {"error": f"Invalid dimensions: depth={d_depth}, width={d_width}, length={d_length}"}
        except Exception as e:
            return {"error": f"Parsing error in GIS calculation: {str(e)}"}

        # 模拟复杂的 GIS 运算过程
        # 实际场景中这里会调用 ArcGIS/QGIS API 或 CAD 引擎
        print(f"    [GIS] Fetching terrain data for {terrain_data_id}...")
        print(f"    [GIS] Calculating cross-sections along {d_length}m path...")
        
        # 模拟地形起伏导致的额外工程量
        terrain_multiplier = 1.15 # 假设平均地形比设计标高高出 15%
        base_area = d_width * d_depth
        slope_area = (d_depth * d_depth * 3) # 1:3 边坡
        total_volume = (base_area + slope_area) * d_length * terrain_multiplier
        
        return {
            "total_volume_m3": round(total_volume, 2),
            "terrain_source": terrain_data_id,
            "calculation_engine": "PicoGIS-v1.0",
            "confidence_score": 0.98
        }

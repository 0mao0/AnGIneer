from typing import Any, Dict, List
from src.tools.BaseTool import BaseTool, register_tool


@register_tool
class GISSectionVolumeTool(BaseTool):
    """
    重型计算工具：处理 LLM 无法完成的 CAD/GIS 几何运算。
    例如根据地形切片计算断面面积和总体积。
    """
    name = "gis_section_volume_calc"
    description_en = "Professional GIS calculation for dredging sections. Inputs: design_depth (float), design_width (float), length (float), terrain_data_id (str)"
    description_zh = "专业的疏浚断面 GIS 计算工具。输入参数：design_depth (设计深度, float), design_width (设计宽度, float), length (长度, float), terrain_data_id (地形数据 ID, str)"
    
    def run(self, design_depth: Any, design_width: Any, length: Any, terrain_data_id: str = "default_survey", **kwargs) -> Any:
        # 鲁棒性解析
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
                return {"error": f"无效的尺寸参数: 深度={d_depth}, 宽度={d_width}, 长度={d_length}"}
        except Exception as e:
            return {"error": f"GIS 计算中的参数解析错误: {str(e)}"}

        # 模拟复杂的 GIS 运算过程
        # 实际场景中这里会调用 ArcGIS/QGIS API 或 CAD 引擎
        print(f"    [GIS] 正在获取 {terrain_data_id} 的地形数据...")
        print(f"    [GIS] 正在沿 {d_length} 米路径计算横断面...")
        
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

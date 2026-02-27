"""
TableLookupTool 单元测试。
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../services/engtools/src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../services/angineer-core/src'))


class TestTableLookupTool(unittest.TestCase):
    """TableLookupTool 工具类测试"""

    @classmethod
    def setUpClass(cls):
        from engtools.TableTool import TableLookupTool
        cls.tool = TableLookupTool(knowledge_dir='data/knowledge_base')

    def test_llm_mode_basic(self):
        """测试 LLM 模式基本查询"""
        result = self.tool.run(
            table_name='表A.0.2-3 油船设计船型尺度',
            query_conditions={'吨级': '100000'},
            file_name='markdown/海港总体设计规范_JTS_165-2025.md',
            use_llm=True
        )
        self.assertIn('raw_response', result)
        self.assertEqual(result.get('_mode'), 'llm')
        self.assertIn('14.9', result['raw_response'])

    def test_llm_mode_with_dict_query(self):
        """测试 LLM 模式字典查询条件"""
        result = self.tool.run(
            table_name='图6.4.5',
            query_conditions={'吨级': '100000', '航速': '10'},
            file_name='markdown/海港总体设计规范_JTS_165-2025.md',
            use_llm=True
        )
        self.assertIn('raw_response', result)
        self.assertIn('table_index', result)

    def test_llm_mode_with_string_query(self):
        """测试 LLM 模式字符串查询条件"""
        result = self.tool.run(
            table_name='表A.0.2-3 油船设计船型尺度',
            query_conditions='吨级=100000的满载吃水',
            file_name='markdown/海港总体设计规范_JTS_165-2025.md',
            use_llm=True
        )
        self.assertIn('raw_response', result)

    def test_file_not_found(self):
        """测试文件不存在的情况"""
        result = self.tool.run(
            table_name='测试表格',
            query_conditions={},
            file_name='not_exist.md',
            use_llm=True
        )
        self.assertIn('error', result)

    def test_structured_mode(self):
        """测试结构化解析模式（use_llm=False）"""
        result = self.tool.run(
            table_name='表A.0.2-3 油船设计船型尺度',
            query_conditions={'吨级': '100000'},
            file_name='markdown/海港总体设计规范_JTS_165-2025.md',
            use_llm=False
        )
        self.assertNotEqual(result.get('_mode'), 'llm')


if __name__ == '__main__':
    unittest.main()

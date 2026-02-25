"""
单元测试：Memory 模块。
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.core.memory import (
    Memory,
    StepRecord,
    UndefinedVariableError,
)
from angineer_core.config import MemoryConfig


class TestMemory(unittest.TestCase):
    """测试 Memory 类。"""
    
    def setUp(self):
        """每个测试前的准备工作。"""
        self.memory = Memory()
    
    def test_initial_state(self):
        """测试初始状态。"""
        self.assertEqual(self.memory.blackboard, {})
        self.assertEqual(self.memory.history, [])
        self.assertEqual(self.memory.chat_context, [])
    
    def test_update_context(self):
        """测试更新黑板。"""
        self.memory.update_context({"key1": "value1", "key2": 123})
        self.assertEqual(self.memory.blackboard["key1"], "value1")
        self.assertEqual(self.memory.blackboard["key2"], 123)
    
    def test_add_history(self):
        """测试添加执行历史。"""
        record = StepRecord(
            step_id="step_1",
            tool_name="calculator",
            inputs={"expr": "1+1"},
            outputs=2
        )
        self.memory.add_history(record)
        self.assertEqual(len(self.memory.history), 1)
        self.assertEqual(self.memory.history[0].step_id, "step_1")
    
    def test_add_chat_message(self):
        """测试添加聊天记录。"""
        self.memory.add_chat_message("user", "你好")
        self.memory.add_chat_message("assistant", "你好，有什么可以帮助你的？")
        self.assertEqual(len(self.memory.chat_context), 2)


class TestResolveValue(unittest.TestCase):
    """测试变量解析功能。"""
    
    def setUp(self):
        """每个测试前的准备工作。"""
        self.memory = Memory()
        self.memory.update_context({
            "name": "test",
            "count": 42,
            "nested": {"inner": "value"}
        })
    
    def test_resolve_simple_variable(self):
        """测试解析简单变量。"""
        result = self.memory.resolve_value("${name}")
        self.assertEqual(result, "test")
    
    def test_resolve_integer_variable(self):
        """测试解析整数变量。"""
        result = self.memory.resolve_value("${count}")
        self.assertEqual(result, 42)
    
    def test_resolve_nested_variable(self):
        """测试解析嵌套变量。"""
        result = self.memory.resolve_value("${nested.inner}")
        self.assertEqual(result, "value")
    
    def test_resolve_in_string(self):
        """测试在字符串中解析变量。"""
        result = self.memory.resolve_value("名称是 ${name}，数量是 ${count}")
        self.assertEqual(result, "名称是 test，数量是 42")
    
    def test_resolve_dict_values(self):
        """测试解析字典中的变量。"""
        data = {"key": "${name}", "num": "${count}"}
        result = self.memory.resolve_value(data)
        self.assertEqual(result["key"], "test")
        self.assertEqual(result["num"], 42)
    
    def test_resolve_list_values(self):
        """测试解析列表中的变量。"""
        data = ["${name}", "${count}"]
        result = self.memory.resolve_value(data)
        self.assertEqual(result[0], "test")
        self.assertEqual(result[1], 42)
    
    def test_resolve_non_string_value(self):
        """测试非字符串值直接返回。"""
        result = self.memory.resolve_value(123)
        self.assertEqual(result, 123)
        
        result = self.memory.resolve_value([1, 2, 3])
        self.assertEqual(result, [1, 2, 3])


class TestResolveUndefinedVariable(unittest.TestCase):
    """测试未定义变量的处理。"""
    
    def setUp(self):
        """每个测试前的准备工作。"""
        self.memory = Memory()
        self.memory.update_context({"existing": "value"})
    
    def test_undefined_variable_lenient_mode(self):
        """测试非严格模式下未定义变量使用替换值。"""
        result = self.memory.resolve_value("${undefined}", strict=False, none_replacement="<未定义>")
        self.assertEqual(result, "<未定义>")
    
    def test_undefined_variable_strict_mode(self):
        """测试严格模式下未定义变量抛出异常。"""
        with self.assertRaises(UndefinedVariableError) as context:
            self.memory.resolve_value("${undefined}", strict=True)
        
        self.assertEqual(context.exception.variable_name, "undefined")
    
    def test_undefined_variable_in_string_lenient(self):
        """测试非严格模式下字符串中的未定义变量。"""
        result = self.memory.resolve_value("值是 ${undefined}", strict=False, none_replacement="")
        self.assertEqual(result, "值是 ")


class TestHistoryAccess(unittest.TestCase):
    """测试历史记录访问。"""
    
    def setUp(self):
        """每个测试前的准备工作。"""
        self.memory = Memory()
        record = StepRecord(
            step_id="step_1",
            tool_name="calculator",
            inputs={"expr": "1+1"},
            outputs={"result": 2}
        )
        self.memory.add_history(record)
    
    def test_access_step_output(self):
        """测试访问步骤输出。"""
        result = self.memory.resolve_value("${step_1.output}")
        self.assertEqual(result["result"], 2)
    
    def test_access_step_output_field(self):
        """测试访问步骤输出的字段。"""
        result = self.memory.resolve_value("${step_1.outputs.result}")
        self.assertEqual(result, 2)


class TestHelperMethods(unittest.TestCase):
    """测试辅助方法。"""
    
    def setUp(self):
        """每个测试前的准备工作。"""
        self.memory = Memory()
        self.memory.update_context({"key1": "value1", "key2": "value2"})
    
    def test_has_variable_true(self):
        """测试检查变量存在。"""
        self.assertTrue(self.memory.has_variable("key1"))
        self.assertTrue(self.memory.has_variable("key2"))
    
    def test_has_variable_false(self):
        """测试检查变量不存在。"""
        self.assertFalse(self.memory.has_variable("nonexistent"))
    
    def test_list_available_variables(self):
        """测试列出可用变量。"""
        variables = self.memory.list_available_variables()
        self.assertIn("key1", variables)
        self.assertIn("key2", variables)


class TestStepRecord(unittest.TestCase):
    """测试 StepRecord 类。"""
    
    def test_create_step_record(self):
        """测试创建步骤记录。"""
        record = StepRecord(
            step_id="test_step",
            tool_name="test_tool",
            inputs={"arg": "value"},
            outputs="result"
        )
        self.assertEqual(record.step_id, "test_step")
        self.assertEqual(record.tool_name, "test_tool")
        self.assertEqual(record.status, "success")
    
    def test_step_record_with_error(self):
        """测试带错误的步骤记录。"""
        record = StepRecord(
            step_id="failed_step",
            tool_name="test_tool",
            inputs={},
            outputs=None,
            status="failed",
            error="执行失败"
        )
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.error, "执行失败")


class TestMemoryConfig(unittest.TestCase):
    """测试 Memory 配置。"""
    
    def test_default_config(self):
        """测试默认配置。"""
        memory = Memory()
        config = memory.get_config()
        self.assertFalse(config.strict_mode)
        self.assertEqual(config.none_replacement, "")
    
    def test_custom_config(self):
        """测试自定义配置。"""
        memory = Memory()
        custom_config = MemoryConfig(strict_mode=True, none_replacement="<缺失>")
        memory.set_config(custom_config)
        
        config = memory.get_config()
        self.assertTrue(config.strict_mode)
        self.assertEqual(config.none_replacement, "<缺失>")


if __name__ == "__main__":
    unittest.main()

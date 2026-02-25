"""
Dispatcher 单元测试。
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
import os

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.core.dispatcher import Dispatcher
from angineer_core.core.memory import Memory
from angineer_core.standard.context_models import SOP, Step


class TestDispatcherInit(unittest.TestCase):
    """测试 Dispatcher 初始化。"""
    
    def test_init_default(self):
        """测试默认初始化。"""
        dispatcher = Dispatcher()
        self.assertIsNotNone(dispatcher.memory)
        self.assertEqual(dispatcher.mode, "instruct")
    
    def test_init_with_custom_params(self):
        """测试自定义参数初始化。"""
        memory = Memory()
        mock_llm = Mock()
        
        dispatcher = Dispatcher(
            config_name="test_config",
            mode="thinking",
            result_md_path=None,
            memory=memory,
            llm_client=mock_llm
        )
        
        self.assertEqual(dispatcher.memory, memory)
        self.assertEqual(dispatcher.config_name, "test_config")
        self.assertEqual(dispatcher.mode, "thinking")
        self.assertEqual(dispatcher._llm_client, mock_llm)
    
    def test_init_with_result_md_path(self):
        """测试带 Markdown 日志路径初始化。"""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            temp_path = f.name
        
        try:
            dispatcher = Dispatcher(result_md_path=temp_path)
            self.assertTrue(os.path.exists(temp_path))
            
            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("SOP 执行日志", content)
        finally:
            os.unlink(temp_path)


class TestShouldSkipStep(unittest.TestCase):
    """测试 _should_skip_step 方法。"""
    
    def setUp(self):
        """设置测试环境。"""
        self.dispatcher = Dispatcher()
    
    def test_skip_step_outputs_exist(self):
        """测试输出已存在时跳过步骤。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value"}
        )
        context = {"result": 42}
        
        result = self.dispatcher._should_skip_step(step, context)
        self.assertTrue(result)
    
    def test_skip_step_outputs_partial_exist(self):
        """测试部分输出存在时不跳过步骤。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value", "another": "value2"}
        )
        context = {"result": 42}
        
        result = self.dispatcher._should_skip_step(step, context)
        self.assertFalse(result)
    
    def test_skip_step_outputs_not_exist(self):
        """测试输出不存在时不跳过步骤。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value"}
        )
        context = {}
        
        result = self.dispatcher._should_skip_step(step, context)
        self.assertFalse(result)
    
    def test_skip_step_no_outputs(self):
        """测试无输出定义时不跳过步骤。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )
        context = {}
        
        result = self.dispatcher._should_skip_step(step, context)
        self.assertFalse(result)
    
    def test_skip_step_wildcard_outputs(self):
        """测试输出为空字典时（类似通配符效果）不跳过步骤。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )
        context = {"result": 42}
        
        result = self.dispatcher._should_skip_step(step, context)
        self.assertFalse(result)
    
    def test_skip_step_output_is_none(self):
        """测试输出值为 None 时不跳过步骤。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value"}
        )
        context = {"result": None}
        
        result = self.dispatcher._should_skip_step(step, context)
        self.assertFalse(result)


class TestProcessOutputs(unittest.TestCase):
    """测试 _process_outputs 方法。"""
    
    def setUp(self):
        """设置测试环境。"""
        self.dispatcher = Dispatcher()
    
    def test_process_outputs_dict_mapping(self):
        """测试字典映射输出处理。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value", "status": "status"}
        )
        tool_result = {"value": 42, "status": "success"}
        
        updates = self.dispatcher._process_outputs(step, tool_result)
        
        self.assertEqual(updates["result"], 42)
        self.assertEqual(updates["status"], "success")
    
    def test_process_outputs_empty_dict(self):
        """测试空字典输出处理（不映射任何输出）。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )
        tool_result = {"value": 42, "status": "success"}
        
        updates = self.dispatcher._process_outputs(step, tool_result)
        
        self.assertEqual(updates, {})
    
    def test_process_outputs_no_outputs_defined(self):
        """测试无输出定义时的处理。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )
        tool_result = {"value": 42}
        
        updates = self.dispatcher._process_outputs(step, tool_result)
        
        self.assertEqual(updates, {})
    
    def test_process_outputs_scalar_result(self):
        """测试标量结果的处理。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value"}
        )
        tool_result = 42
        
        updates = self.dispatcher._process_outputs(step, tool_result)
        
        self.assertEqual(updates, {})


class TestExecuteStep(unittest.TestCase):
    """测试 _execute_step 方法。"""
    
    def setUp(self):
        """设置测试环境。"""
        self.mock_llm = Mock()
        self.dispatcher = Dispatcher(llm_client=self.mock_llm)
    
    def test_execute_step_analyzed_status(self):
        """测试已分析状态的步骤执行。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={"expr": "1+1"},
            outputs={},
            analysis_status="analyzed"
        )
        
        with patch.object(self.dispatcher, '_execute_analyzed_step') as mock_execute:
            self.dispatcher._execute_step(step)
            mock_execute.assert_called_once_with(step)
    
    def test_execute_step_classic_mode(self):
        """测试经典模式步骤执行。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={"expression": "1+1"},
            outputs={"result": "value"}
        )
        
        with patch.object(self.dispatcher, '_execute_tool_safe') as mock_execute:
            self.dispatcher._execute_step(step)
            mock_execute.assert_called_once()


class TestSmartStepExecution(unittest.TestCase):
    """测试 _smart_step_execution 方法。"""
    
    def setUp(self):
        """设置测试环境。"""
        self.mock_llm = Mock()
        self.dispatcher = Dispatcher(llm_client=self.mock_llm)
    
    def test_smart_step_return_value(self):
        """测试智能步骤返回值动作。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value"}
        )
        
        self.mock_llm.chat.return_value = json.dumps({
            "action": "return_value",
            "value": 42
        })
        
        with patch.object(self.dispatcher, '_process_outputs') as mock_process:
            mock_process.return_value = {"result": 42}
            self.dispatcher._smart_step_execution(step, "test", [])
            
            mock_process.assert_called_once_with(step, 42)
    
    def test_smart_step_ask_user(self):
        """测试智能步骤询问用户动作。"""
        step = Step(
            id="step1",
            tool="user_input",
            inputs={},
            outputs={}
        )
        
        self.mock_llm.chat.return_value = json.dumps({
            "action": "ask_user",
            "question": "请输入参数值"
        })
        
        with patch.object(self.dispatcher, '_execute_tool_safe') as mock_execute:
            self.dispatcher._smart_step_execution(step, "test", [])
            mock_execute.assert_called_once()
    
    def test_smart_step_skip(self):
        """测试智能步骤跳过动作。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )
        
        self.mock_llm.chat.return_value = json.dumps({
            "action": "skip",
            "reason": "不需要执行"
        })
        
        self.dispatcher._smart_step_execution(step, "test", [])
    
    def test_smart_step_execute_tool(self):
        """测试智能步骤执行工具动作。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )
        
        self.mock_llm.chat.return_value = json.dumps({
            "action": "execute_tool",
            "tool": "calculator",
            "inputs": {"expression": "1+1"}
        })
        
        with patch.object(self.dispatcher, '_execute_tool_safe') as mock_execute:
            self.dispatcher._smart_step_execution(step, "test", [])
            mock_execute.assert_called_once_with("calculator", {"expression": "1+1"}, step)


class TestLogPreExecution(unittest.TestCase):
    """测试 log_pre_execution 方法。"""
    
    def test_log_pre_execution(self):
        """测试前置日志记录。"""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            temp_path = f.name
        
        try:
            dispatcher = Dispatcher(result_md_path=temp_path)
            
            logs = [
                {
                    "event": "用户需求",
                    "method": "User Input",
                    "time": "2024-01-01 10:00:00",
                    "duration": "0.5s",
                    "details": "计算 25 * 4"
                }
            ]
            
            dispatcher.log_pre_execution(logs)
            
            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("前置过程概览", content)
                self.assertIn("用户需求", content)
                self.assertIn("计算 25 * 4", content)
        finally:
            os.unlink(temp_path)
    
    def test_log_pre_execution_no_path(self):
        """测试无路径时不记录日志。"""
        dispatcher = Dispatcher(result_md_path=None)
        
        logs = [{"event": "test"}]
        dispatcher.log_pre_execution(logs)
        
        self.assertIsNone(dispatcher.result_md_path)


class TestRun(unittest.TestCase):
    """测试 run 方法。"""
    
    def setUp(self):
        """设置测试环境。"""
        self.mock_llm = Mock()
        self.dispatcher = Dispatcher(llm_client=self.mock_llm)
    
    def test_run_simple_sop(self):
        """测试执行简单 SOP。"""
        sop = SOP(
            id="test_sop",
            description="测试 SOP",
            steps=[
                Step(id="step1", tool="calculator", inputs={}, outputs={})
            ]
        )
        
        with patch.object(self.dispatcher, '_execute_step') as mock_execute:
            result = self.dispatcher.run(sop, {"user_query": "test"})
            
            mock_execute.assert_called_once()
            self.assertIn("user_query", result)
    
    def test_run_with_pre_logs(self):
        """测试带前置日志的执行。"""
        sop = SOP(
            id="test_sop",
            description="测试 SOP",
            steps=[]
        )
        
        pre_logs = [{"event": "test"}]
        
        with patch.object(self.dispatcher, 'log_pre_execution') as mock_log:
            self.dispatcher.run(sop, {}, pre_logs=pre_logs)
            mock_log.assert_called_once_with(pre_logs)


if __name__ == "__main__":
    unittest.main()

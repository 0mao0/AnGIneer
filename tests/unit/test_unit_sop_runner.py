"""
SopRunner 单元测试。
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.sop_runner import SopRunner
from angineer_core.sop_domain import DomainHints
from angineer_core.memory import Memory
from angineer_core.base_contracts import SOP, Step
from ai_inference.llm_client import ChatResult


class TestSopRunnerInit(unittest.TestCase):
    """测试 SopRunner 初始化。"""

    def test_init_default(self):
        """测试默认初始化。"""
        runner = SopRunner()
        self.assertIsNotNone(runner.memory)
        self.assertEqual(runner.mode, "instruct")

    def test_init_with_custom_params(self):
        """测试自定义参数初始化。"""
        memory = Memory()
        mock_llm = Mock()

        runner = SopRunner(
            config_name="test_config",
            mode="thinking",
            result_md_path=None,
            memory=memory,
            llm_client=mock_llm
        )

        self.assertEqual(runner.memory, memory)
        self.assertEqual(runner.config_name, "test_config")
        self.assertEqual(runner.mode, "thinking")
        self.assertEqual(runner._llm_client, mock_llm)

    def test_init_with_result_md_path(self):
        """测试带 Markdown 日志路径初始化。"""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            temp_path = f.name

        try:
            runner = SopRunner(result_md_path=temp_path)
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
        self.runner = SopRunner()

    def test_skip_step_outputs_exist(self):
        """测试输出已存在时跳过步骤。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value"}
        )

        context = {"result": 42}

        result = self.runner._should_skip_step(step, context)
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

        result = self.runner._should_skip_step(step, context)
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

        result = self.runner._should_skip_step(step, context)
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

        result = self.runner._should_skip_step(step, context)
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

        result = self.runner._should_skip_step(step, context)
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

        result = self.runner._should_skip_step(step, context)
        self.assertFalse(result)


class TestProcessOutputs(unittest.TestCase):
    """测试 _process_outputs 方法。"""

    def setUp(self):
        """设置测试环境。"""
        self.runner = SopRunner()

    def test_process_outputs_dict_mapping(self):
        """测试字典映射输出处理。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value", "status": "status"}
        )

        tool_result = {"value": 42, "status": "success"}

        updates = self.runner._process_outputs(step, tool_result)

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

        updates = self.runner._process_outputs(step, tool_result)

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

        updates = self.runner._process_outputs(step, tool_result)

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

        updates = self.runner._process_outputs(step, tool_result)

        self.assertEqual(updates, {})


class TestExecuteStep(unittest.TestCase):
    """测试 _execute_step 方法。"""

    def setUp(self):
        """设置测试环境。"""
        self.mock_llm = Mock()
        self.runner = SopRunner(llm_client=self.mock_llm)

    def test_execute_step_analyzed_status(self):
        """测试已分析状态的步骤执行。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={"expr": "1+1"},
            outputs={},
            analysis_status="analyzed"
        )

        with patch.object(self.runner, '_execute_analyzed_step') as mock_execute:
            self.runner._execute_step(step)
            mock_execute.assert_called_once_with(step)

    def test_execute_step_classic_mode(self):
        """测试经典模式步骤执行。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={"expression": "1+1"},
            outputs={"result": "value"}
        )

        with patch.object(self.runner, '_execute_tool_safe') as mock_execute:
            self.runner._execute_step(step)
            mock_execute.assert_called_once()


class TestSmartStepExecution(unittest.TestCase):
    """测试 _smart_step_execution 方法。"""

    def setUp(self):
        """设置测试环境。"""
        self.mock_llm = Mock()
        self.runner = SopRunner(llm_client=self.mock_llm)

    def test_smart_step_return_value(self):
        """测试智能步骤返回值动作。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={"result": "value"}
        )

        self.mock_llm.chat_result.return_value = ChatResult(
            text=json.dumps({"action": "return_value", "value": 42}),
            finish_reason="stop"
        )

        with patch.object(self.runner, '_process_outputs') as mock_process:
            mock_process.return_value = {"result": 42}
            self.runner._smart_step_execution(step, "test", [])

            mock_process.assert_called_once_with(step, 42)

    def test_smart_step_ask_user(self):
        """测试智能步骤询问用户动作。"""
        step = Step(
            id="step1",
            tool="user_input",
            inputs={},
            outputs={}
        )

        self.mock_llm.chat_result.return_value = ChatResult(
            text=json.dumps({"action": "ask_user", "question": "请输入参数值"}),
            finish_reason="stop"
        )

        with patch.object(self.runner, '_execute_tool_safe') as mock_execute:
            self.runner._smart_step_execution(step, "test", [])
            mock_execute.assert_called_once()

    def test_smart_step_skip(self):
        """测试智能步骤跳过动作。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )

        self.mock_llm.chat_result.return_value = ChatResult(
            text=json.dumps({"action": "skip", "reason": "不需要执行"}),
            finish_reason="stop"
        )

        self.runner._smart_step_execution(step, "test", [])

    def test_smart_step_execute_tool(self):
        """测试智能步骤执行工具动作。"""
        step = Step(
            id="step1",
            tool="calculator",
            inputs={},
            outputs={}
        )

        self.mock_llm.chat_result.return_value = ChatResult(
            text=json.dumps({"action": "execute_tool", "tool": "calculator", "inputs": {"expression": "1+1"}}),
            finish_reason="stop"
        )

        with patch.object(self.runner, '_execute_tool_safe') as mock_execute:
            self.runner._smart_step_execution(step, "test", [])
            mock_execute.assert_called_once_with("calculator", {"expression": "1+1"}, step)


class TestLogPreExecution(unittest.TestCase):
    """测试 log_pre_execution 方法。"""

    def test_log_pre_execution(self):
        """测试前置日志记录。"""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            temp_path = f.name

        try:
            runner = SopRunner(result_md_path=temp_path)

            logs = [
                {
                    "event": "用户需求",
                    "method": "User Input",
                    "time": "2024-01-01 10:00:00",
                    "duration": "0.5s",
                    "details": "计算 25 * 4"
                }
            ]

            runner.log_pre_execution(logs)

            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("前置过程概览", content)
            self.assertIn("用户需求", content)
            self.assertIn("计算 25 * 4", content)
        finally:
            os.unlink(temp_path)

    def test_log_pre_execution_no_path(self):
        """测试无路径时不记录日志。"""
        runner = SopRunner(result_md_path=None)

        logs = [{"event": "test"}]
        runner.log_pre_execution(logs)

        self.assertIsNone(runner.result_md_path)


class TestStepGraphTraversal(unittest.TestCase):
    """测试 run_sop 按步骤图遍历（next_step_id / on_failure 契约）。"""

    def _make_sop(self, steps):
        return SOP(id="sop_graph", name_zh="图遍历测试", steps=steps)

    def _run_with_stub(self, sop, fail_ids=()):
        """替换 _execute_step 为桩：记录执行序，失败步骤落 failed 记录。"""
        runner = SopRunner(llm_client=Mock())
        order = []
        callback_infos = []

        def fake_execute(step):
            order.append(step.id)
            if step.id in fail_ids:
                runner._record_step(step, {}, None, error="boom")
            else:
                runner._record_step(step, {}, {"ok": True})

        runner._execute_step = fake_execute
        runner.run_sop(sop, {"user_query": "q"}, step_callback=callback_infos.append)
        return runner, order, callback_infos

    def test_linear_without_next_step_id(self):
        """无 next_step_id 时保持列表顺序线性执行。"""
        steps = [Step(id=f"s{i}", tool="calculator") for i in range(1, 4)]
        _, order, _ = self._run_with_stub(self._make_sop(steps))
        self.assertEqual(order, ["s1", "s2", "s3"])

    def test_chain_order_overrides_list_order(self):
        """next_step_id 链存在时按链序执行，而非列表序。"""
        steps = [
            Step(id="s1", tool="calculator", next_step_id="s2"),
            Step(id="s3", tool="calculator"),
            Step(id="s2", tool="calculator", next_step_id="s3"),
        ]
        _, order, _ = self._run_with_stub(self._make_sop(steps))
        self.assertEqual(order, ["s1", "s2", "s3"])

    def test_island_steps_fall_back_to_linear(self):
        """未被链路覆盖的 island 步骤按列表顺序线性兜底补跑。"""
        steps = [
            Step(id="s1", tool="calculator", next_step_id="s2"),
            Step(id="s2", tool="calculator"),
            Step(id="island", tool="calculator"),
        ]
        _, order, _ = self._run_with_stub(self._make_sop(steps))
        self.assertEqual(set(order), {"s1", "s2", "island"})
        self.assertEqual(order.index("s1"), 0)
        self.assertEqual(order.index("s2"), 1)
        self.assertEqual(len(order), 3)

    def test_on_failure_jump_skips_intermediates(self):
        """失败且 on_failure 命中时跳转，中间步骤记 skipped 且不执行。"""
        steps = [
            Step(id="s1", tool="calculator", next_step_id="s2"),
            Step(id="s2", tool="calculator", next_step_id="s3", on_failure="s4"),
            Step(id="s3", tool="calculator"),
            Step(id="s4", tool="calculator"),
        ]
        runner, order, callback_infos = self._run_with_stub(
            self._make_sop(steps), fail_ids={"s2"}
        )
        self.assertEqual(order, ["s1", "s2", "s4"])
        skipped = [r for r in runner.memory.history if r.step_id == "s3"]
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0].outputs.get("skipped"))
        skipped_infos = [i for i in callback_infos if i["step_id"] == "s3"]
        self.assertEqual(len(skipped_infos), 1)

    def test_on_failure_not_triggered_on_success(self):
        """步骤成功时 on_failure 不生效，全步骤按序执行。"""
        steps = [
            Step(id="s1", tool="calculator", next_step_id="s2"),
            Step(id="s2", tool="calculator", next_step_id="s3", on_failure="s4"),
            Step(id="s3", tool="calculator"),
            Step(id="s4", tool="calculator"),
        ]
        _, order, _ = self._run_with_stub(self._make_sop(steps))
        self.assertEqual(order, ["s1", "s2", "s3", "s4"])

    def test_each_step_runs_exactly_once(self):
        """next_step_id 指向已执行步骤时回退线性兜底，步骤不重复执行。"""
        steps = [
            Step(id="s1", tool="calculator", next_step_id="s2"),
            Step(id="s2", tool="calculator", next_step_id="s1"),
        ]
        _, order, _ = self._run_with_stub(self._make_sop(steps))
        self.assertEqual(set(order), {"s1", "s2"})
        self.assertEqual(len(order), 2)


class TestDomainHintsWiring(unittest.TestCase):
    """测试领域知识包提示在执行器内的消费（别名/calculator 领域规则）。"""

    def test_output_alias_from_domain_hints(self):
        """领域包别名参与输出值挑选。"""
        hints = DomainHints(output_aliases={"t": ["draft"]})
        runner = SopRunner(llm_client=Mock(), domain_hints=hints)
        self.assertEqual(runner._select_output_value("T", {"design_draft": 5.5}), 5.5)

    def test_no_builtin_aliases_without_hints(self):
        """空提示下无别名可用（内置港口别名已外置）。"""
        runner = SopRunner(llm_client=Mock())
        self.assertIsNone(runner._select_output_value("dwl_basic", {"a": 1, "b": 2}))

    def test_calculator_domain_hint_appended(self):
        """calculator 步骤的领域取值规则追加到提示词。"""
        hints = DomainHints(calculator_hint="- For K1: use 0.3")
        runner = SopRunner(llm_client=Mock(), domain_hints=hints)
        step = Step(id="s", name="算一下", tool="calculator")
        prompt = runner._build_smart_execution_prompt(step, "test", "{}")
        self.assertIn("- For K1: use 0.3", prompt)

    def test_prompt_has_no_builtin_domain_rules(self):
        """不启用领域包时提示词不含内置领域取值规则。"""
        runner = SopRunner(llm_client=Mock())
        step = Step(id="s", name="算一下", tool="calculator")
        prompt = runner._build_smart_execution_prompt(step, "test", "{}")
        self.assertNotIn("K1=0.3", prompt)
        self.assertIn("derive them from Context Variables", prompt)


if __name__ == "__main__":
    unittest.main()

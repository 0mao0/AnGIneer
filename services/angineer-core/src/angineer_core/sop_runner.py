"""SOP 执行引擎（P6.1 从旧 dispatcher.py 下沉；P7+ 清退 Dispatcher 壳后为本类）。

承载 `run_sop` 及配套步骤执行、工具安全调用、智能执行、Markdown 日志、
输出映射与执行记录。接入层直接使用 `SopRunner`。
"""
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Tuple

from angineer_core.base_contracts import SOP, Step
from angineer_core.base_logger import get_logger
from angineer_core.memory import Memory, StepRecord
from angineer_core.prompts.dispatcher import (
    SMART_EXECUTION_CALCULATOR_HINT,
    SMART_EXECUTION_PROMPT,
    SMART_SELECT_TOOL_PROMPT,
    STEP_SUMMARY_PROMPT,
)

logger = get_logger(__name__)

_TOOL_EXEC_TIMEOUT_SECONDS = 120

try:
    from engtools.BaseTool import ToolRegistry
except ImportError:
    ToolRegistry = None

from ai_inference.llm_client import chat_result_guarded, get_llm_client


class SopRunner:
    """SOP 步骤执行引擎：blackboard 更新、工具调用、trace 记录与回调。"""

    def __init__(
        self,
        config_name: str = None,
        mode: str = "instruct",
        result_md_path: str = None,
        memory: Optional[Memory] = None,
        llm_client: Optional[Any] = None,
        tool_timeout_s: int = _TOOL_EXEC_TIMEOUT_SECONDS,
    ):
        self.memory = memory or Memory()
        self.config_name = config_name
        self.mode = mode or "instruct"
        self.result_md_path = result_md_path
        self._llm_client = llm_client or get_llm_client()
        self.tool_timeout_s = max(1, int(tool_timeout_s or _TOOL_EXEC_TIMEOUT_SECONDS))
        self.variable_metadata = {}
        self.start_time = None
        self.step_durations = {}
        self.summary_durations = {}
        self.tool_durations = {}

        if self.result_md_path:
            with open(self.result_md_path, "w", encoding="utf-8") as f:
                f.write("# SOP 执行日志 (LLM 风格小结版)\n\n")
                f.write("> **说明**: 本日志展示了每一步的执行小结与 Blackboard 状态快照。更新的内容已高亮显示。\n\n")

    @property
    def llm_client(self):
        """获取 LLM 客户端。"""
        return self._llm_client

    def _extract_json_from_response(self, response: str) -> Dict[str, Any]:
        """
        从 LLM 响应中提取 JSON 数据。
        
        支持以下格式:
        - ```json {...} ```
        - ``` {...} ```
        - 纯 JSON 字符串
        - 嵌入在文本中的首个 {...} 对象（正则兜底）
        
        Args:
            response: LLM 的原始响应字符串
            
        Returns:
            解析后的 JSON 字典
            
        Raises:
            json.JSONDecodeError: 当无法解析 JSON 时
        """
        cleaned = response.strip()
        
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0]
        
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            pass
        
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        brace_start = cleaned.find('{')
        brace_end = cleaned.rfind('}')
        if brace_start >= 0 and brace_end > brace_start:
            candidate = cleaned[brace_start:brace_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        
        raise json.JSONDecodeError(
            f"无法从响应中提取有效JSON (长度={len(response)})",
            response,
            0
        )

    def log_pre_execution(self, logs: List[Dict[str, Any]]):
        """
        记录前置过程日志到 Markdown。
        logs: list of dict, each containing:
            - event: 事件名称 (e.g. "用户需求")
            - method: 获得方式 (e.g. "User Input")
            - time: 发生时间 (e.g. "2023-10-27 10:00:00")
            - duration: 耗时 (e.g. "0.5s")
            - details: 详细内容
        """
        if not self.result_md_path:
            return
            
        with open(self.result_md_path, "a", encoding="utf-8") as f:
            f.write("## 0. 前置过程概览\n\n")
            f.write("| 事件 | 获得方式 | 时间 | 耗时 | 详情 |\n")
            f.write("| --- | --- | --- | --- | --- |\n")
            
            for log in logs:
                event = log.get("event", "-")
                method = log.get("method", "-")
                time_str = log.get("time", "-")
                duration = log.get("duration", "-")
                details = str(log.get("details", "-")).replace("\n", "<br>")
                if len(details) > 100:
                    details = details[:97] + "..."
                    
                f.write(f"| {event} | {method} | {time_str} | {duration} | {details} |\n")
            
            f.write("\n---\n\n")

    def run_sop(self, sop: SOP, initial_context: Dict[str, Any], pre_logs: List[Dict[str, Any]] = None, step_callback=None):
        """
        Execute the SOP with the given initial context.
        Args:
            sop: SOP 对象
            initial_context: 初始上下文
            pre_logs: 预执行日志
            step_callback: 每个步骤执行完后的回调函数，签名为 callback(step_info: Dict)
        """
        self.start_time = time.time()
        logger.info(f"[{sop.id}] Starting execution: {sop.description}")

        # Log pre-execution events if provided
        if pre_logs:
            self.log_pre_execution(pre_logs)

        self.memory.update_context(initial_context)

        # Simple linear execution for now
        # In a real FSM, we would follow next_step_id
        for step in sop.steps:
            try:
                self._execute_step(step)
            except Exception as e:
                # 单步异常不应中断整个 SOP：记录错误并继续后续步骤
                logger.error(f"[{sop.id}] Step {step.id} 执行异常，继续后续步骤: {e}")
                self._record_step(step, {}, None, error=f"unhandled: {e}")

            if step_callback:
                step_info = self._build_step_info(step)
                try:
                    step_callback(step_info)
                except Exception as e:
                    logger.warning(f"step_callback 调用失败: {e}")

        logger.info(f"[{sop.id}] Execution finished.")
        
        # Log total time
        total_duration = time.time() - self.start_time
        
        # Calculate breakdowns
        total_tool_time = sum(self.tool_durations.values())
        total_summary_time = sum(self.summary_durations.values())
        total_step_overhead = sum(self.step_durations.values()) - total_tool_time - total_summary_time
        
        if self.result_md_path:
            with open(self.result_md_path, "a", encoding="utf-8") as f:
                f.write(f"## 执行总结\n\n")
                f.write(f"| 项目 | 耗时 | 占比 |\n")
                f.write(f"| --- | --- | --- |\n")
                f.write(f"| **总耗时** | **{total_duration:.2f}s** | 100% |\n")
                f.write(f"| 工具执行 | {total_tool_time:.2f}s | {(total_tool_time/total_duration)*100:.1f}% |\n")
                f.write(f"| LLM 总结 | {total_summary_time:.2f}s | {(total_summary_time/total_duration)*100:.1f}% |\n")
                f.write(f"| 调度开销 | {total_step_overhead:.2f}s | {(total_step_overhead/total_duration)*100:.1f}% |\n")
                f.write(f"\n> 注: '调度开销' 包含 Python 代码执行、文件 I/O 及其他逻辑处理时间。\n")
        
        return self.memory.blackboard

    def _build_step_info(self, step: Step) -> Dict[str, Any]:
        """构建单个步骤的执行信息，用于回调通知。"""
        history = getattr(self.memory, "history", [])
        step_durations = getattr(self, "step_durations", {}) or {}
        record = None
        for r in history:
            if r.step_id == step.id:
                record = r
                break
        return {
            "step_id": step.id,
            "step_name": step.name or step.name_zh or step.id,
            "step_index": len([s for s in history if s]) + 1,
            "tool": step.tool or "auto",
            "description": step.description_zh or (step.description.content if step.description else ""),
            "inputs": (record.inputs if record else step.inputs) or {},
            "outputs": (record.outputs if record else None),
            "duration": step_durations.get(step.id, 0.0),
            "status": (record.status if record else "pending"),
            "error": (record.error if record else None),
            "thinking": (record.thinking if record else None),
            "evidence": (record.evidence if record else None),
        }

    def _execute_step(self, step: Step):
        step_start = time.time()
        logger.info(f"Executing Step: {step.name or step.id} ({step.tool})")
        
        # [Hybrid Architecture Check]
        # If this step was generated by LLM analysis (Scenario A)
        if getattr(step, "analysis_status", None) == "analyzed":
            self._execute_analyzed_step(step)
        else:
            # [Classic Logic] (Scenario B)
            # 1. Resolve Inputs
            tool_inputs = {}
            for key, value in step.inputs.items():
                resolved_value = self.memory.resolve_value(value)
                tool_inputs[key] = resolved_value
                
            # 2. Determine Tool (Static or Auto)
            target_tool_name = step.tool
            if target_tool_name == "auto":
                logger.debug("Detecting tool via LLM...")
                detected_tool, detected_inputs = self._smart_select_tool(step, tool_inputs)
                if detected_tool:
                    logger.info(f"Auto selected tool: {detected_tool}")
                    target_tool_name = detected_tool
                    tool_inputs.update(detected_inputs)
                else:
                    logger.warning("Auto tool selection failed")
                    self._record_step(step, tool_inputs, None, error="Auto-selection failed")
                    return
    
            # 3. Execute Tool
            self._execute_tool_safe(target_tool_name, tool_inputs, step)
            
        # Record duration
        duration = time.time() - step_start
        self.step_durations[step.id] = duration
        
        # If markdown log was written inside _execute_tool_safe, we need to inject duration there?
        # Actually _execute_tool_safe calls _write_markdown_log.
        # But at that point we don't have the full duration (summary generation takes time too).
        # We might need to pass start time to _write_markdown_log or update it later.
        # Simpler approach: Calculate tool execution time inside _execute_tool_safe and pass it.

    def _execute_analyzed_step(self, step: Step):
        """
        Execute a step that was analyzed by LLM (Hybrid Mode).
        Logic:
        1. Resolve all inputs from context.
        2. Check if any resolved input indicates missing data (e.g. explicit None or unresolved vars).
        3. Check if 'notes' exist.
        4. If (Missing Inputs OR Notes OR Tool='auto'), wake up LLM.
        5. Else, execute directly.
        """
        context = self.memory.blackboard
        # Check if step outputs already exist in context
        if self._should_skip_step(step, context):
            self._record_step(step, {}, {"skipped": True, "reason": "value exists in context"})
            return
            
        missing_params = []
        ready_inputs = {}
        
        # 1. Resolve Inputs
        for param_name, value_expr in step.inputs.items():
            resolved_value = self.memory.resolve_value(value_expr)
            ready_inputs[param_name] = resolved_value
            
            # Simple check: if resolved value looks like an unresolved template or None
            if resolved_value is None:
                 missing_params.append(f"{param_name} (value is None)")
            elif isinstance(resolved_value, str) and "${" in resolved_value:
                 # Check if it's an unresolved reference
                 # This is a heuristic, but often useful
                 missing_params.append(f"{param_name} (unresolved: {resolved_value})")

        # 1.5. 检查所有输入是否有效（非空），避免将空值传递给工具
        non_auto_tools = {"calculator", "table_lookup", "knowledge_search", "user_input"}
        if step.tool in non_auto_tools:
            all_inputs_empty = all(
                v in (None, "", {}, [])
                or (isinstance(v, str) and not v.strip())
                for v in ready_inputs.values()
            )
            if all_inputs_empty and ready_inputs:
                logger.warning(f"[Step {step.id}] 所有输入参数均为空值，无法执行工具调用")
                self._record_step(step, ready_inputs,
                    {"error": "所有输入参数均为空值，无法执行工具调用。请检查前序步骤输出是否正常。"},
                    error="empty_inputs")
                return

        # 1.6. Try to derive missing variables from context (K1, 折减系数, etc.)
        if missing_params and step.tool == "calculator":
            logger.debug(f"Missing calculator params, will rely on LLM: {missing_params}")

        # 2. Decision Logic
        needs_llm = False
        reason = ""
        
        if missing_params:
            needs_llm = True
            reason = f"Missing parameters: {missing_params}"
        elif step.tool == "auto":
            needs_llm = True
            reason = "Tool is 'auto'"
            
        if needs_llm:
            logger.debug(f"Hybrid mode: waking up LLM - {reason}")
            self._smart_step_execution(step, reason, missing_params)
        else:
            logger.debug("Hybrid mode: rule-based execution (all params ready)")
            # Execute directly
            if step.tool == "table_lookup" and "use_llm" not in ready_inputs:
                ready_inputs["use_llm"] = False
            self._execute_tool_safe(step.tool, ready_inputs, step)

    def _should_skip_step(self, step: Step, context: Dict[str, Any]) -> bool:
        """Check if step outputs are already present in context and valid."""
        if not step.outputs:
            return False
        # If outputs is "*" we can't easily check, so don't skip
        if step.outputs == "*":
            return False
            
        output_keys = list(step.outputs.keys())
        if not output_keys:
            return False
            
        for key in output_keys:
            value = context.get(key)
            # 值必须存在且不为 None
            if value is None:
                return False
            # 值不能是空字符串
            if isinstance(value, str) and not value.strip():
                return False
            # 值不能是明显的错误标记
            if isinstance(value, str) and value.strip().lower() in {"error", "failed", "null", "none", "undefined", "nan"}:
                return False
            # 数值类型不能是 NaN
            if isinstance(value, float) and math.isnan(value):
                return False
            # 如果是字典/列表，不能为空
            if isinstance(value, (dict, list)) and not value:
                return False
        return True

    # 执行元 SOP 内置工具（llm_generate）
    def _execute_meta_sop_tool(self, tool_name: str, inputs: Dict[str, Any], step: Step) -> Any:
        if tool_name == "llm_generate":
            messages = []
            query = inputs.get("query", "")
            context = inputs.get("context", "")
            if context:
                messages.append({"role": "system", "content": f"请根据以下上下文回答用户问题：\n{context}"})
            messages.append({"role": "user", "content": query})

            def _do_chat():
                return self._llm_client.chat(messages, mode=self.mode, config_name=self.config_name)

            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(_do_chat)
                response_text = future.result(timeout=self.tool_timeout_s)
            except FuturesTimeoutError:
                # P6.2：llm_generate 纳入统一超时；超时后立即放弃等待，如实记录线程泄漏
                logger.warning(
                    "llm_generate 元工具超时（%ss），线程未杀死（泄漏，彻底解需 multiprocessing）",
                    self.tool_timeout_s,
                )
                raise TimeoutError(
                    f"llm_generate 元工具执行超时（{self.tool_timeout_s}s）；线程未杀死（泄漏）"
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            return {"answer": response_text or ""}

        return None

    def _execute_tool_safe(self, tool_name: str, inputs: Dict[str, Any], step: Step):
        """Helper to execute tool and record history"""
        meta_sop_tools = {"llm_generate"}
        if tool_name in meta_sop_tools:
            try:
                tool_start = time.time()
                result = self._execute_meta_sop_tool(tool_name, inputs, step)
                tool_duration = time.time() - tool_start
                self.tool_durations[step.id] = tool_duration
                normalized_result = self._adapt_result_for_step(step, tool_name, inputs, result)
                tool_error = self._extract_tool_error(normalized_result)
                updates = {} if tool_error else self._process_outputs(step, normalized_result)
                self._record_step(step, inputs, normalized_result, error=tool_error)
                if self.result_md_path:
                    self._write_markdown_log(step, inputs, normalized_result, updates, duration=tool_duration)
            except Exception as e:
                logger.error(f"元 SOP 工具执行错误: {e}")
                self.tool_durations[step.id] = 0.0
                self._record_step(step, inputs, None, error=str(e))
                if self.result_md_path:
                    self._write_markdown_log(step, inputs, {"error": str(e)}, {}, duration=0.0)
            return

        if ToolRegistry is None:
            error_msg = "ToolRegistry not available (engtools not installed)"
            logger.error(error_msg)
            self._record_step(step, inputs, None, error=error_msg)
            raise RuntimeError(error_msg)
            
        tool = ToolRegistry.get_tool(tool_name)
        if not tool:
            error_msg = f"Tool not found: {tool_name}"
            logger.error(error_msg)
            self._record_step(step, inputs, None, error=error_msg)
            raise RuntimeError(error_msg)
            
        try:
            run_kwargs = dict(inputs)
            if self.config_name:
                run_kwargs["config_name"] = self.config_name
            if self.mode:
                run_kwargs["mode"] = self.mode
                
            tool_start = time.time()
            
            def _do_tool_run():
                return tool.run(**run_kwargs)
            
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(_do_tool_run)
                result = future.result(timeout=self.tool_timeout_s)
            except FuturesTimeoutError:
                error_msg = f"Tool '{tool_name}' execution timed out after {self.tool_timeout_s}s"
                logger.error(error_msg)
                raise TimeoutError(error_msg)
            finally:
                # P6.2：超时后立即放弃等待（禁止 with ThreadPoolExecutor 默认 wait=True）
                executor.shutdown(wait=False, cancel_futures=True)
                
            tool_duration = time.time() - tool_start
            
            # Record tool duration
            self.tool_durations[step.id] = tool_duration
            
            normalized_result = self._adapt_result_for_step(step, tool_name, inputs, result)
            tool_error = self._extract_tool_error(normalized_result)
            logger.debug(f"Tool result: {normalized_result}")
            
            # Process outputs using the standard method
            updates = {} if tool_error else self._process_outputs(step, normalized_result)
            
            # Record history
            self._record_step(step, inputs, normalized_result, error=tool_error)
            
            # Write log
            if self.result_md_path:
                self._write_markdown_log(step, inputs, normalized_result, updates, duration=tool_duration)
                
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            self.tool_durations[step.id] = 0.0
            self._record_step(step, inputs, None, error=str(e))
            if self.result_md_path:
                 self._write_markdown_log(step, inputs, {"error": str(e)}, {}, duration=0.0)

    def _handle_action_return_value(self, step: Step, action_data: Dict[str, Any]):
        """处理 return_value Action：直接返回值。"""
        value = action_data.get("value")
        logger.info(f"Returning value: {value}")
        normalized_value = self._adapt_result_for_step(step, "return_value", {}, value)
        tool_error = self._extract_tool_error(normalized_value)
        updates = {} if tool_error else self._process_outputs(step, normalized_value)
        self._record_step(step, {}, normalized_value, error=tool_error)
        if self.result_md_path:
            self._write_markdown_log(step, {}, normalized_value, updates)

    def _handle_action_ask_user(self, step: Step, action_data: Dict[str, Any]):
        """处理 ask_user Action：向用户询问输入。"""
        question = action_data.get("question")
        variable = action_data.get("variable")
        logger.info(f"Asking user: {question}")
        inputs = {"question": question}
        if variable:
            inputs["variable"] = variable
        self._execute_tool_safe("user_input", inputs, step)

    def _handle_action_execute_tool(self, step: Step, action_data: Dict[str, Any]):
        """处理 execute_tool Action：执行指定工具。"""
        tool_name = action_data.get("tool")
        inputs = action_data.get("inputs", {})
        if tool_name == "table_lookup" and "use_llm" not in inputs:
            inputs["use_llm"] = False
        self._execute_tool_safe(tool_name, inputs, step)

    def _handle_action_table_lookup(self, step: Step, action_data: Dict[str, Any]):
        """处理 table_lookup Action：查表操作，映射到 table_lookup 工具。"""
        table_name = action_data.get("table_name", "")
        conditions = action_data.get("conditions", {})
        target_column = action_data.get("target_column", "")
        file_name = action_data.get("file_name", "")
        inputs = {
            "table_name": table_name,
            "query_conditions": conditions if isinstance(conditions, dict) else {},
            "target_column": target_column,
            "use_llm": False,
        }
        if file_name:
            inputs["file_name"] = file_name
        self._execute_tool_safe("table_lookup", inputs, step)

    def _handle_action_conditional(self, step: Step, action_data: Dict[str, Any]):
        """处理 conditional Action：执行条件分支工具。"""
        condition_var = action_data.get("condition_var")
        resolved_condition = condition_var
        if isinstance(condition_var, str):
            if "${" in condition_var:
                resolved_condition = self.memory.resolve_value(condition_var)
            elif condition_var in self.memory.blackboard:
                resolved_condition = self.memory.resolve_value(f"${{{condition_var}}}")
        inputs = {
            "condition_var": resolved_condition,
            "branches": action_data.get("branches", []),
            "default": action_data.get("default"),
        }
        self._execute_tool_safe("conditional", inputs, step)

    def _handle_action_search_knowledge(self, step: Step, action_data: Dict[str, Any]):
        """处理 search_knowledge Action：知识检索，映射到语义检索工具。"""
        query = action_data.get("query", "")
        inputs = {"query": query}
        self._execute_tool_safe("knowledge_search", inputs, step)

    def _handle_action_skip(self, step: Step, action_data: Dict[str, Any]):
        """处理 skip Action：跳过步骤。"""
        skip_reason = action_data.get('reason', 'No reason provided')
        logger.info(f"Skipping step: {skip_reason}")
        self._record_step(step, {}, {"skipped": True, "reason": skip_reason})
        if self.result_md_path:
            self._write_markdown_log(step, {}, {"skipped": True, "reason": skip_reason}, {})

    def _handle_action_unknown(self, step: Step, action: str):
        """处理未知的 Action 类型。"""
        error_msg = f"Unknown action: {action}"
        logger.error(error_msg)
        self._record_step(step, {}, None, error=error_msg)

    def _is_value_from_context(self, value) -> bool:
        """检查 return_value 的值是否可追溯到当前上下文。"""
        if isinstance(value, (int, float)):
            return True
        value_str = str(value)
        if value_str in self.memory.blackboard:
            return True
        for v in self.memory.blackboard.values():
            if value_str in str(v):
                return True
        return False

    def _should_allow_skip(self, step: Step) -> bool:
        """检查步骤是否应该允许跳过（其输出已存在于上下文中）。"""
        if not step.outputs:
            return False
        for output_def in step.outputs:
            key = getattr(output_def, "key", None) or getattr(output_def, "name", None)
            if key and key in self.memory.blackboard and self.memory.blackboard[key] is not None:
                continue
            return False
        return True

    def _smart_step_execution(self, step: Step, reason: str, missing_params: List[str]):
        """
        LLM 智能执行步骤。

        通过 LLM 分析当前步骤状态，决定执行何种操作来完成步骤。
        支持的操作包括：询问用户、执行工具、返回值、跳过。
        注意：具体的工具执行由 LLM 返回 execute_tool action，通过 tool 字段指定工具名。
        
        Args:
            step: 当前执行的步骤
            reason: 需要 LLM 介入的原因
            missing_params: 缺失的参数列表
        """
        # 构建上下文字符串
        context_str = json.dumps(self.memory.get_context_snapshot(), default=str, ensure_ascii=False)
        if len(context_str) > 3000:
            context_str = context_str[:3000] + "..."
        
        # 构建 Prompt 并调用 LLM
        system_prompt = self._build_smart_execution_prompt(step, reason, context_str)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请完成步骤: {step.name or step.id}"},
        ]
        
        try:
            result = chat_result_guarded(
                self.llm_client,
                messages,
                mode=self.mode,
                config_name=self.config_name,
                max_tokens=512
            )
            response = result.text
            action_data = self._extract_json_from_response(response)
            action = action_data.get("action")

            # 验证 return_value 和 skip 不会绕过必要的工具执行
            if action == "return_value":
                value = action_data.get("value")
                if value is not None and not self._is_value_from_context(value):
                    logger.warning(f"LLM 尝试 return_value 但值未在上下文中找到: {value}")
                    self._record_step(step, action_data,
                        {"error": "return_value 使用的值未在当前上下文中找到，LLM 可能正在绕过必要的计算步骤"},
                        error="return_value_rejected")
                    return
            if action == "skip":
                if not self._should_allow_skip(step):
                    logger.warning(f"LLM 尝试 skip 步骤 {step.id} 但输出尚未在上下文中")
                    self._record_step(step, action_data,
                        {"error": "skip 被拒绝：步骤的必要输出尚未在上下文中，请完成此步骤"},
                        error="skip_rejected")
                    return

            logger.debug(f"AI decision: {action}")
            
            # 使用策略模式分发到对应的处理方法
            action_handlers = {
                "return_value": self._handle_action_return_value,
                "ask_user": self._handle_action_ask_user,
                "execute_tool": self._handle_action_execute_tool,
                "table_lookup": self._handle_action_table_lookup,
                "conditional": self._handle_action_conditional,
                "search_knowledge": self._handle_action_search_knowledge,
                "skip": self._handle_action_skip,
            }
            
            handler = action_handlers.get(action)
            if handler:
                handler(step, action_data)
            else:
                self._handle_action_unknown(step, action)
                
        except Exception as e:
            error_msg = f"Smart execution error: {e}"
            logger.error(error_msg)
            self._record_step(step, {}, None, error=error_msg)

    def _write_markdown_log(self, step: Step, inputs: Any, result: Any, updates: Dict[str, Any], duration: float = 0.0):
        """Write step execution details to Markdown file"""
        if not self.result_md_path:
            return
            
        blackboard_values = self.memory.blackboard
        step_id = step.id
        step_name = step.name or step_id
        tool_name = step.tool
        description = step.description.content if step.description else ""
        
        # Determine current step note based on tool
        current_step_note = f"工具: {tool_name}"
        if tool_name == "table_lookup":
             table_name = inputs.get('table_name', '') if isinstance(inputs, dict) else ''
             current_step_note = f"查表: {table_name}"
        elif tool_name == "calculator":
             expr = inputs.get('expression', '') if isinstance(inputs, dict) else ''
             if len(expr) > 25:
                 expr = expr[:22] + "..."
             current_step_note = f"公式: {expr}" if expr else "公式计算"
        elif tool_name == "user_input":
             current_step_note = "用户输入"
        elif tool_name == "auto":
             current_step_note = "自动生成"
             
        # Update metadata for new variables
        for key in updates:
            self.variable_metadata[key] = {
                "source_step": step_id,
                "note": current_step_note,
                "duration": duration
            }
        
        with open(self.result_md_path, "a", encoding="utf-8") as f:
            f.write(f"## {step_id}: {step_name}\n\n")
            
            # 1. 写入 LLM 小结
            summary_start = time.time()
            llm_summary = self._generate_step_summary(step_name, tool_name, inputs, result, updates)
            summary_duration = time.time() - summary_start
            self.summary_durations[step.id] = summary_duration
            
            f.write(f"**LLM 小结** (耗时: {summary_duration:.2f}s): {llm_summary}\n\n")
            
            # 2. 写入 Blackboard 更新表格
            f.write(f"**Blackboard 状态**:\n\n")
            f.write("| 序号 | 参数 | 类型 | 取值 | 状态 | 耗时 | 备注 |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
            
            # 固定顺序：按字母序排序
            all_keys = sorted(blackboard_values.keys())
            
            for idx, key in enumerate(all_keys, 1):
                val = blackboard_values.get(key)
                
                # Default values
                status = "⚪ 已知量"
                note = "-"
                time_str = "-"
                
                if key in updates:
                    status = f"🟢 {step_id} 结果"
                    note = current_step_note
                    time_str = f"{duration:.2f}s"
                elif key in self.variable_metadata:
                    meta = self.variable_metadata[key]
                    source = meta.get("source_step", "Unknown")
                    status = f"🟡 {source} 求解"
                    note = meta.get("note", "-")
                    prev_duration = meta.get("duration", 0.0)
                    time_str = f"{prev_duration:.2f}s" if prev_duration > 0 else "-"
                else:
                    status = "⚪ 已知量"
                    note = "初始参数"
                    time_str = "-"

                # Type Inference (Simple)
                val_type = type(val).__name__
                if isinstance(val, (int, float)):
                    val_type = "数值"
                elif isinstance(val, str):
                    val_type = "字符串"
                
                # Format Value (Truncate if too long)
                val_str = str(val)
                # Escape pipe characters to avoid breaking the table
                val_str = val_str.replace("|", "\\|").replace("\n", " ")
                if len(val_str) > 50:
                    val_str = val_str[:47] + "..."

                f.write(f"| {idx} | {key} | {val_type} | {val_str} | {status} | {time_str} | {note} |\n")
                
            f.write("\n")
            
            # 3. 详细工具日志（折叠）
            f.write("<details>\n<summary>点击查看工具调用详情</summary>\n\n")
            f.write(f"**说明**: {description}\n\n")
            f.write(f"**工具**: `{tool_name}`\n\n")
            f.write(f"**耗时**: {duration:.4f}s\n\n")
            f.write("**输入**:\n")
            f.write(f"```json\n{json.dumps(inputs, ensure_ascii=False, indent=2)}\n```\n\n")
            f.write("**输出**:\n")
            f.write(f"```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n\n")
            f.write("</details>\n\n")
            f.write("---\n\n")

    def _process_outputs(self, step: Step, result: Any) -> Dict[str, Any]:
        # Update global context based on output mapping
        updates = {}
        if not step.outputs:
            return updates
            
        # If outputs is "*" map everything (if result is dict)
        if step.outputs == "*":
            if isinstance(result, dict):
                updates = result
                self.memory.update_context(result)
            else:
                updates = {"last_result": result}
                self.memory.update_context(updates)
            return updates
            
        for context_key, result_path in step.outputs.items():
            # Simple extraction
            # If result_path is empty string or ".", use the whole result
            if not result_path or result_path == ".":
                val = result
            # If result_path is "result", extract the 'result' field from dict
            elif result_path == "result":
                if isinstance(result, dict) and "result" in result:
                    val = result["result"]
                elif isinstance(result, dict) and context_key in result:
                    val = result[context_key]
                else:
                    val = result if not isinstance(result, dict) else None
            elif isinstance(result, dict) and result_path in result:
                val = result[result_path]
            else:
                # Try to treat result_path as a literal constant (e.g. "0.15", "-1", "True")
                try:
                    # Check for boolean first
                    if result_path.lower() == "true":
                         val = True
                    elif result_path.lower() == "false":
                         val = False
                    else:
                         # Try float/int
                         # Remove whitespace
                         rp = result_path.strip()
                         val = float(rp)
                         # Convert to int if it's an integer value and original string didn't look like a float (optional)
                         if val.is_integer() and '.' not in rp:
                             val = int(val)
                except:
                     val = None
                
            if val is not None:
                updates[context_key] = val
                self.memory.update_context({context_key: val})
        
        return updates
                
    def _extract_tool_error(self, result: Any) -> Optional[str]:
        """从工具输出中提取显式错误信息。"""
        if not isinstance(result, dict):
            return None
        error = result.get("error")
        return str(error) if error else None

    def _adapt_result_for_step(self, step: Step, tool_name: str, inputs: Dict[str, Any], result: Any) -> Any:
        """按步骤输出契约为工具结果补齐别名键，降低 LLM 返回格式漂移的影响。"""
        if not isinstance(result, dict):
            return result

        adapted = dict(result)
        output_keys = list(step.outputs.keys()) if isinstance(step.outputs, dict) else []
        if not output_keys:
            return adapted

        if tool_name == "calculator" and isinstance(adapted.get("results"), list):
            for item in adapted["results"]:
                if not isinstance(item, dict):
                    continue
                label = item.get("label")
                value = item.get("result")
                expression = item.get("expression")
                if label and value is not None and label not in adapted:
                    adapted[str(label)] = value
                if expression and value is not None and expression not in adapted:
                    adapted[str(expression)] = value

        for output_key in output_keys:
            if output_key in adapted:
                continue
            candidate_value = self._select_output_value(output_key, adapted)
            if candidate_value is not None:
                adapted[output_key] = candidate_value

        if "result" not in adapted and len(output_keys) == 1 and output_keys[0] in adapted:
            adapted["result"] = adapted[output_keys[0]]

        return adapted

    def _select_output_value(self, output_key: str, result: Dict[str, Any]) -> Any:
        """根据输出键语义从结果字典中选择最合适的值。"""
        candidates = self._collect_result_candidates(result)
        if not candidates:
            return None

        normalized_key = output_key.lower()
        exact_value = candidates.get(output_key)
        if exact_value is not None:
            return exact_value

        if normalized_key == "e":
            numeric_values = [value for value in candidates.values() if isinstance(value, (int, float))]
            if numeric_values:
                return max(numeric_values)

        aliases = []
        if normalized_key == "dwl_basic":
            aliases = ["design_high_water_level", "basic", "design"]
        elif normalized_key == "dwl_extreme":
            aliases = ["extreme_high_water_level", "extreme"]
        elif normalized_key == "delta_w_basic":
            aliases = ["delta_w_10yr", "10yr", "10_year", "10年", "basic"]
        elif normalized_key == "delta_w_extreme":
            aliases = ["delta_w_2yr", "2yr", "2_year", "2年", "extreme"]
        elif normalized_key == "e_basic":
            aliases = ["e_basic", "basic", "10yr", "10年"]
        elif normalized_key == "e_extreme":
            aliases = ["e_extreme", "extreme", "2yr", "2年"]
        elif normalized_key == "t":
            aliases = ["满载吃水t", "吃水t", "design_draft", "draft", "吃水"]
        elif normalized_key == "z1":
            aliases = ["z1", "龙骨下最小富裕深度"]
        elif normalized_key == "z2":
            aliases = ["z2", "波浪富裕深度"]
        elif normalized_key == "z3":
            aliases = ["z3", "船舶装载纵倾富裕深度", "船尾吃水"]
        elif normalized_key == "z4":
            aliases = ["z4", "备淤富裕深度"]

        for alias in aliases:
            for candidate_key, candidate_value in candidates.items():
                candidate_text = str(candidate_key).lower()
                if alias in candidate_text:
                    return candidate_value

        if len(candidates) == 1:
            return next(iter(candidates.values()))
        return None

    def _collect_result_candidates(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从结果字典中提取可映射到 blackboard 的候选值。"""
        meta_keys = {
            "result",
            "results",
            "labeled_results",
            "errors",
            "error",
            "expression",
            "cleaned_expression",
            "variables_used",
            "solve_for",
            "unknowns",
        }
        candidates: Dict[str, Any] = {}

        for key, value in result.items():
            if key in meta_keys:
                continue
            if isinstance(value, dict):
                nested_value = value.get("result")
                if nested_value is not None:
                    candidates[str(key)] = nested_value
                continue
            if isinstance(value, list):
                continue
            candidates[str(key)] = value

        labeled_results = result.get("labeled_results")
        if isinstance(labeled_results, dict):
            for key, value in labeled_results.items():
                if value is not None:
                    candidates[str(key)] = value

        results = result.get("results")
        if isinstance(results, list):
            for index, item in enumerate(results):
                if not isinstance(item, dict):
                    continue
                item_value = item.get("result")
                if item_value is None:
                    continue
                label = item.get("label") or f"expr_{index + 1}"
                candidates[str(label)] = item_value
                expression = item.get("expression")
                if expression:
                    candidates[str(expression)] = item_value

        nested_result = result.get("result")
        if isinstance(nested_result, dict):
            for key, value in nested_result.items():
                if value is not None and not isinstance(value, (dict, list)):
                    candidates[str(key)] = value

        return candidates

    def _record_step(self, step: Step, inputs: Any, outputs: Any, error: str = None, thinking: str = None, evidence: Dict[str, Any] = None):
        inferred_error = error or self._extract_tool_error(outputs)
        status = "failed" if inferred_error else "success"
        record = StepRecord(
            step_id=step.id,
            tool_name=step.tool,
            inputs=inputs,
            outputs=outputs,
            status=status,
            error=inferred_error,
            thinking=thinking,
            evidence=evidence,
        )
        self.memory.add_step_io({
            "step_id": step.id,
            "tool_name": step.tool,
            "inputs": inputs,
            "outputs": outputs,
            "status": status,
            "error": inferred_error,
            "thinking": thinking,
            "evidence": evidence,
        })
        self.memory.add_history(record)

    def _smart_select_tool(self, step: Step, current_inputs: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Use LLM to select the best tool and formulate inputs when step.tool is 'auto'.
        """
        if ToolRegistry is None:
            return None, {}
            
        tools_desc = ToolRegistry.list_tools()
        tools_str = "\n".join([f"- {name}: {desc}" for name, desc in tools_desc.items()])
        
        # Prepare context snapshot (truncated to avoid huge prompt)
        context_str = json.dumps(self.memory.get_context_snapshot(), default=str, ensure_ascii=False)
        if len(context_str) > 2000:
            context_str = context_str[:2000] + "...(truncated)"
            
        system_prompt = SMART_SELECT_TOOL_PROMPT.format(
            tools_str=tools_str,
            step_id=step.id,
            step_description=(
                step.description_zh
                or (step.description.content if step.description else "")
            ),
            current_inputs=json.dumps(current_inputs, default=str, ensure_ascii=False),
            context_str=context_str,
        )
        messages = [{"role": "system", "content": system_prompt}]
        try:
            response = self.llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            data = self._extract_json_from_response(response)
            return data.get("tool"), data.get("inputs", {})
        except Exception as e:
            logger.error(f"Smart selection failed: {e}")
            return None, {}

            
    def _build_smart_execution_prompt(self, step: Step, reason: str, context_str: str) -> str:
        """
        构建智能执行步骤的 System Prompt。
        
        Args:
            step: 当前执行的步骤
            reason: 需要 LLM 介入的原因
            context_str: 上下文变量字符串
            
        Returns:
            构建好的 system prompt
        """
        tool_hint = SMART_EXECUTION_CALCULATOR_HINT if step.tool == "calculator" else ""
        step_tool = step.tool if step.tool != "auto" else "calculator"
        return SMART_EXECUTION_PROMPT.format(
            step_name=step.name,
            step_description=(step.description.content if step.description else ""),
            step_notes=step.notes,
            step_inputs=json.dumps(step.inputs, ensure_ascii=False),
            context_str=context_str,
            reason=reason,
            tool_hint=tool_hint,
            step_tool=step_tool,
        )

    def _generate_step_summary(self, step_name: str, tool_name: str, resolved_inputs: Any, result: Any, updates: Dict[str, Any]) -> str:
        """Use LLM to generate a natural language summary of the step execution."""
        try:
            # Prepare data for prompt, truncating large structures
            inputs_str = json.dumps(resolved_inputs, default=str, ensure_ascii=False)
            if len(inputs_str) > 500: inputs_str = inputs_str[:500] + "..."
            
            result_str = json.dumps(result, default=str, ensure_ascii=False)
            if len(result_str) > 500: result_str = result_str[:500] + "..."
            
            updates_str = json.dumps(updates, default=str, ensure_ascii=False)
            
            system_prompt = STEP_SUMMARY_PROMPT.format(
                step_name=step_name,
                tool_name=tool_name,
                inputs_str=inputs_str,
                result_str=result_str,
                updates_str=updates_str,
            )
            messages = [{"role": "system", "content": system_prompt.strip()}]
            
            response = self.llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            return response.strip()
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return f"执行工具 {tool_name} 完成。更新变量: {list(updates.keys())}"

    @staticmethod
    def _build_citations_from_sop_trace(runner) -> list:
        """从 SOP 执行追踪中构建 citations。"""
        citations = []
        history = getattr(getattr(runner, "memory", None), "history", [])
        for record in history:
            tool_name = getattr(record, "tool_name", "") or ""
            step_id = getattr(record, "step_id", "") or ""
            outputs = getattr(record, "outputs", None) or {}
            if tool_name in ("table_lookup", "knowledge_search"):
                citations.append({
                    "source": tool_name,
                    "step_id": step_id,
                    "snippet": str(outputs)[:200],
                })
        return citations

    @staticmethod
    def _build_sop_trace(runner, sop: "SOP") -> list:
        """从 SOP 执行追踪中构建步骤明细列表。"""
        step_durations = getattr(runner, "step_durations", {}) or {}
        history = getattr(getattr(runner, "memory", None), "history", [])
        trace = []
        for idx, step in enumerate(sop.steps):
            record = None
            for r in history:
                if r.step_id == step.id:
                    record = r
                    break
            trace.append({
                "step_id": step.id,
                "step_name": step.name or step.name_zh or step.id,
                "step_index": idx + 1,
                "tool": step.tool or "auto",
                "description": step.description_zh or (step.description.content if step.description else ""),
                "inputs": (record.inputs if record else step.inputs) or {},
                "outputs": (record.outputs if record else None),
                "duration": step_durations.get(step.id, 0.0),
                "status": (record.status if record else "pending"),
                "error": (record.error if record else None),
                "thinking": (record.thinking if record else None),
                "evidence": (record.evidence if record else None),
            })
        return trace

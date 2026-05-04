"""
执行调度核心模块，负责 SOP 步骤编排、工具调用与上下文更新。

支持依赖注入：
- memory: Memory 实例
- llm_client: LLMClient 实例
"""
import time
import json
import os
from typing import Dict, Any, Tuple, List, Optional, TYPE_CHECKING
from angineer_core.base_contracts import SOP, Step
from angineer_core.memory import Memory, StepRecord
from angineer_core.base_logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from ai_inference.llm_client import LLMClient

try:
    from engtools.BaseTool import ToolRegistry
except ImportError:
    ToolRegistry = None

from ai_inference.llm_client import llm_client as default_llm_client


class Dispatcher:
    def __init__(
        self,
        config_name: str = None,
        mode: str = "instruct",
        result_md_path: str = None,
        memory: Optional[Memory] = None,
        llm_client: Optional["LLMClient"] = None
    ):
        """
        初始化执行器上下文与模型配置。
        
        Args:
            config_name: LLM 配置名称
            mode: 执行模式
            result_md_path: Markdown 日志文件路径
            memory: 可选的 Memory 实例（依赖注入）
            llm_client: 可选的 LLMClient 实例（依赖注入）
        """
        self.memory = memory or Memory()
        self.config_name = config_name
        self.mode = mode or "instruct"
        self.result_md_path = result_md_path
        self._llm_client = llm_client or default_llm_client
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
        
        return json.loads(cleaned.strip())
    
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

    def run(self, sop: SOP, initial_context: Dict[str, Any], pre_logs: List[Dict[str, Any]] = None):
        """
        Execute the SOP with the given initial context.
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
            self._execute_step(step)
            
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

        # 2. Decision Logic
        needs_llm = False
        reason = ""
        
        if missing_params:
            needs_llm = True
            reason = f"Missing parameters: {missing_params}"
        elif step.notes:
            needs_llm = True
            reason = f"Notes present: {step.notes}"
        elif step.tool == "auto":
            needs_llm = True
            reason = "Tool is 'auto'"
            
        if needs_llm:
            logger.debug(f"Hybrid mode: waking up LLM - {reason}")
            self._smart_step_execution(step, reason, missing_params)
        else:
            logger.debug("Hybrid mode: rule-based execution (all params ready)")
            # Execute directly
            self._execute_tool_safe(step.tool, ready_inputs, step)

    def _should_skip_step(self, step: Step, context: Dict[str, Any]) -> bool:
        """Check if step outputs are already present in context."""
        if not step.outputs:
            return False
        # If outputs is "*" we can't easily check, so don't skip
        if step.outputs == "*":
            return False
            
        output_keys = list(step.outputs.keys())
        if not output_keys:
            return False
            
        # Check if all output keys exist and are not None
        # Exception: if the value in context is explicitly "None" string or something? No.
        return all(key in context and context.get(key) is not None for key in output_keys)

    # 执行元 SOP 内置工具（llm_generate）
    def _execute_meta_sop_tool(self, tool_name: str, inputs: Dict[str, Any], step: Step) -> Any:
        if tool_name == "llm_generate":
            messages = []
            query = inputs.get("query", "")
            context = inputs.get("context", "")
            if context:
                messages.append({"role": "system", "content": f"请根据以下上下文回答用户问题：\n{context}"})
            messages.append({"role": "user", "content": query})
            response_text = self._llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
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
                updates = self._process_outputs(step, result)
                self._record_step(step, inputs, result)
                if self.result_md_path:
                    self._write_markdown_log(step, inputs, result, updates, duration=tool_duration)
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
            result = tool.run(**run_kwargs)
            tool_duration = time.time() - tool_start
            
            # Record tool duration
            self.tool_durations[step.id] = tool_duration
            
            logger.debug(f"Tool result: {result}")
            
            # Process outputs using the standard method
            updates = self._process_outputs(step, result)
            
            # Record history
            self._record_step(step, inputs, result)
            
            # Write log
            if self.result_md_path:
                self._write_markdown_log(step, inputs, result, updates, duration=tool_duration)
                
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
        updates = self._process_outputs(step, value)
        self._record_step(step, {}, value)
        if self.result_md_path:
            self._write_markdown_log(step, {}, value, updates)

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
        self._execute_tool_safe(tool_name, inputs, step)

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
        messages = [{"role": "system", "content": system_prompt}]
        
        try:
            response = self.llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            action_data = self._extract_json_from_response(response)
            action = action_data.get("action")
            
            logger.debug(f"AI decision: {action}")
            
            # 使用策略模式分发到对应的处理方法
            action_handlers = {
                "return_value": self._handle_action_return_value,
                "ask_user": self._handle_action_ask_user,
                "execute_tool": self._handle_action_execute_tool,
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
        description = step.description or ""
        
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
                else:
                    val = result  # Fallback to whole result if no 'result' field
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
                
    def _record_step(self, step: Step, inputs: Any, outputs: Any, error: str = None):
        record = StepRecord(
            step_id=step.id,
            tool_name=step.tool,
            inputs=inputs,
            outputs=outputs,
            status="failed" if error else "success",
            error=error
        )
        self.memory.add_step_io({
            "step_id": step.id,
            "tool_name": step.tool,
            "inputs": inputs,
            "outputs": outputs,
            "status": "failed" if error else "success",
            "error": error
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
            
        system_prompt = f"""
You are an intelligent agent dispatcher. Your task is to select the most appropriate tool to execute the current step.

Available Tools:
{tools_str}

Current Step Information:
- ID: {step.id}
- Description: {step.description_zh or step.description}
- Pre-resolved Inputs: {json.dumps(current_inputs, default=str, ensure_ascii=False)}

Global Context:
{context_str}

Instructions:
1. Analyze the step description and context.
2. Select the best tool from the available list to accomplish the step goal.
3. Extract or formulate the necessary arguments for the tool based on context and inputs.
4. Return a JSON object with "tool" and "inputs".

Example Output:
{{
  "tool": "calculator",
  "inputs": {{ "expression": "12 * 50" }}
}}
"""
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
        return f"""You are the Step Executor of an expert system. You are facing a step that requires your attention.

Current Step:
- Name: {step.name}
- Description: {step.description}
- Notes/Warnings: {step.notes}
- Required Inputs: {step.inputs}

Context Variables:
{context_str}

Situation: {reason}

Your Goal: Complete this step or make progress towards it.

Available Actions (Output JSON):
1. ASK_USER: If parameters are missing and you cannot deduce them.
   {{ "action": "ask_user", "question": "...", "variable": "变量名" }}
   
2. SEARCH_KNOWLEDGE: If you need to check textual regulations.
    {{ "action": "search_knowledge", "query": "..." }}
    
 3. TABLE_LOOKUP: If you need to find a value in a standard table (e.g. Dimensions of 10000 DWT ship).
    {{ "action": "table_lookup", "table_name": "...", "conditions": "...", "target_column": "..." }}

 4. EXECUTE_TOOL: If you have enough info to run the tool (calculator, etc).
    {{ "action": "execute_tool", "tool": "{step.tool if step.tool != 'auto' else 'appropriate_tool'}", "inputs": {{ ... }} }}
    
 5. RETURN_VALUE: If the step is just setting a value or you know the answer directly.
    {{ "action": "return_value", "value": 0.15 }}

 6. SKIP: If this step is already done or irrelevant.
    {{ "action": "skip", "reason": "..." }}

Output ONLY the JSON."""

    def _generate_step_summary(self, step_name: str, tool_name: str, resolved_inputs: Any, result: Any, updates: Dict[str, Any]) -> str:
        """Use LLM to generate a natural language summary of the step execution."""
        try:
            # Prepare data for prompt, truncating large structures
            inputs_str = json.dumps(resolved_inputs, default=str, ensure_ascii=False)
            if len(inputs_str) > 500: inputs_str = inputs_str[:500] + "..."
            
            result_str = json.dumps(result, default=str, ensure_ascii=False)
            if len(result_str) > 500: result_str = result_str[:500] + "..."
            
            updates_str = json.dumps(updates, default=str, ensure_ascii=False)
            
            system_prompt = f"""
你是一个专家系统的执行记录员。请根据以下信息生成一段简洁、客观的中文执行小结。

【上下文信息】
- 步骤名称: {step_name}
- 工具: {tool_name}
- 输入: {inputs_str}
- 输出: {result_str}
- 状态更新: {updates_str}

【撰写要求】
1. **极其简洁**：字数控制在 80 字以内。
2. **客观陈述**：直接陈述事实，不要使用“我”、“系统”、“执行了”等主语。
3. **重点突出**：核心关注“根据什么输入（如条件、公式），得到了什么结果（关键数值）”。
4. **错误处理**：如果输出包含 error，必须明确指出错误原因。
5. **格式示例**：
   - 查表（表A），在条件 x=1 下获取到 y=2。
   - 根据公式 a+b 计算得到 c=3。
   - 用户输入变量 d，值为 4。
"""
            messages = [{"role": "system", "content": system_prompt.strip()}]
            
            response = self.llm_client.chat(messages, mode=self.mode, config_name=self.config_name)
            return response.strip()
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return f"执行工具 {tool_name} 完成。更新变量: {list(updates.keys())}"

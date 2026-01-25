import os
import time
import json
from dotenv import load_dotenv
from openai import OpenAI

# 加载环境变量
load_dotenv()

class LLMClient:
    """
    LLM 客户端类，负责管理多个 LLM 配置并处理对话请求。
    默认优先使用 NVIDIA 提供的模型，支持自动切换备用配置。
    """
    def __init__(self):
        # 加载所有 LLM 配置
        nvidia_api_key = os.getenv("NVIDIA_API_KEY")
        nvidia_base_url = os.getenv("NVIDIA_API_URL")
        
        self.configs = [
            # 阿里云系列模型
            {
                "name": "私有配置 (Private)",
                "api_key": os.getenv("Private_ALIYUN_API_KEY"),
                "base_url": os.getenv("Private_ALIYUN_API_URL"),
                "model": os.getenv("Private_ALIYUN_MODEL")
            },
            # NVIDIA 系列模型
            {
                "name": "NVIDIA (Nemotron)",
                "api_key": nvidia_api_key,
                "base_url": nvidia_base_url,
                "model": os.getenv("NVIDIA_MODEL_NEMOTRON")
            },
            {
                "name": "DeepSeek Official",
                "api_key": os.getenv("DEEPSEEK_API_KEY"),
                "base_url": os.getenv("DEEPSEEK_API_URL"),
                "model": os.getenv("DEEPSEEK_MODEL")
            },
            {
                "name": "NVIDIA (Kimi/Moonshot)",
                "api_key": nvidia_api_key,
                "base_url": nvidia_base_url,
                "model": os.getenv("NVIDIA_MODEL_KIMI")
            },
            {
                "name": "NVIDIA (MiniMax)",
                "api_key": nvidia_api_key,
                "base_url": nvidia_base_url,
                "model": os.getenv("NVIDIA_MODEL_MINIMAX")
            },
            # 智谱 AI 系列模型
            {
                "name": "智谱 AI (GLM-4.7-Flash)",
                "api_key": os.getenv("ZHIPU_API_KEY"),
                "base_url": os.getenv("ZHIPU_API_URL"),
                "model": os.getenv("ZHIPU_MODEL")
            },
            {
                "name": "公共配置 (Public)",
                "api_key": os.getenv("Public_ALIYUN_API_KEY"),
                "base_url": os.getenv("Public_ALIYUN_API_URL"),
                "model": os.getenv("Public_ALIYUN_MODEL")
            }
        ]
        
    def chat(self, messages: list, temperature: float = 0.1, model: str = None, mode: str = "instruct", config_name: str = None) -> str:
        """
        发送对话请求并获取响应。
        
        Args:
            messages: 消息列表
            temperature: 生成温度
            model: 可选，指定使用的模型 ID。如果未提供，则使用配置中的默认模型。
            mode: 指定运行模式 ('thinking', 'instruct')，默认为 'instruct'。
            config_name: 可选，指定使用的配置名称 (e.g., "NVIDIA (Nemotron)", "DeepSeek Official")
            
        Returns:
            str: 模型生成的回答内容
        """
        # 允许通过环境变量强制覆盖模式（主要用于测试）
        env_mode = os.getenv("FORCE_LLM_MODE")
        if env_mode:
            mode = env_mode

        last_error = None
        processed_messages = list(messages)
        
        # 处理模式 (Mode) 逻辑
        if mode == "thinking":
            # 如果是思考模式，且没有显式指定模型，优先尝试寻找带 "thinking" 或 "r1" 的模型
            if not model:
                for config in self.configs:
                    if config.get("model") and ("thinking" in config["model"].lower() or "r1" in config["model"].lower()):
                        model = config["model"]
                        break
            
            # 注入思考提示词
            thinking_prompt = "请在回答之前进行深度思考，并给出详细的思考过程（使用 <thought> 标签包裹）。"
            has_system = any(m.get("role") == "system" for m in processed_messages)
            if has_system:
                for m in processed_messages:
                    if m.get("role") == "system":
                        m["content"] = f"{m['content']}\n\n{thinking_prompt}"
            else:
                processed_messages.insert(0, {"role": "system", "content": thinking_prompt})
                
        elif mode == "instruct":
            instruct_prompt = "请作为一个专业的助手，严格按照指令进行回答，保持简洁且专业。"
            has_system = any(m.get("role") == "system" for m in processed_messages)
            if not has_system:
                processed_messages.insert(0, {"role": "system", "content": instruct_prompt})

        for config in self.configs:
            if not config["api_key"] or not config["base_url"]:
                continue

            # 如果指定了 config_name，跳过不匹配的配置
            if config_name and config["name"] != config_name:
                continue
            
            # 确定当前使用的模型：
            # 1. 如果外部指定了 model，且当前配置是 NVIDIA（因为 NVIDIA 接口通用性最强），则使用指定的 model
            # 2. 否则使用该配置默认的 model
            current_model = config["model"]
            if model and (config["name"].startswith("NVIDIA") or config["name"].startswith("DeepSeek")):
                 # 如果用户指定了 model，且当前是支持多模型的 Provider (NVIDIA/DeepSeek)，尝试匹配
                 # 但这里简单处理：如果 config["name"] 匹配了请求的 config name，才使用
                 pass
            
            # 修正逻辑：LLMClient 会遍历所有 config 尝试调用
            # 我们应该只调用匹配的 config (如果指定了 config name)
            # 目前的逻辑是遍历所有 config，直到成功。
            # 这会导致如果第一个失败，会尝试第二个。
            
            # 为了支持前端选择特定 Config (Model Provider)
            # 我们可以在 chat 参数里加一个 config_name? 
            # 暂时保持现状，但注意 DeepSeek 的 base_url 是特定的
            
            # 记录日志：开始连接
            print("\n" + "="*50)
            print(f"[LLM 呼叫] 正在连接: {config['name']} | 模式: {mode or '默认'}")
            print(f"   模型: {current_model}")
            print(f"   地址: {config['base_url']}")
            print("-" * 20)
            print("[输入消息]:")
            for msg in processed_messages:
                role = msg.get('role', '未知')
                content = msg.get('content', '')
                print(f"   [{role.upper()}]: {content}")
            print("-" * 20)

            start_time = time.time()
            
            try:
                # 如果地址以 /chat/completions 结尾，则清理掉，OpenAI 客户端会自动补全
                base_url = config["base_url"]
                if base_url.endswith("/chat/completions"):
                    base_url = base_url.replace("/chat/completions", "")
                
                client = OpenAI(
                    api_key=config["api_key"],
                    base_url=base_url
                )
                
                # 如果是 DeepSeek，确保 model 正确
                if config["name"] == "DeepSeek Official" and not current_model:
                     current_model = "deepseek-chat"

                response = client.chat.completions.create(
                    model=current_model,
                    messages=processed_messages,
                    temperature=temperature,
                    max_tokens=1024
                )
                
                content = response.choices[0].message.content
                duration = time.time() - start_time
                
                # 记录日志：成功返回
                print(f"[输出响应] (耗时: {duration:.2f}秒):")
                print(f"   {content}")
                print("="*50 + "\n")
                
                return content
                
            except Exception as e:
                duration = time.time() - start_time
                print(f"❌ [错误] (耗时: {duration:.2f}秒): {str(e)}")
                print("="*50 + "\n")
                last_error = e
                continue
                
        # 如果所有配置都尝试失败
        raise last_error or ValueError("未找到有效的 LLM 配置")
            
# 全局单例
llm_client = LLMClient()

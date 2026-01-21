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
                "name": "NVIDIA (DeepSeek-V3)",
                "api_key": nvidia_api_key,
                "base_url": nvidia_base_url,
                "model": os.getenv("NVIDIA_MODEL_DEEPSEEK")
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
            {
                "name": "公共配置 (Public)",
                "api_key": os.getenv("Public_ALIYUN_API_KEY"),
                "base_url": os.getenv("Public_ALIYUN_API_URL"),
                "model": os.getenv("Public_ALIYUN_MODEL")
            }
        ]
        
    def chat(self, messages: list, temperature: float = 0.1, model: str = None) -> str:
        """
        发送对话请求并获取响应。
        
        Args:
            messages: 消息列表
            temperature: 生成温度
            model: 可选，指定使用的模型 ID。如果未提供，则使用配置中的默认模型。
            
        Returns:
            str: 模型生成的回答内容
        """
        last_error = None
        
        for config in self.configs:
            if not config["api_key"] or not config["base_url"]:
                continue
            
            # 确定当前使用的模型
            current_model = model if model and config["name"].startswith("NVIDIA") else config["model"]
            
            # 记录日志：开始连接
            print("\n" + "="*50)
            print(f"[LLM 呼叫] 正在连接: {config['name']}")
            print(f"   模型: {current_model}")
            print(f"   地址: {config['base_url']}")
            print("-" * 20)
            print("[输入消息]:")
            for msg in messages:
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
                
                response = client.chat.completions.create(
                    model=current_model,
                    messages=messages,
                    temperature=temperature
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

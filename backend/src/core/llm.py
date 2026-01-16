import os
import time
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

class LLMClient:
    def __init__(self):
        # Load both configs
        self.configs = [
            {
                "name": "Private",
                "api_key": os.getenv("Private_ALIYUN_API_KEY"),
                "base_url": os.getenv("Private_ALIYUN_API_URL"),
                "model": os.getenv("Private_ALIYUN_MODEL")
            },
            {
                "name": "Public",
                "api_key": os.getenv("Public_ALIYUN_API_KEY"),
                "base_url": os.getenv("Public_ALIYUN_API_URL"),
                "model": os.getenv("Public_ALIYUN_MODEL")
            }
        ]
        
    def chat(self, messages: list, temperature: float = 0.1) -> str:
        last_error = None
        
        for config in self.configs:
            if not config["api_key"] or not config["base_url"]:
                continue
                
            # Log Start
            print("\n" + "="*50)
            print(f"🤖 [LLM Call] Connecting to: {config['name']}")
            print(f"   Model: {config['model']}")
            print(f"   URL: {config['base_url']}")
            print("-" * 20)
            print("📤 [Input Messages]:")
            for msg in messages:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                print(f"   [{role.upper()}]: {content}")
            print("-" * 20)

            start_time = time.time()
            
            try:
                # Clean base_url if it ends with /chat/completions
                base_url = config["base_url"]
                if base_url.endswith("/chat/completions"):
                    base_url = base_url.replace("/chat/completions", "")
                
                client = OpenAI(
                    api_key=config["api_key"],
                    base_url=base_url
                )
                
                response = client.chat.completions.create(
                    model=config["model"],
                    messages=messages,
                    temperature=temperature
                )
                
                content = response.choices[0].message.content
                duration = time.time() - start_time
                
                # Log Success
                print(f"📥 [Output Response] ({duration:.2f}s):")
                print(f"   {content}")
                print("="*50 + "\n")
                
                return content
                
            except Exception as e:
                duration = time.time() - start_time
                print(f"❌ [Error] ({duration:.2f}s): {str(e)}")
                print("="*50 + "\n")
                last_error = e
                continue
                
        # If we get here, all failed
        raise last_error or ValueError("No valid LLM configuration found")
            
llm_client = LLMClient()

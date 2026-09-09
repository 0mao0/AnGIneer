import requests
import json
import os
from tqdm import tqdm

import fitz  # PyMuPDF
from PIL import Image
import io
import base64

# First run Popo and Qwen3-VL Locally by vllm

_TRANSFORMERS_MODEL = None
_TRANSFORMERS_PROCESSOR = None


def _popo_endpoints():
    """推理端点列表：[(url, key, model), ...]，数组顺序=优先级，第一项为默认。

    来自 POPO_CONFIGS (JSON list)：[{"name","url","api_key","model"}, ...]；
    连接失败/超时自动尝试列表中的下一项（由调用方循环实现）。
    """
    raw = os.environ.get("POPO_CONFIGS", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        print("POPO_CONFIGS 非法 JSON，忽略")
        return []
    if not isinstance(data, list):
        return []
    endpoints = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        key = str(item.get("api_key") or "").strip()
        model = str(item.get("model") or "").strip() or "Popo"
        endpoints.append((url, key, model))
    return endpoints


def _transformers_generate(prompt, base64_image):
    global _TRANSFORMERS_MODEL, _TRANSFORMERS_PROCESSOR
    import torch
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    model_path = os.environ.get(
        "POPO_MODEL_PATH",
        "popo_model",
    )
    max_new_tokens = int(os.environ.get("POPO_MAX_NEW_TOKENS", "2048"))

    if _TRANSFORMERS_MODEL is None or _TRANSFORMERS_PROCESSOR is None:
        _TRANSFORMERS_MODEL = Qwen3VLForConditionalGeneration.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )
        _TRANSFORMERS_PROCESSOR = AutoProcessor.from_pretrained(
            model_path,
            tokenizer_kwargs={"padding_side": "left"},
        )
        if hasattr(_TRANSFORMERS_PROCESSOR, "tokenizer") and hasattr(_TRANSFORMERS_PROCESSOR.tokenizer, "padding_side"):
            _TRANSFORMERS_PROCESSOR.tokenizer.padding_side = "left"

    content = []
    if base64_image:
        content.append(
            {
                "type": "image",
                "image": f"data:image/jpeg;base64,{base64_image}",
            }
        )
    content.append({"type": "text", "text": prompt[:100000] if len(prompt) > 100000 else prompt})
    messages = [{"role": "user", "content": content}]

    inputs = _TRANSFORMERS_PROCESSOR.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = inputs.to(_TRANSFORMERS_MODEL.device)
    with torch.no_grad():
        generated_ids = _TRANSFORMERS_MODEL.generate(**inputs, max_new_tokens=max_new_tokens)
    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = _TRANSFORMERS_PROCESSOR.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )
    return output_text[0] if output_text else ""

def popo_generate(prompt, base64_image):
    if os.environ.get("POPO_INFERENCE_BACKEND") == "transformers":
        return _transformers_generate(prompt, base64_image)

    from openai import OpenAI

    endpoints = _popo_endpoints()
    res = ""
    prompt = prompt[:100000] if len(prompt)>100000 else prompt
    max_tokens = int(os.environ.get("POPO_MAX_TOKENS", "4096"))

    if base64_image:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
    else:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ],
            }
        ]

    last_error = None
    for url, key, base_model in endpoints:
        try:
            client = OpenAI(
                base_url=url or None,
                api_key=key or None,
                timeout=float(os.environ.get("POPO_API_TIMEOUT", "300")),
            )
            cnt = 0
            while cnt < 2:
                try:
                    response = client.chat.completions.create(
                        model=base_model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=1,
                    )
                    res = response.choices[0].message.content
                    return res
                except Exception as e:
                    cnt += 1
                    last_error = e
                    print(e)
            raise last_error
        except Exception as e:
            last_error = e
            print(f"POPO endpoint {url} failed: {e}")

    return ""

def qwen_generate(prompt, base64_image):
    from openai import OpenAI

    endpoints = _popo_endpoints()
    base_model = "Qwen3-VL-4B-Instruct"
    res = ""
    prompt = prompt[:100000] if len(prompt)>100000 else prompt
    max_tokens = int(os.environ.get("POPO_MAX_TOKENS", "4096"))

    if base64_image:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
    else:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ],
            }
        ]

    for url, key, _model in endpoints:
        try:
            client = OpenAI(
                base_url=url or None,
                api_key=key or None,
                timeout=float(os.environ.get("POPO_API_TIMEOUT", "300")),
            )
            cnt = 0
            while cnt < 2:
                try:
                    response = client.chat.completions.create(
                        model=base_model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature = 1
                    )
                    res = response.choices[0].message.content

                    return res

                except Exception as e:
                    cnt += 1
                    print(e)
            raise RuntimeError("all retries failed")
        except Exception as e:
            print(f"POPO endpoint {url} failed: {e}")

    return ""

def gpt_generate(prompt, base64_image):#gemini-3-pro-preview
    from openai import OpenAI

    endpoints = _popo_endpoints()
    base_model = "gemini-3-flash-preview"
    res = ""
    prompt = prompt[:100000] if len(prompt)>100000 else prompt
    max_tokens = int(os.environ.get("POPO_MAX_TOKENS", "4096"))

    if base64_image:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
    else:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ],
            }
        ]

    for url, key, _model in endpoints:
        try:
            client = OpenAI(
                base_url=url or None,
                api_key=key or None,
                timeout=float(os.environ.get("POPO_API_TIMEOUT", "300")),
            )
            cnt = 0
            while cnt < 2:
                try:
                    response = client.chat.completions.create(
                        model=base_model,
                        messages=messages,
                        temperature = 1
                    )
                    res = response.choices[0].message.content

                    return res

                except Exception as e:
                    cnt += 1
                    print(e)
            raise RuntimeError("all retries failed")
        except Exception as e:
            print(f"POPO endpoint {url} failed: {e}")

    return ""

import requests
import json
import os
import itertools
import threading
from tqdm import tqdm

import fitz  # PyMuPDF
from PIL import Image
import io
import base64

# First run Popo and Qwen3-VL Locally by vllm

_TRANSFORMERS_MODEL = None
_TRANSFORMERS_PROCESSOR = None

# 多端点轮询游标（进程内单调计数；本模块每次推理在独立子进程加载，
# 子进程内各计数器的起点仍保证近似按权重分配）。
_POPO_RR_LOCK = threading.Lock()
_POPO_RR_CURSOR = itertools.count()


def _endpoint_weights(endpoints):
    """POPO_ENDPOINT_WEIGHTS='dgx:1,company:3' → [1, 3]（与 endpoints 同序）。

    缺省/未匹配的端点权重 1。权重语义=发往该端点的请求占比（轮询配比），
    不是并发上限——并发由 POPO_MAX_CONCURRENCY（文档槽位）× 占比决定。
    """
    raw = os.environ.get("POPO_ENDPOINT_WEIGHTS", "").strip()
    table = {}
    for part in raw.split(","):
        if ":" in part:
            k, _, v = part.partition(":")
            try:
                table[k.strip()] = max(1, int(v))
            except ValueError:
                pass
    out = []
    for ep in endpoints:
        name = ep[0] if len(ep) > 3 else ""
        out.append(table.get(name, 1))
    return out


def _rotated_endpoints(endpoints):
    """按权重轮转端点：第 N 次请求优先按展开表选中某端点，失败顺延其余端点。

    展开表 = 每个端点按权重重复 N 次（如 dgx:1,company:3 → [dgx, c, c, c]）；
    轮转后按 URL 去重保序（第一个=首选，其余=失败回退顺序）。
    单端点时恒返回原列表，行为不变。"""
    if len(endpoints) <= 1:
        return list(endpoints)
    weights = _endpoint_weights(endpoints)
    expanded = [ep for ep, w in zip(endpoints, weights) for _ in range(w)]
    with _POPO_RR_LOCK:
        start = next(_POPO_RR_CURSOR) % len(expanded)
    order = expanded[start:] + expanded[:start]
    seen = set()
    uniq = []
    for ep in order:
        url = ep[1]
        if url not in seen:
            seen.add(url)
            uniq.append(ep)
    return uniq


def _popo_endpoints():
    """推理端点列表：[(name, url, key, model), ...]，数组顺序=优先级，第一项为默认。

    来自 POPO_CONFIGS (JSON list)：[{"name","url","api_key","model"}, ...]；
    连接失败/超时自动尝试列表中的下一项（由调用方循环实现）；
    name 供 POPO_ENDPOINT_WEIGHTS 按端点配请求占比。
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
        name = str(item.get("name") or "").strip() or url.split("//")[-1].split("/")[0]
        endpoints.append((name, url, key, model))
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

    # 多端点=按请求计数轮询分流（每端点承 1/N 流量，各端点并发闸=总闸/N）；
    # 失败时顺延尝试其余端点（每端点一次），全失败才 return ""（2026-10-15 双端点改造；
    # 原语义「顺序优先级回退」在 DGX 健康时会让 company 端点零流量，无法并行提速）。
    order = _rotated_endpoints(endpoints)
    last_error = None
    for _name, url, key, base_model in order:
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

    for _name, url, key, _model in endpoints:
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

    for _name, url, key, _model in endpoints:
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

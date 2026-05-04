"""bge-m3 Embedding 服务（OpenAI 兼容 API）。"""
import os
from typing import List, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_PATH = os.environ.get("BGE_M3_MODEL_PATH", r"D:\AI\AImodles\bge-m3")
PORT = int(os.environ.get("BGE_M3_PORT", "7997"))

# 自动检测 CUDA 可用性
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[INFO] Using device: {DEVICE}")

app = FastAPI(title="bge-m3 Embedding Service")
model: Optional[SentenceTransformer] = None


class EmbeddingInput(BaseModel):
    input: List[str]
    model: str = "bge-m3"
    encoding_format: str = "float"


class EmbeddingData(BaseModel):
    embedding: List[float]
    index: int


class EmbeddingUsage(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    data: List[EmbeddingData]
    model: str
    usage: EmbeddingUsage


@app.on_event("startup")
def load_model():
    global model
    model = SentenceTransformer(MODEL_PATH, device=DEVICE, trust_remote_code=True)
    model.max_seq_length = 8192


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def embed(req: EmbeddingInput):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    texts = [str(t or "").strip() for t in req.input]
    if not texts:
        raise HTTPException(status_code=400, detail="Empty input")
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    total_tokens = sum(len(t.split()) for t in texts)
    return EmbeddingResponse(
        data=[EmbeddingData(embedding=e.tolist(), index=i) for i, e in enumerate(embeddings)],
        model=req.model,
        usage=EmbeddingUsage(prompt_tokens=total_tokens, total_tokens=total_tokens),
    )


@app.get("/health")
def health():
    return {"status": "ok", "model": "bge-m3", "loaded": model is not None}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

"""bge-reranker-v2-m3 Reranker 服务。"""
import os
from typing import List, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import CrossEncoder

MODEL_PATH = os.environ.get("BGE_RERANKER_MODEL_PATH", r"D:\AI\AImodles\bge-reranker-v2-m3")
PORT = int(os.environ.get("BGE_RERANKER_PORT", "7998"))

# 自动检测 CUDA 可用性
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[INFO] Using device: {DEVICE}")

app = FastAPI(title="bge-reranker-v2-m3 Reranker Service")
model: Optional[CrossEncoder] = None


class RerankRequest(BaseModel):
    model: str = "bge-reranker-v2-m3"
    query: str
    documents: List[str]
    top_n: int = Field(default=20, ge=1)


class RerankResult(BaseModel):
    index: int
    relevance_score: float


class RerankResponse(BaseModel):
    model: str
    results: List[RerankResult]


@app.on_event("startup")
def load_model():
    global model
    model = CrossEncoder(MODEL_PATH, device=DEVICE, trust_remote_code=True, max_length=512)


@app.post("/v1/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    if not req.documents:
        raise HTTPException(status_code=400, detail="Empty documents")
    pairs = [[req.query, doc] for doc in req.documents]
    scores = model.predict(pairs, show_progress_bar=False)
    if not hasattr(scores, "__len__"):
        scores = [float(scores)]
    else:
        scores = [float(s) for s in scores]
    results = [
        RerankResult(index=i, relevance_score=s)
        for i, s in enumerate(scores)
    ]
    results.sort(key=lambda x: x.relevance_score, reverse=True)
    return RerankResponse(
        model=req.model,
        results=results[: req.top_n],
    )


@app.get("/health")
def health():
    return {"status": "ok", "model": "bge-reranker-v2-m3", "loaded": model is not None}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

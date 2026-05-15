import os
import re
from typing import Any, Dict, Optional
from .BaseTool import BaseTool, register_tool
from .config import KNOWLEDGE_DIR
from ai_inference.llm_client import llm_client


def _normalize_doc_title(raw: str) -> str:
    """规范化文档标题用于匹配，去除路径前缀、扩展名、年份后缀、统一空格/下划线。"""
    t = raw
    if t.startswith("markdown/"):
        t = t[len("markdown/"):]
    if t.endswith(".md"):
        t = t[:-3]
    if t.endswith(".pdf"):
        t = t[:-4]
    t = t.replace("_", " ").replace("—", "-").replace("–", "-")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_matches(query_title: str, node_title: str) -> bool:
    """宽松匹配文档标题，忽略年份/版本号后缀差异。"""
    q = query_title.lower()
    nt = node_title.lower()
    if q in nt or nt in q:
        return True
    q_no_year = re.sub(r"[-_]\d{4}\s*$", "", q).strip()
    nt_no_year = re.sub(r"[-_]\d{4}\s*$", "", nt).strip()
    if q_no_year and (q_no_year in nt_no_year or nt_no_year in q_no_year):
        return True
    q_prefix = q[:15] if len(q) > 15 else q
    if q_prefix and nt.startswith(q_prefix):
        return True
    # 提取规范编号模式如 JTS 165 进行匹配
    q_code = re.search(r"(jts|jtj|gb|jgj)\s*\d+", q)
    nt_code = re.search(r"(jts|jtj|gb|jgj)\s*\d+", nt)
    if q_code and nt_code and q_code.group(0) == nt_code.group(0):
        return True
    return False


def _resolve_knowledge_file(file_name: str) -> Optional[str]:
    """解析知识库文件路径，仅基于数据库中的文档存储查找。"""
    normalized = _normalize_doc_title(file_name)
    if not normalized:
        return None
    try:
        from docs_core.ingest.store.assets_file_store import file_storage
        from docs_core.knowledge_service import knowledge_service as ks
        nodes = ks.list_nodes("default")
        for node in nodes:
            if node.type != "document":
                continue
            node_norm = _normalize_doc_title(node.title)
            if _title_matches(normalized, node_norm):
                content_path = file_storage.get_parsed_markdown_path("default", node.id)
                if content_path.exists():
                    return str(content_path)
                edited_path = file_storage.get_edited_markdown_path("default", node.id)
                if edited_path.exists():
                    return str(edited_path)
    except Exception:
        pass
    return None


@register_tool
class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description_en = "Document/Report retrieval tool: search for relevant paragraphs in unstructured documents (e.g., regulations, design reports, research literature). Inputs: query (str), file_name (str, optional)"
    description_zh = "文档/报告检索工具：根据查询关键词，在非结构化文档（如规范条文、设计报告、研究文献）中查找相关段落。输入参数：query (str), file_name (str, optional)"
    
    knowledge_dir: str = KNOWLEDGE_DIR

    def __init__(self, knowledge_dir: str = None, **data):
        super().__init__(**data)
        if knowledge_dir:
            self.knowledge_dir = knowledge_dir

    def run(self, query: str, file_name: str = "《海港水文规范》.md", config_name: str = None, mode: str = "instruct", **kwargs) -> Dict[str, Any]:
        """优先使用 BM25 快速检索段落，可选再用 LLM 精炼。"""
        print(f"  [知识检索] 正在检索文档: {query}，来源: {file_name}")
        knowledge_file = _resolve_knowledge_file(file_name)
        if not knowledge_file:
            return {"error": f"未找到知识库文件: {file_name}"}
        with open(knowledge_file, 'r', encoding='utf-8') as f:
            full_content = f.read()

        def tokenize(text: str):
            """分词，兼容中英文与符号。"""
            import re
            tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+", text.lower())
            return tokens

        def bm25_rank(query_text: str, paragraphs: list, k1=1.5, b=0.75):
            """对段落进行 BM25 排序。"""
            import math
            q_tokens = tokenize(query_text)
            docs_tokens = [tokenize(p) for p in paragraphs]
            N = len(docs_tokens)
            avgdl = sum(len(d) for d in docs_tokens) / (N or 1)
            df = {}
            for d in docs_tokens:
                uniq = set(d)
                for t in uniq:
                    df[t] = df.get(t, 0) + 1
            idf = {t: math.log((N - df_t + 0.5) / (df_t + 0.5) + 1) for t, df_t in df.items()}
            scores = []
            for idx, d in enumerate(docs_tokens):
                score = 0.0
                tf = {}
                for t in d:
                    tf[t] = tf.get(t, 0) + 1
                dl = len(d)
                for qt in q_tokens:
                    if qt not in tf:
                        continue
                    idf_val = idf.get(qt, 0.0)
                    denom = tf[qt] + k1 * (1 - b + b * (dl / (avgdl or 1)))
                    score += idf_val * (tf[qt] * (k1 + 1)) / (denom or 1)
                scores.append((score, idx))
            scores.sort(key=lambda x: x[0], reverse=True)
            return scores

        paras = [p.strip() for p in full_content.split("\n\n") if p.strip()]
        if len(paras) < 5:
            paras = [p.strip() for p in full_content.split("\n") if p.strip()]
        ranked = bm25_rank(query, paras)
        top_k = [paras[i] for _, i in ranked[:5]]
        joined = "\n\n".join(top_k)

        use_llm = kwargs.get("use_llm", False)
        if use_llm:
            prompt = [
                {"role": "system", "content": "请从候选段落中提取最相关的回答，保留公式符号与关键变量。无法确定则返回“未找到”。"},
                {"role": "user", "content": f"查询: {query}\n\n候选段落:\n{joined}\n\n提取结果:"}
            ]
            try:
                extract = llm_client.chat(prompt, mode=mode, config_name=config_name)
                return {"result": extract, "source": file_name, "_method": "bm25+llm"}
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"result": joined, "source": file_name, "_method": "bm25", "_count": len(top_k)}


@register_tool
class ContentSummarizer(BaseTool):
    name = "summarizer"
    description_en = "Summarizes text content (Placeholder). Inputs: text (str), max_words (int)"
    description_zh = "文本内容摘要工具（占位符）。输入参数：text (str), max_words (int)"
    
    def run(self, text: str, max_words: int = 50, config_name: str = None, mode: str = "instruct", **kwargs) -> Any:
        """使用模型对文本进行摘要。"""
        prompt = [
            {"role": "system", "content": f"请将以下内容摘要为不超过 {max_words} 个字。"},
            {"role": "user", "content": text}
        ]
        try:
            return llm_client.chat(prompt, mode=mode, config_name=config_name)
        except Exception:
            return f"内容摘要: {text[:100]}..."

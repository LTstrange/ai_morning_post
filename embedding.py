"""文章语义嵌入模块：懒加载模型，计算/序列化/反序列化向量，语义检索。"""

from pathlib import Path

import numpy as np

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODELS_DIR = Path(__file__).parent / "models"

_model = None


def _get_model():
    """懒加载 SentenceTransformer 模型（单例），模型缓存在项目 models/ 目录下。优先离线加载。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        MODELS_DIR.mkdir(exist_ok=True)
        try:
            _model = SentenceTransformer(
                MODEL_NAME, cache_folder=str(MODELS_DIR), local_files_only=True
            )
        except OSError:
            _model = SentenceTransformer(MODEL_NAME, cache_folder=str(MODELS_DIR))
    return _model


def compute_embedding(text):
    """计算文本的嵌入向量，返回 bytes（float32 BLOB）。"""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32).tobytes()


def deserialize_embedding(blob):
    """将 BLOB 反序列化为 numpy 向量。"""
    return np.frombuffer(blob, dtype=np.float32)


def semantic_search(query_text, articles, top_k=10):
    """根据查询文本对文章列表做语义排序，返回 top_k 篇最相关的文章。

    articles: 必须包含 'embedding' 字段（bytes）的 dict 列表。
    """
    query_vec = deserialize_embedding(compute_embedding(query_text))

    scored = []
    for article in articles:
        if not article["embedding"]:
            continue
        article_vec = deserialize_embedding(article["embedding"])
        score = float(np.dot(query_vec, article_vec))
        scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [article for _, article in scored[:top_k]]

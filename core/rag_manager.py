"""RagManager —— RAG 检索（增强版）

- 优先使用 sentence-transformers 向量嵌入（all-mpnet-base-v2）；
- 若 sentence_transformers / 嵌入模型不可用，自动降级为 TF-IDF 关键词检索
  （轻量、零模型下载，角色知识库数据量小时检索质量足够）；
- 支持 FAISS 索引落盘复用（data/rag_index/），加速冷启动。
"""
import math
import pickle
import re
from pathlib import Path

from core.character_profile import CharacterProfile

try:
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    _LANGCHAIN_OK = True
except ImportError:
    _LANGCHAIN_OK = False
    FAISS = None
    HuggingFaceEmbeddings = None
    RecursiveCharacterTextSplitter = None

try:
    import sentence_transformers  # noqa: F401  触发依赖检测
    _ST_OK = True
except ImportError:
    _ST_OK = False


class _TfidfIndex:
    """轻量 TF-IDF 检索索引（无外部依赖）"""

    def __init__(self, documents: list[str]):
        self.docs = documents
        self._df: dict[str, int] = {}
        self._tf: list[dict[str, int]] = []
        self._build()

    def _tokenize(self, text: str) -> list[str]:
        # 中文按字符二元组 + 英文按词，简单有效
        tokens = []
        for w in re.findall(r'[a-zA-Z0-9_]+', text.lower()):
            tokens.append(w)
        cjk = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i] + cjk[i + 1])
        tokens.extend(cjk)
        return tokens

    def _build(self):
        for doc in self.docs:
            tf: dict[str, int] = {}
            for tok in self._tokenize(doc):
                tf[tok] = tf.get(tok, 0) + 1
            self._tf.append(tf)
            for tok in set(tf):
                self._df[tok] = self._df.get(tok, 0) + 1

    def search(self, query: str, k: int = 3) -> list[str]:
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return self.docs[:k]
        n = max(1, len(self.docs))
        q_tf: dict[str, int] = {}
        for tok in q_tokens:
            q_tf[tok] = q_tf.get(tok, 0) + 1
        scored = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            for tok, qc in q_tf.items():
                if tok in tf:
                    idf = math.log(n / (1 + self._df.get(tok, 0))) + 1.0
                    score += (qc / len(q_tokens)) * idf
            scored.append((score, i))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [self.docs[i] for s, i in scored[:k] if s > 0] or self.docs[:k]


class RagManager:
    """RAG 检索 —— 向量(FAISS)优先，TF-IDF 降级兜底，索引可持久化"""

    def __init__(self, use_tfidf_fallback: bool = True):
        self.embeddings = None
        self.text_splitter = None
        self._vector_ok = False

        if _LANGCHAIN_OK and _ST_OK:
            try:
                self.embeddings = HuggingFaceEmbeddings(
                    model_name="sentence-transformers/all-mpnet-base-v2"
                )
                self.text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=200, chunk_overlap=20
                )
                self._vector_ok = True
            except Exception:
                self.embeddings = None

        self.use_tfidf_fallback = use_tfidf_fallback and not self._vector_ok
        self.dbs = {}            # character_name → FAISS 或 _TfidfIndex
        self._index_dir = Path(__file__).parent.parent / "data" / "rag_index"

    # -- 构建 ---------------------------------------------------------
    def build_all(self):
        """为 CHARACTER_DB 中全部角色构建索引"""
        from core.config import CHARACTER_DB
        for char_name in CHARACTER_DB:
            self.build(CharacterProfile(char_name))
        return self.dbs

    def build(self, profile: CharacterProfile):
        """为单个角色构建索引（尝试落盘复用）"""
        name = profile.name
        texts = profile.all_texts()
        if not texts:
            self.dbs[name] = []
            return self.dbs[name]

        # 向量模式：尝试读缓存
        if self._vector_ok:
            cached = self._load_cache(name, texts)
            if cached is not None:
                self.dbs[name] = cached
                return cached
            documents = self.text_splitter.create_documents(texts)
            db = FAISS.from_documents(documents, self.embeddings)
            self.dbs[name] = db
            self._save_cache(name, db, texts)
            return db

        # TF-IDF 降级
        self.dbs[name] = _TfidfIndex(texts)
        return self.dbs[name]

    # -- 检索 ---------------------------------------------------------
    def retrieve(self, character_name, query, k=3):
        if character_name not in self.dbs:
            return []
        db = self.dbs[character_name]
        if isinstance(db, _TfidfIndex):
            return db.search(query, k=k)
        if isinstance(db, list):  # 空库
            return []
        try:
            results = db.similarity_search(query, k=k)
            return [doc.page_content for doc in results]
        except Exception:
            return []

    def retrieve_as_context(self, character_name, query, k=3):
        fragments = self.retrieve(character_name, query, k)
        return "\n".join(f"- {f}" for f in fragments)

    @property
    def mode(self) -> str:
        """当前检索模式：vector / tfidf / none"""
        if self._vector_ok:
            return "vector"
        if self.use_tfidf_fallback:
            return "tfidf"
        return "none"

    # -- 索引持久化（向量模式） -----------------------------------------
    def _cache_path(self, name: str) -> Path:
        return self._index_dir / f"{name}.faiss.pkl"

    def _load_cache(self, name: str, texts: list[str]):
        path = self._cache_path(name)
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            if data.get("texts") == texts and data.get("db") is not None:
                return data["db"]
        except Exception:
            pass
        return None

    def _save_cache(self, name: str, db, texts: list[str]):
        try:
            self._index_dir.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path(name), "wb") as f:
                pickle.dump({"texts": texts, "db": db}, f)
        except Exception:
            pass  # 缓存失败不影响运行

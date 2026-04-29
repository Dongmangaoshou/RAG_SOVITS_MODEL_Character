from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.character_profile import CharacterProfile


class RagManager:
    """RAG 检索 —— 为每个角色构建 FAISS 向量库，按查询检索相关片段"""

    def __init__(self):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-mpnet-base-v2"
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=200, chunk_overlap=20
        )
        self.dbs = {}  # character_name → FAISS

    def build_all(self):
        """为 CHARACTER_DB 中全部角色构建向量库"""
        from core.config import CHARACTER_DB
        for char_name in CHARACTER_DB:
            self.build(CharacterProfile(char_name))
        return self.dbs

    def build(self, profile: CharacterProfile):
        """为单个角色构建向量库"""
        documents = self.text_splitter.create_documents(profile.all_texts())
        self.dbs[profile.name] = FAISS.from_documents(documents, self.embeddings)
        return self.dbs[profile.name]

    def retrieve(self, character_name, query, k=3):
        """检索与查询最相关的 k 个片段"""
        if character_name not in self.dbs:
            return []
        results = self.dbs[character_name].similarity_search(query, k=k)
        return [doc.page_content for doc in results]

    def retrieve_as_context(self, character_name, query, k=3):
        """检索并拼接为 prompt 可用的上下文字符串"""
        fragments = self.retrieve(character_name, query, k)
        return "\n".join(f"- {f}" for f in fragments)

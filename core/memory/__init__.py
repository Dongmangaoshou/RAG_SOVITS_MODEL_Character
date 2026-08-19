"""MemoryV2 门面 —— 三层记忆统一入口，接入 AdvancedCharacterSystem"""
import threading
import time

from core.memory import db
from core.memory.working import RollingSummarizer
from core.memory.episodic import EpisodicMemory, EventExtractor
from core.memory.semantic import SemanticMemory
from core.memory.relationship import RelationshipV2
from core.memory.policy import MemoryInjectionPolicy

__all__ = [
    "MemoryV2", "RollingSummarizer", "EpisodicMemory", "EventExtractor",
    "SemanticMemory", "RelationshipV2", "MemoryInjectionPolicy", "init_db",
]

_db_initialized = False


def init_db():
    """幂等初始化数据库 schema"""
    global _db_initialized
    if not _db_initialized:
        db.init_db()
        _db_initialized = True


class MemoryV2:
    """三层记忆门面：
    - 短期：滚动摘要（Working）
    - 情景：事件提取 + 遗忘曲线检索（Episodic）
    - 语义：用户画像 + 三维关系（Semantic + Relationship）
    对外提供 save_turn / build_context / 管理接口。"""

    def __init__(self, character: str, llm=None, token_budget: int = 1000,
                 summarize_interval: int = 5, use_extractor: bool = True):
        init_db()
        self.character = character
        self.llm = llm
        self.window: list[tuple[str, str]] = []      # [(role, content)] 当前窗口
        self.summarizer = RollingSummarizer(llm=llm, interval=summarize_interval)
        self.episodic = EpisodicMemory(character)
        self.semantic = SemanticMemory(character)
        self.relationship = RelationshipV2(character)
        self.policy = MemoryInjectionPolicy(character, token_budget)
        self._use_extractor = use_extractor
        self._extractor = EventExtractor(llm=llm) if use_extractor else None
        self._turn_count = 0

    # -- 每轮对话写入 ------------------------------------------------
    def save_turn(self, user_input: str, response: str, emotion_tag: str = "",
                  is_share_emotion: bool = False, do_extract: bool = True):
        """保存一轮对话：更新窗口/摘要/事件/画像/关系"""
        self.window.append(("user", user_input))
        self.window.append(("assistant", response))
        self._turn_count += 1

        # 1) 滚动摘要：每 interval 轮压缩一次
        if self._turn_count % self.summarizer.interval == 0:
            summary = self.summarizer.summarize(
                self.character, self.summarizer.load_summary(self.character), self.window
            )
            self.summarizer.save_summary(self.character, summary, self._turn_count)
            # 压缩后保留最近 3 轮原始消息，其余交给摘要
            self.window = self.window[-6:]

        # 2) 情景记忆：事件提取（后台线程，不阻塞主链路；失败静默）
        if do_extract and self._extractor is not None:
            def _extract_bg():
                try:
                    events = self._extractor.extract(user_input, response)
                    if events:
                        self.episodic.add_many(events, emotion_tag)
                        self.semantic.aggregate_from_events()
                except Exception:
                    pass  # 事件提取失败不影响主链路
            t = threading.Thread(target=_extract_bg, daemon=True)
            t.start()

        # 3) 关系更新
        self.relationship.update(user_input, is_share_emotion=is_share_emotion)

    # -- Prompt 上下文构建 -------------------------------------------
    def build_context(self, query: str) -> str:
        """构建注入 Prompt 的记忆区块（含预算控制）"""
        summary = self.summarizer.load_summary(self.character)
        window_text = "\n".join(f"{r}: {c}" for r, c in self.window[-6:])
        return self.policy.build_context(query, window_text=window_text, summary=summary)

    def build_context_with_emotion(self, query: str, emotion_hint: str = "") -> str:
        """带情感提示的上下文（Phase 2 联调用）"""
        ctx = self.build_context(query)
        if emotion_hint:
            ctx = f"{ctx}\n{emotion_hint}" if ctx else emotion_hint
        return ctx

    # -- 管理接口 ------------------------------------------------------
    def list_events(self, limit: int = 50) -> list[dict]:
        return self.episodic.list_events(limit)

    def delete_event(self, event_id: int):
        self.episodic.delete_event(event_id)

    def get_profile(self) -> dict:
        return self.semantic.get_profile()

    def get_relationship(self) -> dict:
        return self.relationship.to_dict()

    def clear_all(self):
        """清除全部记忆（隐私需求）"""
        self.episodic.clear()
        db.execute("DELETE FROM profile WHERE character=?", (self.character,))
        db.execute("DELETE FROM relationship WHERE character=?", (self.character,))
        db.execute("DELETE FROM summaries WHERE character=?", (self.character,))
        self.window = []
        self._turn_count = 0

    # -- 兼容旧接口 ------------------------------------------------------
    @property
    def relationship_level(self) -> int:
        return self.relationship.level

"""记忆注入策略 —— 区块优先级 + token 预算控制"""
from core.memory.episodic import EpisodicMemory
from core.memory.semantic import SemanticMemory
from core.memory.relationship import RelationshipV2


class MemoryInjectionPolicy:
    """按优先级与预算组装 Prompt 记忆区块：
    1 短期窗口(最近3-4轮) → 2 滚动摘要 → 3 情景检索(Top-3) → 4 用户画像 → 5 关系状态"""

    def __init__(self, character: str, token_budget: int = 1000):
        self.character = character
        self.token_budget = token_budget
        self.episodic = EpisodicMemory(character)
        self.semantic = SemanticMemory(character)
        self.relationship = RelationshipV2(character)

    # 粗略中文字符→token 估算：1 汉字 ≈ 1.5 token，1 英文 ≈ 0.3 token
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
        return int(cjk * 1.5 + (len(text) - cjk) * 0.35)

    def build_context(self, query: str, window_text: str = "", summary: str = "",
                      k: int = 3, budget: int | None = None) -> str:
        budget = budget or self.token_budget
        blocks = []

        # 关系状态实时刷新（避免缓存旧值）
        try:
            self.relationship.load()
        except Exception:
            pass

        def _append(title: str, body: str, est: int) -> bool:
            if not body.strip():
                return True
            total = sum(b[2] for b in blocks)
            if total + est > budget:
                return False
            blocks.append((title, body, est))
            return True

        _append("【近期对话】", window_text, self._estimate_tokens(window_text))
        _append("【会话摘要】", summary, self._estimate_tokens(summary))

        events = self.episodic.retrieve(query, k=k)
        if events:
            ev_text = "\n".join(f"- {e['text']}" for e in events)
            _append("【你曾告诉我的事】", ev_text, self._estimate_tokens(ev_text))

        profile_text = self.semantic.to_prompt_block()
        if profile_text:
            _append("【我对你的了解】", profile_text, self._estimate_tokens(profile_text))

        rel_text = self.relationship.to_prompt_text()
        _append("【关系】", rel_text, self._estimate_tokens(rel_text))

        return "\n".join(body for _, body, _ in blocks)

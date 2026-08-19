"""短期工作记忆 —— 对话窗口 + 滚动摘要（增量压缩）"""
import time
import uuid

from core.memory import db


class RollingSummarizer:
    """滚动摘要器：每累计 interval 轮调用一次 LLM 增量压缩，
    生成 ≤ max_chars 字的会话摘要，替代被压缩掉的原始消息。"""

    def __init__(self, llm=None, interval: int = 5, max_chars: int = 200):
        self.llm = llm                     # ChatOpenAI 实例（可为 None，则退化为截断）
        self.interval = interval
        self.max_chars = max_chars
        self.session_id = uuid.uuid4().hex[:8]

    # -- 摘要主逻辑 -------------------------------------------------
    def summarize(self, character: str, old_summary: str, new_messages: list[tuple[str, str]]) -> str:
        """增量压缩：old_summary(旧摘要) + new_messages(新消息) → 新摘要。
        new_messages: [(role, content), ...]"""
        if not new_messages:
            return old_summary

        if self.llm is not None:
            try:
                return self._llm_summarize(character, old_summary, new_messages)
            except Exception:
                pass  # 失败退化为截断法
        return self._truncate_summary(character, old_summary, new_messages)

    def _llm_summarize(self, character, old_summary, new_messages):
        transcript = "\n".join(f"{role}: {content}" for role, content in new_messages)
        prompt = (
            f"你是{character}的对话记忆管家。请把【旧摘要】与【新增对话】合并为一份新的简明摘要。\n"
            f"要求：只保留对{character}了解用户有帮助的关键信息（事实、偏好、情绪、承诺），"
            f"忽略寒暄；不超过{self.max_chars}字；直接输出摘要文本，不要任何前缀。\n\n"
            f"【旧摘要】\n{old_summary or '（无）'}\n\n"
            f"【新增对话】\n{transcript}\n\n"
            f"【新摘要】\n"
        )
        resp = self.llm.invoke(prompt)
        text = getattr(resp, "content", None) or str(resp)
        text = text.strip().strip("【】\"").strip()
        if not text:
            return self._truncate_summary(character, old_summary, new_messages)
        return text[: self.max_chars * 2]  # 保险截断

    def _truncate_summary(self, character, old_summary, new_messages):
        """无 LLM 时的退化策略：保留旧摘要 + 新消息最后若干条"""
        tail = "\n".join(f"{r}: {c}" for r, c in new_messages[-3:])
        merged = f"{old_summary}\n{tail}" if old_summary else tail
        return merged[: self.max_chars * 2]

    # -- 会话摘要存取 ------------------------------------------------
    def load_summary(self, character: str) -> str:
        row = db.query_one(
            "SELECT summary_text FROM summaries WHERE character=? AND session_id=? ORDER BY id DESC LIMIT 1",
            (character, self.session_id),
        )
        return row["summary_text"] if row else ""

    def save_summary(self, character: str, summary: str, last_msg_idx: int = 0):
        db.execute(
            "INSERT INTO summaries(character, session_id, summary_text, last_msg_idx, updated_at) "
            "VALUES(?,?,?,?,?)",
            (character, self.session_id, summary, last_msg_idx,
             time.strftime("%Y-%m-%d %H:%M:%S")),
        )

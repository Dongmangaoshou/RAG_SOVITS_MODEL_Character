"""情景记忆 —— 事件提取（LLM 结构化） + SQLite 存储 + 遗忘曲线检索"""
import json
import re
import time

from core.memory import db

# 事件类型 → 默认重要性 / 遗忘衰减系数 λ
EVENT_META = {
    "fact":       {"importance": 0.9, "lambda": 0.02},   # 用户事实（姓名/职业/生日）
    "preference": {"importance": 0.8, "lambda": 0.05},   # 偏好
    "emotion":    {"importance": 0.95, "lambda": 0.02},  # 情绪事件
    "promise":    {"importance": 0.85, "lambda": 0.03},  # 承诺/约定
    "chat":       {"importance": 0.3, "lambda": 0.10},   # 日常闲聊
}

_TYPE_CN = {
    "fact": "用户事实", "preference": "偏好", "emotion": "情绪事件",
    "promise": "承诺约定", "chat": "日常闲聊",
}


class EventExtractor:
    """事件提取器：LLM 从对话中抽取 5 类事件，JSON 输出；失败静默降级。
    与语义情感识别合并调用（Phase 2），此处仅负责记忆事件。"""

    def __init__(self, llm=None):
        self.llm = llm

    def extract(self, user_input: str, response: str) -> list[dict]:
        """返回事件列表 [{event_type, text, importance}]；LLM 不可用时返回空"""
        if self.llm is None:
            return []
        try:
            prompt = (
                "从下面的对话中抽取值得长期记忆的信息，按类型归类。\n"
                "类型: fact(用户事实) / preference(偏好) / emotion(情绪事件) / "
                "promise(承诺约定) / chat(日常闲聊)\n"
                "只抽取用户侧信息；闲聊若不重要返回空列表；直接输出 JSON 数组，"
                "每项 {\"event_type\":\"...\",\"text\":\"...\"}，text 用第一人称原样概括，不超过40字。\n\n"
                f"用户: {user_input}\n角色: {response}\n\nJSON:"
            )
            resp = self.llm.invoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
            # 提取第一个 [...] 块（容忍模型额外输出）
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if not m:
                return []
            items = json.loads(m.group(0))
            result = []
            for it in items:
                et = it.get("event_type", "chat")
                if et not in EVENT_META:
                    et = "chat"
                result.append({
                    "event_type": et,
                    "text": str(it.get("text", ""))[:80],
                    "importance": EVENT_META[et]["importance"],
                })
            return result
        except Exception:
            return []


class EpisodicMemory:
    """情景记忆：事件入库 + 遗忘曲线评分检索"""

    def __init__(self, character: str):
        self.character = character

    # -- 写入 --------------------------------------------------------
    def add_event(self, event_type: str, text: str, importance: float | None = None,
                  emotion_tag: str = "") -> int:
        meta = EVENT_META.get(event_type, EVENT_META["chat"])
        imp = importance if importance is not None else meta["importance"]
        return db.execute(
            "INSERT INTO events(character, event_type, text, importance, emotion_tag) VALUES(?,?,?,?,?)",
            (self.character, event_type, text, imp, emotion_tag),
        )

    def add_many(self, events: list[dict], emotion_tag: str = ""):
        for ev in events:
            self.add_event(ev["event_type"], ev["text"], ev.get("importance"), emotion_tag)

    # -- 检索 --------------------------------------------------------
    def retrieve(self, query: str, k: int = 3, min_score: float = 0.25,
                 days_limit: int = 30) -> list[dict]:
        """按遗忘曲线打分：score = sim × importance × exp(-λ×Δdays)
        sim 用 SQLite FTS5 全文匹配近似（无 FTS5 时退化为关键词计数），
        保证零额外依赖、本地秒级检索。"""
        rows = db.query_all(
            "SELECT * FROM events WHERE character=? ORDER BY id DESC LIMIT 200",
            (self.character,),
        )
        keywords = [w for w in re.split(r"[\s，。！？,.!?、\n]+", query) if len(w) >= 2]
        scored = []
        now = time.time()
        for r in rows:
            if days_limit:
                try:
                    created = time.mktime(time.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S"))
                    delta_days = max(0.0, (now - created) / 86400.0)
                except Exception:
                    delta_days = 0.0
                if delta_days > days_limit and r["event_type"] not in ("fact", "emotion"):
                    continue  # 超期且非重要类型，跳过
            sim = self._text_sim(query, r["text"], keywords)
            if sim <= 0:
                continue
            score = sim * r["importance"] * _decay(r["event_type"], delta_days)
            if score < min_score:
                continue
            scored.append({**r, "score": round(score, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    @staticmethod
    def _text_sim(query: str, text: str, keywords: list[str]) -> float:
        """轻量文本相似度：关键词命中率 + 子串重叠"""
        if not keywords:
            return 0.0
        q_lower, t_lower = query.lower(), text.lower()
        hit = sum(1 for w in keywords if w.lower() in t_lower)
        overlap = 0.0
        if len(q_lower) >= 3:
            for i in range(0, len(q_lower) - 2, 1):
                if q_lower[i:i + 3] in t_lower:
                    overlap += 1
        char_sim = min(1.0, overlap / max(1, len(q_lower) - 2))
        return min(1.0, (hit / len(keywords)) * 0.7 + char_sim * 0.3)

    # -- 管理 --------------------------------------------------------
    def list_events(self, limit: int = 50) -> list[dict]:
        return db.query_all(
            "SELECT * FROM events WHERE character=? ORDER BY id DESC LIMIT ?",
            (self.character, limit),
        )

    def delete_event(self, event_id: int):
        db.execute("DELETE FROM events WHERE id=? AND character=?", (event_id, self.character))

    def clear(self):
        db.execute("DELETE FROM events WHERE character=?", (self.character,))


def _decay(event_type: str, delta_days: float) -> float:
    """遗忘衰减：chat 衰减最快，重要事件几乎不衰减"""
    lam = EVENT_META.get(event_type, EVENT_META["chat"])["lambda"]
    return 2.71828 ** (-lam * delta_days)

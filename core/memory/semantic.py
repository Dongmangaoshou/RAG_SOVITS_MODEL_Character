"""语义记忆 —— 用户画像聚合（偏好/回避话题/性格观察/关心事项）+ 长期事实库"""
import json

from core.memory import db


class SemanticMemory:
    """从情景事件聚合用户画像；画像为 4 槽位 JSON，随事件更新"""

    SLOTS = ["preferences", "avoid_topics", "personality_notes", "concerns"]
    SLOT_CN = {
        "preferences": "偏好", "avoid_topics": "回避话题",
        "personality_notes": "性格观察", "concerns": "关心事项",
    }

    def __init__(self, character: str):
        self.character = character

    # -- 画像读写 ----------------------------------------------------
    def get_profile(self) -> dict:
        row = db.query_one("SELECT * FROM profile WHERE character=?", (self.character,))
        if not row:
            return {s: [] for s in self.SLOTS}
        return {
            s: json.loads(row[s] or "[]")
            for s in self.SLOTS
        }

    def update_slot(self, slot: str, items: list[str], append: bool = True, limit: int = 5):
        if slot not in self.SLOTS:
            return
        profile = self.get_profile()
        current = profile.get(slot, [])
        for it in items:
            it = it.strip()
            if not it:
                continue
            if it not in current:
                current.append(it)
        profile[slot] = current[:limit]
        db.execute(
            "INSERT INTO profile(character, preferences, avoid_topics, personality_notes, concerns, updated_at) "
            "VALUES(?,?,?,?,?,datetime('now','localtime')) "
            "ON CONFLICT(character) DO UPDATE SET preferences=excluded.preferences, "
            "avoid_topics=excluded.avoid_topics, personality_notes=excluded.personality_notes, "
            "concerns=excluded.concerns, updated_at=datetime('now','localtime')",
            (
                self.character,
                json.dumps(profile["preferences"], ensure_ascii=False),
                json.dumps(profile["avoid_topics"], ensure_ascii=False),
                json.dumps(profile["personality_notes"], ensure_ascii=False),
                json.dumps(profile["concerns"], ensure_ascii=False),
            ),
        )

    # -- 画像聚合（从事件批量刷新，异步调用）---------------------------
    def aggregate_from_events(self):
        rows = db.query_all(
            "SELECT event_type, text FROM events WHERE character=? ORDER BY id DESC LIMIT 60",
            (self.character,),
        )
        prefs, avoids, concerns = [], [], []
        for r in rows:
            if r["event_type"] == "preference":
                prefs.append(r["text"])
            elif r["event_type"] == "emotion" and ("难受" in r["text"] or "伤心" in r["text"] or "哭" in r["text"] or "压力" in r["text"]):
                concerns.append(r["text"])
            elif r["event_type"] == "fact":
                concerns.append(r["text"])
        if prefs:
            self.update_slot("preferences", prefs)
        if avoids:
            self.update_slot("avoid_topics", avoids)
        if concerns:
            self.update_slot("concerns", concerns)

    def to_prompt_block(self, max_chars_per_slot: int = 40) -> str:
        """生成 Prompt 可用的画像文本块"""
        profile = self.get_profile()
        lines = []
        for slot in self.SLOTS:
            items = profile.get(slot, [])
            if not items:
                continue
            short = []
            budget = 0
            for it in items:
                if budget + len(it) > max_chars_per_slot * 2:
                    break
                short.append(it)
                budget += len(it) + 1
            lines.append(f"{self.SLOT_CN[slot]}: {'、'.join(short)}")
        return "\n".join(lines) if lines else ""

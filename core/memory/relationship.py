"""三维关系系统 —— 好感/信任/熟悉（0-100），替代单一好感度；
保留旧 RelationshipTracker 兼容层"""
import re

from core.memory import db

_INTIMACY_LEVELS = [
    (0, "陌生人"), (20, "初识"), (40, "熟人"),
    (60, "朋友"), (80, "挚友"), (101, "灵魂伴侣"),
]

# 触发词（默认，可经 config 覆盖）
_POSITIVE = ["谢谢", "理解", "帮助", "开心", "喜欢", "太好了", "爱你", "感谢"]
_NEGATIVE = ["讨厌", "滚", "混蛋", "废物", "闭嘴", "烦死了", "恶心"]
_TRUST = ["秘密", "告诉你", "心里话", "压力", "难过", "害怕", "孤独", "脆弱", "只跟你说"]
_TRUST_NEG = ["骗", "撒谎", "敷衍", "不理"]


class RelationshipV2:
    """三维关系：affinity(好感) / trust(信任) / familiarity(熟悉)"""

    def __init__(self, character: str):
        self.character = character
        self.affinity = 0
        self.trust = 0
        self.familiarity = 0
        self.load()

    # -- 持久化 --------------------------------------------------------
    def load(self):
        row = db.query_one("SELECT * FROM relationship WHERE character=?", (self.character,))
        if row:
            self.affinity = int(row["affinity"])
            self.trust = int(row["trust"])
            self.familiarity = int(row["familiarity"])

    def save(self):
        db.execute(
            "INSERT INTO relationship(character, affinity, trust, familiarity, updated_at) "
            "VALUES(?,?,?,?,datetime('now','localtime')) "
            "ON CONFLICT(character) DO UPDATE SET affinity=excluded.affinity, "
            "trust=excluded.trust, familiarity=excluded.familiarity, updated_at=datetime('now','localtime')",
            (self.character, self.affinity, self.trust, self.familiarity),
        )

    # -- 更新规则 --------------------------------------------------------
    def update(self, user_input: str, is_share_emotion: bool = False) -> None:
        """每轮对话后更新；is_share_emotion 表示用户分享了情绪/私密内容"""
        if any(kw in user_input for kw in _POSITIVE):
            self.affinity = min(100, self.affinity + 3)
        if any(kw in user_input for kw in _NEGATIVE):
            self.affinity = max(0, self.affinity - 6)
        if is_share_emotion or any(kw in user_input for kw in _TRUST):
            self.trust = min(100, self.trust + 6)
        if any(kw in user_input for kw in _TRUST_NEG):
            self.trust = max(0, self.trust - 8)
        self.familiarity = min(100, self.familiarity + 1)
        self.save()

    # -- 派生 ----------------------------------------------------------
    @property
    def level(self) -> int:
        """兼容旧接口：返回 0-10 关系等级（由三均值映射）"""
        avg = (self.affinity + self.trust + self.familiarity) / 3.0
        return int(avg / 10.0)

    @property
    def intimacy_level(self) -> str:
        avg = (self.affinity + self.trust + self.familiarity) / 3.0
        for threshold, name in _INTIMACY_LEVELS:
            if avg < threshold:
                return name
        return "灵魂伴侣"

    def to_dict(self) -> dict:
        return {"affinity": self.affinity, "trust": self.trust,
                "familiarity": self.familiarity, "intimacy": self.intimacy_level}

    def to_prompt_text(self) -> str:
        return (f"当前关系: {self.intimacy_level}（好感{self.affinity}/信任{self.trust}/"
                f"熟悉{self.familiarity}）")


class RelationshipTracker:
    """兼容层：旧代码仍可 import 使用，内部委托 RelationshipV2"""

    def __init__(self, character: str = ""):
        self._v2 = RelationshipV2(character or "默认")

    @property
    def level(self) -> int:
        return self._v2.level

    @level.setter
    def level(self, value: int):
        self._v2.affinity = value * 10
        self._v2.save()

    def update(self, user_input: str) -> int:
        self._v2.update(user_input)
        return self.level

    def is_close(self) -> bool:
        return self.level > 5

    def to_dict(self) -> dict:
        return {"level": self.level}

    def from_dict(self, data: dict):
        self.level = data.get("level", 0)

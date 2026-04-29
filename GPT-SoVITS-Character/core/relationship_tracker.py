from core.config import CONFIG


class RelationshipTracker:
    """关系管理 —— 跟踪好感度并根据关键词自动增减"""

    def __init__(self):
        self.level = 0
        self._positive_keywords = CONFIG["relationship"]["positive_keywords"]
        self._close_threshold = CONFIG["relationship"]["close_threshold"]

    def update(self, user_input: str) -> int:
        """根据用户输入更新关系等级，返回当前值"""
        if any(kw in user_input for kw in self._positive_keywords):
            self.level = min(10, self.level + 1)
        return self.level

    def is_close(self) -> bool:
        """关系是否达到亲近阈值"""
        return self.level > self._close_threshold

    def to_dict(self) -> dict:
        return {"level": self.level}

    def from_dict(self, data: dict):
        self.level = data.get("level", 0)

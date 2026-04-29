from core.config import CONFIG


class EmotionEngine:
    """情感检测 —— 基于关键词匹配识别用户情绪"""

    def __init__(self, keywords=None):
        self.keywords = keywords or CONFIG["emotion_keywords"]

    def detect(self, text: str) -> str:
        for emotion, words in self.keywords.items():
            if any(w in text for w in words):
                return emotion
        return "neutral"

    def get_context_hint(self, emotion: str) -> str:
        """根据情绪返回应追加到 RAG 上下文的提示语"""
        hints = {
            "depressed": "特别注意: 用户情绪低落，需要温柔鼓励",
            "angry":    "特别注意: 用户比较生气，需要平静安慰",
            "anxious":  "特别注意: 用户感到焦虑，需要安抚和引导",
        }
        return hints.get(emotion, "")

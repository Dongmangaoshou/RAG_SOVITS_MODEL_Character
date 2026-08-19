# -*- coding: utf-8 -*-
"""EI v2 情感检测器 —— SemanticDetector

基于 LLM JSON 输出（temperature=0）或内置关键词词典识别用户情感，
输出 8 类情感之一：喜悦 / 平静 / 低落 / 悲伤 / 愤怒 / 焦虑 / 疲惫 / 兴奋。

设计约束：纯 Python 3.10、零第三方依赖（仅标准库 re / json），
不 import langchain；llm 采用鸭子类型接口，兼容 langchain 风格对象。
"""

import json
import re

from core.config import CONFIG

# ---------------------------------------------------------------------------
# 模块级常量：所有"魔法数字"集中于此，均可通过 CONFIG["emotion"] 后补覆盖
# ---------------------------------------------------------------------------

# 情感 8 分类（顺序同时作为关键词兜底打平时的优先级顺序）
EMOTIONS = ("喜悦", "平静", "低落", "悲伤", "愤怒", "焦虑", "疲惫", "兴奋")

# 内置关键词词典（覆盖 8 类，作为 LLM 不可用 / 解析失败时的兜底）
KEYWORD_DEFAULTS = {
    "喜悦": ["开心", "高兴", "快乐", "愉快", "幸福", "哈哈", "耶", "好耶", "太棒了",
             "太好了", "好开心", "真高兴", "nice", "好爽", "爽", "喜欢", "爱你", "我爱你"],
    "平静": ["嗯嗯", "好的", "知道了", "还行", "随便", "哦哦", "可以", "没事"],
    "低落": ["低落", "沮丧", "消沉", "提不起劲", "没意思", "无聊", "算了", "唉",
             "灰心", "失望", "丧", "烦死了", "好烦"],
    "悲伤": ["伤心", "难过", "悲伤", "绝望", "抑郁", "失落", "痛苦", "郁闷", "想哭",
             "心碎", "哭泣", "哭", "泪", "难受", "心累", "呜呜", "好难过"],
    "愤怒": ["生气", "愤怒", "烦躁", "不爽", "恼火", "气死", "火大", "可恶", "傻逼",
             "滚蛋", "去死", "气炸", "火冒三丈"],
    "焦虑": ["焦虑", "紧张", "担心", "害怕", "不安", "忧虑", "恐惧", "忐忑", "惶恐",
             "慌", "怎么办", "万一", "压力好大", "好慌", "怕死", "可怕"],
    "疲惫": ["疲惫", "好累", "累了", "困了", "好困", "没力气", "筋疲力尽", "乏",
             "倦", "撑不住", "累死", "身心俱疲"],
    "兴奋": ["兴奋", "激动", "超开心", "好激动", "哇", "天哪", "牛", "厉害", "太爽",
             "啊啊啊", "太厉害了", "超棒"],
}

# 各类情感的中文提示语 hint（注入 Prompt 时使用）
HINTS = {
    "喜悦": "用户情绪喜悦，语气轻快，与用户一同分享开心的事",
    "平静": "用户情绪平静，自然交流即可",
    "低落": "用户情绪低落，温柔鼓励，放轻语气，多陪伴少说教",
    "悲伤": "用户情绪悲伤，先表达关心与理解，再温柔安慰、耐心陪伴",
    "愤怒": "用户情绪愤怒，保持冷静克制，先安抚情绪再理性沟通",
    "焦虑": "用户情绪焦虑，语速放缓，给予安抚与确定性引导",
    "疲惫": "用户情绪疲惫，少说废话，放轻语气，多关心、建议休息",
    "兴奋": "用户情绪兴奋，可一同兴奋，语气上扬、配合互动",
}

# 关键词匹配的强度 / 置信度计算参数
DEFAULT_INTENSITY = 0.60        # 单次命中的基础强度
INTENSITY_PER_HIT = 0.15        # 每多命中一个关键词追加的强度
DEFAULT_CONFIDENCE = 0.50       # 基础置信度
CONFIDENCE_PER_HIT = 0.15       # 每多命中一个关键词追加的置信度

# 平静（默认情感）的兜底强度与置信度
CALM_INTENSITY = 0.30
CALM_CONFIDENCE = 0.50

# LLM 相关参数
LLM_TEMPERATURE = 0.0           # 要求 LLM 输出温度（尽力设置为 0）
FIELD_MIN = 0.0                 # intensity / confidence 的合法下界
FIELD_MAX = 1.0                 # intensity / confidence 的合法上界


def _clamp(value, lo=FIELD_MIN, hi=FIELD_MAX):
    """把数值限制在 [lo, hi] 区间内"""
    return max(lo, min(hi, float(value)))


def _emotion_cfg(key, default):
    """读取 CONFIG["emotion"] 分区配置，未配置时返回内置默认值（可后补）"""
    return CONFIG.get("emotion", {}).get(key, default)


class SemanticDetector:
    """语义情感检测器（EI v2）

    用法：
        detector = SemanticDetector()
        result = detector.detect("今天好累啊", llm=llm)
        # -> {"emotion": "疲惫", "intensity": 0.6, "confidence": 0.5, "trigger": "好累"}

    - llm 提供时：构造 JSON 输出提示词（temperature=0）解析 8 类情感；
    - llm 为 None / 解析失败 / 返回格式非法：内置关键词词典兜底。
    """

    def __init__(self):
        # LLM 侧的系统提示词：只允许输出严格 JSON
        self.system_prompt = (
            "你是一个中文情感分析引擎。只允许输出严格 JSON，不要输出任何解释、"
            "代码块标记或额外文字。\n"
            '输出格式：{"emotion": "<情感>", "intensity": <0到1小数>, '
            '"confidence": <0到1小数>, "trigger": "<触发短语>"}\n'
            f"emotion 只能是以下之一：{'、'.join(EMOTIONS)}。\n"
            "intensity 表示情感强度；confidence 表示分析置信度；"
            "trigger 是从用户文本中摘录的触发词或短语（无则填空字符串）。"
        )

    # -- 对外接口 ------------------------------------------------------------
    def detect(self, text: str, llm=None) -> dict:
        """检测用户情感，返回 {"emotion", "intensity", "confidence", "trigger"}"""
        if llm is not None:
            result = self._detect_by_llm(text, llm)
            if result is not None:
                return result
        # LLM 不可用 / 解析失败 → 关键词兜底
        return self._detect_by_keywords(text)

    def get_hint(self, emotion: str) -> str:
        """返回某类情感对应的中文提示语 hint（无则返回空串）"""
        hints = _emotion_cfg("hints", HINTS)
        return hints.get(emotion, "")

    # -- LLM 检测路径 --------------------------------------------------------
    def _detect_by_llm(self, text: str, llm) -> dict | None:
        """走 LLM JSON 输出；任何异常 / 格式错误都返回 None 触发兜底"""
        try:
            reply = self._llm_respond(llm, self._build_llm_messages(text))
        except Exception:
            return None
        if not reply:
            return None
        try:
            return self._parse_llm_json(reply)
        except Exception:
            return None

    def _build_llm_messages(self, text: str) -> list:
        """构造发给 LLM 的消息列表（system + user）"""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"请分析以下用户发言的情感：\n“{text}”"},
        ]

    def _llm_respond(self, llm, messages: list) -> str:
        """以多种常见接口风格调用 llm，统一返回文本字符串"""
        # 尽力把温度设为 0，保证输出稳定（设置失败静默）
        try:
            if hasattr(llm, "temperature"):
                llm.temperature = LLM_TEMPERATURE
        except Exception:
            pass

        # 1) langchain 风格：invoke(messages)
        if hasattr(llm, "invoke"):
            raw = self._extract_text(llm.invoke(messages))
            if raw:
                return raw
        # 2) chat 风格：chat(messages)
        if hasattr(llm, "chat"):
            raw = self._extract_text(llm.chat(messages))
            if raw:
                return raw
        # 3) 直接可调用对象
        if callable(llm):
            raw = self._extract_text(llm(messages))
            if raw:
                return raw
        raise ValueError("无法识别的 llm 接口")

    @staticmethod
    def _extract_text(raw) -> str | None:
        """从各种常见返回形态中提取纯文本内容"""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            for key in ("content", "text", "output"):
                if key in raw:
                    text = SemanticDetector._extract_text(raw[key])
                    if text:
                        return text
            return None
        content = getattr(raw, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # 多模态 content blocks
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("text"):
                    parts.append(str(block["text"]))
            return "".join(parts)
        return None

    @staticmethod
    def _parse_llm_json(reply: str) -> dict | None:
        """解析 LLM 回复中的 JSON 对象，并校验字段合法性"""
        # 兼容 ```json ... ``` 等包裹，取第一个 {...} 块
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None

        emotion = str(data.get("emotion", "")).strip()
        if emotion not in EMOTIONS:
            return None
        try:
            intensity = _clamp(float(data.get("intensity", DEFAULT_INTENSITY)))
            confidence = _clamp(float(data.get("confidence", DEFAULT_CONFIDENCE)))
        except (TypeError, ValueError):
            return None
        trigger = str(data.get("trigger", "")).strip()
        return {
            "emotion": emotion,
            "intensity": round(intensity, 4),
            "confidence": round(confidence, 4),
            "trigger": trigger,
        }

    # -- 关键词兜底路径 ------------------------------------------------------
    def _detect_by_keywords(self, text: str) -> dict:
        """内置关键词词典兜底：覆盖 8 类，命中得分 = 命中关键词总字数"""
        keywords = _emotion_cfg("keywords", KEYWORD_DEFAULTS)
        best_emotion, best_score, best_hits = "平静", 0, []
        for emotion in EMOTIONS:
            hits = [w for w in keywords.get(emotion, ()) if w in text]
            # 更长关键词权重更高，避免"烦"命中"烦躁"之类的子串误伤
            score = sum(len(w) for w in hits)
            if score > best_score:
                best_emotion, best_score, best_hits = emotion, score, hits

        if best_score == 0:
            # 未命中任何关键词 → 默认平静
            return {
                "emotion": "平静",
                "intensity": CALM_INTENSITY,
                "confidence": CALM_CONFIDENCE,
                "trigger": "",
            }

        # 命中次数越多，强度 / 置信度越高（首个命中作为 trigger）
        hits_count = len(best_hits)
        intensity = _clamp(DEFAULT_INTENSITY + INTENSITY_PER_HIT * (hits_count - 1))
        confidence = _clamp(DEFAULT_CONFIDENCE + CONFIDENCE_PER_HIT * (hits_count - 1))
        return {
            "emotion": best_emotion,
            "intensity": round(intensity, 4),
            "confidence": round(confidence, 4),
            "trigger": best_hits[0],
        }

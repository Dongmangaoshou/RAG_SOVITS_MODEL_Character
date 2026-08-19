# -*- coding: utf-8 -*-
"""EI v2 情感智能升级模块

提供三件套：
- SemanticDetector     语义情感检测（LLM JSON + 关键词兜底，8 类情感）
- EmotionFSM           角色情感状态机（状态转移 / 衰减 / Live2D 表情 / Prompt hint）
- EmotionAudioMatcher  情感音频匹配（按状态与强度选择参考音频）
"""

from core.emotion.audio_matcher import EmotionAudioMatcher
from core.emotion.detector import SemanticDetector
from core.emotion.fsm import EmotionFSM

__all__ = ["SemanticDetector", "EmotionFSM", "EmotionAudioMatcher"]

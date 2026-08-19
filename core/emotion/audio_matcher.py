# -*- coding: utf-8 -*-
"""EI v2 情感音频匹配器 —— EmotionAudioMatcher

根据角色情感状态（state + intensity）从 CharacterProfile.emotion_audio_map
中挑选最合适的参考音频，返回 (refer_wav_path, prompt_text)。

匹配逻辑：
1. 优先按角色状态找候选（心疼 → 音频键"悲伤"、羞怯 → 音频键"开心"等别名映射）；
2. 候选为空 → 回退 profile.resolve_emotion_audio("平静")；
3. 多条候选按强度分段：intensity >= 0.6 取列表后半段（高情绪样本），否则取前半段；
4. 段内轮换选取：用模块级 last_used 记录避免连续重复。
"""

import random
import re
from pathlib import Path

from core.config import CONFIG

# 情感状态 → emotion_audio_map 音频键（兼容旧键名：开心/悲伤/愤怒/焦虑/平静）
AUDIO_KEY_ALIAS = {
    "心疼": "悲伤",     # 心疼 → 悲伤键
    "羞怯": "开心",     # 羞怯 → 开心键
    "喜悦": "开心",
    "兴奋": "开心",
    "低落": "悲伤",
    "悲伤": "悲伤",
    "疲惫": "平静",
    "焦虑": "焦虑",
    "愤怒": "愤怒",
    "平静": "平静",
}

# 高情绪样本分段阈值：intensity >= 该值使用候选列表后半段
HIGH_INTENSITY_THRESHOLD = 0.60

# 亲密度 → 有效强度修正量（陌生偏低、亲密偏高，用于分段判断）
INTIMACY_BONUS = {"陌生": -0.20, "熟人": 0.00, "亲密": 0.20}

# 模块级轮换记录：{(角色名, 音频键): 上次使用的样本下标}，避免连续重复
_LAST_USED: dict = {}


def _clamp(value, lo=0.0, hi=1.0):
    """把数值限制在 [lo, hi] 区间内"""
    return max(lo, min(hi, float(value)))


def _emotion_cfg(key, default):
    """读取 CONFIG["emotion"] 分区配置，未配置时返回内置默认值（可后补）"""
    return CONFIG.get("emotion", {}).get(key, default)


def reset_rotation():
    """清空全局轮换记录（换角色 / 单元测试时调用）"""
    _LAST_USED.clear()


class EmotionAudioMatcher:
    """情感音频匹配器（EI v2）

    resolve(profile, state, intensity, intimacy="熟人") -> (refer_wav_path, prompt_text)
    """

    def resolve(self, profile, state: str, intensity: float,
                intimacy: str = "熟人") -> tuple[str, str]:
        """按角色状态与强度选择参考音频，返回 (refer_wav_path, prompt_text)"""
        audio_map = profile.emotion_audio_map
        base_dir = profile._audio_base_dir()
        key = self._audio_key(state)

        candidates = []
        if audio_map and base_dir:
            # 优先按映射键找候选，未命中再直查原始状态键
            candidates = list(audio_map.get(key) or [])
            if not candidates and key != state:
                candidates = list(audio_map.get(state) or [])

        if not candidates:
            # 候选为空 → 由 profile 兜底（其内部会自动回退"平静"）
            return profile.resolve_emotion_audio("平静")

        # 强度分段：>= 阈值取后半段（高情绪样本），否则取前半段
        eff_intensity = _clamp(float(intensity) + self._intimacy_bonus(intimacy))
        threshold = float(_emotion_cfg("high_intensity_threshold", HIGH_INTENSITY_THRESHOLD))
        half = len(candidates) // 2
        segment = candidates[half:] if eff_intensity >= threshold else candidates[:half]
        if not segment:  # 单样本等边界情况 → 退回全量
            segment = candidates

        filename = self._pick(profile.name, key, segment)
        full_path = str(Path(base_dir) / filename)

        # 从文件名提取 prompt_text：去掉【情绪】前缀与扩展名
        prompt = re.sub(r"^【[^】]*】", "", filename)
        prompt = re.sub(r"\.[^.]+$", "", prompt)

        return full_path, prompt

    # -- 内部工具 ---------------------------------------------------------------
    def _audio_key(self, state: str) -> str:
        """情感状态 → emotion_audio_map 音频键（心疼→悲伤、羞怯→开心等）"""
        return AUDIO_KEY_ALIAS.get(state, state)

    def _intimacy_bonus(self, intimacy: str) -> float:
        """亲密度对有效强度的修正量（未知值按"熟人"处理）"""
        return INTIMACY_BONUS.get(intimacy, INTIMACY_BONUS.get("熟人", 0.0))

    def _pick(self, character: str, key: str, segment: list) -> str:
        """段内轮换选取：避免与上次使用连续重复（记录于模块级 dict）"""
        last = _LAST_USED.get((character, key))
        if len(segment) <= 1:
            idx = 0
        else:
            # 从"不是上次下标"的候选中随机选，保证轮换不连续重复
            options = [i for i in range(len(segment)) if i != last]
            idx = random.choice(options)
        _LAST_USED[(character, key)] = idx
        return segment[idx]

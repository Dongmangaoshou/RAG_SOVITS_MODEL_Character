# -*- coding: utf-8 -*-
"""EI v2 角色情感状态机 —— EmotionFSM

维护角色的情感状态（state + intensity），根据用户情感与对话文本
计算状态转移，输出 Live2D 表情名 expression 与注入 Prompt 的中文情感指令 hint。

状态转移规则：
- 用户喜悦          → 角色喜悦 +0.3
- 用户悲伤 / 低落   → 角色心疼（音频映射低落）+0.4
- 用户愤怒          → 角色平静 +0.3
- 被夸奖（谢谢/喜欢/夸等）→ 角色羞怯（音频映射喜悦）+0.4
- 攻击（讨厌/滚/混蛋等）→ 角色低落 +0.5
- 无事件            → 强度 ×0.85 衰减，< 0.2 回到平静
"""

from core.config import CONFIG

# 情感 8 分类（状态空间，与 detector 保持一致）
STATES = ("喜悦", "平静", "低落", "悲伤", "愤怒", "焦虑", "疲惫", "兴奋")

# 特殊状态：由特定事件派生（音频 / 表情映射回基础类别）
SPECIAL_STATES = ("心疼", "羞怯")

# 无事件时的强度衰减系数与回平静阈值
DECAY_FACTOR = 0.85
CALM_THRESHOLD = 0.20

# 用户情感 → 角色状态转移规则：{用户情感: (目标状态, 基础强度增量)}
EMOTION_TRANSITIONS = {
    "喜悦": ("喜悦", 0.3),   # 用户喜悦 → 角色喜悦 +0.3
    "悲伤": ("心疼", 0.4),   # 用户悲伤 → 角色心疼 +0.4
    "低落": ("心疼", 0.4),   # 用户低落 → 角色心疼 +0.4
    "愤怒": ("平静", 0.3),   # 用户愤怒 → 角色平静 +0.3
    "疲惫": ("心疼", 0.3),   # 用户疲惫 → 角色心疼（关怀）+0.3
    "焦虑": ("心疼", 0.4),   # 用户焦虑 → 角色心疼（安抚）+0.4
}

# 被夸奖文本触发（优先级高于用户情感规则）
PRAISE_KEYWORDS = ("谢谢", "感谢", "喜欢", "爱你", "夸", "夸奖", "真棒", "厉害",
                   "崇拜", "好可爱", "太帅了", "好帅")
PRAISE_TARGET = "羞怯"
PRAISE_DELTA = 0.4

# 攻击文本触发（最高优先级）
ATTACK_KEYWORDS = ("讨厌", "滚", "混蛋", "滚蛋", "去死", "傻逼", "蠢货",
                   "垃圾", "废物", "贱人", "神经病", "有病")
ATTACK_TARGET = "低落"
ATTACK_DELTA = 0.5

# 用户情绪强度对转移增量的调制区间（0.5~1.0 倍：情绪越强角色反应越强）
INTENSITY_MOD_MIN = 0.5
INTENSITY_MOD_MAX = 1.0

# 状态 → Live2D 表情名映射表
EXPRESSION_MAP = {
    "喜悦": "喜悦",
    "平静": "平静",
    "低落": "低落",
    "悲伤": "低落",     # 悲伤无独立表情 → 复用低落
    "愤怒": "愤怒",
    "焦虑": "焦虑",
    "疲惫": "平静",     # 疲惫无独立表情 → 复用平静
    "兴奋": "兴奋",
    "心疼": "低落",     # 心疼 → 复用低落
    "羞怯": "羞怯",
}

# 状态 → 注入 Prompt 的中文情感指令（表达方式）
STATE_HINTS = {
    "喜悦": "语气轻快、带着笑意",
    "平静": "语气平稳、不紧不慢",
    "低落": "语气低沉、说话放缓",
    "悲伤": "声音低沉、略带哽咽",
    "愤怒": "语气强硬、语速加快",
    "焦虑": "语气急促、略带不安",
    "疲惫": "声音有气无力、语速放慢",
    "兴奋": "语气高昂、语速轻快",
    "心疼": "温柔安慰、压低语气",
    "羞怯": "语气躲闪、轻声细语",
}

# hint 模板：注入 Prompt 的中文情感指令
HINT_TEMPLATE = "角色当前情感：{state}(强度{intensity:.1f})，表达方式：{hint_text}"


def _clamp(value, lo=0.0, hi=1.0):
    """把数值限制在 [lo, hi] 区间内"""
    return max(lo, min(hi, float(value)))


def _emotion_cfg(key, default):
    """读取 CONFIG["emotion"] 分区配置，未配置时返回内置默认值（可后补）"""
    return CONFIG.get("emotion", {}).get(key, default)


class EmotionFSM:
    """角色情感状态机（EI v2）

    - state：角色当前情感（8 类 + 心疼 / 羞怯）
    - intensity：情感强度（0~1，无事件时随时间衰减）

    update(user_emotion, user_intensity, text) -> dict
      返回 {"state", "intensity", "expression", "hint"}
    """

    def __init__(self, state: str = "平静", intensity: float = 0.0):
        self.state = state if state in STATES + SPECIAL_STATES else "平静"
        self.intensity = _clamp(intensity)

    # -- 状态机主流程 ----------------------------------------------------------
    def update(self, user_emotion: str, user_intensity: float, text: str) -> dict:
        """根据用户情感与文本更新角色状态

        事件优先级：攻击文本 > 夸奖文本 > 用户情感规则 > 无事件衰减
        """
        # 1) 攻击文本 → 角色低落（最高优先级）
        if any(w in text for w in _emotion_cfg("attack_keywords", ATTACK_KEYWORDS)):
            self._apply(_emotion_cfg("attack_target", ATTACK_TARGET),
                        float(_emotion_cfg("attack_delta", ATTACK_DELTA)), user_intensity)
        # 2) 被夸奖文本 → 角色羞怯
        elif any(w in text for w in _emotion_cfg("praise_keywords", PRAISE_KEYWORDS)):
            self._apply(_emotion_cfg("praise_target", PRAISE_TARGET),
                        float(_emotion_cfg("praise_delta", PRAISE_DELTA)), user_intensity)
        # 3) 用户情感规则
        else:
            transitions = _emotion_cfg("emotion_transitions", EMOTION_TRANSITIONS)
            if user_emotion in transitions:
                target, delta = transitions[user_emotion]
                self._apply(target, float(delta), user_intensity)
            # 4) 无事件 → 强度衰减，跌破阈值回平静
            else:
                self._decay()
        return self._result()

    def reset(self):
        """重置为初始状态（平静，强度 0）"""
        self.state = "平静"
        self.intensity = 0.0
        return self

    def to_dict(self) -> dict:
        """序列化状态（用于持久化存档）"""
        return {"state": self.state, "intensity": round(self.intensity, 4)}

    def from_dict(self, data: dict) -> "EmotionFSM":
        """从字典恢复状态（用于加载存档）"""
        state = data.get("state", "平静")
        self.state = state if state in STATES + SPECIAL_STATES else "平静"
        self.intensity = _clamp(data.get("intensity", 0.0))
        return self

    # -- 内部实现 --------------------------------------------------------------
    def _apply(self, target: str, delta: float, user_intensity: float):
        """切换到目标状态并累加强度（增量受用户情绪强度调制）"""
        mod = INTENSITY_MOD_MIN + (INTENSITY_MOD_MAX - INTENSITY_MOD_MIN) * _clamp(user_intensity)
        self.state = target
        self.intensity = _clamp(self.intensity + delta * mod)

    def _decay(self):
        """无事件时的强度衰减；跌破阈值回到平静"""
        factor = float(_emotion_cfg("decay_factor", DECAY_FACTOR))
        threshold = float(_emotion_cfg("calm_threshold", CALM_THRESHOLD))
        self.intensity = self.intensity * factor
        if self.intensity < threshold:
            self.state = "平静"
            self.intensity = 0.0

    def _result(self) -> dict:
        """组装输出：状态 / 强度 / Live2D 表情名 / Prompt 情感指令"""
        expression = EXPRESSION_MAP.get(self.state, "平静")
        hint_text = STATE_HINTS.get(self.state, "语气自然")
        template = _emotion_cfg("hint_template", HINT_TEMPLATE)
        hint = template.format(state=self.state, intensity=self.intensity, hint_text=hint_text)
        return {
            "state": self.state,
            "intensity": round(self.intensity, 4),
            "expression": expression,
            "hint": hint,
        }

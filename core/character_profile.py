import random
import re
from pathlib import Path

from core.config import CHARACTER_DB


class CharacterProfile:
    """角色数据管理 —— 封装 character_database.json 中单个角色的全部属性"""

    def __init__(self, character_name):
        self.name = character_name
        self.data = CHARACTER_DB[character_name]

    # -- 基础信息 ------------------------------------------------
    @property
    def source(self):
        return self.data["source"]

    @property
    def backstory(self):
        return self.data["backstory"]

    @property
    def personality(self):
        return self.data["personality"]

    @property
    def style(self):
        return self.data["style"]

    # -- 装饰元素 ------------------------------------------------
    @property
    def catchphrases(self):
        return self.data["catchphrases"]

    @property
    def visual_elements(self):
        return self.data["visual_elements"]

    # -- 语音合成路径 --------------------------------------------
    @property
    def sovits_path(self):
        return self.data["sovits_path"]

    @property
    def gpt_path(self):
        return self.data["gpt_path"]

    @property
    def refer_wav_path(self):
        return self.data.get("refer_wav_path", "")

    @property
    def prompt_text(self):
        return self.data.get("prompt_text", "")

    # -- 情感→参考音频动态选择 ----------------------------------
    @property
    def emotion_audio_map(self):
        return self.data.get("emotion_audio_map", {})

    def _audio_base_dir(self) -> str:
        """从 refer_wav_path 模板推导实际目录，去除 {emotion} 占位符"""
        rwp = self.refer_wav_path
        if not rwp:
            return ""
        base = re.sub(r'[/\\]?\{?emotion\}?$', '', rwp)
        return base

    def resolve_emotion_audio(self, emotion: str) -> tuple[str, str]:
        """根据情感从 refer_wav_path 模板目录 + emotion_audio_map 中选取
        参考音频文件，返回 (refer_wav_path, prompt_text)。
        prompt_text 自动从文件名中提取（去除【情绪】前缀和扩展名）。
        """
        audio_map = self.emotion_audio_map
        base_dir = self._audio_base_dir()

        if not audio_map or not base_dir:
            return self.refer_wav_path, self.prompt_text

        candidates = audio_map.get(emotion)
        if not candidates:
            candidates = audio_map.get("平静", [])

        if not candidates:
            return self.refer_wav_path, self.prompt_text

        filename = random.choice(candidates)
        full_path = str(Path(base_dir) / filename)

        # 去掉【情绪】前缀和扩展名，提取纯文本作为 prompt_text
        prompt = re.sub(r'^【[^】]*】', '', filename)
        prompt = re.sub(r'\.[^.]+$', '', prompt)

        return full_path, prompt

    # -- RAG 素材 ------------------------------------------------
    @property
    def story_settings(self):
        return self.data.get("story_setting", [])

    @property
    def lines_library(self):
        return self.data.get("lines_library", [])

    def all_texts(self):
        """返回用于构建 RAG 向量库的文本列表"""
        texts = [f"角色设定: {self.backstory}"]
        texts.extend(f"故事背景: {s}" for s in self.story_settings)
        texts.extend(f"经典台词: {l}" for l in self.lines_library)
        return texts

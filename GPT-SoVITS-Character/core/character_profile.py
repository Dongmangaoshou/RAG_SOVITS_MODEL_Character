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
        return self.data["refer_wav_path"]

    @property
    def prompt_text(self):
        return self.data["prompt_text"]

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

import os
import random
import re
import time
import pygame
from pathlib import Path

from langchain.chains import LLMChain
from langchain.callbacks.base import BaseCallbackHandler
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from core.config import CONFIG, SCRIPT_DIR
from core.character_profile import CharacterProfile
from core.rag_manager import RagManager
from core.emotion_engine import EmotionEngine
from core.relationship_tracker import RelationshipTracker
from core.memory_manager import MemoryManager, list_saved_conversations
from core.speech_synthesizer import SpeechSynthesizer


class StreamHandler(BaseCallbackHandler):
    """流式输出回调 —— 实时打印 LLM 生成的 token"""

    def __init__(self):
        self.tokens = []

    def on_llm_new_token(self, token: str, **kwargs):
        print(token, end="", flush=True)
        self.tokens.append(token)

    def get_complete_text(self):
        return "".join(self.tokens)


class AdvancedCharacterSystem:
    """角色对话系统门面 —— 组合所有子模块，对外暴露统一接口"""

    def __init__(self, character_name, rag_manager: RagManager):
        self.profile = CharacterProfile(character_name)
        self.rag = rag_manager
        self.emotion = EmotionEngine()
        self.relationship = RelationshipTracker()
        self.memory = MemoryManager()
        self.tts = SpeechSynthesizer()

        api_key = os.environ.get('DEEPSEEK_API_KEY')
        llm_cfg = CONFIG["llm"]
        self.llm = ChatOpenAI(
            openai_api_key=api_key,
            base_url=llm_cfg["base_url"],
            model=llm_cfg["model"],
            temperature=llm_cfg["temperature"],
            streaming=True,
        )

        pygame.mixer.init()
        self.conversation = LLMChain(
            llm=self.llm,
            prompt=self._create_prompt_template(),
            verbose=False,
            output_key="output",
        )

    # -- Prompt --------------------------------------------------
    def _create_prompt_template(self):
        base_prompt = (
            f"你正在扮演{self.profile.source}中的{self.profile.name}。\n"
            f"角色背景故事: {self.profile.backstory}\n\n"
            f"角色性格: {self.profile.personality}\n"
            f"说话风格: {self.profile.style}\n\n"
            "重要规则:\n"
            "1. 严格保持角色设定和语言风格\n"
            "2. 在回复中自然融入角色经典台词\n"
            "3. 每2-3句话添加一个颜文字或表情符号\n"
            "4. 作为心理支持角色，要理解用户情绪并提供支持\n"
            "5. 如果用户表现出负面情绪，先表达同理心再引导积极思考\n\n"
            "当前对话历史:\n"
            "{history}\n\n"
            "角色相关上下文:\n"
            "{rag_context}\n\n"
            "用户: {input}\n"
            f"{self.profile.name}:"
        )
        return PromptTemplate(
            input_variables=["history", "input", "rag_context"],
            template=base_prompt,
        )

    # -- 核心流程 ------------------------------------------------
    def generate_response(self, user_input: str) -> str:
        """生成角色回复（含 RAG、情感、关系、API 重试）"""
        rag_context = self._build_rag_context(user_input)

        max_retries = CONFIG["llm"]["max_retries"]
        base_delay = CONFIG["llm"]["retry_base_delay"]

        for attempt in range(max_retries):
            try:
                history = self.memory.load_history({"input": user_input})
                stream_handler = StreamHandler()
                result = self.conversation.invoke(
                    {"input": user_input, "rag_context": rag_context, "history": history},
                    config={"callbacks": [stream_handler]},
                )
                text_response = result.get('output')
                final_response = self._inject_character_elements(text_response)
                self.memory.save_context(user_input, final_response)
                return final_response

            except Exception as e:
                if attempt < max_retries - 1:
                    wait = base_delay * (2 ** attempt)
                    print(f"\n[API 异常: {e}，{wait}s 后重试 ({attempt+1}/{max_retries})]")
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"API 调用失败（已重试 {max_retries} 次）: {e}"
                    ) from e

    def _build_rag_context(self, user_input: str) -> str:
        """构建 RAG 上下文，融合情绪和关系信息"""
        ctx = self.rag.retrieve_as_context(self.profile.name, user_input)

        emotion = self.emotion.detect(user_input)
        hint = self.emotion.get_context_hint(emotion)
        if hint:
            ctx += f"\n{hint}"

        self.relationship.update(user_input)
        if self.relationship.level > 3:
            ctx += f"\n关系等级: {self.relationship.level}/10 - 角色可以更亲近"
            if self.relationship.is_close():
                self.profile.data["style"] += " 对用户更加亲近信任"

        return ctx

    def _inject_character_elements(self, response: str) -> str:
        """注入随机口头禅和颜文字"""
        if random.random() > 0.4:
            response = f"{random.choice(self.profile.catchphrases)} {response}"
        if random.random() > 0.3:
            response = f"{response} {random.choice(self.profile.visual_elements)}"
        return response

    # -- 语音合成 ------------------------------------------------
    def synthesize_speech(self, text: str) -> bool:
        return self.tts.synthesize(self.profile, text)

    # -- 持久化 --------------------------------------------------
    def save_conversation(self, save_dir=None):
        return self.memory.save_to_file(
            self.profile.name, self.relationship.level, save_dir
        )

    def load_conversation(self, filepath):
        rel = self.memory.load_from_file(filepath)
        self.relationship.level = rel

    @staticmethod
    def list_saved_conversations(character_name):
        return list_saved_conversations(character_name)

    # -- 便捷属性 ------------------------------------------------
    @property
    def character_name(self):
        return self.profile.name

    @property
    def relationship_level(self):
        return self.relationship.level

    @property
    def tts_enabled(self):
        return self.tts.enabled

    def disable_tts(self):
        self.tts.disable()

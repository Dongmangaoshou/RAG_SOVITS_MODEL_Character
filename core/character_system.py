import os
import random
import re
import time
import threading
import queue
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

# --- V2 集成（缺失时优雅降级，不破坏旧功能） ------------------------
try:
    from core.memory import MemoryV2
    _MEMORY_V2 = True
except ImportError:
    MemoryV2 = None
    _MEMORY_V2 = False

try:
    from core.emotion import SemanticDetector, EmotionFSM, EmotionAudioMatcher
    _EMOTION_V2 = True
except ImportError:
    SemanticDetector = None
    EmotionFSM = None
    EmotionAudioMatcher = None
    _EMOTION_V2 = False


class _QueueCallback(BaseCallbackHandler):
    """将 token 放入线程安全队列的回调"""
    def __init__(self, q: queue.Queue):
        self.q = q

    def on_llm_new_token(self, token: str, **kwargs):
        self.q.put(token)


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
        self._last_emotion = "平静"
        self._last_emotion_intensity = 0.0

        api_key = os.environ.get('DEEPSEEK_API_KEY')
        llm_cfg = CONFIG["llm"]
        self.llm = ChatOpenAI(
            openai_api_key=api_key,
            base_url=llm_cfg["base_url"],
            model=llm_cfg["model"],
            temperature=llm_cfg["temperature"],
            streaming=True,
        )

        # --- V2 组件（失败降级为 None，不影响旧链路） ----------------
        self.memory_v2 = None
        self.emotion_fsm = None
        self.emotion_detector = None
        self.emotion_audio_matcher = None
        try:
            if _MEMORY_V2 and MemoryV2 is not None:
                self.memory_v2 = MemoryV2(
                    character_name,
                    llm=self.llm,
                    token_budget=int(CONFIG.get("memory", {}).get("token_budget", 1000)),
                    summarize_interval=int(CONFIG.get("memory", {}).get("summarize_interval", 5)),
                )
        except Exception as e:
            print(f"[V2] 记忆系统初始化失败，降级旧记忆: {e}")
            self.memory_v2 = None
        try:
            if _EMOTION_V2:
                self.emotion_fsm = EmotionFSM()
                self.emotion_detector = SemanticDetector()
                self.emotion_audio_matcher = EmotionAudioMatcher()
        except Exception as e:
            print(f"[V2] 情感系统初始化失败，降级旧情感: {e}")
            self.emotion_fsm = None
            self.emotion_detector = None
            self.emotion_audio_matcher = None

        try:
            pygame.mixer.init()
        except Exception:
            pass
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
                self._save_v2_memory(user_input, final_response)
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
        """构建 RAG 上下文，融合情绪、关系、记忆（V2）信息"""
        ctx = self.rag.retrieve_as_context(self.profile.name, user_input)

        # --- V2 情感：语义识别 → 状态机转移 ---------------------------
        # 注意：主链路用关键词快速检测（llm=None，零额外 LLM 延迟），
        # 语义级分类在 save_turn 的事件提取阶段异步补全。
        if self.emotion_detector is not None and self.emotion_fsm is not None:
            try:
                det = self.emotion_detector.detect(user_input, llm=None)
                fsm_res = self.emotion_fsm.update(
                    det.get("emotion", "平静"),
                    float(det.get("intensity", 0.0)),
                    user_input,
                )
                self._last_emotion = fsm_res.get("state", "平静")
                self._last_emotion_intensity = float(fsm_res.get("intensity", 0.0))
                hint = fsm_res.get("hint", "")
                if hint:
                    ctx += f"\n{hint}"
                if fsm_res.get("expression"):
                    ctx += f"\n表情指示: {fsm_res['expression']}"
            except Exception:
                pass  # V2 情感失败回退旧关键词检测
        if self._last_emotion == "平静" or not (self.emotion_detector and self.emotion_fsm):
            emotion = self.emotion.detect(user_input)
            self._last_emotion = emotion
            hint = self.emotion.get_context_hint(emotion)
            if hint:
                ctx += f"\n{hint}"

        # --- V2 记忆：注入记忆上下文（跨会话） --------------------------
        if self.memory_v2 is not None:
            try:
                mem_ctx = self.memory_v2.build_context(user_input)
                if mem_ctx:
                    ctx += f"\n{mem_ctx}"
            except Exception:
                pass  # 记忆失败不影响主链路

        # --- 关系 ------------------------------------------------------
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

    def generate_response_stream(self, user_input: str):
        """流式生成（生成器）—— 每收到一个 token 就 yield 累积文本，供 WebUI 实时显示"""
        rag_context = self._build_rag_context(user_input)
        history = self.memory.load_history({"input": user_input})
        token_queue = queue.Queue()

        def _run():
            try:
                self.conversation.invoke(
                    {"input": user_input, "rag_context": rag_context, "history": history},
                    config={"callbacks": [_QueueCallback(token_queue)]},
                )
            except Exception as e:
                token_queue.put(e)
            finally:
                token_queue.put(None)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        raw = ""
        while True:
            token = token_queue.get()
            if token is None:
                break
            if isinstance(token, Exception):
                raise token
            raw += token
            yield raw, None, ""

        thread.join()
        final = self._inject_character_elements(raw)
        self.memory.save_context(user_input, final)
        self._save_v2_memory(user_input, final)

        # 尝试合成语音（先快速探测 TTS 服务，不可用立即跳过，避免阻塞流式连接）
        audio_path = None
        status = ""
        if self.tts.enabled:
            tts_ok = False
            try:
                tts_ok = self.tts.is_available()
            except Exception:
                tts_ok = False
            if tts_ok:
                try:
                    ref_path, ref_text = self._resolve_audio()
                    audio_path = self.tts.synthesize_to_path(
                        self.profile, re.sub(r'\([^)]*\)', '', final),
                        refer_wav_path=ref_path, prompt_text=ref_text)
                    status = "✓ 语音已合成" if audio_path else "✗ 语音合成失败"
                except Exception:
                    audio_path = None
                    status = "✗ 语音合成失败"
            else:
                status = "✗ TTS 服务未运行（仅文本）"

        yield final, audio_path, status

    def _save_v2_memory(self, user_input: str, response: str):
        """保存 V2 记忆（尽力而为，失败静默）"""
        if self.memory_v2 is None:
            return
        try:
            is_share = self._last_emotion in ("悲伤", "低落", "焦虑")
            self.memory_v2.save_turn(
                user_input, response,
                emotion_tag=self._last_emotion,
                is_share_emotion=is_share,
                do_extract=True,
            )
        except Exception:
            pass

    # -- 语音合成 ------------------------------------------------
    def _resolve_audio(self) -> tuple[str, str]:
        """按角色情感状态（V2 匹配器）选取参考音频；回退旧逻辑"""
        if self.emotion_audio_matcher is not None:
            try:
                intimacy = "熟人"
                if self.memory_v2 is not None:
                    intimacy = self.memory_v2.relationship.intimacy_level
                return self.emotion_audio_matcher.resolve(
                    self.profile, self._last_emotion,
                    self._last_emotion_intensity, intimacy,
                )
            except Exception:
                pass
        return self.profile.resolve_emotion_audio(self._last_emotion)

    def synthesize_speech(self, text: str) -> bool:
        ref_path, ref_text = self._resolve_audio()
        return self.tts.synthesize(self.profile, text,
                                   refer_wav_path=ref_path, prompt_text=ref_text)

    def get_tts_audio(self, text: str) -> str | None:
        """合成语音并返回路径（WebUI 用）"""
        ref_path, ref_text = self._resolve_audio()
        return self.tts.synthesize_to_path(self.profile,
                       re.sub(r'\([^)]*\)', '', text),
                       refer_wav_path=ref_path, prompt_text=ref_text)

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

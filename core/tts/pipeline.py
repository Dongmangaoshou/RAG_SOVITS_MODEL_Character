"""句级合成流水线 —— 低延迟对话链路第三环：切句 → 查缓存 → 逐句合成。

行为约定：
- 每句独立调用 GPT-SoVITS API（SpeechSynthesizer.synthesize_to_path）；
- 单句失败跳过，不阻塞整段文本；
- 单句超时由 SpeechSynthesizer 内部（CONFIG["tts"]["timeout"]）处理；
- 返回按句合成的 wav 路径列表，每句一个文件，文件名带 seq 前缀；
- 可选 LRU 磁盘缓存（TTSCache）与外部中断信号（stop_event）。
"""

import hashlib
import shutil
import threading
import time
from pathlib import Path

from core.config import CONFIG, SCRIPT_DIR
from core.character_profile import CharacterProfile
from core.speech_synthesizer import SpeechSynthesizer
from core.tts.sentence_splitter import split_sentences, DEFAULT_MAX_LEN
from core.tts.cache import TTSCache

# 默认输出根目录（data/tts_seq，可由 CONFIG["latency"]["seq_output_dir"] 覆盖）
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "data" / "tts_seq"
# 文件名中文本哈希截取长度
_HASH_PREFIX_LEN = 8
# 默认情感标签（调用方未指定情感时用于缓存键）
DEFAULT_EMOTION = "平静"
# 会话目录命名取模数（避免并发/重复调用文件名冲突）
_SESSION_ID_MOD = 1_000_000


class SentencePipeline:
    """句级合成流水线：切句 → 缓存查询 → 逐句合成 → 输出 seq 前缀文件。"""

    def __init__(self, max_len: int = DEFAULT_MAX_LEN, output_dir=None):
        latency_cfg = CONFIG.get("latency", {})
        self.max_len = int(
            max_len
            if max_len is not None
            else latency_cfg.get("max_sentence_len", DEFAULT_MAX_LEN)
        )
        self.output_dir = Path(
            output_dir
            or latency_cfg.get("seq_output_dir")
            or DEFAULT_OUTPUT_DIR
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _seq_hash(text: str) -> str:
        """句子内容哈希（截取前缀），用于 seq 文件名的唯一性"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()[:_HASH_PREFIX_LEN]

    def synthesize_sequence(
        self,
        profile: CharacterProfile,
        text: str,
        refer_wav_path: str = "",
        prompt_text: str = "",
        tts: SpeechSynthesizer | None = None,
        cache: TTSCache | None = None,
        *,
        emotion: str = DEFAULT_EMOTION,
        stop_event: threading.Event | None = None,
        verbose: bool = False,
    ) -> list[str]:
        """按句合成整段文本。

        Args:
            profile: 角色配置
            text: 待合成文本（内部先切句）
            refer_wav_path: 参考音频路径，空则用 profile 默认值
            prompt_text: 参考音频文本，空则用 profile 默认值
            tts: 语音合成器，None 时内部创建
            cache: 磁盘缓存，None 时不启用
            emotion: 情感标签（缓存键的一部分，也用于参考音频选择）
            stop_event: 中断信号（set 后停止后续句子合成）
            verbose: 为 True 时打印每句耗时

        Returns:
            按句合成的 wav 路径列表（每句一个文件，带 seq 前缀）
        """
        sentences = split_sentences(text, self.max_len)
        if not sentences:
            return []

        if tts is None:
            tts = SpeechSynthesizer()

        # 本次调用独享一个会话子目录，避免并发/重复调用文件名冲突
        session = (
            time.strftime("%Y%m%d_%H%M%S")
            + f"_{int(time.time() * 1000) % _SESSION_ID_MOD:06d}"
        )
        session_dir = self.output_dir / session
        session_dir.mkdir(parents=True, exist_ok=True)

        result: list[str] = []
        total = len(sentences)
        for i, sent in enumerate(sentences, start=1):
            if stop_event is not None and stop_event.is_set():
                if verbose:
                    print(f"[流水线] 收到中断信号，跳过剩余 {total - i + 1} 句")
                break

            start_t = time.perf_counter()
            wav_path = self._synthesize_one(
                profile, sent, refer_wav_path, prompt_text,
                tts, cache, emotion, session_dir, i,
            )
            elapsed = time.perf_counter() - start_t

            if wav_path is None:
                if verbose:
                    print(f"[句 {i}/{total} 失败跳过] {sent}")
                continue
            result.append(wav_path)
            if verbose:
                print(
                    f"[句 {i}/{total} 耗时 {elapsed:.2f}s] {sent}"
                    f" -> {Path(wav_path).name}"
                )

        return result

    # -- 内部 ----------------------------------------------------
    def _synthesize_one(
        self,
        profile: CharacterProfile,
        sent: str,
        refer_wav_path: str,
        prompt_text: str,
        tts: SpeechSynthesizer,
        cache: TTSCache | None,
        emotion: str,
        session_dir: Path,
        seq: int,
    ) -> str | None:
        """单句合成：优先查缓存，未命中则调用 TTS，并统一落到 seq 前缀文件。"""
        seq_file = session_dir / f"seq_{seq:03d}_{self._seq_hash(sent)}.wav"

        src: str | None = None
        if cache is not None:
            src = cache.get(profile.name, emotion, sent)
        if src is None:
            src = tts.synthesize_to_path(profile, sent, refer_wav_path, prompt_text)
            if src is None:
                return None  # 单句失败跳过，不阻塞后续句子
            if cache is not None:
                cache.put(profile.name, emotion, sent, src)

        try:
            shutil.copy2(src, seq_file)
            return str(seq_file)
        except OSError:
            # 源文件可能已被外部清理：存在则直接返回源路径，否则视为失败
            return src if Path(src).exists() else None

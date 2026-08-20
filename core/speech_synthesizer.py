import socket
import subprocess
import time
import requests
from pathlib import Path

from core.config import CONFIG, SCRIPT_DIR
from core.character_profile import CharacterProfile


class SpeechSynthesizer:
    """语音合成 —— 调用 GPT-SoVITS API 生成语音并播放"""

    _availability_cache: dict = {}   # api_url -> (available, checked_at)

    def __init__(self):
        self._enabled = CONFIG["tts"]["enabled"]

    @property
    def enabled(self):
        return self._enabled

    def disable(self):
        self._enabled = False

    def is_available(self, timeout: float = 0.8, cache_ttl: float = 5.0) -> bool:
        """快速探测 TTS 服务是否可连接（socket 握手，不发起真实合成）。
        结果带 5 秒缓存，避免频繁探测。"""
        api_url = CONFIG["tts"].get("api_url", "http://127.0.0.1:9880")
        now = time.time()
        cached = self._availability_cache.get(api_url)
        if cached and now - cached[1] < cache_ttl:
            return cached[0]
        available = False
        try:
            from urllib.parse import urlparse
            u = urlparse(api_url)
            host, port = u.hostname or "127.0.0.1", u.port or 9880
            with socket.create_connection((host, port), timeout=timeout):
                available = True
        except Exception:
            available = False
        self._availability_cache[api_url] = (available, now)
        return available

    @staticmethod
    def _fix_audio(filepath):
        """用 ffmpeg 将音频转为 pcm_s16le 标准格式，覆盖原文件"""
        src = Path(filepath)
        tmp = src.with_name(src.stem + "_raw" + src.suffix)
        try:
            src.rename(tmp)
            subprocess.run([
                "ffmpeg", "-y", "-i", str(tmp),
                "-acodec", "pcm_s16le", str(src),
            ], capture_output=True)
            tmp.unlink()
            print(f" 音频已修复: {src.name}")
        except Exception as e:
            if tmp.exists():
                tmp.rename(src)
            print(f" ffmpeg 修复跳过: {e}")

    @staticmethod
    def _play_audio(filepath, timeout=60):
        """播放音频：优先 VLC，不可用时降级 pygame"""
        try:
            import vlc
        except (ImportError, OSError):
            vlc = None

        if vlc is not None:
            try:
                player = vlc.MediaPlayer(str(filepath))
                player.audio_set_volume(100)
                player.play()
                import time as _t
                start = _t.time()
                while player.get_state() in (
                    vlc.State.NothingSpecial, vlc.State.Opening, vlc.State.Buffering
                ):
                    if _t.time() - start > 10:
                        break
                    _t.sleep(0.05)
                elapsed = 0
                while player.is_playing() and elapsed < timeout:
                    _t.sleep(0.1)
                    elapsed += 0.1
                player.stop()
                player.release()
                print(" VLC 播放完成")
                return
            except Exception:
                print(" VLC 播放失败，尝试 pygame...")

        try:
            import pygame
            sound = pygame.mixer.Sound(str(filepath))
            print(f" pygame 播放中... ({sound.get_length():.1f}s)")
            channel = sound.play()
            while channel.get_busy():
                pygame.time.wait(10)
            print(" pygame 播放完成")
        except Exception as e:
            print(f" 播放失败: {e}")

    def _resolve_tts_url(self) -> str:
        """返回 GPT-SoVITS /tts 端点 URL（兼容配置中带/不带路径）"""
        base = CONFIG["tts"].get("api_url", "http://127.0.0.1:9880").rstrip("/")
        if base.endswith("/tts"):
            return base
        return base + "/tts"

    def _resolve_ref_audio(self, profile: CharacterProfile,
                           refer_wav_path: str, prompt_text: str):
        """解析参考音频路径与提示文本：
        - 若调用方显式传入（已由 EmotionAudioMatcher 解析）则直接使用
        - 否则从角色配置解析，并替换 {emotion} 占位符"""
        if refer_wav_path and "{emotion}" not in refer_wav_path:
            return refer_wav_path, prompt_text
        # 尝试按情感解析（默认平静）
        try:
            return profile.resolve_emotion_audio("平静")
        except Exception:
            return profile.refer_wav_path, profile.prompt_text

    def _build_payload(self, profile: CharacterProfile, text: str,
                       ref_path: str, ref_text: str) -> dict:
        """按 GPT-SoVITS api_v2.py 新版参数契约构建请求体。
        注意：sovits_path/gpt_path 由服务端 tts_infer.yaml 管理，不再传。"""
        return {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": ref_path,
            "prompt_lang": "ja",
            "prompt_text": ref_text,
            "text_split_method": "cut5",
            "batch_size": 1,
            "media_type": "wav",
            "streaming_mode": False,
            "top_k": 5,
            "top_p": 1,
            "temperature": 1,
        }

    def synthesize(self, profile: CharacterProfile, text: str,
                   refer_wav_path: str = "", prompt_text: str = "") -> bool:
        """合成语音 → ffmpeg 格式修复 → 播放"""
        ref_path, ref_text = self._resolve_ref_audio(
            profile, refer_wav_path, prompt_text)
        payload = self._build_payload(profile, text, ref_path, ref_text)

        try:
            print("正在合成语音...", end="", flush=True)
            resp = requests.post(self._resolve_tts_url(), json=payload,
                                 timeout=CONFIG["tts"]["timeout"])
            if resp.status_code != 200:
                print(f" API错误 {resp.status_code}")
                return False

            content_type = resp.headers.get('Content-Type', '')
            if 'audio' not in content_type:
                print(f" 非音频响应: {content_type}")
                return False

            output_dir = SCRIPT_DIR / "generated_audio"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            audio_path = output_dir / f"{profile.name}_{timestamp}.wav"
            audio_path.write_bytes(resp.content)
            print(f" 已保存: {audio_path}")

            self._fix_audio(audio_path)
            self._play_audio(audio_path)
            return True
        except Exception as e:
            print(f"语音合成异常: {e}")
            return False

    def synthesize_to_path(self, profile: CharacterProfile, text: str,
                           refer_wav_path: str = "", prompt_text: str = "") -> str | None:
        """合成语音 → ffmpeg 格式修复 → 返回路径（供 WebUI 使用）"""
        ref_path, ref_text = self._resolve_ref_audio(
            profile, refer_wav_path, prompt_text)
        payload = self._build_payload(profile, text, ref_path, ref_text)
        try:
            resp = requests.post(self._resolve_tts_url(), json=payload,
                                 timeout=CONFIG["tts"]["timeout"])
            if resp.status_code != 200:
                return None
            if 'audio' not in resp.headers.get('Content-Type', ''):
                return None
            output_dir = SCRIPT_DIR / "generated_audio"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            audio_path = output_dir / f"{profile.name}_{timestamp}.wav"
            audio_path.write_bytes(resp.content)

            self._fix_audio(audio_path)
            return str(audio_path)
        except Exception:
            return None

import time
import requests

from core.config import CONFIG, SCRIPT_DIR
from core.character_profile import CharacterProfile


class SpeechSynthesizer:
    """语音合成 —— 调用 GPT-SoVITS API 生成语音并播放"""

    def __init__(self):
        self._enabled = CONFIG["tts"]["enabled"]

    @property
    def enabled(self):
        return self._enabled

    def disable(self):
        self._enabled = False

    def synthesize(self, profile: CharacterProfile, text: str) -> bool:
        """合成语音，保存到 generated_audio 并用 pygame 播放"""
        import pygame
        payload = {
            "sovits_path": profile.sovits_path,
            "gpt_path": profile.gpt_path,
            "refer_wav_path": profile.refer_wav_path,
            "prompt_text": profile.prompt_text,
            "prompt_language": "ja",
            "text": text,
            "text_language": "zh",
            "media_type": "wav",
        }

        try:
            print("正在合成语音...", end="", flush=True)
            resp = requests.post(CONFIG["tts"]["api_url"], json=payload,
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

            sound = pygame.mixer.Sound(str(audio_path))
            print(f" 播放中... (真实时长: {sound.get_length():.2f}s)")
            channel = sound.play()
            while channel.get_busy():
                pygame.time.wait(10)
            print(" 播放完成")
            return True
        except Exception as e:
            print(f"语音合成异常: {e}")
            return False

import time
import wave
from pathlib import Path

try:
    import vlc
    HAS_VLC = True
except ImportError:
    HAS_VLC = False
except OSError:
    HAS_VLC = False


def get_audio_duration(audio_path):
    """获取 WAV 音频文件的精确时长（秒），非 WAV 返回估算值"""
    audio_path = Path(audio_path)
    try:
        if audio_path.suffix.lower() == '.wav':
            with wave.open(str(audio_path), 'rb') as f:
                return f.getnframes() / f.getframerate()
        # 非 WAV 用 VLC 获取时长
        if HAS_VLC:
            media = vlc.Media(str(audio_path))
            media.parse()
            dur = media.get_duration() / 1000.0
            return dur if dur > 0 else 5.0
    except Exception:
        pass
    return 5.0


def play_audio_with_system_player(audio_path, timeout=60):
    """使用 VLC 播放音频，阻塞等待播放完成"""
    audio_path = Path(audio_path)

    if not audio_path.exists():
        print(f"音频文件不存在: {audio_path}")
        return False

    if not HAS_VLC:
        print("VLC 未安装，请执行: pip install python-vlc (且系统需安装 VLC 播放器)")
        return False

    try:
        duration = get_audio_duration(audio_path)
        print(f"VLC 播放中 ({duration:.1f}s): {audio_path.name}")

        player = vlc.MediaPlayer(str(audio_path))
        player.audio_set_volume(100)
        player.play()

        # 等待播放开始
        start = time.time()
        while player.get_state() in (vlc.State.NothingSpecial, vlc.State.Opening, vlc.State.Buffering):
            if time.time() - start > 10:
                break
            time.sleep(0.05)

        # 等待播放完成
        elapsed = 0
        while player.is_playing() and elapsed < timeout:
            time.sleep(0.1)
            elapsed += 0.1

        player.stop()
        player.release()
        return True
    except Exception as e:
        print(f"VLC 播放失败: {e}")
        return False

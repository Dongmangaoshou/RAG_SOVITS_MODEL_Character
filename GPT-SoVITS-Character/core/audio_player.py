import os
import wave
import subprocess
from pathlib import Path

try:
    import simpleaudio as sa
    HAS_SIMPLEAUDIO = True
except ImportError:
    HAS_SIMPLEAUDIO = False

try:
    import winsound
except ImportError:
    winsound = None


def get_audio_duration(audio_path):
    """获取 WAV 或 OGG 音频文件的精确时长（秒）"""
    audio_path = Path(audio_path)
    try:
        if audio_path.suffix.lower() == '.wav':
            with wave.open(str(audio_path), 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                return frames / rate
        else:
            file_size = os.path.getsize(audio_path)
            estimated_bitrate = 160000
            return max((file_size * 8) / estimated_bitrate, 0.5)
    except Exception as e:
        print(f"获取音频时长失败: {e}，使用默认值 5 秒")
        return 5.0


def play_audio_with_system_player(audio_path, timeout=30):
    """使用 Windows 系统播放器播放音频文件，自动等待播放完成"""
    audio_path = Path(audio_path)

    if not audio_path.exists():
        print(f"音频文件不存在: {audio_path}")
        return False

    if winsound:
        try:
            duration = get_audio_duration(audio_path)
            print(f"使用 winsound 播放 (预期时长: {duration:.2f}秒)")
            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
            return True
        except Exception as e:
            print(f"winsound 播放失败: {e}，尝试备选方案...")

    try:
        duration = get_audio_duration(audio_path)
        print(f"使用 PowerShell 播放 (预期时长: {duration:.2f}秒)")
        ps_command = (
            f"$player = New-Object System.Media.SoundPlayer; "
            f"$player.SoundLocation = '{audio_path}'; "
            f"$player.PlaySync()"
        )
        process = subprocess.Popen(
            ["powershell", "-Command", ps_command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        actual_wait = min(duration + 1, timeout)
        try:
            process.wait(timeout=actual_wait)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        print("PowerShell 播放完成")
        return True
    except Exception as e:
        print(f"PowerShell 播放失败: {e}，尝试备选方案...")

    if HAS_SIMPLEAUDIO:
        try:
            if audio_path.suffix.lower() == '.wav':
                wave_obj = sa.WaveObject.from_wave_file(str(audio_path))
                play_obj = wave_obj.play()
                duration = get_audio_duration(audio_path)
                actual_wait = min(duration + 0.5, timeout)
                play_obj.wait_done(timeout=actual_wait)
                print(f"simpleaudio 播放完成 (耗时: {actual_wait:.2f}秒)")
                return True
        except Exception as e:
            print(f"simpleaudio 播放失败: {e}")

    print("所有播放方案都失败，音频未能播放")
    return False

"""命令行演示：GPT-SoVITS 句级合成（低延迟对话链路）。

用法:
    python scripts/tts_demo.py --character 明日香 --text "你好呀。今天天气真不错！我们出去玩吧？"

说明:
    - 先打印切句结果，再逐句调用 SentencePipeline 合成；
    - 打印每句耗时与最终文件路径；
    - 文本不传时从 stdin 读取。
"""

import argparse
import sys
import time
from pathlib import Path

# 将项目根目录加入 sys.path，保证可 import core.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.character_profile import CharacterProfile
from core.speech_synthesizer import SpeechSynthesizer
from core.tts.sentence_splitter import split_sentences
from core.tts.cache import TTSCache
from core.tts.pipeline import SentencePipeline

# 默认单句最大长度
DEFAULT_MAX_LEN = 30


def main():
    parser = argparse.ArgumentParser(description="GPT-SoVITS 句级 TTS 合成演示")
    parser.add_argument(
        "--character", required=True,
        help="角色名（character_database.json 中的键）",
    )
    parser.add_argument(
        "--text", default="",
        help="待合成的文本；不传则从 stdin 读取",
    )
    parser.add_argument(
        "--max-len", type=int, default=DEFAULT_MAX_LEN,
        help=f"单句最大长度（默认 {DEFAULT_MAX_LEN}）",
    )
    parser.add_argument(
        "--use-cache", action="store_true",
        help="启用磁盘缓存（data/tts_cache）",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="禁用磁盘缓存",
    )
    args = parser.parse_args()

    text = args.text.strip()
    if not text:
        print("请输入文本（Ctrl+Z 结束输入）：", end="", flush=True)
        text = sys.stdin.read().strip()
    if not text:
        print("文本为空，退出。")
        return

    # 0) 切句预览
    sentences = split_sentences(text, max_len=args.max_len)
    print(f"\n=== 切句结果（{len(sentences)} 句）===")
    for i, s in enumerate(sentences, start=1):
        print(f"  [{i:02d}] {s}")

    # 1) 初始化组件
    profile = CharacterProfile(args.character)
    tts = SpeechSynthesizer()
    use_cache = args.use_cache and not args.no_cache
    cache = TTSCache() if use_cache else None
    pipeline = SentencePipeline(max_len=args.max_len)

    # 2) 逐句合成（verbose=True 打印每句耗时）
    print(
        f"\n=== 逐句合成（角色: {args.character}, "
        f"缓存: {'开' if use_cache else '关'}）==="
    )
    total_start = time.perf_counter()
    paths = pipeline.synthesize_sequence(
        profile, text,
        tts=tts, cache=cache, verbose=True,
    )
    total_elapsed = time.perf_counter() - total_start

    # 3) 结果汇总
    print(
        f"\n=== 结果（成功 {len(paths)}/{len(sentences)} 句, "
        f"总耗时 {total_elapsed:.2f}s）==="
    )
    for i, p in enumerate(paths, start=1):
        print(f"  [{i:02d}] {p}")


if __name__ == "__main__":
    main()

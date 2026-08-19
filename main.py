# GPT-SoVITS Character Dialogue System
#
# 使用方式:
#   python main.py                           # 交互式选择角色
#   python main.py -c 雷姆                   # 直接指定角色
#   python main.py -c 雷姆 --text-only       # 纯文本模式
#   python main.py -c 雷姆 --load latest     # 加载最近对话
#   python main.py --list-characters         # 列出所有角色

import argparse
import re
import sys

import speech_recognition as sr

from core.config import CONFIG, CHARACTER_DB
from core.rag_manager import RagManager
from core.character_system import AdvancedCharacterSystem


def parse_args():
    parser = argparse.ArgumentParser(
        description="GPT-SoVITS 角色对话系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py                             交互模式
  python main.py -c 雷姆                     直接与雷姆对话
  python main.py -c 雷姆 --text-only         纯文本模式（不合成语音）
  python main.py -l                          列出可用角色
  python main.py -c 雷姆 --load latest       加载最近一次对话
        """,
    )
    parser.add_argument("-c", "--character", help="角色名称（跳过选择）")
    parser.add_argument("-l", "--list-characters", action="store_true", help="列出所有角色后退出")
    parser.add_argument("--text-only", action="store_true", help="禁用语音合成")
    parser.add_argument("--load", nargs="?", const="latest", help="加载历史对话 (latest / 文件路径)")
    return parser.parse_args()


def select_character() -> str:
    char_list = list(CHARACTER_DB.keys())
    if len(char_list) == 1:
        return char_list[0]
    print("请选择对话角色:")
    for i, char in enumerate(char_list, 1):
        print(f"  {i}. {char} ({CHARACTER_DB[char]['source']})")
    while True:
        try:
            choice = int(input("输入角色编号: ")) - 1
            if 0 <= choice < len(char_list):
                return char_list[choice]
        except ValueError:
            pass
        print("输入无效，请重试")


def voice_input(recognizer, microphone) -> str | None:
    print("\n请说话（5秒内）...", end="", flush=True)
    try:
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source)
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
        return recognizer.recognize_google(audio, language="zh-CN")
    except sr.WaitTimeoutError:
        print("\n未检测到语音输入，请重试")
    except sr.UnknownValueError:
        print("\n无法识别语音，请重试")
    except Exception as e:
        print(f"\n语音识别错误: {e}")
    return None


def main():
    args = parse_args()

    if args.list_characters:
        print("可用角色:")
        for name, data in CHARACTER_DB.items():
            print(f"  {name} — {data['source']}")
            print(f"    性格: {data['personality']}")
            print(f"    风格: {data['style']}")
        return

    # 初始化
    print("正在初始化...", end="", flush=True)
    rag = RagManager()
    rag.build_all()
    print(" ✓")

    # 选择/指定角色
    character_name = args.character or select_character()

    print(f"\n正在接通 {character_name} 系统...")
    system = AdvancedCharacterSystem(character_name, rag)

    # 处理 --load
    if args.load:
        if args.load == "latest":
            saved = AdvancedCharacterSystem.list_saved_conversations(character_name)
            if saved:
                system.load_conversation(saved[0])
            else:
                print("没有找到历史对话，开始新对话")
        else:
            system.load_conversation(args.load)

    # 处理 --text-only
    if args.text_only:
        system.disable_tts()
        print("[纯文本模式]")

    print(f"\n你正在与 [{character_name}] 对话 (输入'退出'结束)")
    print(f"角色背景: {system.profile.backstory[:100]}...")
    print("=" * 60)

    # 输入方式选择（非 text-only 时询问）
    input_mode = "text"
    if not args.text_only:
        print("\n输入方式: [1] 文本  [2] 语音")
        input_mode = "voice" if input("选择 (默认1): ").strip() == "2" else "text"

    recognizer = sr.Recognizer()
    microphone = sr.Microphone() if input_mode == "voice" else None

    while True:
        try:
            if input_mode == "voice":
                result = voice_input(recognizer, microphone)
                if result is None:
                    continue
                user_input = result
                print(f"识别结果: {user_input}")
            else:
                user_input = input("\n晴天好心情: ")

            if user_input.lower() in ["退出", "exit", "quit"]:
                print("对话已结束，期待下次再见！")
                if CONFIG["conversation"]["auto_save"]:
                    system.save_conversation()
                break

            print(f"[关系等级: {system.relationship_level}/10]")
            print(f"\n{character_name}: ", end="", flush=True)

            text_response = system.generate_response(user_input)

            if system.tts_enabled:
                print(" [合成中...]", end="", flush=True)
                clean_text = re.sub(r'\([^)]*\)', '', text_response)
                success = system.synthesize_speech(clean_text)
                if not success:
                    print("[语音合成失败，已切换为纯文本模式]")
                    system.disable_tts()
            print()

        except KeyboardInterrupt:
            print("\n\n对话中断，是否退出？(y/n): ", end="")
            if input().lower() == "y":
                if CONFIG["conversation"]["auto_save"]:
                    system.save_conversation()
                break
        except Exception as e:
            print(f"\n[对话异常: {e}]")
            continue


if __name__ == "__main__":
    main()

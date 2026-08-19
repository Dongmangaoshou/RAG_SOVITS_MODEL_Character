import re
import time
import speech_recognition as sr

from core.config import CONFIG, CHARACTER_DB
from core.rag_manager import RagManager
from core.character_system import AdvancedCharacterSystem

# ============================================================
# 性能优化建议（根据计时结果选择）:
#   LLM 慢 → config.yaml 中改 model 为 deepseek-chat (V3更快)
#          → 或降低 temperature 到 0.5 (减少随机采样)
#   TTS 慢 → config.yaml 中改 enabled: false 先纯文本测试
#          → 或缩短回复文本长度
#   启动慢 → 注释掉 rag.build_all() 跳过 420MB 嵌入模型加载
# ============================================================


def character_dialogue_system():
    # 初始化 RAG
    rag = RagManager()
    rag.build_all()

    # 选角色
    print("请选择对话角色:")
    char_list = list(CHARACTER_DB.keys())
    for i, char in enumerate(char_list, 1):
        print(f"{i}. {char} ({CHARACTER_DB[char]['source']})")

    choice = int(input("输入角色编号: ")) - 1
    character_name = char_list[choice]

    print(f"\n正在接通 {character_name} 系统...")
    system = AdvancedCharacterSystem(character_name, rag)

    # 历史对话恢复
    saved = AdvancedCharacterSystem.list_saved_conversations(character_name)
    if saved:
        print(f"\n发现 {len(saved)} 个历史对话:")
        print("0. 开始新对话")
        for i, fpath in enumerate(saved[:5], 1):
            print(f"{i}. {fpath.stem}")
        load_choice = input("输入编号加载历史对话 (默认0): ") or "0"
        if load_choice != "0":
            try:
                idx = int(load_choice) - 1
                system.load_conversation(saved[idx])
            except (ValueError, IndexError):
                print("无效选择，开始新对话")

    print(f"\n你正在与 [{character_name}] 对话 (输入'退出'结束)")
    print(f"角色背景: {system.profile.backstory[:100]}...")
    print("=" * 60)

    # 输入方式
    print("\n请选择输入方式:")
    print("1. 文本输入")
    print("2. 语音输入")
    input_choice = input("输入选项编号 (默认为1): ") or "1"

    recognizer = sr.Recognizer()
    microphone = sr.Microphone()

    while True:
        try:
            if input_choice == "2":
                print("\n请说话（5秒内）...", end="", flush=True)
                try:
                    with microphone as source:
                        recognizer.adjust_for_ambient_noise(source)
                        audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
                    user_input = recognizer.recognize_google(audio, language="zh-CN")
                    print(f"\n识别结果: {user_input}")
                except sr.WaitTimeoutError:
                    print("\n未检测到语音输入，请重试")
                    continue
                except sr.UnknownValueError:
                    print("\n无法识别语音，请重试")
                    continue
                except Exception as e:
                    print(f"\n语音识别错误: {str(e)}")
                    continue
            else:
                user_input = input("\n晴天好心情: ")

            if user_input.lower() in ["退出", "exit", "quit"]:
                print("对话已结束，期待下次再见！")
                if CONFIG["conversation"]["auto_save"]:
                    system.save_conversation()
                break

            print(f"[关系等级: {system.relationship_level}/10]")
            print(f"\n{character_name}: ", end="", flush=True)

            # --- 计时: LLM 生成 ---
            t0 = time.time()
            text_response = system.generate_response(user_input)
            t_llm = time.time() - t0
            print(f"  [{t_llm:.1f}s LLM]", end="", flush=True)

            if system.tts_enabled:
                t1 = time.time()
                clean_text = re.sub(r'\([^)]*\)', '', text_response)
                success = system.synthesize_speech(clean_text)
                t_tts = time.time() - t1
                tag = "✓" if success else "✗"
                print(f" [{t_tts:.1f}s TTS {tag}]", end="", flush=True)
                if not success:
                    print("[语音合成失败，已切换为纯文本模式]")
                    system.disable_tts()
            print(f" [总计 {time.time()-t0:.1f}s]")

        except Exception as e:
            print(f"\n[对话异常: {e}]")
            continue


if __name__ == "__main__":
    character_dialogue_system()

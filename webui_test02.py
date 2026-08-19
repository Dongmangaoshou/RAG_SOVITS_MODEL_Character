"""
GPT-SoVITS Character Dialogue — WebUI (精简版)
基于 test02.py 的 Web 端实现
启动: python webui_test02.py
"""

import os
import re
import speech_recognition as sr

os.environ.setdefault("no_proxy", "localhost,127.0.0.1,::1")
os.environ.setdefault("GRADIO_SERVER_NAME", "127.0.0.1")

import gradio as gr

from core.config import CONFIG, CHARACTER_DB
from core.rag_manager import RagManager
from core.character_system import AdvancedCharacterSystem

rag = RagManager()
rag.build_all()
_system: AdvancedCharacterSystem | None = None


def select_character(name: str):
    global _system
    if not name:
        return "", [], gr.update()
    _system = AdvancedCharacterSystem(name, rag)
    p = _system.profile
    info = f"**{p.name}**  |  {p.source}\n\n{p.personality}\n\n> {p.backstory[:120]}..."
    return info, [], gr.update(choices=refresh_saved_list(name))


def chat(message: str, history: list):
    global _system
    if not _system or not message.strip():
        yield history, ""
        return
    history = (history or []) + [{"role": "user", "content": message}]
    yield history, "生成中..."
    try:
        for partial_text, _, status in _system.generate_response_stream(message):
            updated = list(history)
            for i in range(len(updated) - 1, -1, -1):
                if updated[i]["role"] == "assistant":
                    updated[i]["content"] = partial_text
                    break
            else:
                updated.append({"role": "assistant", "content": partial_text})
            yield updated, status or ""
    except Exception as e:
        history.append({"role": "assistant", "content": f"错误: {e}"})
        yield history, ""


def voice_chat(audio_path, history: list):
    if not audio_path:
        yield history, ""
        return
    r = sr.Recognizer()
    try:
        with sr.AudioFile(audio_path) as source:
            audio = r.record(source)
        text = r.recognize_google(audio, language="zh-CN")
        yield from chat(text, history)
    except Exception as e:
        history = (history or []) + [{"role": "assistant", "content": f"语音识别失败: {e}"}]
        yield history, ""


def clear_chat():
    global _system
    if _system:
        _system.memory.memory.clear()
        _system.relationship.level = 0
    return [], ""


def save_chat():
    global _system
    if _system:
        path = _system.save_conversation()
        return f"已保存: {os.path.basename(path)}"
    return "无对话可保存"


def load_chat(file):
    global _system
    if _system and file:
        _system.load_conversation(file.name)
        return f"已加载"
    return "加载失败"


def load_saved(filename: str):
    global _system
    if not filename or not _system:
        return [], "请先选择角色"
    try:
        _system.load_conversation(filename)
        return [], f"已加载: {os.path.basename(filename)}"
    except Exception as e:
        return [], f"加载失败: {e}"


def refresh_saved_list(name: str = None):
    if name:
        files = AdvancedCharacterSystem.list_saved_conversations(name)
    elif _system:
        files = AdvancedCharacterSystem.list_saved_conversations(_system.character_name)
    else:
        files = []
    return [str(f) for f in files]


def build_ui():
    char_names = list(CHARACTER_DB.keys())

    with gr.Blocks(title="GPT-SoVITS Character Dialogue") as ui:
        gr.Markdown("# GPT-SoVITS Character Dialogue")

        with gr.Row():
            with gr.Column(scale=1, min_width=240):
                gr.Markdown("### 角色")
                char_dd = gr.Dropdown(
                    choices=char_names, label="选择角色",
                    value=char_names[0] if char_names else None,
                )
                char_info = gr.Markdown("选择角色后显示详情...")

                gr.Markdown("### 输入方式")
                input_mode = gr.Radio(
                    choices=["文本", "语音"], label="模式",
                    value="文本",
                )

                gr.Markdown("### 历史对话")
                saved_dd = gr.Dropdown(choices=[], label="已保存对话")
                with gr.Row():
                    load_btn = gr.Button("加载", size="sm")
                    refresh_btn = gr.Button("刷新", size="sm")

                gr.Markdown("### 操作")
                with gr.Row():
                    save_btn = gr.Button("保存", size="sm")
                    clear_btn = gr.Button("清空", size="sm")
                load_file = gr.File(label="导入 (.json)", file_types=[".json"])
                status = gr.Textbox(label="状态")

            with gr.Column(scale=3):
                chatbot = gr.Chatbot(value=[], label="对话", height=500, type="messages")
                with gr.Row():
                    text_input = gr.Textbox(
                        placeholder="输入消息... (输入'退出'结束对话)",
                        label="", show_label=False, scale=5,
                    )
                    mic_input = gr.Audio(
                        sources=["microphone"], type="filepath",
                        label="", show_label=False, scale=1, visible=False,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)

        # 角色切换
        char_dd.change(
            fn=lambda n: select_character(n),
            inputs=[char_dd],
            outputs=[char_info, chatbot, saved_dd],
        )

        # 输入模式切换
        def toggle(mode):
            return (
                gr.update(visible=(mode == "文本")),
                gr.update(visible=(mode == "语音")),
            )
        input_mode.change(fn=toggle, inputs=[input_mode], outputs=[text_input, mic_input])

        # 发送
        ins = [text_input, chatbot]
        outs = [chatbot, status]
        send_btn.click(fn=chat, inputs=ins, outputs=outs).then(
            lambda: "", None, [text_input]
        )
        text_input.submit(fn=chat, inputs=ins, outputs=outs).then(
            lambda: "", None, [text_input]
        )
        mic_input.stop_recording(fn=voice_chat, inputs=[mic_input, chatbot], outputs=outs)

        # 操作
        clear_btn.click(fn=clear_chat, outputs=[chatbot, status])
        save_btn.click(fn=save_chat, outputs=[status])
        load_file.upload(fn=load_chat, inputs=[load_file], outputs=[status])
        refresh_btn.click(fn=lambda: refresh_saved_list(), outputs=[saved_dd])
        load_btn.click(fn=load_saved, inputs=[saved_dd], outputs=[chatbot, status])

        # 初始化
        if char_names:
            ui.load(
                fn=lambda: select_character(char_names[0]),
                outputs=[char_info, chatbot, saved_dd],
            )

    return ui


if __name__ == "__main__":
    ui = build_ui()
    ui.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        server_port=7861,
        share=True,
        inbrowser=True,
    )

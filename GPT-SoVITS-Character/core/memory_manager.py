import json
import time
from pathlib import Path

from langchain.memory import ConversationBufferWindowMemory
from langchain_core.messages import HumanMessage, AIMessage

from core.config import CONFIG, SCRIPT_DIR


class MemoryManager:
    """对话记忆 —— 窗口管理 + 持久化序列化"""

    def __init__(self, window_size=None):
        k = window_size if window_size is not None else CONFIG["conversation"]["memory_window"]
        self.memory = ConversationBufferWindowMemory(
            memory_key="history",
            input_key="input",
            output_key="output",
            k=k,
        )

    def load_history(self, inputs: dict) -> str:
        """加载当前窗口内的对话历史（用于填入 prompt）"""
        vars_ = self.memory.load_memory_variables(inputs)
        return vars_.get("history", "")

    def save_context(self, user_input: str, response: str):
        """保存一轮对话"""
        self.memory.save_context(
            {"input": user_input},
            {"output": response},
        )

    # -- 持久化 --------------------------------------------------
    def save_to_file(self, character_name, relationship_level,
                     save_dir=None, auto_print=True):
        save_dir = Path(save_dir or SCRIPT_DIR / CONFIG["conversation"]["save_dir"])
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = save_dir / f"{character_name}_{timestamp}.json"
        data = {
            "character_name": character_name,
            "relationship_level": relationship_level,
            "messages": self._serialize_messages(),
            "timestamp": timestamp,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if auto_print:
            print(f"对话已保存: {filepath}")
        return filepath

    def load_from_file(self, filepath) -> int:
        """返回恢复的 relationship_level"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for msg in data.get("messages", []):
            if msg["type"] == "human":
                self.memory.chat_memory.add_user_message(msg["content"])
            elif msg["type"] == "ai":
                self.memory.chat_memory.add_ai_message(msg["content"])
        rel_level = data.get("relationship_level", 0)
        print(f"对话已恢复 ({len(data.get('messages', []))} 条消息, 关系等级 {rel_level})")
        return rel_level

    # -- helpers -------------------------------------------------
    def _serialize_messages(self) -> list[dict]:
        return [
            {"type": "human" if isinstance(m, HumanMessage) else "ai",
             "content": m.content}
            for m in self.memory.chat_memory.messages
        ]

    @property
    def message_count(self) -> int:
        return len(self.memory.chat_memory.messages)


def list_saved_conversations(character_name):
    """列出指定角色已保存的对话"""
    save_dir = SCRIPT_DIR / CONFIG["conversation"]["save_dir"]
    if not save_dir.exists():
        return []
    return sorted(save_dir.glob(f"{character_name}_*.json"), reverse=True)

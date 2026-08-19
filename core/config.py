import json
import os
from dotenv import load_dotenv
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent

load_dotenv(SCRIPT_DIR / ".env")

# --- 默认配置（config.yaml 中的值会覆盖此处）-------------------
_DEFAULTS = {
    "llm": {
        "provider": "deepseek",        # deepseek / openai / ollama
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "temperature": 0.75,
        "max_retries": 3,
        "retry_base_delay": 2,
    },
    "tts": {
        "provider": "sovits",          # sovits / edge-tts / dummy
        "api_url": "http://127.0.0.1:9880",
        "timeout": 60,
        "enabled": True,
    },
    "conversation": {
        "memory_window": 10,
        "save_dir": "conversations",
        "auto_save": True,
    },
    "emotion_keywords": {
        "开心": ["开心", "高兴", "快乐", "兴奋", "愉快", "幸福", "哈哈", "太棒了", "好开心", "真高兴", "太好了", "nice", "耶"],
        "悲伤": ["伤心", "绝望", "难过", "抑郁", "悲伤", "失落", "痛苦", "郁闷", "想哭", "心碎", "哭泣", "泪", "难受", "心累"],
        "愤怒": ["生气", "愤怒", "烦躁", "不爽", "恼火", "气死", "火大", "讨厌", "可恶", "混蛋", "傻逼", "滚"],
        "焦虑": ["焦虑", "紧张", "担心", "害怕", "不安", "忧虑", "恐惧", "忐忑", "惶恐", "慌", "怕", "怎么办"],
    },
    "relationship": {
        "positive_keywords": ["谢谢", "理解", "帮助", "开心", "喜欢"],
        "close_threshold": 5,
    },
    "character_db": "character_database.json",
    # --- V2 新增分区 ------------------------------------------------
    "memory": {
        "sqlite_path": "data/memory.db",
        "event_window": 3,
        "forget_threshold": 0.25,
        "token_budget": 1000,
        "summarize_interval": 5,
    },
    "emotion": {
        "classes": ["喜悦", "平静", "低落", "悲伤", "愤怒", "焦虑", "疲惫", "兴奋"],
        "decay_rate": 0.85,
        "min_intensity": 0.2,
        "audio_score": {"emotion": 0.5, "rotation": 0.3, "intimacy": 0.2},
    },
    "latency": {
        "sentence_max_len": 30,
        "tts_timeout": 8,
        "enable_audio_cache": True,
        "cache_dir": "data/tts_cache",
        "cache_max_entries": 1000,
        "default_character": "明日香",
        "host": "127.0.0.1",
        "port": 8000,
    },
    "pet": {
        "ws_port": 8765,
        "transparent": True,
        "always_on_top": True,
    },
}


def _deep_merge(base, override):
    """递归合并字典，override 中的值覆盖 base"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml_config(path: Path) -> dict:
    """尝试加载 YAML 配置文件，失败则返回空字典"""
    try:
        import yaml
    except ImportError:
        return {}
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG = _deep_merge(_DEFAULTS, _load_yaml_config(SCRIPT_DIR / "config.yaml"))

# --- 角色数据库 ------------------------------------------------
_db_path = SCRIPT_DIR / CONFIG.get("character_db", "character_database.json")
with open(_db_path, "r", encoding="utf-8") as f:
    CHARACTER_DB = json.load(f)

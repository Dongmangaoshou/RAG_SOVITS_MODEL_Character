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
        "model": "deepseek-v4-pro",
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
        "depressed": ["伤心", "绝望", "难过", "抑郁"],
        "angry":    ["生气", "愤怒", "烦躁", "不爽"],
        "anxious":  ["焦虑", "紧张", "担心", "害怕"],
    },
    "relationship": {
        "positive_keywords": ["谢谢", "理解", "帮助", "开心", "喜欢"],
        "close_threshold": 5,
    },
    "character_db": "character_database.json",
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

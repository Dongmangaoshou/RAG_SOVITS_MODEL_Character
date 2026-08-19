"""LRU 磁盘缓存 —— 低延迟对话链路第二环：以 (角色, 情感, 文本) 为键缓存合成音频。

实现说明：
- 缓存键 = md5("character|emotion|text").hexdigest()；
- 用文件的 mtime 模拟 LRU：命中时刷新 mtime，超过 max_entries 时删除最旧文件；
- 线程安全（内部持锁），get / put / clear 均可并发调用。

存储目录：data/tts_cache（可由 CONFIG["latency"]["cache_dir"] 覆盖）。
"""

import hashlib
import os
import shutil
import threading
from pathlib import Path

from core.config import CONFIG, SCRIPT_DIR

# 默认缓存根目录（项目根 data/tts_cache）
DEFAULT_CACHE_DIR = SCRIPT_DIR / "data" / "tts_cache"
# 默认最大缓存条目数
DEFAULT_MAX_ENTRIES = 1000
# 缓存文件后缀
_FILE_SUFFIX = ".wav"
# 键分隔符
_KEY_SEP = "|"


class TTSCache:
    """LRU 磁盘缓存。构造时自动创建缓存目录。"""

    def __init__(self, cache_dir=None, max_entries: int = DEFAULT_MAX_ENTRIES):
        # 兼容 CONFIG["latency"] 分区（可后补）：优先取配置值
        latency_cfg = CONFIG.get("latency", {})
        self.cache_dir = Path(
            cache_dir
            or latency_cfg.get("cache_dir")
            or DEFAULT_CACHE_DIR
        )
        self.max_entries = int(
            max_entries
            if max_entries is not None
            else latency_cfg.get("cache_max_entries", DEFAULT_MAX_ENTRIES)
        )
        self._lock = threading.Lock()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- 键与路径 ------------------------------------------------
    @staticmethod
    def _key(character: str, emotion: str, text: str) -> str:
        """缓存键：md5(character|emotion|text)"""
        raw = _KEY_SEP.join((character, emotion, text))
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}{_FILE_SUFFIX}"

    # -- 对外接口 ------------------------------------------------
    def get(self, character: str, emotion: str, text: str) -> str | None:
        """命中返回缓存 wav 路径并刷新 mtime（LRU 保活）；未命中返回 None"""
        with self._lock:
            p = self._path_for(self._key(character, emotion, text))
            if p.exists():
                try:
                    # 刷新访问时间 → 该文件成为最新，LRU 淘汰时优先保活
                    os.utime(p, None)
                except OSError:
                    pass
                return str(p)
            return None

    def put(self, character: str, emotion: str, text: str, wav_path) -> str:
        """把 wav_path 复制进缓存；超容量时按 mtime 淘汰最旧文件。返回缓存内路径。"""
        with self._lock:
            target = self._path_for(self._key(character, emotion, text))
            src = Path(wav_path)
            if src.exists():
                if src.resolve() != target.resolve():
                    shutil.copy2(str(src), str(target))
            elif not target.exists():
                raise FileNotFoundError(f"源音频不存在: {src}")
            self._evict_if_needed()
            return str(target)

    def clear(self):
        """清空缓存目录下全部缓存文件"""
        with self._lock:
            for p in self.cache_dir.glob(f"*{_FILE_SUFFIX}"):
                try:
                    p.unlink()
                except OSError:
                    pass

    # -- 内部 ----------------------------------------------------
    def _evict_if_needed(self):
        """按 mtime 升序删除最旧文件，直到条目数不超过 max_entries"""
        if self.max_entries <= 0:
            return  # 0 或负数表示不限容量
        files = sorted(
            (p for p in self.cache_dir.glob(f"*{_FILE_SUFFIX}") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        while len(files) > self.max_entries:
            oldest = files[0]
            try:
                oldest.unlink()
            except OSError:
                pass
            files = files[1:]

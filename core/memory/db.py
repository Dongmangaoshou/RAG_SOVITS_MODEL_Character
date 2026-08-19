"""记忆数据库连接管理 —— 轻量 SQLite 封装，线程安全"""
import sqlite3
import threading
from pathlib import Path

from core.config import SCRIPT_DIR, CONFIG

_lock = threading.Lock()


def get_db_path() -> Path:
    """返回记忆库路径（config.memory.sqlite_path 或默认 data/memory.db）"""
    cfg_path = CONFIG.get("memory", {}).get("sqlite_path", "data/memory.db")
    p = Path(cfg_path)
    if not p.is_absolute():
        p = SCRIPT_DIR / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _init_schema(conn: sqlite3.Connection):
    schema = Path(__file__).parent / "schema.sql"
    conn.executescript(schema.read_text(encoding="utf-8"))
    conn.commit()


def get_connection() -> sqlite3.Connection:
    """获取带行工厂的 SQLite 连接（调用方负责 close）"""
    conn = sqlite3.connect(str(get_db_path()), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库 schema（幂等）"""
    with _lock:
        conn = get_connection()
        try:
            _init_schema(conn)
        finally:
            conn.close()


def execute(sql: str, params: tuple = ()) -> int:
    """执行写操作，返回 lastrowid；自动加锁防并发"""
    with _lock:
        conn = get_connection()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    """查询多行，返回 dict 列表"""
    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """查询单行"""
    conn = get_connection()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

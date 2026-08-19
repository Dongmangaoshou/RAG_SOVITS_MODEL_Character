-- GPT-SoVITS Character V2 · Memory Schema
-- 三层记忆：events(情景) + profile(画像) + relationship(关系) + summaries(摘要)

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    character     TEXT    NOT NULL,             -- 角色名
    event_type    TEXT    NOT NULL,             -- fact/preference/emotion/promise/chat
    text          TEXT    NOT NULL,             -- 事件内容
    importance    REAL    DEFAULT 0.5,          -- 0-1
    emotion_tag   TEXT    DEFAULT '',           -- 关联情感标签（Phase 2 回填）
    created_at    TEXT    DEFAULT (datetime('now','localtime')),
    last_access   TEXT    DEFAULT (datetime('now','localtime')),
    access_count  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_character ON events(character);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

CREATE TABLE IF NOT EXISTS profile (
    character         TEXT PRIMARY KEY,
    preferences       TEXT DEFAULT '[]',        -- JSON 数组
    avoid_topics      TEXT DEFAULT '[]',
    personality_notes TEXT DEFAULT '[]',
    concerns          TEXT DEFAULT '[]',
    updated_at        TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS relationship (
    character   TEXT PRIMARY KEY,
    affinity    INTEGER DEFAULT 0,              -- 好感 0-100
    trust       INTEGER DEFAULT 0,              -- 信任 0-100
    familiarity INTEGER DEFAULT 0,              -- 熟悉 0-100
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS summaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    character    TEXT NOT NULL,
    session_id   TEXT NOT NULL,                 -- 会话标识
    summary_text TEXT NOT NULL,
    last_msg_idx INTEGER DEFAULT 0,             -- 已覆盖的消息序号
    updated_at   TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_summaries_char ON summaries(character);

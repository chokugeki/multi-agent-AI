-- =============================================================================
-- Sato Clone Organization - Knowledge Brain Schema
-- SQLite3ベースの長期記憶システム
-- =============================================================================

-- 知識テーブル: クローンの長期記憶
CREATE TABLE IF NOT EXISTS knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    body        BLOB,
    source      TEXT DEFAULT 'conversation',
    relevance   REAL DEFAULT 1.0,
    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT DEFAULT (datetime('now', 'localtime')),
    expires_at  TEXT
);

-- タグテーブル
CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

-- 知識-タグ紐付け（多対多）
CREATE TABLE IF NOT EXISTS knowledge_tags (
    knowledge_id INTEGER REFERENCES knowledge(id) ON DELETE CASCADE,
    tag_id       INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (knowledge_id, tag_id)
);

-- 参照ログ: 知識がいつ使われたかを記録（淘汰判定に使用）
CREATE TABLE IF NOT EXISTS relevance_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id INTEGER REFERENCES knowledge(id) ON DELETE CASCADE,
    accessed_at  TEXT DEFAULT (datetime('now', 'localtime')),
    context      TEXT
);

-- 全文検索インデックス（FTS5）
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title, summary, content=knowledge, content_rowid=id
);

-- FTS同期トリガー: INSERT
CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, title, summary)
    VALUES (new.id, new.title, new.summary);
END;

-- FTS同期トリガー: DELETE
CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, summary)
    VALUES ('delete', old.id, old.title, old.summary);
END;

-- FTS同期トリガー: UPDATE
CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, summary)
    VALUES ('delete', old.id, old.title, old.summary);
    INSERT INTO knowledge_fts(rowid, title, summary)
    VALUES (new.id, new.title, new.summary);
END;

-- 興味テーブル: 質問から学習した関心トピック（パトロール拡張用）
CREATE TABLE IF NOT EXISTS interests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT UNIQUE NOT NULL,
    asked_count INTEGER DEFAULT 1,
    first_asked TEXT DEFAULT (datetime('now', 'localtime')),
    last_asked  TEXT DEFAULT (datetime('now', 'localtime'))
);

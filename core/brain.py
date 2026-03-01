#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sato Clone Organization - Knowledge Brain
SQLite3ベースの長期記憶システム。
知識の保存・検索・淘汰を担当し、オーケストレーターとパトロールの両方から使用される。
"""

import sqlite3
import gzip
import os
import re
import glob
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 定数
# ==============================================================================

_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(_DIR, "brain_schema.sql")
DEFAULT_DB_PATH = os.path.join(_DIR, "..", "brain.db")
MEMORY_DIR = os.path.join(_DIR, "..", "data", "memory")

# 淘汰パラメータ
DECAY_DAYS = 30          # この日数アクセスがなければ淘汰候補
DECAY_THRESHOLD = 0.3    # この関連度以下を淘汰
PROTECTED_TAGS = {"backbone", "profile", "permanent"}  # 淘汰対象外のタグ


def _sanitize(text: str) -> str:
    """UTF-8サロゲート文字を除去する（UnicodeEncodeError防止）"""
    if not text:
        return text
    return text.encode('utf-8', errors='replace').decode('utf-8')


# ==============================================================================
# DB接続管理
# ==============================================================================

def get_connection(db_path: str = None) -> sqlite3.Connection:
    """SQLite3接続を取得する（WALモード有効）"""
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    # サロゲート文字を含むデータを安全に読み取る
    conn.text_factory = lambda b: b.decode('utf-8', errors='replace')
    return conn


def init_db(db_path: str = None) -> sqlite3.Connection:
    """スキーマを適用してDBを初期化する"""
    conn = get_connection(db_path)
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


# ==============================================================================
# 書き込み
# ==============================================================================

def store(conn: sqlite3.Connection,
          title: str,
          summary: str,
          body: str = "",
          tags: list[str] = None,
          source: str = "conversation",
          relevance: float = 1.0,
          expires_at: str = None) -> int:
    """
    知識を脳に保存する。bodyはgzip圧縮される。
    
    Returns:
        保存された知識のID
    """
    # 入力をサニタイズ
    title = _sanitize(title)
    summary = _sanitize(summary)
    body = _sanitize(body)
    # 本文をgzip圧縮
    compressed_body = gzip.compress(body.encode("utf-8")) if body else None
    
    cur = conn.execute(
        """INSERT INTO knowledge (title, summary, body, source, relevance, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (title, summary, compressed_body, source, relevance, expires_at)
    )
    knowledge_id = cur.lastrowid
    
    # タグの紐付け
    if tags:
        for tag_name in tags:
            tag_name = tag_name.strip().lower()
            if not tag_name:
                continue
            # UPSERT: 既存タグがあればそのIDを使う
            conn.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,)
            )
            tag_row = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (tag_name,)
            ).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_tags (knowledge_id, tag_id) VALUES (?, ?)",
                (knowledge_id, tag_row["id"])
            )
    
    conn.commit()
    return knowledge_id


def get_body(conn: sqlite3.Connection, knowledge_id: int) -> str:
    """圧縮されたbodyを展開して返す"""
    row = conn.execute(
        "SELECT body FROM knowledge WHERE id = ?", (knowledge_id,)
    ).fetchone()
    if row and row["body"]:
        return gzip.decompress(row["body"]).decode("utf-8")
    return ""


# ==============================================================================
# 検索
# ==============================================================================

def search(conn: sqlite3.Connection,
           query: str,
           limit: int = 5,
           tags_filter: list[str] = None) -> list[dict]:
    """
    知識を検索する。LIKE検索を主戦略とする（FTS5は日本語トークン化非対応のため）。
    タグフィルタが指定された場合はAND条件で絞り込む。
    """
    # クエリをトークンに分割（日本語の助詞でも分割）
    tokens = re.split(r'[\s、。,.\-/]+', query)
    # 日本語の助詞・接続詞でさらに分割
    expanded = []
    for t in tokens:
        parts = re.split(r'(について|から|まで|として|に対して|にとって|のため|による|を|が|は|の|に|で|と|も|へ|より)', t)
        expanded.extend(parts)
    # ASCII/数字の連続部分を独立トークンとして抽出
    ascii_tokens = re.findall(r'[A-Za-z0-9]{2,}', query)
    expanded.extend(ascii_tokens)
    # 重複除去・2文字未満除外
    seen = set()
    tokens = []
    for t in expanded:
        t = t.strip()
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            tokens.append(t)
    
    if not tokens:
        # トークンがない場合は最新のものを返す
        rows = conn.execute(
            """SELECT id, title, summary, source, relevance, created_at
               FROM knowledge ORDER BY updated_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    
    # LIKE検索: 各トークンがtitleまたはsummaryに含まれるか（OR結合）
    like_clauses = " OR ".join(
        "(title LIKE ? OR summary LIKE ?)" for _ in tokens
    )
    like_params = []
    for t in tokens:
        like_params.extend([f"%{t}%", f"%{t}%"])
    
    if tags_filter:
        placeholders = ",".join("?" for _ in tags_filter)
        rows = conn.execute(
            f"""SELECT DISTINCT k.id, k.title, k.summary, k.source, k.relevance, k.created_at
                FROM knowledge k
                JOIN knowledge_tags kt ON kt.knowledge_id = k.id
                JOIN tags t ON t.id = kt.tag_id
                WHERE ({like_clauses})
                  AND t.name IN ({placeholders})
                ORDER BY k.relevance DESC, k.updated_at DESC
                LIMIT ?""",
            (*like_params, *tags_filter, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT id, title, summary, source, relevance, created_at
                FROM knowledge
                WHERE {like_clauses}
                ORDER BY relevance DESC, updated_at DESC
                LIMIT ?""",
            (*like_params, limit)
        ).fetchall()
    
    return [dict(r) for r in rows]


def get_context_for(query: str, db_path: str = None, limit: int = 5) -> str:
    """
    オーケストレーターが呼ぶメイン関数。
    クエリに関連する知識を検索し、500字以内のサマリー文字列を返す。
    該当する知識のアクセスログも記録する。
    """
    conn = get_connection(db_path)
    try:
        results = search(conn, query, limit=limit)
        
        if not results:
            return "関連する過去の文脈は見つかりませんでした。"
        
        # アクセスログを記録
        for r in results:
            record_access(conn, r["id"], query)
        
        # サマリーを構築（500字以内）
        lines = []
        char_count = 0
        for r in results:
            entry = f"- **{r['title']}**: {r['summary']}"
            if char_count + len(entry) > 480:
                lines.append("- ...(他の関連知識あり)")
                break
            lines.append(entry)
            char_count += len(entry)
        
        return "\n".join(lines)
    finally:
        conn.close()

def check_brain_cache(conn: sqlite3.Connection, query: str) -> str | None:
    """
    ユーザーの入力(query)に対する「完全に一致する過去の質問の回答」を検索し、
    キャッシュヒットすれば回答文字列を返す。ヒットしなければNoneを返す。
    """
    # bodyはgzip圧縮されているためSQLのLIKE検索が効かない。
    # 代わりにtitle（先頭50文字）で検索し、Python側で解凍して完全一致を確認する。
    short_query = query[:50]
    title_deep = f"考察: {short_query}…" if len(query) > 50 else f"考察: {short_query}"
    title_ga = f"雑談: {short_query}…" if len(query) > 50 else f"雑談: {short_query}"
    
    rows = conn.execute(
        """
        SELECT source, body FROM knowledge
        WHERE source IN ('deep_reasoning', 'ga_chat')
          AND (title = ? OR title = ?)
        ORDER BY created_at DESC LIMIT 5
        """,
        (title_deep, title_ga)
    ).fetchall()
    
    for row in rows:
        if not row["body"]:
            continue
            
        body_text = ""
        try:
            # BLOB (gzip) か str かを判定してデコード
            if isinstance(row["body"], bytes):
                body_text = gzip.decompress(row["body"]).decode("utf-8")
            else:
                body_text = row["body"]
        except Exception:
            continue
            
        source = row["source"]
        # bodyが対象のqueryを含んでいるか厳密チェック
        if source == "deep_reasoning" and body_text.startswith(f"質問: {query} 知識:"):
            if " 考察: " in body_text:
                return body_text.split(" 考察: ", 1)[1]
        elif source == "ga_chat" and body_text.startswith(f"質問: {query} 回答:"):
            if " 回答: " in body_text:
                return body_text.split(" 回答: ", 1)[1]
                
    return None

# ==============================================================================
# ビジネスアイデア収集 (フェーズ11拡張)
# ==============================================================================

def get_biz_idea_categories(conn: sqlite3.Connection) -> list[dict]:
    """
    biz_ideaタグを持つ知識の、category:*タグによる分類と件数を取得する
    戻り値: [{"category": "HR", "count": 2}, ...]
    """
    rows = conn.execute(
        """
        SELECT t.name as category, COUNT(DISTINCT k.id) as cnt
        FROM knowledge k
        JOIN knowledge_tags kt_biz ON k.id = kt_biz.knowledge_id
        JOIN tags t_biz ON kt_biz.tag_id = t_biz.id AND t_biz.name = 'biz_idea'
        JOIN knowledge_tags kt_cat ON k.id = kt_cat.knowledge_id
        JOIN tags t ON kt_cat.tag_id = t.id AND t.name LIKE 'category:%'
        GROUP BY t.name
        ORDER BY cnt DESC
        """
    ).fetchall()
    return [{"category": r["category"].replace("category:", ""), "count": r["cnt"]} for r in rows]

def get_biz_ideas_by_category(conn: sqlite3.Connection, category_name: str) -> list[dict]:
    """指定カテゴリのビジネスアイデア一覧（title, summary, body）を取得する"""
    tag_name = f"category:{category_name}"
    rows = conn.execute(
        """
        SELECT k.id, k.title, k.summary, k.body, k.created_at
        FROM knowledge k
        JOIN knowledge_tags kt_biz ON k.id = kt_biz.knowledge_id
        JOIN tags t_biz ON kt_biz.tag_id = t_biz.id AND t_biz.name = 'biz_idea'
        JOIN knowledge_tags kt_cat ON k.id = kt_cat.knowledge_id
        JOIN tags t ON kt_cat.tag_id = t.id AND t.name = ?
        ORDER BY k.created_at DESC
        """, (tag_name,)
    ).fetchall()
    
    ideas = []
    for r in rows:
        body_text = gzip.decompress(r["body"]).decode("utf-8") if r["body"] else ""
        ideas.append({
            "id": r["id"],
            "title": r["title"],
            "summary": r["summary"],
            "body": body_text,
            "created_at": r["created_at"]
        })
    return ideas


# ==============================================================================
# 参照ログ
# ==============================================================================

def record_access(conn: sqlite3.Connection,
                  knowledge_id: int,
                  context: str = ""):
    """知識が参照されたことを記録する"""
    conn.execute(
        "INSERT INTO relevance_log (knowledge_id, context) VALUES (?, ?)",
        (knowledge_id, context)
    )
    # relevanceスコアを微増（最大1.0）
    conn.execute(
        """UPDATE knowledge
           SET relevance = MIN(1.0, relevance + 0.05),
               updated_at = datetime('now', 'localtime')
           WHERE id = ?""",
        (knowledge_id,)
    )
    conn.commit()


# ==============================================================================
# 興味管理
# ==============================================================================

NO_KNOWLEDGE_MSG = "関連する過去の文脈は見つかりませんでした。"


def register_interest(conn: sqlite3.Connection, keywords: list[str]):
    """
    質問から抽出したキーワードを「興味」として登録する。
    既存のキーワードは asked_count を増やし、last_asked を更新する。
    """
    for kw in keywords:
        kw = kw.strip().lower()
        if len(kw) < 2:
            continue
        existing = conn.execute(
            "SELECT id FROM interests WHERE keyword = ?", (kw,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE interests SET asked_count = asked_count + 1,
                   last_asked = datetime('now', 'localtime')
                   WHERE id = ?""",
                (existing["id"],)
            )
        else:
            conn.execute(
                "INSERT INTO interests (keyword) VALUES (?)", (kw,)
            )
    conn.commit()


def get_interests(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """登録された興味一覧を取得する（asked_count降順）"""
    rows = conn.execute(
        """SELECT keyword, asked_count, last_asked FROM interests
           ORDER BY asked_count DESC, last_asked DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_brain_stats(conn: sqlite3.Connection) -> dict:
    """脳（DB）の現在の統計情報を取得する"""
    stats = {}
    try:
        # 知識の総件数
        count_row = conn.execute("SELECT COUNT(*) as cnt FROM knowledge").fetchone()
        stats["total_knowledge"] = count_row["cnt"] if count_row else 0
        
        # タグの種類数
        tag_count_row = conn.execute("SELECT COUNT(*) as cnt FROM tags").fetchone()
        stats["total_tags"] = tag_count_row["cnt"] if tag_count_row else 0
        
        # 最近追加された知識のソース内訳
        source_counts = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM knowledge GROUP BY source"
        ).fetchall()
        stats["sources"] = {r["source"]: r["cnt"] for r in source_counts}
        
        # 最近の興味キーワード
        interests = get_interests(conn, limit=5)
        stats["recent_interests"] = [i["keyword"] for i in interests]
        
        # ファイルサイズ（MB）
        db_path = DEFAULT_DB_PATH
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            stats["db_size_mb"] = round(size_bytes / (1024 * 1024), 2)
        else:
            stats["db_size_mb"] = 0.0
    except Exception as e:
        print(f"Stats Error: {e}")
        stats = {}
        
    return stats

# ==============================================================================
# 知識の淘汰
# ==============================================================================

def decay(conn: sqlite3.Connection) -> list[dict]:
    """
    古く参照されていない知識を淘汰する。
    - DECAY_DAYS日以上参照なし AND relevance < DECAY_THRESHOLD
    - PROTECTED_TAGS（backbone, profile, permanent）タグ付きは対象外
    
    Returns:
        削除された知識のリスト（[{"id": ..., "title": ...}, ...]）
    """
    cutoff = (datetime.now() - timedelta(days=DECAY_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    
    # 淘汰候補を取得（保護タグを持つものを除外）
    candidates = conn.execute(
        """SELECT k.id, k.title, k.relevance, k.source
           FROM knowledge k
           WHERE k.relevance < ?
             AND k.id NOT IN (
                 SELECT rl.knowledge_id FROM relevance_log rl
                 WHERE rl.accessed_at > ?
             )
             AND k.id NOT IN (
                 SELECT kt.knowledge_id FROM knowledge_tags kt
                 JOIN tags t ON t.id = kt.tag_id
                 WHERE t.name IN ({})
             )""".format(",".join("?" for _ in PROTECTED_TAGS)),
        (DECAY_THRESHOLD, cutoff, *PROTECTED_TAGS)
    ).fetchall()
    
    deleted = []
    for c in candidates:
        deleted.append({"id": c["id"], "title": c["title"]})
        conn.execute("DELETE FROM knowledge WHERE id = ?", (c["id"],))
    
    conn.commit()
    return deleted


def decay_all(conn: sqlite3.Connection, factor: float = 0.95):
    """
    全知識のrelevanceを一律に減衰させる（定期実行用）。
    保護タグ付きは減衰しない。
    """
    conn.execute(
        """UPDATE knowledge
           SET relevance = relevance * ?
           WHERE id NOT IN (
               SELECT kt.knowledge_id FROM knowledge_tags kt
               JOIN tags t ON t.id = kt.tag_id
               WHERE t.name IN ({})
           )""".format(",".join("?" for _ in PROTECTED_TAGS)),
        (factor, *PROTECTED_TAGS)
    )
    conn.commit()


# ==============================================================================
# Markdownインポーター
# ==============================================================================

def _infer_tags_from_filename(filename: str) -> list[str]:
    """ファイル名からタグを推定する"""
    name = Path(filename).stem.lower()
    tags = []
    
    # 特別なファイルには保護タグを付与
    if "backbone" in name or "profile" in name:
        tags.append("backbone")
        tags.append("permanent")
    
    # ファイル名のパーツをタグ化
    parts = re.split(r'[_\-\s]+', name)
    for p in parts:
        if len(p) >= 2 and p not in ("md", "research", "results"):
            tags.append(p)
    
    return tags


def _extract_title_and_summary(content: str) -> tuple[str, str]:
    """Markdownの先頭からタイトルと要約を抽出する"""
    lines = content.strip().split("\n")
    title = "無題"
    summary_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and title == "無題":
            title = stripped[2:].strip()
        elif stripped and not stripped.startswith("#") and len(summary_lines) < 3:
            summary_lines.append(stripped)
    
    summary = " ".join(summary_lines)
    if len(summary) > 200:
        summary = summary[:197] + "..."
    if not summary:
        summary = title
    
    return title, summary


def import_markdown(conn: sqlite3.Connection,
                    directory: str = None,
                    force: bool = False) -> list[dict]:
    """
    data/memory/*.md を脳にインポートする。
    既にインポート済み（同タイトル・同ソース）のものはスキップする。
    
    Args:
        force: Trueの場合、既存エントリを上書き
    
    Returns:
        インポートされた知識のリスト
    """
    dir_path = directory or MEMORY_DIR
    imported = []
    
    for md_file in sorted(glob.glob(os.path.join(dir_path, "*.md"))):
        filename = os.path.basename(md_file)
        
        # HEARTBEATは除外
        if filename.upper().startswith("HEARTBEAT"):
            continue
        
        with open(md_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        if not content.strip():
            continue
        
        title, summary = _extract_title_and_summary(content)
        tags = _infer_tags_from_filename(filename)
        
        # 重複チェック
        if not force:
            existing = conn.execute(
                "SELECT id FROM knowledge WHERE title = ? AND source = 'markdown_import'",
                (title,)
            ).fetchone()
            if existing:
                continue
        
        kid = store(
            conn,
            title=title,
            summary=summary,
            body=content,
            tags=tags,
            source="markdown_import",
            relevance=0.8 if "backbone" not in tags else 1.0,
        )
        imported.append({"id": kid, "title": title, "file": filename})
    
    return imported


# ==============================================================================
# 統計
# ==============================================================================

def stats(conn: sqlite3.Connection) -> dict:
    """脳の統計情報を返す"""
    total = conn.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()["c"]
    by_source = conn.execute(
        "SELECT source, COUNT(*) as c FROM knowledge GROUP BY source"
    ).fetchall()
    total_tags = conn.execute("SELECT COUNT(*) as c FROM tags").fetchone()["c"]
    total_accesses = conn.execute(
        "SELECT COUNT(*) as c FROM relevance_log"
    ).fetchone()["c"]
    avg_relevance = conn.execute(
        "SELECT AVG(relevance) as avg FROM knowledge"
    ).fetchone()["avg"] or 0.0
    
    return {
        "total_knowledge": total,
        "by_source": {r["source"]: r["c"] for r in by_source},
        "total_tags": total_tags,
        "total_accesses": total_accesses,
        "avg_relevance": round(avg_relevance, 3),
    }


# ==============================================================================
# CLI エントリポイント
# ==============================================================================

if __name__ == "__main__":
    import sys
    import json
    
    conn = init_db()
    
    if len(sys.argv) < 2:
        print("Usage: brain.py <command> [args]")
        print("Commands:")
        print("  init          - DBを初期化（existing data/memory/*.mdをインポート）")
        print("  search <q>    - 全文検索")
        print("  stats         - 統計情報")
        print("  decay         - 知識の淘汰を実行")
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    if cmd == "init":
        imported = import_markdown(conn)
        print(f"✅ 脳を初期化しました。{len(imported)}件の知識をインポート:")
        for item in imported:
            print(f"   📝 {item['title']} ← {item['file']}")
        st = stats(conn)
        print(f"\n📊 脳の状態: {st['total_knowledge']}件 | タグ: {st['total_tags']}個")
    
    elif cmd == "search":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        results = search(conn, query)
        if results:
            for r in results:
                print(f"  [{r['id']}] {r['title']} (rel={r['relevance']:.2f})")
                print(f"      {r['summary'][:80]}...")
        else:
            print("  (該当なし)")
    
    elif cmd == "stats":
        st = stats(conn)
        print(json.dumps(st, indent=2, ensure_ascii=False))
    
    elif cmd == "decay":
        deleted = decay(conn)
        if deleted:
            print(f"🗑️ {len(deleted)}件を淘汰:")
            for d in deleted:
                print(f"   - {d['title']}")
        else:
            print("淘汰対象はありませんでした。")
    
    else:
        print(f"Unknown command: {cmd}")
    
    conn.close()

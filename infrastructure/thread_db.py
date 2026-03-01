import sqlite3
import os
import json
import logging

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(_DIR, "..", "data", "threads.db")

def get_connection():
    """SQLiteコネクションを取得（外部キーサポート有効）"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """テーブルの初期化"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # threadsテーブルの作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                full_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    except Exception as e:
        logging.error(f"Error initializing thread memory DB: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def save_thread(title: str, summary: str, messages: list) -> bool:
    """
    スレッド情報をDBに保存する。
    messages: [{"role": "user/assistant", "content": "..."}] のリスト
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        full_text_json = json.dumps(messages, ensure_ascii=False)
        
        cursor.execute(
            '''INSERT INTO threads (title, summary, full_text) VALUES (?, ?, ?)''',
            (title, summary, full_text_json)
        )
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Error saving thread: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def get_all_threads(limit: int = 50) -> list:
    """
    保存された全スレッドを新しい順で取得する
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT id, title, summary, full_text, created_at 
               FROM threads 
               ORDER BY created_at DESC 
               LIMIT ?''', 
            (limit,)
        )
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "messages": json.loads(row["full_text"]),
                "created_at": row["created_at"]
            })
        return results
    except Exception as e:
        logging.error(f"Error getting threads: {e}")
        return []
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    init_db()
    print(f"Initialized thread database at: {DB_FILE}")

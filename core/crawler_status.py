import json
import os
import fcntl
from datetime import datetime
from typing import Dict, Any

_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(_DIR, '..', 'data', 'crawler_status.json')

def _ensure_file():
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    if not os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)

def update_status(job_id: str, crawler_type: str, site: str, total: int, crawled: int, data_bytes: int, tags: int, status: str = "running"):
    """
    クローラーの進捗を更新します。
    job_id: クローラーの一意なID
    crawler_type: "patrol" または "scrape_ideas"
    site: 対象サイト名やトピック
    total: 全件数 (-1 等で不明を示す)
    crawled: クロール済みの件数
    data_bytes: 保存したデータ量 (バイト)
    tags: 取得したタグの数
    status: "running", "completed", "error" など
    """
    _ensure_file()
    
    try:
        with open(STATUS_FILE, 'r+', encoding='utf-8') as f:
            # ファイルロックを取得
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
            
            data[job_id] = {
                "type": crawler_type,
                "site": site,
                "total": total,
                "crawled": crawled,
                "data_bytes": data_bytes,
                "tags": tags,
                "status": status,
                "last_updated": datetime.now().isoformat()
            }
            
            # 古い完了済みジョブのクリーンアップ（1時間以上前の "completed" を削除）
            now = datetime.now()
            keys_to_delete = []
            for k, v in data.items():
                if v.get("status") in ("completed", "error"):
                    try:
                        last_upd = datetime.fromisoformat(v.get("last_updated"))
                        if (now - last_upd).total_seconds() > 3600:
                            keys_to_delete.append(k)
                    except ValueError:
                        keys_to_delete.append(k)
            
            for k in keys_to_delete:
                del data[k]
                
            f.seek(0)
            f.truncate()
            json.dump(data, f, ensure_ascii=False, indent=2)
            
            # ロック解放
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        print(f"Failed to update crawler status: {e}")

def get_all_status() -> Dict[str, Any]:
    """すべてのクローラーステータスを取得します"""
    _ensure_file()
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            # 読み込みの共有ロック
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return data
    except Exception:
        return {}

def remove_status(job_id: str):
    """特定のジョブを削除します"""
    _ensure_file()
    try:
        with open(STATUS_FILE, 'r+', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
            
            if job_id in data:
                del data[job_id]
                f.seek(0)
                f.truncate()
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass

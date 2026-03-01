#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sato Clone Organization - Autonomous Patrol Worker
自律的に情報を収集し、佐藤氏に有益な知識を蓄積するワーカー。

Usage:
    python3 patrol.py --once       # 1回だけ実行（テスト用）
    python3 patrol.py              # APSchedulerで定期実行
"""

import sys
import os
import json
import time
import re
from datetime import datetime
from pathlib import Path

# core/ 内のモジュールをインポート
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
from brain import init_db, store as brain_store, get_context_for, get_connection, get_interests, stats
from orchestrator import call_agent, CostTracker, MAX_OUTPUT_CHARS
from crawler_status import update_status, remove_status

# ==============================================================================
# 定数
# ==============================================================================

CONFIG_PATH = os.path.join(_DIR, "..", "config", "patrol_config.yaml")
ALERT_LOG_PATH = os.path.join(_DIR, "..", "data", "patrol_alerts.json")
STATE_PATH = os.path.join(_DIR, "..", "data", "patrol_state.json")
SITES_LIST_PATH = os.path.join(_DIR, "..", "data", "patrol_sites.txt")

# ==============================================================================
# 設定読み込み
# ==============================================================================

def load_config() -> dict:
    """patrol_config.yaml を読み込む"""
    try:
        import yaml
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f).get("patrol", {})
    except ImportError:
        # PyYAML未インストール時は簡易パース
        config = {
            "interval_hours": 6,
            "max_cost_per_run_usd": 0.01,
            "topics": [
                "最新 AIエージェント AGI ニュース",
                "軽量LLM 新モデル リリース",
                "マルチエージェント オーケストレーション 最新動向",
                "ヒューマノイドロボット 最新ニュース",
                "AI医療 最新研究",
            ],
            "alert_threshold": 0.7,
        }
        return config


# ==============================================================================
# パトロール実行
# ==============================================================================

def _load_state() -> dict:
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            fallback = os.path.join(_DIR, "..", "patrol_state.json")
            if os.path.exists(fallback):
                with open(fallback, "r", encoding="utf-8") as f:
                    return json.load(f)
    except Exception:
        pass
    return {"last_index": 0}

def _save_state(index: int):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"last_index": index}, f)
    except PermissionError:
        fallback = os.path.join(_DIR, "..", "patrol_state.json")
        try:
            with open(fallback, "w", encoding="utf-8") as f:
                json.dump({"last_index": index}, f)
        except Exception as e:
            print(f"Failed to save state to fallback: {e}")
    except Exception as e:
        print(f"Failed to save state: {e}")

def run_patrol_once(config: dict = None) -> dict:
    """
    1回のパトロールを実行する。
    """
    if config is None:
        config = load_config()
    
    conn = get_connection()
    
    # 静的トピック + 動的トピック（興味）
    topics = config.get("topics", [])
    
    # ユーザー指定のカスタムリスト (TXTファイル) のロード
    try:
        sites_file = SITES_LIST_PATH
        if not os.path.exists(sites_file):
            # プロジェクトルートにフォールバック
            sites_file = os.path.join(_DIR, "..", "patrol_sites.txt")
            
        if os.path.exists(sites_file):
            with open(sites_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # "site:" プレフィックスを付けるか、そのまま追加
                        if line.startswith("http"):
                            topics.append(f"サイト巡回: {line}")
                        else:
                            topics.append(line)
    except Exception as e:
        print(f"カスタムリストの読み込みエラー: {e}")
        
    try:
        interests = get_interests(conn)
        for interest in interests:
            topics.append(f"最新情報: {interest['keyword']}")
    except Exception as e:
        print(f"興味の読み込みエラー: {e}")
        
    if not topics:
        print("トピックがありません。")
        conn.close()
        return {}

    alert_threshold = config.get("alert_threshold", 0.7)
    max_cost = config.get("max_cost_per_run_usd", 0.01)
    
    state = _load_state()
    start_index = state.get("last_index", 0)
    if start_index >= len(topics):
        start_index = 0
        
    tracker = CostTracker()
    results = []
    alerts = []
    total_stored = 0
    total_data_bytes = 0
    total_tags_count = 0
    
    # 状態のトラッキング
    job_id = f"patrol_{int(time.time())}"
    update_status(
        job_id=job_id,
        crawler_type="patrol",
        site="Initial sweep start",
        total=len(topics),
        crawled=0,
        data_bytes=0,
        tags=0,
        status="running"
    )
    
    print(f"🔍 パトロール開始: {len(topics)}トピック (Resume from: {start_index}) | 上限: ${max_cost}")
    print(f"   時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    current_index = start_index
    # 最大3トピックを1回で処理して終了するか、コスト上限まで
    processed_count = 0
    max_process_per_run = 3
    
    while processed_count < max_process_per_run and processed_count < len(topics):
        topic = topics[current_index]
        print(f"  [{current_index+1}/{len(topics)}] 調査中: {topic[:40]}...", flush=True)
        update_status(
            job_id=job_id,
            crawler_type="patrol",
            site=topic[:100],
            total=len(topics),
            crawled=processed_count,
            data_bytes=total_data_bytes,
            tags=total_tags_count,
            status="running"
        )
        
        # 重複チェック（直近3日以内に同じトピックを調査していないか）
        title_pattern = f"パトロール: {topic[:40]}"
        recent_check = conn.execute(
            "SELECT id FROM knowledge WHERE title = ? AND created_at >= datetime('now', '-3 days')",
            (title_pattern,)
        ).fetchone()
        
        if recent_check:
            print("    ✅ 直近で調査済みのためスキップ")
            current_index = (current_index + 1) % len(topics)
            processed_count += 1
            continue
        
        # Researchエージェントに調査させる
        research_prompt = (
            f"以下のトピックについて、最新のニュースと事実を調査してください。\n"
            f"事実のみを箇条書きで出力してください。\n\n"
            f"トピック: {topic}"
        )
        
        facts = call_agent("research", research_prompt, tracker)
        
        if "(応答を解析できませんでした)" in facts or "[エラー]" in facts or "[タイムアウト]" in facts:
            print(f"    ⚠️ 調査失敗: {facts[:60]}")
            continue
        
        # 脳に保存
        tags = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}', topic)
        tags = [t.lower() for t in tags[:5]]
        tags.append("patrol")
        total_tags_count += len(tags)
        total_data_bytes += len(facts.encode('utf-8'))
        
        kid = brain_store(
            conn,
            title=f"パトロール: {topic[:40]}",
            summary=facts[:200],
            body=facts,
            tags=tags,
            source="patrol",
            relevance=0.6,
        )
        total_stored += 1
        
        # 佐藤氏の文脈を取得
        context = get_context_for(topic)
        
        # Planningに有益性判定させる
        judge_prompt = (
            f"以下の「ニュース事実」が佐藤氏にとって有益かどうかを判定してください。\n"
            f"回答は「関連度: X.X」（0.0〜1.0）と「理由: 一行」のフォーマットで。\n\n"
            f"## 佐藤氏の文脈\n{context}\n\n"
            f"## ニュース事実\n{facts[:500]}"
        )
        
        judgment = call_agent("planning", judge_prompt, tracker)
        
        # 関連度をパース
        relevance_match = re.search(r'関連度[:：]\s*([\d.]+)', judgment)
        relevance_score = float(relevance_match.group(1)) if relevance_match else 0.5
        
        # relevanceを更新
        conn.execute(
            "UPDATE knowledge SET relevance = ? WHERE id = ?",
            (min(1.0, relevance_score), kid)
        )
        conn.commit()
        
        result = {
            "topic": topic,
            "knowledge_id": kid,
            "relevance": relevance_score,
            "judgment": judgment[:200],
            "is_alert": relevance_score >= alert_threshold,
        }
        results.append(result)
        
        if relevance_score >= alert_threshold:
            alerts.append({
                "timestamp": datetime.now().isoformat(),
                "topic": topic,
                "relevance": relevance_score,
                "summary": facts[:200],
                "judgment": judgment[:200],
            })
            print(f"    🔔 有益! (関連度: {relevance_score:.1f})")
        else:
            print(f"    📦 保存のみ (関連度: {relevance_score:.1f})")
        
        # 次のループ準備
        current_index = (current_index + 1) % len(topics)
        processed_count += 1
        
        # コスト上限チェック
        est_cost = _estimate_cost(tracker)
        if est_cost >= max_cost:
            print(f"\n  ⚠️ コスト上限到達 (${est_cost:.4f} >= ${max_cost})")
            break
            
    # レジューム状態を保存
    _save_state(current_index)
    
    # ジョブ完了
    update_status(
        job_id=job_id,
        crawler_type="patrol",
        site="Completed sweep",
        total=len(topics),
        crawled=processed_count,
        data_bytes=total_data_bytes,
        tags=total_tags_count,
        status="completed"
    )
    
    conn.close()
    
    # アラートログに追記
    if alerts:
        _append_alerts(alerts)
    
    # サマリー
    summary = {
        "timestamp": datetime.now().isoformat(),
        "topics_checked": len(results),
        "knowledge_stored": total_stored,
        "alerts": len(alerts),
        "cost": tracker.summary(),
    }
    
    print(f"\n{'='*50}")
    print(f"📊 パトロール完了")
    print(f"   調査: {len(results)}トピック | 保存: {total_stored}件 | アラート: {len(alerts)}件")
    print(f"   {tracker.summary()}")
    
    return summary


def _estimate_cost(tracker: CostTracker) -> float:
    """現在の推定コストを計算する"""
    total_input = sum(c["input_chars"] for c in tracker.calls)
    total_output = sum(c["output_chars"] for c in tracker.calls)
    est_input_tokens = int(total_input * 1.5)
    est_output_tokens = int(total_output * 1.5)
    return (est_input_tokens * 0.15 + est_output_tokens * 0.60) / 1_000_000


def _append_alerts(alerts: list[dict]):
    """アラートログに追記する"""
    existing = []
    try:
        if os.path.exists(ALERT_LOG_PATH):
            with open(ALERT_LOG_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
    except (json.JSONDecodeError, PermissionError):
        pass
    
    existing.extend(alerts)
    
    # 最新100件のみ保持
    existing = existing[-100:]
    
    try:
        os.makedirs(os.path.dirname(ALERT_LOG_PATH), exist_ok=True)
        with open(ALERT_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except PermissionError:
        # data/ がroot所有の場合はプロジェクトルートにフォールバック
        fallback = os.path.join(_DIR, "..", "patrol_alerts.json")
        with open(fallback, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)


# ==============================================================================
# スケジューラー
# ==============================================================================

def run_scheduled(config: dict = None):
    """APSchedulerで定期的にパトロールを実行する"""
    if config is None:
        config = load_config()
    
    interval_hours = config.get("interval_hours", 6)
    
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        
        scheduler = BlockingScheduler()
        scheduler.add_job(
            run_patrol_once,
            'interval',
            hours=interval_hours,
            args=[config],
            id='patrol_job',
            name=f'Sato Patrol (every {interval_hours}h)',
        )
        
        print(f"🤖 自律パトロール・スケジューラー起動")
        print(f"   間隔: {interval_hours}時間ごと")
        print(f"   トピック数: {len(config.get('topics', []))}")
        print(f"   Ctrl+Cで停止")
        print()
        
        # 初回はすぐ実行
        run_patrol_once(config)
        
        scheduler.start()
        
    except ImportError:
        print("⚠️ APSchedulerが見つかりません。")
        print("   pip install apscheduler でインストールするか、")
        print("   --once フラグで1回のみ実行してください。")
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        print("終了します。")


# ==============================================================================
# エントリポイント
# ==============================================================================

if __name__ == "__main__":
    # DBを初期化
    init_db()
    
    if "--once" in sys.argv:
        result = run_patrol_once()
    else:
        run_scheduled()

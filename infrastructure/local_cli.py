#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Local CLI Interface for Sato Clone Organization
マルチエージェント・オーケストレーターを通じて、
Chain of Thought パイプラインによる深い考察が可能なCLIインタフェースです。
"""

import subprocess
import sys
import os
import tempfile
import re
from datetime import datetime

# core/orchestrator.py をインポートできるようにパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
from orchestrator import run, CONTAINER_NAME
from brain import get_connection, get_brain_stats, get_biz_idea_categories, get_biz_ideas_by_category
from crawler_status import get_all_status


def main():
    print("=" * 56)
    print(" 🦞 Sato Digital Clone - Multi-Agent CLI")
    print("=" * 56)
    print(f" コンテナ: {CONTAINER_NAME}")
    print(f" パイプライン: GA → Management → Research → Planning")
    print(f" ガードレール: 最大4回のLLM呼び出し / コスト追跡")
    print(" 💡 コマンド一覧を見る: '/h' または '/help'")
    print()
    
    # Docker生存確認
    try:
        check = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
            capture_output=True, text=True, timeout=5
        )
        if "true" not in check.stdout:
            print(f"❌ コンテナ '{CONTAINER_NAME}' が起動していません。")
            sys.exit(1)
        print("✅ クローン組織に接続しました！\n")
    except Exception:
        print("❌ Dockerへの接続に失敗しました。")
        sys.exit(1)
    
    while True:
        try:
            user_input = input("あなた: ").strip()
            
            if user_input in ['/e', '/edit']:
                editor = os.environ.get('EDITOR', 'nano')
                with tempfile.NamedTemporaryFile(suffix=".txt", mode="w+", delete=False) as tf:
                    tf_path = tf.name
                
                try:
                    subprocess.run([editor, tf_path])
                    with open(tf_path, "r", encoding="utf-8") as f:
                        user_input = f.read().strip()
                except Exception as e:
                    print(f"エディタの起動に失敗しました: {e}")
                    user_input = ""
                finally:
                    if os.path.exists(tf_path):
                        os.remove(tf_path)
                
                if not user_input:
                    print("入力がキャンセルされました。")
                    continue
                else:
                    # エディタからの入力をエコー表示
                    print(f"あなた(Editor):\n{user_input}\n")
            
            elif user_input in ['/s', '/status']:
                try:
                    conn = get_connection()
                    stats = get_brain_stats(conn)
                    conn.close()
                    
                    print("\n🧠 **Sato Clone 脳（記憶）のステータス**")
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"  - 現在時刻:   {current_time}")
                    print(f"  - 蓄積知識数: {stats.get('total_knowledge', 0)} 件")
                    print(f"  - 登録タグ数: {stats.get('total_tags', 0)} 種類")
                    print(f"  - DBサイズ:   {stats.get('db_size_mb', 0.0)} MB")
                    
                    sources = stats.get('sources', {})
                    if sources:
                        print("  - 情報ソース:")
                        for s, count in sources.items():
                            print(f"      - {s}: {count}件")
                            
                    interests = stats.get('recent_interests', [])
                    if interests:
                        print(f"  - 最近の興味: {', '.join(interests)}")
                    print()
                except Exception as e:
                    print(f"ステータス取得エラー: {e}")
                continue
                
            elif user_input in ['/h', '/help']:
                print("\n🛠️  **利用可能なコマンド一覧**")
                print("  /e, /edit        : 外部エディタ(nano/vim)を開いて長文を入力します")
                print("  /s, /status      : 脳（SQLite）の現在の記憶量や内訳を表示します")
                print("  /ideas           : ストックされたビジネスアイデア(biz_idea)をカテゴリ別に閲覧します")
                print("  /crawl           : 指定したURLからビジネスアイデアを抽出しストックします（バックグラウンド実行）")
                print("  /cstat           : バックグラウンドで稼働しているクローラーの現在状況を表示します")
                print("  /interval <時間> : 自動パトロールの間隔を変更し、再起動します（例: `/interval 2`）")
                print("  /h, /help        : このヘルプメッセージを表示します")
                print("  exit, quit       : チャットを終了します\n")
                continue
                
            elif user_input in ['/crawl', '/c']:
                print("\n👀 探索したいサイトのURLを貼り付けてください（キャンセルは空のままEnter）:")
                target_url = input("  URL > ").strip()
                if not target_url:
                    print("  キャンセルしました。")
                    continue
                    
                if not target_url.startswith("http"):
                    print("  ⚠️ URLは http または https で始まる必要があります。")
                    continue
                    
                print(f"  🔄 {target_url} の探索を準備中...")
                
                # ログディレクトリの作成
                log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "logs")
                os.makedirs(log_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = os.path.join(log_dir, f"crawl_{timestamp}.log")
                
                # サブプロセスとしてバックグラウンド実行
                script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "scrape_ideas.py")
                try:
                    with open(log_file, "w") as f:
                        subprocess.Popen(
                            ["python3", script_path, target_url],
                            stdout=f,
                            stderr=subprocess.STDOUT,
                            start_new_session=True # 親プロセス終了後も継続させる
                        )
                    print(f"\n✅ クローラーをバックグラウンドで起動しました！")
                    print(f"  👉 処理の進捗ログは {log_file} に記録されます。")
                    print(f"  （※チャットは引き続きそのままご利用いただけます）\n")
                except Exception as e:
                    print(f"  ❌ クローラーの起動に失敗しました: {e}")
                continue
                
            elif user_input in ['/cstat', '/crawlers']:
                try:
                    statuses = get_all_status()
                    if not statuses:
                        print("\n🕸️ 現在稼働中のクローラーはありません。\n")
                        continue
                        
                    print("\n🕸️ **稼働中のクローラー状況**")
                    print(f"{'='*60}")
                    for jid, s in statuses.items():
                        c_type = "自動パトロール" if s['type'] == 'patrol' else "アイデア収集"
                        site = s['site'][:40] + "..." if len(s['site']) > 40 else s['site']
                        total_str = str(s['total']) if s['total'] >= 0 else "?"
                        status_mark = "🏃" if s['status'] == 'running' else "✅" if s['status'] == 'completed' else "❌"
                        
                        updated = s.get('last_updated', '')
                        if updated:
                            try:
                                dt = datetime.fromisoformat(updated)
                                updated = dt.strftime("%H:%M:%S")
                            except ValueError:
                                pass
                                
                        print(f"{status_mark} [{c_type}] {site}")
                        if s['status'] == "running":
                            print(f"    進捗: {s['crawled']} / {total_str} 件完了")
                        else:
                            print(f"    状態: {s['status']}")
                        print(f"    データ量: {s['data_bytes'] / 1024:.1f} KB | 取得タグ: {s['tags']} 件")
                        print(f"    更新時刻: {updated}")
                        print(f"{'-'*60}")
                    print()
                except Exception as e:
                    print(f"ステータス取得エラー: {e}")
                continue
                
            elif user_input in ['/ideas', '/i']:
                try:
                    conn = get_connection()
                    while True:
                        categories = get_biz_idea_categories(conn)
                        if not categories:
                            print("\n💡 現在ストックされているビジネスアイデアはありません。")
                            break
                            
                        print(f"\n💡 **ストックされたビジネスアイデア（全 {sum(c['count'] for c in categories)} 件）**")
                        for idx, cat in enumerate(categories, 1):
                            print(f"  [{idx}] 📁 {cat['category']} ({cat['count']}件)")
                        print("  [0] 戻る\n")
                        
                        cat_choice = input("  番号を選択してください > ").strip()
                        if cat_choice == '0' or not cat_choice:
                            break
                            
                        if cat_choice.isdigit():
                            cat_idx = int(cat_choice) - 1
                            if 0 <= cat_idx < len(categories):
                                selected_cat = categories[cat_idx]['category']
                                ideas = get_biz_ideas_by_category(conn, selected_cat)
                                
                                while True:
                                    print(f"\n--- 📁 {selected_cat}分野の有望サービス ({len(ideas)}件) ---")
                                    for i, idea in enumerate(ideas, 1):
                                        body_text = idea['body']
                                        
                                        # 評価星数と適性を抽出してタイトル行にまとめる
                                        star = ""
                                        star_match = re.search(r'【評価星数】:(.*?)(?=\n【|$)', body_text, flags=re.DOTALL)
                                        if star_match:
                                            star = star_match.group(1).strip()
                                            
                                        vc = ""
                                        vc_match = re.search(r'【VibeCoding適性】:(.*?)(?=\n【|$)', body_text, flags=re.DOTALL)
                                        if vc_match:
                                            vc = vc_match.group(1).strip()
                                            
                                        # サマリー
                                        summary = idea['summary']
                                        if len(summary) > 60:
                                            summary = summary[:60] + "..."
                                            
                                        title_line = f"[{i}] {star} {idea['title']}"
                                        print(f"\n{title_line}")
                                        print(f"    概要: {summary}")
                                        if vc:
                                            print(f"    開発適性: {vc}")
                                            
                                    print("\n  [0] カテゴリ選択に戻る")
                                    idea_choice = input("  詳細を見る番号を選択してください > ").strip()
                                    
                                    if idea_choice == '0' or not idea_choice:
                                        break
                                        
                                    if idea_choice.isdigit():
                                        idea_idx = int(idea_choice) - 1
                                        if 0 <= idea_idx < len(ideas):
                                            idea = ideas[idea_idx]
                                            body_text = idea['body']
                                            
                                            print(f"\n{'='*50}")
                                            print(f" 💡 詳細企画: {idea['title']}")
                                            print(f"{'='*50}\n")
                                            
                                            # VibeCoding適性
                                            vc_match = re.search(r'【VibeCoding適性】:(.*?)(?=\n【|$)', body_text, flags=re.DOTALL)
                                            if vc_match:
                                                print(f"【VibeCoding適性】 {vc_match.group(1).strip()}")
                                                
                                            # URL
                                            url_match = re.search(r'【URL】:(.*?)(?=\n【|$)', body_text, flags=re.DOTALL)
                                            if url_match:
                                                print(f"【URL】 {url_match.group(1).strip()}")
                                                
                                            print("\n【詳細な実装アイデア / 企画】")
                                                
                                            # 詳細な実装アイデアまたは主要機能
                                            details_match = re.search(r'【詳細な実装アイデア】:(.*?)(?=\n【|$)', body_text, flags=re.DOTALL)
                                            if not details_match:
                                                details_match = re.search(r'【主要機能】:(.*?)(?=\n【|$)', body_text, flags=re.DOTALL)
                                                
                                            if details_match:
                                                # 長文を見やすくインデントして表示
                                                for line in details_match.group(1).strip().split('\n'):
                                                    if line.strip():
                                                        print(f"  {line.strip()}")
                                            else:
                                                print("  (詳細な企画情報がありません)")
                                                
                                            print(f"\n{'-'*50}")
                                            input("  (Enterでリストに戻る) > ")
                            else:
                                print("  ⚠️ 無効な番号です。")
                        else:
                            print("  ⚠️ 数字を入力してください。")
                            
                    conn.close()
                except Exception as e:
                    print(f"アイデア閲覧エラー: {e}")
                continue
                
            elif user_input.startswith('/interval '):
                parts = user_input.split()
                if len(parts) == 2 and parts[1].isdigit():
                    new_interval = int(parts[1])
                    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'patrol_config.yaml')
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # YAMLの設定を書き換え
                        new_content = re.sub(r'interval_hours:\s*\d+', f'interval_hours: {new_interval}', content)
                        
                        with open(config_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                            
                        print(f"\n⚙️ パトロール間隔を {new_interval} 時間に設定しました。")
                        
                        # バックグラウンドプロセスを再起動
                        print("🔄 パトロールサービスを再起動しています...")
                        subprocess.run(["pkill", "-f", "patrol.py"])
                        script_path = os.path.join(os.path.dirname(__file__), 'start_patrol.sh')
                        subprocess.Popen(["bash", script_path])
                        print("✅ 再起動完了。監視を開始しました。\n")
                    except Exception as e:
                        print(f"❌ 設定変更に失敗しました: {e}")
                else:
                    print("⚠️ 使い方が間違っています。例: `/interval 2`")
                continue
                
        except (KeyboardInterrupt, EOFError):
            print("\n\nセッションを終了します。")
            break
        
        if not user_input:
            continue
        if user_input.lower() in ['exit', 'quit']:
            print("セッションを終了します。")
            break
        
        print("  ⏳ エージェント処理中...", end="", flush=True)
        
        response, tracker = run(user_input)
        
        # 「処理中...」行をクリア
        print("\r" + " " * 40 + "\r", end="")
        
        print(f"\n🦞 [総務部]: {response}\n")
        print(f"  {tracker.summary()}\n")

if __name__ == "__main__":
    main()

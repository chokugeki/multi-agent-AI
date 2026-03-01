#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Business Idea Scraper (Sato Clone)
指定された評価サイトのURLからテキストを抽出し、
VibeCoding適性を評価して佐藤クローンの脳（SQLite）にストックします。
"""

import sys
import os
import re
import urllib.parse
import cloudscraper
from bs4 import BeautifulSoup

# coreモジュールへのパス追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
from orchestrator import call_agent, CostTracker
from orchestrator import call_agent, CostTracker
from brain import get_connection, store
from crawler_status import update_status, remove_status

def get_scraper():
    return cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    })

def fetch_html(url: str) -> str:
    """指定URLからHTMLを抽出（Cloudflare等回避）"""
    scraper = get_scraper()
    try:
        response = scraper.get(url, timeout=20)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error fetching URL {url}: {e}")
        return ""

def html_to_text(html: str) -> str:
    """BeautifulSoupでテキストのみを抽出"""
    if not html: return ""
    soup = BeautifulSoup(html, "html.parser")
    # 不要なタグを除外
    for script in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        script.extract()
    text = soup.get_text(separator=' ', strip=True)
    return text

def extract_links_from_html(html: str, base_url: str) -> list[str]:
    """BeautifulSoupでaタグのリンクを抽出"""
    if not html: return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('javascript:') or href.startswith('#'):
            continue
        try:
            full_url = urllib.parse.urljoin(base_url, href)
            # 画像などの静的ファイルを除外
            if full_url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.css', '.js', '.pdf')):
                continue
            if full_url not in links:
                links.append(full_url)
        except:
            pass
    return links

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/scrape_ideas.py <URL>")
        sys.exit(1)
        
    
    base_url = sys.argv[1]
    tracker = CostTracker()
    job_id = f"scrape_{os.getpid()}"
    
    update_status(
        job_id=job_id,
        crawler_type="scrape_ideas",
        site=base_url,
        total=-1,
        crawled=0,
        data_bytes=0,
        tags=0,
        status="running"
    )
    
    # ---------------------------------------------------------
    # ステップ1: インデックス生成（リンクの収集と有望リンクの選定）
    # ---------------------------------------------------------
    print(f"🔍 [STEP 1] 起点URLからインデックスを生成します: {base_url}")
    
    html = fetch_html(base_url)
    if not html:
        print(f"❌ サイトの読み込みに失敗しました。")
        update_status(
            job_id=job_id,
            crawler_type="scrape_ideas",
            site=base_url,
            total=-1,
            crawled=0,
            data_bytes=0,
            tags=0,
            status="error"
        )
        sys.exit(1)
        
    # 生テキストとリンク一覧を取得
    raw_text = html_to_text(html)
    all_links = extract_links_from_html(html, base_url)
    
    print(f"ℹ️ {len(all_links)}件のリンクを発見しました。エージェントに有望リンクの選定を依頼します...")
    
    # リンクを100件ずつのバッチに分割してLLMに評価させる
    target_urls = []
    batch_size = 100
    
    for i in range(0, len(all_links), batch_size):
        batch_links = all_links[i:i + batch_size]
        links_text = "\n".join(batch_links)
        print(f"   ⏳ バッチ処理中 {i+1}〜{min(i+batch_size, len(all_links))} / {len(all_links)}件...")
        
        index_prompt = f"""
あなたは佐藤デジタルクローン組織の調査・思考コアです。
以下のWebページの概要とリンク一覧を見て、ソフトウェアやWebサービスの詳細説明・レビュー・リポジトリなどが載っている「可能性がある個別ページのURL」を「すべて」選び、そのURLのみを抽出してください。
広告や全く関係ないページを除去しますが、少しでもビジネスアイデアの参考になりそうなものは積極的にリストアップしてください。

出力フォーマット（各行にURLのみを記載）:
[URL 1]
[URL 2]
[URL 3]
...

起点URLの概要テキスト（先頭3000字）:
{raw_text[:3000]}

判定対象のリンク群:
{links_text}
"""
        try:
            index_response = call_agent("planning", index_prompt, tracker)
            batch_target_urls = [line.strip() for line in index_response.split('\n') if line.strip().startswith('http')]
            target_urls.extend(batch_target_urls)
            print(f"      → {len(batch_target_urls)}件の有望リンクを発見")
        except Exception as e:
            print(f"      ⚠️ バッチ処理エラー: {e}")
            
    # 重複排除
    target_urls = list(dict.fromkeys(target_urls))
    
    if not target_urls:
        print("⚠️ 有望な個別ページのURLが見つかりませんでした。起点URLのみで直接評価を試みます。")
        target_urls = [base_url]
    else:
        print(f"🎯 以下の {len(target_urls)} 件の個別ページを深堀り（ディープクロール）対象に決定しました:")
        for t_url in target_urls:
            print(f"   - {t_url}")
            
    print("\n---------------------------------------------------------")
    
    # ---------------------------------------------------------
    # ステップ2: 個別ページのディープクロールと評価
    # ---------------------------------------------------------
    # ---------------------------------------------------------
    conn = get_connection()
    stored_count = 0
    total_data_bytes = 0
    total_tags_count = 0
    
    update_status(
        job_id=job_id,
        crawler_type="scrape_ideas",
        site=base_url,
        total=len(target_urls),
        crawled=0,
        data_bytes=total_data_bytes,
        tags=total_tags_count,
        status="running"
    )
    
    for t_url in target_urls:
        print(f"📖 [STEP 2] 詳細解析中: {t_url}")
        detail_html = fetch_html(t_url)
        detail_text = html_to_text(detail_html)
        if not detail_text:
            print("   ⚠️ 取得失敗によりスキップ")
            
            # ステータス更新（スキップ時）
            update_status(
                job_id=job_id,
                crawler_type="scrape_ideas",
                site=base_url,
                total=len(target_urls),
                crawled=target_urls.index(t_url) + 1,
                data_bytes=total_data_bytes,
                tags=total_tags_count,
                status="running"
            )
            continue
            
        eval_prompt = f"""
あなたは佐藤デジタルクローン組織の思考コアです。
以下のWebページのテキストデータから、個人開発やVibe Coding（AI支援コーディング）のインスピレーションになりそうな「ソフトウェア／Webサービス」または「製品アイデア」を抽出し評価してください。

出力は以下のフォーマットに厳密に従ってください。

フォーマット:
【サービス名】: [サービス名]
【カテゴリ】: [業種やカテゴリ。例: HR, CRM, 医療, 予約システム などシンプルに1単語程度で]
【URL】: [{t_url}]
【評価星数】: [有望かどうかを★1〜★5で評価。例: ★★★☆☆]
【サマリー】: [どんなサービスか、なぜ日本市場や特定ニッチで需要があるのかを簡潔に]
【VibeCoding適性】: [【A】比較的容易, 【B】中規模, 【C】難しい のいずれか]
【詳細な実装アイデア】: 
[このアプリを実際にVibe Codingで一人で作るとしたら、どのような機能が必要か、どの部分が（AIを活用すれば）簡単に作れそうか、収益化やユーザー獲得のポイントは何かなど、開発者目線での『詳細な企画・要約』を3〜5段落程度の丁寧な文章で記述してください。箇条書きの羅列ではなく、読み応えのある評価テキストにしてください。]

抽出元ページURL: {t_url}
抽出元テキスト（先頭15000文字）:
{detail_text[:15000]}
"""
        response = call_agent("planning", eval_prompt, tracker)
        
        # 応答をパースしてDBに保存
        srv = response.strip()
        if not srv or "【サービス名】:" not in srv:
            print("   ⚠️ 有効なフォーマットで回答が得られませんでした。スキップします。")
            
            update_status(
                job_id=job_id,
                crawler_type="scrape_ideas",
                site=base_url,
                total=len(target_urls),
                crawled=target_urls.index(t_url) + 1,
                data_bytes=total_data_bytes,
                tags=total_tags_count,
                status="running"
            )
            continue
            
        try:
            name = srv.split("【サービス名】:")[1].split("\n")[0].strip()
            cat = srv.split("【カテゴリ】:")[1].split("\n")[0].strip()
            
            tags = ["biz_idea", f"category:{cat}"]
            try:
                summary = srv.split("【サマリー】:")[1].split("\n")[0].strip()[:300]
            except:
                summary = "説明なし"
            
            store(
                conn,
                title=f"💡 有望サービス: {name}",
                summary=summary,
                body=srv,
                tags=tags,
                source="scrape_ideas_deep",
                relevance=1.0
            )
            print(f"   ✅ 保存完了: {name} (カテゴリ: {cat})")
            stored_count += 1
            total_tags_count += len(tags)
            total_data_bytes += len(srv.encode('utf-8'))
            
        except Exception as e:
            print(f"   ⚠️ パースエラー: {e}")
            
        # ステータス更新
        update_status(
            job_id=job_id,
            crawler_type="scrape_ideas",
            site=base_url,
            total=len(target_urls),
            crawled=target_urls.index(t_url) + 1,
            data_bytes=total_data_bytes,
            tags=total_tags_count,
            status="running"
        )
            
    conn.close()
    
    print(f"\n🎉 完了! {stored_count}件の有望ビジネスアイデアを脳にディープ・ストックしました。")
    print("  CLIで `/ideas` コマンドを実行して確認してください。")
    print(tracker.summary())
    
    update_status(
        job_id=job_id,
        crawler_type="scrape_ideas",
        site=base_url,
        total=len(target_urls),
        crawled=len(target_urls),
        data_bytes=total_data_bytes,
        tags=total_tags_count,
        status="completed"
    )

if __name__ == "__main__":
    main()

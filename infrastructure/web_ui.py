import sys
import os
import streamlit as st
import subprocess
from datetime import datetime

# sys.path に core や tools へのパスを追加
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_DIR, '..', 'core'))

# Core モジュールのインポート
import orchestrator
import importlib
importlib.reload(orchestrator)
from orchestrator import run as orchestrator_run, CONTAINER_NAME
from brain import get_connection, get_brain_stats
from crawler_status import get_all_status

# スレッド保存DBのインポート
import thread_db
thread_db.init_db()

st.set_page_config(
    page_title="Sato Digital Clone",
    page_icon="🦞",
    layout="wide",
)

# ----------------------------------------------------------------------
# 翻訳辞書データ (Bilingual UI Support)
# ----------------------------------------------------------------------
UI_TEXT = {
    "日本語": {
        "title": "🦞 {0} Digital Clone",
        "activity_monitor": "⚙️ エージェント稼働状況",
        "cost_tracker": "📊 最新コスト概算",
        "brain_stats": "🧠 脳のステータス",
        "total_knowledge": "蓄積知識数",
        "total_tags": "登録タグ数",
        "db_size": "DBサイズ",
        "active_crawlers": "🕸️ 稼働中のクローラー",
        "btn_refresh": "更新",
        "no_crawlers": "現在稼働中のクローラーはありません。",
        "type_patrol": "パトロール",
        "type_scrape": "アイデア収集",
        "progress": "進捗: {0} / {1} 件完了",
        "state": "状態: {0}",
        "data_size": "データ量: {0:.1f} KB",
        "tags_count": "取得タグ: {0} 件",
        "updated_at": "更新: {0}",
        "start_crawler": "🔍 クローラー起動",
        "url_target": "URL対象",
        "url_placeholder": "https://...",
        "btn_start_crawl": "クロール開始",
        "start_success": "クローラーを起動しました！",
        "start_failed": "起動に失敗しました: {0}",
        "url_warning": "URLは http から始まる必要があります",
        "chat_placeholder": "{0}に話しかける。(Shift+Enterで改行)",
        "spinner_msg": "思考部が推論を行っています...",
        "error_msg": "エラーが発生しました: {0}",
        "lbl_continue": "💬 スレッド継続モード",
        "lbl_new": "新 規",
        "btn_save_thread": "💾 このスレッドを保存",
        "btn_thread_list": "💬 スレッド一覧",
        "saved_success": "スレッドを専用データベースに保存しました！",
        "saved_failed": "保存に失敗しました: {0}",
        "hello_msg": "{0} Digital Clone に接続しました。何をお調べしますか？",
        "back_to_chat": "🔙 チャットに戻る",
        "thread_list_title": "過去のスレッド一覧",
        "no_threads": "保存されたスレッドはありません。"
    },
    "English": {
        "title": "🦞 {0} Digital Clone",
        "activity_monitor": "⚙️ Agent Activity",
        "cost_tracker": "📊 Latest Cost Est.",
        "brain_stats": "🧠 Brain Stats",
        "total_knowledge": "Total Knowledge",
        "total_tags": "Total Tags",
        "db_size": "DB Size",
        "active_crawlers": "🕸️ Active Crawlers",
        "btn_refresh": "Refresh",
        "no_crawlers": "No active crawlers currently running.",
        "type_patrol": "Patrol",
        "type_scrape": "Scrape Ideas",
        "progress": "Progress: {0} / {1} completed",
        "state": "Status: {0}",
        "data_size": "Data Size: {0:.1f} KB",
        "tags_count": "Tags Acquired: {0}",
        "updated_at": "Updated: {0}",
        "start_crawler": "🔍 Start Crawler",
        "url_target": "Target URL",
        "url_placeholder": "https://...",
        "btn_start_crawl": "Start Crawling",
        "start_success": "Crawler started successfully!",
        "start_failed": "Failed to start: {0}",
        "url_warning": "URL must start with http",
        "chat_placeholder": "Talk to {0}... (Press Ctrl+Enter to send)",
        "spinner_msg": "Thinking...",
        "error_msg": "An error occurred: {0}",
        "lbl_continue": "💬 Thread Continuation Mode",
        "lbl_new": "New",
        "btn_save_thread": "💾 Save This Thread",
        "btn_thread_list": "💬 Thread List",
        "saved_success": "Thread saved to database successfully!",
        "saved_failed": "Failed to save: {0}",
        "hello_msg": "Connected to {0} Digital Clone. What would you like to know?",
        "back_to_chat": "🔙 Back to Chat",
        "thread_list_title": "Saved Thread History",
        "no_threads": "No saved threads found."
    }
}

# ----------------------------------------------------------------------
# サイドバーとセッションの設定
# ----------------------------------------------------------------------
with st.sidebar:
    def sidebar_title(text):
        st.markdown(
            f'<div style="border: 1px solid #4a4a4a; border-radius: 4px; padding: 2px 8px; '
            f'font-size: 13px; font-weight: bold; margin-bottom: 4px; margin-top: 6px; '
            f'display: inline-block; background-color: rgba(255, 255, 255, 0.05);">'
            f'{text}</div>',
            unsafe_allow_html=True
        )
    
    def compact_divider():
        st.markdown('<hr style="margin: 8px 0; border: none; border-top: 1px solid #4a4a4a;">', unsafe_allow_html=True)

    import json
    SETTINGS_FILE = os.path.join(_DIR, "..", "data", "settings.json")
    
    def load_settings():
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "ui_lang": "日本語",
            "clone_name": "佐藤",
            "user_name": "ユーザー",
            "clone_avatar": None,
            "user_avatar": None
        }
        
    def save_settings(settings):
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            st.error(f"設定の保存に失敗しました: {e}")

    # セッション状態の初期化 (Settings)
    if "settings_loaded" not in st.session_state:
        loaded = load_settings()
        st.session_state["ui_lang"] = loaded.get("ui_lang", "日本語")
        st.session_state["clone_name"] = loaded.get("clone_name", "佐藤")
        st.session_state["user_name"] = loaded.get("user_name", "ユーザー")
        st.session_state["clone_avatar"] = loaded.get("clone_avatar", None)
        st.session_state["user_avatar"] = loaded.get("user_avatar", None)
        st.session_state["settings_loaded"] = True
    
    # ----------------------------------------------------------------------
    # 設定モーダルダイアログ
    # ----------------------------------------------------------------------
    @st.dialog("⚙️ システム設定 / System Settings")
    def settings_modal():
        st.markdown("### 👤 クローン名 / Clone Name")
        c_name = st.text_input(
            "Clone Name", 
            value=st.session_state["clone_name"], 
            label_visibility="collapsed"
        )
        st.session_state["clone_name"] = c_name
        
        st.markdown("### 🧑 あなたの名前 / Your Name")
        u_name = st.text_input(
            "User Name",
            value=st.session_state["user_name"],
            label_visibility="collapsed"
        )
        st.session_state["user_name"] = u_name
        
        st.markdown("---")
        st.markdown("### 🖼️ アイコン設定 / Avatar Settings")
        
        import PIL.Image
        import io
        
        def save_uploaded_avatar(uploaded_file, prefix):
            if uploaded_file is None:
                return None
            try:
                img = PIL.Image.open(uploaded_file)
                # Resize to common avatar size for performance
                img.thumbnail((256, 256))
                
                avatars_dir = os.path.join(_DIR, "..", "data", "avatars")
                os.makedirs(avatars_dir, exist_ok=True)
                
                # Use a specific filename per type to avoid unneeded accummulation
                ext = uploaded_file.name.split('.')[-1]
                if ext.lower() not in ['png', 'jpg', 'jpeg']:
                    ext = 'png' # Default fallback
                
                file_path = os.path.join(avatars_dir, f"{prefix}_avatar.{ext}")
                img.save(file_path)
                return file_path
            except Exception as e:
                st.error(f"Failed to process image: {e}")
                return None
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Clone Avatar")
            if st.session_state["clone_avatar"] and os.path.exists(st.session_state["clone_avatar"]):
                st.image(st.session_state["clone_avatar"], width=80)
                if st.button("クリア / Clear", key="clear_c_avatar"):
                    st.session_state["clone_avatar"] = None
                    st.rerun()
            else:
                st.info("Default / デフォルト (🤖)")
            
            c_avatar_upload = st.file_uploader("Upload Clone Avatar", type=["png", "jpg", "jpeg"], key="c_avatar_upload", label_visibility="collapsed")
            if c_avatar_upload:
                st.session_state["new_clone_avatar"] = c_avatar_upload
                
        with col2:
            st.markdown("#### User Avatar")
            if st.session_state["user_avatar"] and os.path.exists(st.session_state["user_avatar"]):
                st.image(st.session_state["user_avatar"], width=80)
                if st.button("クリア / Clear", key="clear_u_avatar"):
                    st.session_state["user_avatar"] = None
                    st.rerun()
            else:
                st.info("Default / デフォルト (🧑)")
                
            u_avatar_upload = st.file_uploader("Upload User Avatar", type=["png", "jpg", "jpeg"], key="u_avatar_upload", label_visibility="collapsed")
            if u_avatar_upload:
                st.session_state["new_user_avatar"] = u_avatar_upload
        
        if st.button("適用 / Apply", use_container_width=True, type="primary"):
            # Update avatars if new ones were uploaded
            if "new_clone_avatar" in st.session_state:
                saved_path = save_uploaded_avatar(st.session_state["new_clone_avatar"], "clone")
                if saved_path:
                    st.session_state["clone_avatar"] = saved_path
                del st.session_state["new_clone_avatar"]
                
            if "new_user_avatar" in st.session_state:
                saved_path = save_uploaded_avatar(st.session_state["new_user_avatar"], "user")
                if saved_path:
                    st.session_state["user_avatar"] = saved_path
                del st.session_state["new_user_avatar"]
                
            save_settings({
                "ui_lang": st.session_state["ui_lang"],
                "clone_name": st.session_state["clone_name"],
                "user_name": st.session_state["user_name"],
                "clone_avatar": st.session_state["clone_avatar"],
                "user_avatar": st.session_state["user_avatar"]
            })
            st.rerun()

    # ----------------------------------------------------------------------
    # サイドバーUI構成
    # ----------------------------------------------------------------------
    st.markdown("🌐 **Language**")
    selected_lang = st.radio(
        "Language", 
        ["日本語", "English"], 
        horizontal=True, 
        index=0 if st.session_state.get("ui_lang", "日本語") == "日本語" else 1,
        label_visibility="collapsed"
    )
    
    # 言語が変更されたら保存してリロード
    if selected_lang != st.session_state["ui_lang"]:
        st.session_state["ui_lang"] = selected_lang
        save_settings({
            "ui_lang": st.session_state["ui_lang"],
            "clone_name": st.session_state["clone_name"],
            "user_name": st.session_state["user_name"],
            "clone_avatar": st.session_state["clone_avatar"],
            "user_avatar": st.session_state["user_avatar"]
        })
        st.rerun()

    t = UI_TEXT[st.session_state["ui_lang"]]
    
    if st.button("⚙️ " + ("設定 / Settings" if t == UI_TEXT["日本語"] else "Settings"), use_container_width=True):
        settings_modal()
        
    compact_divider()
    
    if st.button(t["btn_thread_list"], use_container_width=True):
        st.session_state["view_mode"] = "thread_list"
    compact_divider()

    sidebar_title(t["activity_monitor"])
    activity_placeholder = st.empty()
    if "last_activity" not in st.session_state:
        st.session_state["last_activity"] = "待機中 / Standby"
    activity_placeholder.info(st.session_state["last_activity"])
    
    sidebar_title(t["cost_tracker"])
    cost_placeholder = st.empty()
    if "last_cost" not in st.session_state:
        st.session_state["last_cost"] = ""
    if st.session_state["last_cost"]:
        cost_placeholder.markdown(f"```text\n{st.session_state['last_cost']}\n```")

    compact_divider()

    # 脳のステータス表示
    sidebar_title(t["brain_stats"])
    try:
        conn = get_connection()
        stats = get_brain_stats(conn)
        conn.close()
        
        st.metric(label=t["total_knowledge"], value=f"{stats.get('total_knowledge', 0)}")
        st.metric(label=t["total_tags"], value=f"{stats.get('total_tags', 0)}")
        st.caption(f"{t['db_size']}: {stats.get('db_size_mb', 0.0)} MB")
        
    except Exception as e:
        st.error(f"Brain status error: {e}")

    compact_divider()

    # クローラーステータス表示
    sidebar_title(t["active_crawlers"])
    if st.button(t["btn_refresh"]):
        pass # UI再描画トリガー
        
    try:
        statuses = get_all_status()
        if not statuses:
            st.info(t["no_crawlers"])
        else:
            for jid, s in statuses.items():
                c_type = t["type_patrol"] if s['type'] == 'patrol' else t["type_scrape"]
                site = s['site'][:30] + "..." if len(s['site']) > 30 else s['site']
                total_str = str(s['total']) if s['total'] >= 0 else "?"
                
                status_icon = "🏃" if s['status'] == 'running' else "✅" if s['status'] == 'completed' else "❌"
                
                with st.expander(f"{status_icon} [{c_type}] {site}", expanded=s['status'] == 'running'):
                    if s['status'] == "running":
                        st.progress(s['crawled'] / s['total'] if s['total'] > 0 else 0)
                        st.text(t["progress"].format(s['crawled'], total_str))
                    else:
                        st.text(t["state"].format(s['status']))
                        
                    st.text(t["data_size"].format(s['data_bytes'] / 1024))
                    st.text(t["tags_count"].format(s['tags']))
                    
                    updated = s.get('last_updated', '')
                    if updated:
                        try:
                            dt = datetime.fromisoformat(updated)
                            st.caption(t["updated_at"].format(dt.strftime('%H:%M:%S')))
                        except ValueError:
                            pass
    except Exception as e:
        st.error(f"Crawler status error: {e}")

    compact_divider()
    
    # 新規クローラー起動
    sidebar_title(t["start_crawler"])
    with st.form("crawl_form", clear_on_submit=True):
        url_input = st.text_input(t["url_target"], placeholder=t["url_placeholder"])
        submitted = st.form_submit_button(t["btn_start_crawl"])
        if submitted and url_input:
            if url_input.startswith("http"):
                script_path = os.path.join(_DIR, "..", "tools", "scrape_ideas.py")
                log_dir = os.path.join(_DIR, "..", "data", "logs")
                os.makedirs(log_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = os.path.join(log_dir, f"crawl_{timestamp}.log")
                try:
                    with open(log_file, "w") as f:
                        subprocess.Popen(
                            ["python3", script_path, url_input],
                            stdout=f,
                            stderr=subprocess.STDOUT,
                            start_new_session=True
                        )
                    st.success(t["start_success"])
                except Exception as e:
                    st.error(t["start_failed"].format(e))
            else:
                st.warning(t["url_warning"])

# ----------------------------------------------------------------------
# セッション状態の初期化
# ----------------------------------------------------------------------
if "view_mode" not in st.session_state:
    st.session_state["view_mode"] = "chat"
    
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "日本語"
if "clone_name" not in st.session_state:
    st.session_state["clone_name"] = "佐藤"
if "user_name" not in st.session_state:
    st.session_state["user_name"] = "ユーザー"
if "clone_avatar" not in st.session_state:
    st.session_state["clone_avatar"] = None
if "user_avatar" not in st.session_state:
    st.session_state["user_avatar"] = None

if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {"role": "assistant", "content": "HELLO_MSG_PLACEHOLDER"}
    ]

# ----------------------------------------------------------------------
# メイン画面ルーティング
# ----------------------------------------------------------------------
if st.session_state["view_mode"] == "thread_list":
    st.title(t["thread_list_title"])
    if st.button(t["back_to_chat"]):
        st.session_state["view_mode"] = "chat"
        st.rerun()
        
    threads = thread_db.get_all_threads()
    if not threads:
        st.info(t["no_threads"])
    else:
        for th in threads:
            dt_str = th["created_at"]
            with st.expander(f"💬 {th['title']} ... ({dt_str})"):
                st.write(f"**要約 / Summary:**\n{th['summary']}")
                if st.button("🔄 復元 / Restore", key=f"restore_{th['id']}"):
                    st.session_state.messages = th["messages"]
                    st.session_state["view_mode"] = "chat"
                    st.rerun()

elif st.session_state["view_mode"] == "chat":
    # ----------------------------------------------------------------------
    # メインチャット画面
    # ----------------------------------------------------------------------
    t = UI_TEXT[st.session_state["ui_lang"]]
    st.title(t["title"].format(st.session_state["clone_name"]))

    # これまでの会話履歴を表示
    for msg in st.session_state.messages:
        avatar = st.session_state["clone_avatar"] if msg["role"] == "assistant" else st.session_state["user_avatar"]
        
        with st.chat_message(msg["role"], avatar=avatar):
            if msg["content"] == "HELLO_MSG_PLACEHOLDER":
                st.markdown(t["hello_msg"].format(st.session_state["clone_name"]))
            else:
                st.markdown(msg["content"])

    # ユーザー入力
    if prompt := st.chat_input(t["chat_placeholder"].format(st.session_state["clone_name"])):
        
        # ユーザーの入力を画面に表示
        with st.chat_message("user", avatar=st.session_state["user_avatar"]):
            st.markdown(prompt)
        
        # 履歴に追加
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # クローンからの応答を生成・表示
        with st.chat_message("assistant", avatar=st.session_state["clone_avatar"]):
            with st.spinner(t["spinner_msg"]):
                try:
                    # orchestratorのステータスコールバック
                    def status_update(msg: str):
                        st.session_state["last_activity"] = msg
                        activity_placeholder.info(msg)

                    # Orchestratorを呼び出す
                    import orchestrator
                    response_text, tracker = orchestrator.run(
                        prompt, 
                        response_language=st.session_state["ui_lang"], 
                        status_callback=status_update,
                        clone_name=st.session_state["clone_name"],
                        user_name=st.session_state["user_name"]
                    )
                    
                    # サイドバーの完了更新
                    completed_msg = "✅ 推論完了" if st.session_state["ui_lang"] == "日本語" else "✅ Inference Complete"
                    st.session_state["last_activity"] = completed_msg
                    activity_placeholder.success(completed_msg)
                    
                    st.session_state["last_cost"] = tracker.summary(st.session_state["ui_lang"])
                    cost_placeholder.markdown(f"```text\n{st.session_state['last_cost']}\n```")
                    
                    # チャット画面には応答文章のみ表示
                    final_text = response_text
                    
                    st.markdown(final_text)
                    st.session_state.messages.append({"role": "assistant", "content": final_text})
                except Exception as e:
                    error_msg = t["error_msg"].format(e)
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

    # メッセージが複数（ユーザーの質問が含まれる）ある場合はボタン群を表示
    if len(st.session_state.messages) > 1:
        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            st.button(t["lbl_continue"], use_container_width=True, disabled=True)
                
        with col2:
            if st.button("✨ " + t["lbl_new"], use_container_width=True):
                st.session_state.messages = [
                    {"role": "assistant", "content": "HELLO_MSG_PLACEHOLDER"}
                ]
                st.rerun()
                
        with col3:
            if st.button(t["btn_save_thread"], use_container_width=True):
                with st.spinner("思考抽出中... / Extracting..."):
                    import orchestrator
                    success = orchestrator.process_and_save_thread(st.session_state.messages)
                    if success:
                        st.success(t["saved_success"])
                        st.session_state.messages = [
                            {"role": "assistant", "content": "HELLO_MSG_PLACEHOLDER"}
                        ]
                        import time
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error(t["saved_failed"].format("DB Error"))
                        
    # 画面下部への自動スクロール用ハック
    st.markdown(
        """
        <script>
            var body = window.parent.document.querySelector(".main");
            body.scrollTop = body.scrollHeight;
        </script>
        <div id="page-bottom"></div>
        """,
        unsafe_allow_html=True
    )

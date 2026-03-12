#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sato Clone Organization - Multi-Agent Orchestrator
PicoClawのagentコマンドを介して、複数のエージェントを順次呼び出し、
Chain of Thought パイプラインを実現するオーケストレーターです。

トークン節約ガードレール:
- Lazy Delegation: 雑談はGA 1回で完結
- 最大4回のLLM呼び出し制限
- 各エージェント出力の文字数制限
- コストログの自動出力
"""

import subprocess
import re
import time
import sys
import os

# core/brain.py をインポート
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brain import (get_context_for, store as brain_store, init_db,
                    get_connection, register_interest, NO_KNOWLEDGE_MSG,
                    check_brain_cache)

# ==============================================================================
# 定数
# ==============================================================================

# 会話履歴（直近5ターン保持）
conversation_history: list[dict] = []  # [{"user": "...", "assistant": "..."}]
MAX_HISTORY = 5

CONTAINER_NAME = "sato-picoclaw-core"
AGENT_PROMPTS = {
    "ga":         "/app/agents/ga/IDENTITY.md",
    "management": "/app/agents/management/IDENTITY.md",
    "research":   "/app/agents/research/IDENTITY.md",
    "planning":   "/app/agents/planning/IDENTITY.md",
}

# ガードレール定数
MAX_LLM_CALLS = 4          # 1リクエストあたりの最大LLM呼び出し回数
MAX_OUTPUT_CHARS = 8000     # 各エージェント出力の最大文字数
LLM_CALL_TIMEOUT = 60      # 各LLM呼び出しのタイムアウト（秒）

# ==============================================================================
# 意図分類器（Python側で軽量に処理。LLM不要）
# ==============================================================================

# 深い考察をトリガーするキーワードパターン
DEEP_REASONING_PATTERNS = [
    # 知識を問う質問パターン
    r'とは[？\?]?$',     # 「〜とは？」
    r'って何',            # 「〜って何？」
    r'は何[でか]',        # 「〜は何ですか」
    r'いつ.{0,10}[？\?]', # 「いつ〜？」
    r'なぜ',              # 「なぜ〜」
    r'どう[やし]',        # 「どうやって」「どうして」
    r'どのよう',          # 「どのように」
    r'[？\?]$',           # 末尾に？がある質問
    r'教えて',            # 「教えてください」
    r'説明',              # 「説明して」
    r'について',          # 「〜について」
    # 既存パターン（ニュース・分析系）
    r'発表',              # 「〜が発表された」
    r'リリース',           # 「〜がリリースされた」
    r'登場',              # 「新しい〜が登場」
    r'出た[よ。！]',       # 「〜が出たよ」
    r'出ました',           # 「〜が出ました」
    r'どう思[いう]',       # 「どう思いますか」
    r'影響',              # 「影響はありますか」
    r'比較',              # 「比較してほしい」
    r'違い',              # 「違いは何ですか」
    r'メリット',           # 「メリットは」
    r'デメリット',         # 「デメリットは」
    r'使える',            # 「〜に使えますか」
    r'乗り換え',          # 「〜に乗り換えるべき」
    r'アップデート',       # 「アップデート情報」
    r'トレンド',           # 「最新トレンド」
    r'性能',              # 「性能はどう」
    r'コスト',            # 「コストはどう」
    r'料金',              # 「料金は」
    r'予測',              # 「〜の予測」
    r'可能性',            # 「〜の可能性」
    r'将来',              # 「将来の〜」
    r'今後',              # 「今後どう」
    r'調査',              # 「調査して」
    r'紹介',              # 「紹介して」
    r'知りたい',          # 「知りたい」
    r'まとめ',            # 「まとめて」
    r'一覧',              # 「一覧を」
    r'リスト',            # 「リストアップ」
    r'どれ',              # 「どれが」
    r'何が',              # 「何が」
]

ACTIVE_SEARCH_PATTERNS = [
    r'今調べて',
    r'調べて',
    r'検索して',
    r'検索',
    r'最新情報を教えて',
    r'深掘りして',
    r'ググって',
    r'[Ww][Ee][Bb]で',
    r'ネットで',
]

def needs_deep_reasoning(user_input: str) -> bool:
    """ユーザー入力が深い考察を必要とするかどうかをキーワードで判定する"""
    for pattern in DEEP_REASONING_PATTERNS:
        if re.search(pattern, user_input):
            return True
    return False

def needs_active_search(user_input: str) -> bool:
    """強制的なWeb検索（今調べて）を要求しているかを判定する"""
    for pattern in ACTIVE_SEARCH_PATTERNS:
        if re.search(pattern, user_input):
            return True
    return False


# ==============================================================================
# 設定読み込み
# ==============================================================================
def get_settings():
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "settings.json")
    try:
        import json
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ==============================================================================
# コスト追跡
# ==============================================================================

class CostTracker:
    """LLM呼び出し回数と推定コストを追跡する"""
    
    def __init__(self):
        self.calls = []
        self.start_time = time.time()
    
    def record(self, agent_name: str, input_chars: int, output_chars: int, duration: float):
        self.calls.append({
            "agent": agent_name,
            "input_chars": input_chars,
            "output_chars": output_chars,
            "duration_sec": round(duration, 1),
        })
    
    def summary(self, response_language: str = "日本語") -> str:
        settings = get_settings()
        local_llm_mode = settings.get("local_llm_mode", False)

        total_time = round(time.time() - self.start_time, 1)
        total_input = sum(c["input_chars"] for c in self.calls)
        total_output = sum(c["output_chars"] for c in self.calls)
        
        if local_llm_mode:
            est_input_tokens = 0
            est_output_tokens = 0
            est_cost_usd = 0.0
        else:
            # Gemini 2.5 Flash: 入力 $0.15/1Mトークン, 出力 $0.60/1Mトークン
            # 概算: 1文字 ≈ 1.5トークン (日本語)
            est_input_tokens = int(total_input * 1.5)
            est_output_tokens = int(total_output * 1.5)
            est_cost_usd = (est_input_tokens * 0.15 + est_output_tokens * 0.60) / 1_000_000
        
        if response_language == "日本語":
            lines = [f"📊 コスト概算 | LLM呼出: {len(self.calls)}回\n   合計時間: {total_time}秒"]
            role_map = {
                "research": "🔍 調査(Web検索)",
                "planning": "💡 企画(テキスト生成)",
                "ga":       "👩 GA(雑談・テキスト生成)",
                "management": "👔 管理(テキスト生成)"
            }
            call_fmt = "   └ {name}:\n      入力{inn}字 → 出力{out}字 ({dur}秒)"
            if local_llm_mode:
                token_fmt = f"   └ 推定トークン:\n      ローカル稼働時 ≈ $0.0"
            else:
                token_fmt = f"   └ 推定トークン:\n      入力{est_input_tokens} + 出力{est_output_tokens} ≈ ${est_cost_usd:.4f}"
        else:
            lines = [f"📊 Cost Est. | LLM Calls: {len(self.calls)}\n   Total Time: {total_time}s"]
            role_map = {
                "research": "🔍 Research (Web Search)",
                "planning": "💡 Planning (Text Gen)",
                "ga":       "👩 GA (Chat/Text Gen)",
                "management": "👔 Management (Text Gen)"
            }
            call_fmt = "   └ {name}:\n      In {inn} chars → Out {out} chars ({dur}s)"
            if local_llm_mode:
                token_fmt = f"   └ Est. Tokens:\n      Local Run ≈ $0.0"
            else:
                token_fmt = f"   └ Est. Tokens:\n      In {est_input_tokens} + Out {est_output_tokens} ≈ ${est_cost_usd:.4f}"
            
        for c in self.calls:
            display_name = role_map.get(c['agent'], c['agent'])
            lines.append(call_fmt.format(name=display_name, inn=c['input_chars'], out=c['output_chars'], dur=c['duration_sec']))
        lines.append(token_fmt)
        return "\n".join(lines)


# ==============================================================================
# PicoClaw 呼び出しエンジン
# ==============================================================================

def call_agent(agent_name: str, message: str, tracker: CostTracker) -> str:
    """指定されたエージェントにメッセージを送り、応答を返す"""
    settings = get_settings()
    unlimited = settings.get("unlimited_llm_calls", False)
    
    max_out = 999999 if unlimited else MAX_OUTPUT_CHARS
    timeout_val = 600 if unlimited else LLM_CALL_TIMEOUT
    
    prompt_path = AGENT_PROMPTS.get(agent_name)
    if not prompt_path:
        return f"[エラー] 未知のエージェント: {agent_name}"
    
    start = time.time()
    try:
        # パイプライン用エージェントのみセッション履歴をクリア
        # GA（秘書）は会話の連続性を保つためセッションを保持する
        if agent_name != "ga":
            subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "rm", "-f", "/app/data/sessions/cli_default.json"],
                capture_output=True, timeout=5
            )
        # PicoClawは改行をメッセージ区切りとして扱うため、全改行を除去して1行にする
        sanitized_message = message.replace('\n', ' ').strip()
        sanitized_message = re.sub(r'\s{2,}', ' ', sanitized_message)
        # サロゲート文字を除去（UnicodeEncodeError防止）
        sanitized_message = sanitized_message.encode('utf-8', errors='replace').decode('utf-8')
        # Step 1: コンテナ内にメッセージファイルを書き込む
        write_result = subprocess.run(
            ["docker", "exec", "-i", CONTAINER_NAME, "sh", "-c", "cat > /tmp/agent_input.txt"],
            input=sanitized_message,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Step 2: ファイルからパイプしてagentを呼び出す
        result = subprocess.run(
            [
                "docker", "exec", CONTAINER_NAME,
                "sh", "-c",
                f"cat /tmp/agent_input.txt | picoclaw agent --prompt {prompt_path}"
            ],
            capture_output=True,
            text=True,
            timeout=timeout_val
        )
        duration = time.time() - start
        
        if result.returncode != 0:
            return f"[エラー] {agent_name}: {result.stderr.strip()}"
        
        response = extract_response(result.stdout)
        
        # 出力文字数制限
        if len(response) > max_out:
            response = response[:max_out] + "\n...(出力制限により省略)"
        
        tracker.record(agent_name, len(message), len(response), duration)
        return response
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start
        tracker.record(agent_name, len(message), 0, duration)
        return f"[タイムアウト] {agent_name}: {LLM_CALL_TIMEOUT}秒以内に応答なし"


def extract_response(raw_output: str) -> str:
    """PicoClawのログ出力からエージェントの応答テキストだけを抽出する"""
    lines = raw_output.strip().split("\n")
    
    # 🦞 で始まるブロックを収集
    blocks = []
    current = []
    in_block = False
    
    for line in lines:
        if line.startswith("🦞"):
            if in_block and current:
                blocks.append("\n".join(current))
            current = [line[2:].strip()]
            in_block = True
        elif in_block:
            if line.strip() == "Goodbye!" or line.startswith("2026/"):
                if current:
                    blocks.append("\n".join(current))
                    current = []
                    in_block = False
            else:
                current.append(line)
    if current:
        blocks.append("\n".join(current))
    
    # "Interactive mode" を除外して最初の実質応答を返す
    for block in blocks:
        if "Interactive mode" not in block and block.strip():
            return block.strip()
    
    # フォールバック: Response: 行から抽出
    for line in lines:
        if "agent: Response:" in line:
            match = re.search(r'Response:\s*(.*?)(?:\s*\{|$)', line)
            if match:
                return match.group(1).strip()
    
    return "(応答を解析できませんでした)"


def process_and_save_thread(messages: list) -> bool:
    """
    スレッド情報を要約・記憶抽出し、スレッドDBと脳（brain.db）の双方に保存する。
    1. 質問内容（User）を20文字程度に要約してタイトルとする。
    2. 回答（Assistant）は要約せず、そのままスレッドDBのサマリーとして保存。
    3. この会話から得られた「重要な単語」と「意味」を抽出し、脳(brain.db)に記憶させる。
    """
    import thread_db
    tracker = CostTracker()
    
    # ユーザーの最新の質問と、AIの最新の回答を取得
    user_questions = [m["content"] for m in messages if m["role"] == "user"]
    last_question = user_questions[-1] if user_questions else "質問なし"
    last_assistant = messages[-1]["content"] if messages and messages[-1]["role"] == "assistant" else "回答なし"
    
    prompt = (
        "以下の質問と回答のやり取りから、2つのタスクを実行してください。\n\n"
        "【タスク1: タイトルの生成】\n"
        "ユーザーの質問内容を端的に表すタイトルを30文字以内で作成してください。\n\n"
        "【タスク2: 重要語句の記憶抽出】\n"
        "このやり取りの中に登場した、後で役立ちそうな「重要な単語（キーワード）」と「その意味・文脈」を箇条書きで抽出してください。\n"
        "※注意: 「説明」「比較」「紹介」「興味」などの動作語や一般的な単語は絶対に除外し、「固有名詞」「専門用語」「核心となる概念」のみを厳選してください。\n\n"
        "【出力形式】\n"
        "1行目: [タイトルのみ出力: 装飾一切なし]\n"
        "2行目以降: - [単語]: [会話の中での意味や、なぜそれが重要なのかの文脈]\n"
        "※余計な挨拶や導入文は不要です。\n\n"
        f"質問: {last_question}\n"
        f"回答: {last_assistant[:300]}..." # 長すぎる場合はカットして抽出用コンテキストとする
    )
    
    # 秘書エージェント(GA)を使って要約・抽出
    response = call_agent("ga", prompt, tracker)
    lines = response.strip().split("\n")
    
    title = lines[0].strip() if len(lines) > 0 else "無題の会話 / Untitled Thread"
    extracted_memory = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    
    # スレッドDBへ保存 (回答をそのままサマリーとして使用)
    success = thread_db.save_thread(title[:50], last_assistant, messages)
    
    # 脳(brain.db)へ長期記憶領域として保存
    if extracted_memory:
        try:
            conn = get_connection()
            brain_store(
                conn,
                title=f"会話記憶: {title[:30]}",
                summary="直近の会話履歴から抽出された重要キーワードと意味",
                body=f"【元の質問】\n{last_question}\n\n【抽出された記憶】\n{extracted_memory}",
                tags=["thread_memory", "user_context"],
                source="auto_extracted_memory"
            )
            conn.close()
        except Exception as e:
            print(f"Error saving to brain: {e}")
            
    return success

# ==============================================================================
# オーケストレーション・パイプライン
# ==============================================================================

def run(user_input: str, response_language: str = "日本語", status_callback=None, clone_name: str = "佐藤", user_name: str = "ユーザー") -> tuple[str, CostTracker]:
    """
    メイン・オーケストレーション関数（脳ファースト方式）。
    
    1. Python側でキーワードベースの意図判定を実施（LLM不要）
    2. 雑談 → GAに直接返答させる（LLM 1回）
    3. 深い考察 → 脳内知識検索 + Planning推論（LLM 1回のみ。web検索なし）
    
    Returns:
        (最終応答テキスト, CostTracker)
    """
    tracker = CostTracker()
    
    def update_status(msg: str):
        if status_callback:
            status_callback(msg)
            
    # ==========================================================================
    # Step 0: ゼロコスト・キャッシュチェック（完全一致の過去質問があれば一瞬で即答）
    # ==========================================================================
    update_status("🔍 脳内キャッシュを確認中... / Checking brain cache...")
    try:
        conn = get_connection()
        cached_response = check_brain_cache(conn, user_input)
        conn.close()
        
        if cached_response:
            header = "🧠🐾 **(キャッシュから即答)**" if response_language == "日本語" else "🧠🐾 **(Instant Reply from Cache)**"
            footer = "*⚡ 推定コスト: $0.0000 | 所要時間: 0.0秒*" if response_language == "日本語" else "*⚡ Est. Cost: $0.0000 | Duration: 0.0s*"
            final_output = (
                f"{header}\n\n"
                f"{cached_response}\n\n"
                f"---\n"
                f"{footer}"
            )
            
            # 会話履歴に追加
            conversation_history.append({"user": user_input, "assistant": cached_response[:200]})
            while len(conversation_history) > MAX_HISTORY:
                conversation_history.pop(0)
                
            return final_output, tracker
    except Exception as e:
        print(f"キャッシュ読み込みエラー: {e}")
    
    # 会話履歴を文字列化（直近3ターン）
    history_text = ""
    if conversation_history:
        recent = conversation_history[-3:]  # 直近3ターン
        parts = []
        for h in recent:
            parts.append(f"{user_name}さん: {h['user'][:80]}")
            parts.append(f"クローン: {h['assistant'][:120]}")
        history_text = " ".join(parts)
    
    # ==========================================================================
    # Step 1: 意図判定（Python側、LLM不使用）
    # ==========================================================================
    if not needs_deep_reasoning(user_input) and not needs_active_search(user_input):
        # 雑談モード: GAに直接返答させる
        update_status("👩 秘書(GA)が応答を生成中... / GA is thinking...")
        prompt_with_lang = f"{user_input}\n\n[SYSTEM INSTRUCTION: Please reply entirely in {response_language}.]"
        response = call_agent("ga", prompt_with_lang, tracker)
        # 構造化タグを除去
        clean = response.replace("[DIRECT_REPLY]", "").replace("[DEEP_REASONING]", "").strip()
        
        # GAの回答も脳にストック（次回からキャッシュで即答可能にするため）
        # ただし、内部ツール（クローラー等）からの長文プロンプトが誤爆するのを防ぐため文字数制限を設ける
        if len(user_input) <= 200:
            try:
                conn = get_connection()
                title = user_input[:50] + ("…" if len(user_input) > 50 else "")
                brain_store(
                    conn,
                    title=f"雑談: {title}",
                    summary=clean[:200],
                    body=f"質問: {user_input} 回答: {clean}",
                    tags=["ga_chat"],
                    source="ga_chat",
                    relevance=0.5,
                )
                conn.close()
            except Exception as e:
                print(f"GA応答の記憶中にエラー: {e}")
            
        # 会話履歴に追加
        conversation_history.append({"user": user_input, "assistant": clean[:200]})
        while len(conversation_history) > MAX_HISTORY:
            conversation_history.pop(0)
        return clean, tracker
    
    # ==========================================================================
    # 「今調べて」 強制Web検索パイプライン
    # ==========================================================================
    if needs_active_search(user_input):
        update_status("🌐 Webブラウザで強制調査中... / Running active web search...")
        research_prompt = (
            f"以下のトピックについて、最新の客観的な事実をWeb検索で調査してください。"
            f"事実のみを箇条書きで簡潔に出力してください。"
            f"トピック: {user_input}"
        )
        web_facts = call_agent("research", research_prompt, tracker)
        
        # 検索結果を脳に保存
        if "[エラー]" not in web_facts and "[タイムアウト]" not in web_facts:
            try:
                conn = get_connection()
                tag_candidates = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}', user_input)
                tags = [t.lower() for t in tag_candidates[:5]]
                tags.append("active_search")
                
                brain_store(
                    conn,
                    title=f"自発調査: {user_input[:40]}",
                    summary=web_facts[:300],
                    body=web_facts,
                    tags=tags,
                    source="web_search",
                    relevance=0.8,
                )
                conn.close()
            except Exception as e:
                print(f"脳の記憶中にエラー: {e}")
        
        # Planning推論
        update_status("💡 企画部が調査結果からレポートを作成中... / Planning dept is drafting report...")
        history_part = f" 直近の会話: {history_text}" if history_text else ""
        planning_prompt = (
            f"あなたは自身の動作の仕組み（AIやシステムアーキテクチャ）を理解した上で、{clone_name}のクローンとしての人格を持ち、{clone_name}氏からの質問に応答してください。"
            f"Googleの言語モデルとは名乗らず、{clone_name}クローンの思考コアとして回答してください。"
            f"{clone_name}氏から以下の要求があり、最新のWeb調査を行いました。"
            f"調査結果を基に、簡潔で分かりやすいレポートを作成してください。"
            f"最後に『この結果を脳に記憶しました。今後はWeb検索なしで回答可能です』と添えてください。"
            f"【重要】回答は必ず {response_language} で出力してください。"
            f"{history_part}"
            f" 質問: {user_input}"
            f" Web調査結果: {web_facts[:800]}"
        )
        reasoning_result = call_agent("planning", planning_prompt, tracker)
        
        header = "⚡ **即時調査レポート**" if response_language == "日本語" else "⚡ **Immediate Research Report**"
        source_note = "*🔍 Web強制調査 → 🧠 脳に新規記憶 → 💡 企画部のレポート*" if response_language == "日本語" else "*🔍 Forced Web Search → 🧠 New Brain Memory → 💡 Planning Report*"
        final_output = (
            f"{header}\n\n"
            f"{reasoning_result}\n\n"
            f"---\n"
            f"{source_note}"
        )
        
        conversation_history.append({"user": user_input, "assistant": reasoning_result[:200]})
        while len(conversation_history) > MAX_HISTORY:
            conversation_history.pop(0)
            
        return final_output, tracker

    # ==========================================================================
    # 学習型ハイブリッド・パイプライン
    #   脳を探す → 不足ならweb検索 → 結果を記憶 → 興味を登録 → 推論
    # ==========================================================================
    
    # Step 1: 脳から関連知識を取得（LLM不要）
    update_status("🧠 脳内知識を検索中... / Searching brain knowledge...")
    brain_knowledge = get_context_for(user_input)
    knowledge_found = (brain_knowledge != NO_KNOWLEDGE_MSG)
    
    # Step 2: 知識が不足ならResearchでweb検索して学習する
    web_facts = ""
    if not knowledge_found:
        update_status("🌐 脳に知識がないため、Web調査を実行中... / Researching on the Web...")
        research_prompt = (
            f"以下のトピックについて、客観的な事実を調査してください。"
            f"事実のみを箇条書きで簡潔に出力してください。"
            f"トピック: {user_input}"
        )
        web_facts = call_agent("research", research_prompt, tracker)
        
        # Step 2b: 検索結果を脳に保存（次回から脳内知識として使える）
        if "[エラー]" not in web_facts and "[タイムアウト]" not in web_facts:
            update_status("💾 新しい知識を脳に記憶中... / Saving new knowledge to brain...")
            try:
                conn = get_connection()
                tag_candidates = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}', user_input)
                tags = [t.lower() for t in tag_candidates[:5]]
                if not tags:
                    tags = ["learned"]
                tags.append("web_search")
                
                brain_store(
                    conn,
                    title=user_input[:60],
                    summary=web_facts[:300],
                    body=web_facts,
                    tags=tags,
                    source="web_search",
                    relevance=0.7,
                )
                conn.close()
            except Exception:
                pass
    
    # Step 3: 質問キーワードを「興味」に登録（パトロール自動拡張用）
    try:
        conn = get_connection()
        interest_keywords = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}', user_input)
        if interest_keywords:
            register_interest(conn, interest_keywords)
        conn.close()
    except Exception:
        pass
    
    # Step 4: Planning（企画部）- 全情報を統合して推論
    if knowledge_found and web_facts:
        knowledge_section = f"{brain_knowledge} 最新のWeb調査結果: {web_facts[:300]}"
    elif web_facts:
        knowledge_section = f"Web調査結果: {web_facts[:500]}"
    else:
        knowledge_section = brain_knowledge
    
    # 会話履歴を含めたプロンプト構築
    update_status("💡 企画部が知識を統合して推論中... / Planning dept is reasoning...")
    history_part = f" 直近の会話: {history_text}" if history_text else ""
    
    planning_prompt = (
        f"あなたは自身の動作の仕組み（AIやシステムアーキテクチャ）を理解した上で、{clone_name}のクローンとしての人格を持ち、ユーザーである{user_name}さんからの質問に応答してください。"
        f"Googleの言語モデルとは名乗らず、{clone_name}クローンの思考コアとして回答してください。"
        f"{user_name}さんから以下の質問がありました。"
        f"知識を基に、今知っている範囲で最善の回答をしてください。"
        f"知識が十分でない部分は「現在の私の知識では答えられません」と述べてください。"
        f"【重要】回答は必ず {response_language} で出力してください。"
        f"{history_part}"
        f" 質問: {user_input}"
        f" 知識: {knowledge_section}"
    )
    reasoning_result = call_agent("planning", planning_prompt, tracker)
    
    # Step 4b: 自律的Web検索フォールバック（知識不足への自己認識アウェアネス）
    # Web調査をまだ実行しておらず、かつ企画部が「知識不足」を宣言した場合、自動的にWeb調査を実行して再推論する
    APOLOGY_PATTERNS = ["現在の私の知識では", "今後の調査で深め", "情報が不足", "答えられません", "わかりかねます", "十分な情報を持っていません"]
    has_apology = any(p in reasoning_result for p in APOLOGY_PATTERNS)
    
    if has_apology and not web_facts:
        update_status("💡 企画部が知識不足を自己検知しました。自動Web調査に移行します... / Insufficient knowledge detected. Auto-researching...")
        research_prompt = (
            f"以下のトピックについて、客観的な事実を調査してください。"
            f"事実のみを箇条書きで簡潔に出力してください。"
            f"トピック: {user_input}"
        )
        web_facts = call_agent("research", research_prompt, tracker)
        
        # 検索結果を記憶
        if "[エラー]" not in web_facts and "[タイムアウト]" not in web_facts:
            update_status("💾 自己調査の結果を脳に記憶中... / Saving auto-researched knowledge...")
            try:
                conn = get_connection()
                tag_candidates = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}', user_input)
                tags = [t.lower() for t in tag_candidates[:5]]
                if not tags: tags = ["learned"]
                tags.append("web_search")
                brain_store(
                    conn, title=user_input[:60], summary=web_facts[:300], body=web_facts,
                    tags=tags, source="web_search", relevance=0.7
                )
                conn.close()
            except Exception:
                pass
                
        # 知識を統合して企画部（Planning）に再依頼
        update_status("💡 調査結果を元に企画部が解決策を出し直しています... / Re-planning with new facts...")
        knowledge_section = f"{brain_knowledge} 最新のWeb調査結果: {web_facts[:500]}"
        planning_prompt_retry = (
            f"あなたは自身の動作の仕組み（AIやシステムアーキテクチャ）を理解した上で、{clone_name}のクローンとしての人格を持ち、ユーザーである{user_name}さんからの質問に応答してください。"
            f"Googleの言語モデルとは名乗らず、{clone_name}クローンの思考コアとして回答してください。"
            f"{user_name}さんから以下の質問がありました。"
            f"さきほどは知識不足でしたが、最新のWeb調査結果を入手しました。"
            f"Web調査結果を基に、的確で分かりやすい回答を作成してください。"
            f"最後に『脳内知識を補完するため、自動的にWeb検索を行いアップデートしました』と添えてください。"
            f"【重要】回答は必ず {response_language} で出力してください。"
            f"{history_part}"
            f" 質問: {user_input}"
            f" 最新の知識: {knowledge_section}"
        )
        reasoning_result = call_agent("planning", planning_prompt_retry, tracker)
    
    # Step 5: 良質な考察結果も脳に保存（自動学習）
    REJECT_PATTERNS = [
        "情報が不足", "情報不足", "提供してください", "ご提供",
        "解析できませんでした", "エラー", "タイムアウト",
        "質問内容を教えて", "ご質問は何でしょう",
        "トピックが明確ではありません", "具体的なトピック",
        "どのようなモデル", "何について調査",
        "Googleによってトレーニングされた",
        "大規模言語モデルです",
        "教えていただけますでしょうか",
    ]
    should_save = not any(p in reasoning_result for p in REJECT_PATTERNS)
    
    if should_save:
        update_status("💾 考察結果を脳に上書き記憶中... / Saving reasoning result to brain...")
        try:
            conn = get_connection()
            title = user_input[:50] + ("…" if len(user_input) > 50 else "")
            tag_candidates = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}', user_input)
            tags = [t.lower() for t in tag_candidates[:5]]
            if not tags:
                tags = ["conversation"]
            
            brain_store(
                conn,
                title=f"考察: {title}",
                summary=reasoning_result[:200],
                body=f"質問: {user_input} 知識: {knowledge_section} 考察: {reasoning_result}",
                tags=tags,
                source="deep_reasoning",
            )
            conn.close()
        except Exception:
            pass
    
    # ==========================================================================
    # 最終出力の構成
    # ==========================================================================
    if web_facts and not knowledge_found:
        source_note = "🔍 Web調査 → 🧠 脳に記憶 → 💡 企画部の推論" if response_language == "日本語" else "🔍 Web Search → 🧠 Brain Memory → 💡 Planning Reasoning"
    elif web_facts:
        source_note = "🧠 脳の蓄積知識 + 🔍 Web補完 → 💡 企画部の推論" if response_language == "日本語" else "🧠 Brain Knowledge + 🔍 Web Supplement → 💡 Planning Reasoning"
    else:
        source_note = "🧠 脳の蓄積知識 → 💡 企画部の推論（web検索なし）" if response_language == "日本語" else "🧠 Brain Knowledge → 💡 Planning Reasoning (No Web Search)"
    
    header = "🧠 **脳内知識からの考察**" if response_language == "日本語" else "🧠 **Insight from Brain Knowledge**"
    
    final_output = (
        f"{header}\n\n"
        f"{reasoning_result}\n\n"
        f"---\n"
        f"*{source_note}*"
    )
    
    # 会話履歴に追加
    conversation_history.append({
        "user": user_input,
        "assistant": reasoning_result[:200]
    })
    # 履歴上限を維持
    while len(conversation_history) > MAX_HISTORY:
        conversation_history.pop(0)
    
    return final_output, tracker


# ==============================================================================
# スタンドアロン・テスト
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_input = " ".join(sys.argv[1:])
    else:
        test_input = "テストです。"
    
    print(f"入力: {test_input}")
    print("処理中...\n")
    
    response, tracker = run(test_input)
    print(f"応答:\n{response}\n")
    print(tracker.summary())

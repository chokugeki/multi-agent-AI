# Sato Digital Clone Organization (PicoClaw)

AIエージェントによる自律的な組織運営をシミュレート・実行するための、マルチエージェント・アーキテクチャプラットフォームです。
「総務部」「企画部」「調査部」などの役割を持った複数のAIエージェントが、MQTTを通じて連携・情報共有を行い、自律的に思考し行動します。

バックエンドエンジンとして軽量かつ強力な **PicoClaw** を採用し、Telegramなどの外部インターフェースと連携して動作します。

## 🌟 特徴
- **マルチエージェント構成**: 役割分担されたエージェントたちが連携してタスクを処理。
- **自律的パトロール**: 指定したトピックに関する情報を定期的に収集・分析し、記憶として蓄積。
- **Brain (記憶システム)**: SQLiteとFTS5（全文検索）を活用したベクトルレスの高速な知識検索と、時間の経過とともに古い情報が忘れられる（減衰する）自律的な記憶管理。
- **Telegram連携**: 外部からのコマンド入力やエージェントからの自律的な報告をTelegram経由で送受信可能。

## 🚀 環境構築（使い方）

このリポジトリをローカル環境で動かすための手順です。
前提条件として、**Docker** および **Docker Compose** がインストールされている必要があります。

### 1. リポジトリのクローン
```bash
git clone https://github.com/chokugeki/multi-agent-AI.git
cd multi-agent-AI
```

### 2. 環境変数の設定
システムを動かすためには、LLM（Gemini等）のAPIキーと、連携用のTelegram Botの情報の2つが必要です。
`config/ global.env` という設定ファイルを作成し、以下の内容を記述します。

1. `config/global.env` ファイルを作成（またはコピー）します。
2. 以下の内容を自身の情報に書き換えて保存してください。

```env
# ==========================================
# Sato Digital Clone Organization - Global Env
# ==========================================

# --- Telegram Settings ---
# BotFather (@BotFather) で作成したBotのトークン
TELEGRAM_BOT_TOKEN=ここにTelegramのボットトークンを記載

# あなたのChat ID (例: 12345678)
# IDを取得するには @userinfobot などに話しかけてください
TELEGRAM_USER_ID=ここに管理者のChatIDを記載

# --- LLM API Settings ---
# Google AI Studio 等で生成した API キー
GLOBAL_API_KEY=ここにAPIキーを記載
```

> **⚠️ 注意事項:**
> `global.env` ファイルには重要な秘密情報が含まれます。すでに `.gitignore` でGitの管理対象外に設定されていますので、絶対にコミット・公開しないように注意してください。

### 3. コンテナの起動
Docker Composeを使って、MQTTブローカー、PicoClawコア、Gateway Bridge（Telegram連携）の各コンテナを一括で起動します。

```bash
docker-compose up -d
```

このコマンドを実行すると、初回は必要なイメージがダウンロード・ビルドされ、システムがバックグラウンドで起動します。

### 4. 動作確認
起動後、コンテナのログを確認して、エラーが出ていないかチェックします。

```bash
# PicoClaw本体のログを確認
docker-compose logs -f picoclaw-core

# Telegram連携部分のログを確認
docker-compose logs -f gateway-bridge
```
ログに `Agent initialized` や `Telegram Gateway is running...` と出力されていれば起動成功です！
TelegramからBot宛にメッセージを送信し、応答が返ってくるか確認してください。

## 🛑 停止方法
システムを停止する場合は、以下のコマンドを実行します。

```bash
docker-compose down
```

## 📂 構成ファイル・フォルダ解説
- `agents/`: 各エージェント（企画部、開発部など）のプロンプト・性格設定(`.md`)
- `bridge/`: Telegramとの接続を行うシステムコード
- `config/`: システム全体の設定(`config.json`)や経路設定(`topology.yaml`)
- `core/`: 組織の脳となる記憶システム(`brain.py`)など
- `data/`: 記憶データベースやログが自動的に保存されるフォルダ
- `infrastructure/`: 起動用スクリプトやツール群関連
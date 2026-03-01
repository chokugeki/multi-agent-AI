# 佐藤マルチエージェントプランと経過 (Sato Digital Clone Organization)

## 1. プロジェクト概要と運用環境
* **目的:** 自身の思考と行動を複製・拡張するマルチエージェントシステムの構築。
* **運用ハードウェア:** ノートPC（BakusokuNote / Pentium 4415U）。
    * **最適解は「ノートPC上でのローカルエージェント稼働」**ですが、ほかに「クラウド（GCP等）での常時稼働」という候補もあり、違いは**「機密データのローカル完結性とランニングコストの有無」**です。現状はノートPCのリソース制約下で最適化を図ります。
* **コアエンジン:** PicoClaw Native (v0.1.2)
* **LLM:** Gemini 2.0 Flash (Free Tier)
* **将来展望:** Antigravity（Node.js/TypeScript標準）での開発拡充、およびGCPへのデプロイによる汎用化・販売プラットフォーム化。

---

## 2. Dockerによるインフラ基盤（技術解説）

本システムはDockerを用いて構築されています。

* **Docker採用の理由:**
    * **最適解は「Docker Composeによるコンテナ化」**ですが、ほかに「ホストOSへの直接インストール（ベアメタル）」という候補もあり、違いは**「環境汚染の防止と、GCP等への移行（ポータビリティ）の容易さ」**です。
* **詳細な仕組み:**
    * **隔離環境 (Container):** 仮想マシンのように重いOSを丸ごと立ち上げるのではなく、ホストOSのカーネルを共有しつつ、プロセスやファイルシステムを隔離する技術です。これにより、Pentium 4415Uのような限られたリソースでも複数のサーバー（MQTT、Python、PicoClaw）を同時に軽量動作させることができます。
    * **IaC (Infrastructure as Code):** `docker-compose.yml` にインフラ構成を記述することで、GCPへ移行する際もコマンド一発で同じ環境を完全再現できます。
* **構成サービス:**
    1.  `mqtt-broker`: エージェント間の神経伝達物質（メッセージ）を運ぶバス。
    2.  `picoclaw-core`: 実際のAI推論を行う頭脳部。
    3.  `gateway-bridge`: TelegramとMQTTを翻訳する境界サーバー。

---

## 3. マルチエージェントの命令系統とアーキテクチャ

組織（マルチエージェント）の指揮系統は、厳密なトピックルーティングによって制御されています。

* **アーキテクチャ設計:**
    * **最適解は「総務部（GA）を単一の窓口とするFacadeパターン」**ですが、ほかに「全エージェントがユーザーからの命令を直接リッスンする」候補もあり、違いは**「命令の競合回避と、組織としてのタスクの適切なトリアージ（振り分け）能力」**です。

### 3.1 窓口としての総務部 (General Affairs) と Telegram の連携
1.  **ユーザー入力 (Telegram):** ユーザーはスマホやPCのTelegramアプリからBot宛てにメッセージを送信します。
2.  **プロトコル変換 (Gateway):** 外部ネットワークからの入力を `gateway-bridge` が受け取り、MQTTメッセージ（トピック: `sato/command/external`）に変換して組織内部へブロードキャストします。
3.  **一次受付 (総務部/GA):** `topology.yaml` の設定により、この `external` トピックを購読（サブスクライブ）しているのは **総務部 (ga_agent)** と **保健部** のみです。
4.  **トリアージと指示:** 総務部はユーザーの意図を解釈し、「これは開発部案件だ」「これは調査部が必要だ」と判断した場合、内部トピック（例: `sato/collab/ask/development`）へメッセージを再送信（パブリッシュ）し、専門部署を動かします。
5.  **返答の集約:** 各部署での処理が終わると、結果は再び総務部へ返され、総務部が最終的なレポートとして `sato/report/ceo` にパブリッシュし、Telegram経由でユーザーに届きます。

### 3.2 部署別トピック権限（例）

| 部署 (Agent) | 役割 | リッスン(Sub)するトピック | パブリッシュ(Pub)するトピック |
| :--- | :--- | :--- | :--- |
| **総務部 (GA)** | 外部窓口・全体統括 | `sato/command/external`<br>`sato/collab/response/+` | `sato/report/ceo`<br>`sato/collab/ask/*` |
| **開発部 (Dev)** | Antigravity/アプリ開発 | `sato/collab/ask/development` | `sato/collab/response/ga` |
| **企画部 (Plan)** | 新規プロジェクト立案 | `sato/collab/ask/planning` | `sato/collab/ask/research`<br>`sato/collab/response/ga` |
| **管理部 (Mgmt)** | 記憶・ログの管理 | `sato/report/#` | `sato/log/memory_status` |

---

## 4. ディレクトリ・ファイル構成

```text
sato-clone-org/
├── docker-compose.yml          # コンテナ群の設計図 (version属性は廃止済)
├── config/
│   ├── global.env              # 秘匿情報 (API Key, Telegram ID)
│   ├── topology.yaml           # PicoClawの神経網定義 (Channels/Nodes)
│   └── config.json             # 【重要】PicoClaw起動用グローバル設定
├── data/                       # 各エージェントのワークスペース・長期記憶
├── infrastructure/
│   └── mosquitto/              # MQTTブローカー設定・ログ
├── bridge/
│   └── telegram_gateway.py     # Telegram-MQTT変換スクリプト
└── agents/                     # 組織の部署ごとの人格・規約定義
    ├── ga/IDENTITY.md
    ├── development/IDENTITY.md # ※Antigravity (Node.js/TS) 開発規約を注入予定
    └── (他7部署のIDENTITY.md)
```

## 5. デバッグ・ナレッジ（発生した問題と解決策）
PicoClaw特有の仕様や、環境構築時に突破した技術的課題の記録です。

* **Docker権限エラー:** `docker.sock` のパーミッション不足。`chmod 666` にて解決。
* **Telegram競合エラー:** ホストPC側でのPythonスクリプト二重起動によるToken Conflict。ホスト側プロセスを強制終了（`pkill`）して解決。
* **PicoClaw glm-4.7 フォールバック問題:** PicoClaw v0.1.2 において `topology.yaml` のLLM設定が無視され、デフォルトモデル（ZhipuAI）のAPIキーを要求してクラッシュするバグ。
    * **対策:** 階層構造を持つ専用の `config.json` を作成し、コンテナ内の `/root/.picoclaw/config.json` へ強制マウントさせることで回避。
* **MQTT通信の沈黙（No channels enabled）:** `agent` コマンドが対話専用モードであったため、ネットワーク通信を無視していた。
    * **対策:** 実行コマンドを `gateway` に変更し、`topology.yaml` に `channels: mqtt:` ブロックを明示的に追記して通信手段を確立。
* **Gemini API 429 エラー:** Free Tierのレートリミット到達。待機処理による自然回復。

## 6. 今後の展望とアクション
* **初期疎通:** MQTTチャンネル設定を完了させ、Telegramからの最初の応答（総務部からのレポート）を確認する。
* **開発規約の注入:** 開発部 (`development/IDENTITY.md`) に対し、Antigravity上の開発手法、Node.js、TypeScriptの標準仕様をプロンプトとして組み込む。
* **記憶の統合:** 管理部を通じて、「4D Financial Cartography」や「Daycare Manager」といった既存プロジェクトの仕様をエージェントに学習させる。
* **GCPデプロイ準備:** 汎用パッケージ化を見据え、Dockerイメージの軽量化およびデプロイメント構成の設計を行う。

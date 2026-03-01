# ナレッジ統合と記憶の引き出し（Knowledge Retrieval）仕様

Management（管理部）が、Sato氏特有の「過去の文脈・プロジェクト履歴・コスト感覚」などを引き出すための仕様です。

## 1. 記憶ストレージの構造 (Storage Structure)
将来的なスケーラビリティ（ベクトルDBへのシームレスな移行）を考慮し、まずはプレーンテキストのMarkdownとして保存・検索する手法を採ります。

```text
sato-clone-org/data/memory/
├── 2026-02-18_ApiCostConcerns.md     # APIコストに関する過去のやり取り
├── 2026-02-19_AntigravityVision.md   # Antigravity連携に関する野望
└── 2026-02-20_PicoClawSetup.md      # PicoClaw軽量アーキテクチャの導入
```

## 2. Managementエージェントの処理フレームワーク (Prompt Framework)

Managementエージェントは、`sato/pipeline/reasoning/start` トピックを受信した際、以下の思考プロセスを経て文脈（Context）を生成します。

**【Managementのプロンプト構成案】**
1. **入力解析:** ユーザーの入力（例：「Gemini 3.1が出た」）からKey Term（Gemini, AI, コスト, バージョンアップ等）を抽出する。
2. **記憶の検索 (Retrieval):**
   - *（※現状のPicoClaw v0.1.2では、ファイルシステムを直接grepするTool機能が必要になります。今後のアップデートでManagementに `search_memory_files` ツールを付与する想定です。）*
   - キーワードに関連するMarkdownファイルを検索し、該当する過去の記述を抽出する。
3. **文脈の再構築 (Contextualization):**
   - 抽出した過去の事実を、単なるコピペではなく「Sato氏にとっての前提条件」として要約する。
   - 例: 「Sato氏は過去にAPIレートリミット（15 RPM）による制限を懸念しており、コスト削減とコンテキスト長（トークン数）の拡大に強い関心を持っています。」
4. **出力 (Publish):** 整理された文脈を `sato/pipeline/reasoning/context` へパブリッシュし、企画部（Planning）にパスする。

## 3. 調査部から企画部へのファクト提供の形式

Research（調査部）は事実のみを収集します。企画部に渡す際のフォーマットは以下のように統一し、ノイズを減らします。

**【Facts Format】**
* **トピック:** Gemini 3.1 発表情報
* **検証済み事実:**
    - [事実1] コンテキストウィンドウが200万トークンに倍増。
    - [事実2] API利用料金（入力・出力）がGemini 1.5 Flashから約50%低下。
    - [事実3] 応答速度（レイテンシ）が改善。
* **情報ソース:** (URL等)
* **特記事項:** (主観は含めず、記事に記載されていた事実のみ)

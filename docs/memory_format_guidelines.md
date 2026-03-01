# 長期記憶保存フォーマット (Long-term Memory Format)

管理部（Management Agent / Scribe）が組織内の通信ログやユーザーのアイデアを長期保存する際のフォーマット定義です。
実際のファイルはDockerコンテナが `data/memory/` フォルダ配下に自動生成し保存します。

## ファイル命名規則
* `YYYY-MM-DD_TopicName.md`  (例: `2026-02-20_ArchitectureIdea.md`)
* 単純なデイリーログの場合は `YYYY-MM-DD_DailyLog.md` とする。

## 構造化フォーマット
管理部は傍受した情報を以下のMarkdown形式に整理して保存してください。

```markdown
# [トピックのタイトル]

**Date:** YYYY-MM-DD HH:MM
**Tags:** #AI #アイデア #設定等

## 概要 (Summary)
会話の要旨や、ユーザーが残したかったアイデアの簡潔なまとめ。

## 詳細 (Details)
* 話されていた具体的な内容
* 決まったこと、保留になったこと

## コンテキスト / 生ログの要約
(必要であれば、将来のモデルが前後の文脈を理解しやすいように、会話の流れを箇条書きで記載する)
```

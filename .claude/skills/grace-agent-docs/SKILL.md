---
name: grace-agent-docs
description: >-
  Author or update Japanese module/page documentation for the *_grace_agent
  repos (anthropic/openai/gemini/ollama). Use when writing or modernizing docs
  under <package>/doc/*.md, ui/pages docs, or the top-level readme_*.md /
  docs/*.md, when asked to follow `a_class_method_md_format.md` (modules/classes)
  or `a_pages_md_format.md` (Streamlit UI pages), or when adding Mermaid diagrams
  to these repos. Encodes the IPO doc format, the Streamlit page format
  (layout/session-state/user-flow), the mandatory black-background Mermaid style,
  and the unified tech-stack terminology.
---

# grace_agent ドキュメント作成スキル

日本語RAG/GRACEプロジェクト群（`anthropic_grace_agent` ほか）のモジュール／画面ドキュメントを、
プロジェクト規約どおりに作成・最新化するための知見。

## 0. どのフォーマット仕様を使うか（必ず先に判定）

対象によって**使う仕様書が異なる**。いずれもスキル同梱（`.claude/skills/...`）で、書く前に該当仕様を**実際に読むこと**。

| 対象 | 使う仕様書 | 中心構造 | 主なドキュメント所在 |
|------|-----------|---------|------------------|
| コード・モジュール（クラス/関数） | `.claude/skills/grace-agent-docs/a_class_method_md_format.md` | IPO（Input-Process-Output） | `<package>/doc/<module>.md` |
| Streamlit 画面・ページ | `.claude/skills/grace-agent-docs/a_pages_md_format.md` | 画面レイアウト＋セッション状態＋操作フロー | `ui/pages/doc/<page>.md`（無ければ対象に準ずる） |
| 単体テスト | `.claude/skills/grace-agent-tests/a_test_md_format.md` | SAE（Setup-Action-Expected） | grace-agent-tests スキル参照 |

> テスト仕様（SAE）は **grace-agent-tests** スキルが担当。本スキルはモジュール（IPO）と画面（ページ）を担当する。
> 開発メモ・サンプルQ&A等の参考資料は `.claude/skills/grace-agent-docs/a_memo_dev.txt`。

## 1. モジュール仕様（`a_class_method_md_format.md`・IPO形式）— 必読
- 仕様書はスキル同梱 `.claude/skills/grace-agent-docs/a_class_method_md_format.md`（IPO形式）。**先に読むこと**。
- タイトル: `# <module>.py - <説明> ドキュメント` → 次行 `**Version X.X** | 最終更新: YYYY-MM-DD`。
- 必須セクション順:
  1. 目次
  2. 概要（`### 主な責務` 箇条書き → `### 各責務対応のモジュール` 表 → `### 主要機能一覧` 表）
  3. アーキテクチャ構成図（Mermaid・3層）
  4. モジュール構成図（Mermaid）
  5. クラス・関数一覧表
  6. クラス・関数 IPO詳細：各要素に **概要 / シグネチャ / パラメータ表 / IPOテーブル(Input・Process・Output) / 戻り値例 / 使用例** を必ず付ける
  7. 設定・定数（あれば）
  8. 使用例（ワークフロー）
  9. エクスポート（`__all__`）
  10. 変更履歴（表。版を上げたら必ず追記）
  11. 付録: 依存関係図（Mermaid）
- 横断的な「まとめ」ドキュメントは IPO を各モジュール doc に委ね、本文はアーキテクチャ＋データフロー＋リンク集に徹してよい（例: `grace/doc/agent_rag_grace.md`）。

## 1B. 画面・ページ仕様（`a_pages_md_format.md`・Streamlit UI）— 必読

`ui/pages/*.py`（`show_*_page()` 中心の Streamlit 画面）は IPO ではなく**画面特化フォーマット**を使う。
タイトルは `# <page>.py - <説明> ドキュメント` → `**Version X.X** | 最終更新: YYYY-MM-DD`。

- 必須セクション順:
  1. 目次
  2. 概要（`### 主な責務`＝ユーザー視点の機能 → `### 主要機能一覧` 表。※モジュール仕様の「各責務対応のモジュール」表は不要）
  3. 画面レイアウト図（Mermaid・全体レイアウト＋コンポーネント配置図。`st.*` を明記）
  4. UIコンポーネント詳細（サイドバー／メインエリア／エキスパンダー／ダイアログを表で。`種類`列は `st.selectbox` 等）
  5. セッション状態管理（`st.session_state` の状態一覧表＝キー/型/初期値/説明/リセット条件 ＋ 状態遷移図(Mermaid) ＋ 初期化・リセット条件）
  6. ユーザー操作フロー（操作フロー図(Mermaid flowchart) ＋ 操作シーケンス図(Mermaid sequenceDiagram)）
  7. 関数一覧表（メイン関数＝`show_*_page()` ／ ヘルパー関数＝インポート元モジュール付き）
  8. 関数 IPO詳細（メイン関数は概要/シグネチャ/IPO表/主要処理フロー。外部関数は「**参照**: <module>」で簡略可）
  9. 依存関係（外部ライブラリ／内部モジュール／サービス層の3表）
  10. イベント処理（ボタン／入力／リアルタイム更新の表。`log`/`tool_call`/`tool_result`/`final_answer` 等のイベント種別）
  11. エラーハンドリング（エラー種別／表示＝`st.error`/`st.warning`/`st.info`/`st.toast`）
  12. 使用例（画面操作手順・典型質問例。スクショは任意）
  13. 変更履歴
- 状態遷移図・操作フローは flowchart、操作シーケンスは sequenceDiagram（黒背景ルールは §2 と同じ）。
- 実装整合: `st.session_state` のキー・`should_reinitialize` 等の再初期化条件・各 `st.*` 呼び出しを**実コードと突合**する。

## 2. Mermaid 黒背景・白文字（CLAUDE.md §7 / 仕様書 §16.5）— 必須
- flowchart/graph はブロック末尾に必ず:
  - `classDef default fill:#000,stroke:#fff,color:#fff`
  - `classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff`
  - 全ノード `class <id,...> default`
  - 各サブグラフ `style <Subgraph> fill:#1a1a1a,stroke:#fff,color:#fff`
- sequenceDiagram は先頭に `%%{ init: { "theme":"base", "themeVariables": { ...黒テーマ... } } }%%` を付け、`classDef`/`class` は使わない。
  - **すべての要素を黒背景・白文字に統一する**: `background`/`mainBkg`/`actorBkg`/**`noteBkgColor` を `#000000`**、`textColor`/`actorTextColor`/`noteTextColor` を `#ffffff`、`noteBorderColor` を `#ffffff`。Note（`Note over` 等）の背景も `#000000` とし、`#1a1a1a` は使わない。
  - ⚠️ **Note 背景の変数名は `noteBkgColor`（`noteBkg` ではない）**。`noteBkg` は Mermaid に認識されず既定の黄色（`#fff5ad`）になるため、Note ボックスが黄色背景で描画される不具合の原因になる。
- ノードラベルの特殊文字はダブルクォートで囲む。バッククォート禁止。`<br>` は可。
- 検証（grep）: 各ファイルで `flowchart|graph` の数 == `classDef default fill:#000` の数、`sequenceDiagram` の数 == `%%{ init` の数。

## 3. 技術スタック表記の統一（CLAUDE.md §9.1）
- LLM = **Anthropic Claude**、既定 `claude-sonnet-4-6`（軽量 `claude-haiku-4-5-20251001`）。鍵 `ANTHROPIC_API_KEY`。
- Embedding = **Gemini** `gemini-embedding-001`（3072次元）。鍵 `GOOGLE_API_KEY`/`GEMINI_API_KEY`。
- LLM設定クラスは `ModelConfig`。`text-embedding-3-*` を LLM/本番Embedding用途で書かない。
- モデル名マッピングを作らない（CRITICAL RULES）。`responses.parse()`/`create()` は両方正。

## 4. 実装との整合（重要）
- 書く前に**対応ソースを実際に読む**。シグネチャ・既定値・`__all__` を突合。
- 廃止ファイルを参照しない: `setup.py` / `server.py` / a-prefixed scripts（`a30_qdrant_registration.py` 等）は**存在しない**。現行は
  - チャンク化: `python -m chunking.csv_text_to_chunks_text_csv`
  - Q/A生成+登録: `qa_qdrant/make_qa_register_qdrant.py`（登録のみ `register_to_qdrant.py`）
  - UI: `streamlit run agent_rag.py`
- 現行パイプラインは3段階（チャンキング→Q/A生成→Qdrant登録）。チャンキングは文書境界保証（`load_documents_from_csv`/`doc_id`）・`continuity_mode="rule"`・`max_chunk_tokens=512`・manifest出力。

## 5. ドキュメントの所在
- モジュール個別ドキュメント（IPO）: `<package>/doc/<module>.md`（例 `chunking/doc/`, `qa_generation/doc/`, `grace/doc/`, `qa_qdrant/doc/`, `services/doc/`）。
- 画面・ページドキュメント（ページ形式）: `ui/pages/doc/<page>.md`（ディレクトリが無ければ対象 `ui/pages/` 配下に準じて作成）。
- 横断/利用ガイド: リポジトリ直下 `readme_*.md`・`docs/*.md`。

## 6. 進め方のコツ
- 複数ファイルを最新化するときは **ファイルごとにサブエージェントを並列起動**（各に「**使うフォーマット仕様のパス**（モジュール=`.claude/skills/grace-agent-docs/a_class_method_md_format.md` / 画面=`.claude/skills/grace-agent-docs/a_pages_md_format.md`）＋対象ソース＋黒背景Mermaid規約＋スタック表記」を渡す）。
- 仕上げに mermaid 準拠を grep 検証（`flowchart|graph` 数 == `classDef default fill:#000` 数、`sequenceDiagram` 数 == `%%{ init` 数）し、版・最終更新日・変更履歴を更新。

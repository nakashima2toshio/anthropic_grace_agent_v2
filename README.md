# 自律型Agent + RAG (Anthropic Claude API版) プロジェクト
#### (1) 自律型Agent（Anthropic Claude API利用、スクラッチで作成）
- (1-1) 自立型Agentの全体ロジック・流れ
- 計画策定（Plan） → 実行（Execute）- → 信頼度評価（Confidence） → 介入判定（Intervention） → リプラン（Replan）

![自律型Agent](assets/ReActAgent.png)
##### 2つのエージェントの位置づけ（メニュー・ラベル）:
* 系統A（メニューの: Agent(ReAct+Reflection)) ＝ メニューで先に並ぶ標準版
・経路は静的、「いつ止めるか」をLLMが動的に決める（単純・LLM任せ）

* 系統B（メニューの: 自律型Agent(最新：動的Agent)) ＝ 「最新」表記の推奨版
・経路は動的、計画を状況に合わせて組み替える（高機能・自律適応）。
![a_b](assets/AI_Agent_a_b.png)

### 計画策定（Plan）
![plan](assets/planner_auto.png)
## Planner概要
- `planner.py`は、GRACE自律エージェントの「計画生成（Plan）」層を担うモジュールです。ユーザーの質問を分析し、`rag_search` → `reasoning` を中心とした実行計画（`ExecutionPlan`）を生成します。
- 計画生成は二層方式を採用しており、単純なクエリはルールベースで即時に計画を作り（LLM呼び出しなし）、複雑なクエリや明示的なWeb検索指示のあるクエリのみ LLM（Anthropic Claude）で計画を生成します。
- LLM 呼び出しは `grace/llm_compat.py` の `create_chat_client()` で生成したクライアント経由で行います。
- このクライアントは google-genai 互換の `client.models.generate_content(...)` インターフェースを保ったまま、内部では Anthropic Claude（既定 `claude-sonnet-4-6`、軽量用途 `claude-haiku-4-5-20251001`）を呼び出すアダプターです。Embedding（検索）は別途 Gemini `gemini-embedding-001`（3072次元）を使用します。

### Planner主な責務
- ユーザークエリの複雑度推定（キーワードベース / LLMベース）
- 二層方式による実行計画の生成（ルールベース計画 / LLM計画の振り分け）
- LLM（Anthropic Claude）を用いた実行計画の自動生成
- 利用可能なコレクション（Qdrant）の動的取得
- フィードバックに基づく計画の修正（リファインメント）
- LLMエラー時のフォールバック計画の提供

### 実行（Execute）
![executor](assets/executor.png)
## Executor概要
- `executor.py`は、GRACE（Guided Reasoning with Adaptive Confidence Execution）エージェントの計画実行コンポーネントです。
- Plannerが生成した`ExecutionPlan`を受け取り、各ステップを順次実行して結果を管理します。
- LLM呼び出しは`grace/llm_compat.py`の互換クライアント（`create_chat_client`）経由で Anthropic Claude（デフォルト `claude-sonnet-4-6`）に委譲され、
- Embedding は Gemini（`gemini-embedding-001`、3072次元）を継続利用します。

### Executor主な責務
- 計画の順次実行（ブロッキング版／ジェネレータ版）
- ステップ間の依存関係管理と検索ステップの並列プリフェッチ
- ツールの呼び出しと結果管理（ToolRegistry経由、timeout制御付き）
- RAG検索結果に基づく動的フォールバック連鎖（web_search／ask_user の動的挿入）
- 信頼度（Confidence）の計算と評価（LLM版／Heuristic版／groundedness較正）
- Human-in-the-Loop（HITL）介入処理（NOTIFY／CONFIRM／ESCALATE）
- 失敗時・低信頼度時のリプラン連携（ReplanOrchestrator）
- 実行状態の追跡とコールバック通知

### 信頼度評価（Confidence）
![confidence](assets/confidence.png)
## Confidence概要
- `confidence.py` は、GRACE（Guided Reasoning with Adaptive Confidence Execution）における信頼度計算システムを実装するモジュールです。
- ハイブリッド方式（重み付き平均 + LLM 自己評価 + 根拠妥当性検証）による多軸の信頼度算出と、
- その結果に基づく介入レベル（自動進行〜ユーザー入力要求）の判定を担います。

- LLM 呼び出しは `llm_compat.create_chat_client()` が返す genai 互換クライアント経由で行われ、
- 本プロジェクトでは Anthropic Claude（既定 `claude-sonnet-4-6`）が実体となります。
- 一方、ソース一致度計算の Embedding は Gemini（`gemini-embedding-001`、3072次元）を継続利用します。

### Confidence主な責務
- RAG 検索品質・ツール成功率などの要素から多軸信頼度を計算する
- LLM 自己評価により回答の確信度・網羅度を取得する
- 複数ソース間の意味的一致度を計算する
- 最終回答の各主張が引用ソースに支持されるか（groundedness）を検証する
- 信頼度スコアに基づいて介入レベル（アクション）を決定する
- 複数ステップの信頼度を集計する

### 介入判定（Intervention）
![intervention](assets/intervention.png)
## Intervention概要
- `intervention.py`は、GRACE（GRaded Autonomy and Confidence-based Escalation）フレームワークにおけるHITL（Human-in-the-Loop）介入システムを提供するモジュールです。
- 信頼度に応じた4段階の介入レベル（SILENT、NOTIFY、CONFIRM、ESCALATE）を管理し、人間とAIの協調的な意思決定を実現します。

- 本モジュールは純粋な介入制御ロジックであり、
- LLM（Anthropic Claude `claude-sonnet-4-6`）やEmbedding（Gemini `gemini-embedding-001`）のAPIを直接呼び出しません。
- 信頼度スコアやアクション決定（`ActionDecision`）は上流の `confidence.py` から受け取り、
- 本モジュールはそれに応じた人間への介入要求とレスポンス処理に専念します。

### Intervention主な責務
- 信頼度レベルに応じた介入リクエストの生成
- ユーザーからの介入レスポンスの処理
- 計画確認フロー（確認→修正→実行）の管理
- ユーザーフィードバックに基づく動的閾値調整
- 介入履歴の記録と管理

### リプラン（Replan）
![replan](assets/replanning.png)
### Replan概要
- `replan.py`は、GRACE自律エージェントの「動的リプランニング（Replan）」層を担うモジュールです。
- ステップ実行の失敗・低信頼度・ユーザーフィードバック等のトリガーを検知し、
- 状況に応じた戦略（全体再計画・部分再計画・フォールバック・スキップ・中断）で計画（`ExecutionPlan`）を動的に修正します。
- 再計画の実体は `Planner.create_plan()` に委譲するため、
- LLM（Anthropic Claude、既定 `claude-sonnet-4-6`）の呼び出しは `planner.py` を経由します。

- 本モジュールは、リプラントリガー/戦略を表す `Enum`、
- リプラン時の状態を保持するデータクラス、
- 判定・戦略決定・計画再生成を行う `ReplanManager`、
- Executor と統合して自動リプランフローを管理する `ReplanOrchestrator` から構成されます。

### Replan主な責務
- リプラントリガー（失敗・低信頼度・フィードバック・新情報・タイムアウト）の定義
- リプラン戦略（全体・部分・フォールバック・スキップ・中断）の定義と選択
- ステップ結果・ユーザーフィードバックからのリプラン要否判定
- 戦略に応じた新しい実行計画の生成（Plannerへの委譲を含む）
- フォールバックチェーン（rag_search ↔ web_search）の適用
- Executor と統合した自動リプランフローの管理

## (2) Chunking（意味ある文章に分割する）
- (2-1) 評価用データ：HuggingFaceからダウンロード
- (2-2) RAG: Chunkデータの作成
- (2-3) RAG: Qdrant(ベクターDB)への登録、検索
![データ・ダウンロード]
![ダウンロード](assets/huggingface_download.png)
### HuggingFace Data Download概要
- `down_load_non_qa_rag_data_from_huggingface.py`は、HuggingFace Hub および直接ダウンロードによる
- 非Q&A型データセットの取得・検証・前処理を行う Streamlit Web アプリケーション。
- RAG（Retrieval-Augmented Generation）パイプラインの入力データを準備するためのツールであり、
- 日本語・英語の多様なデータセットに対応する。

### データ・ダウンロード主な責務
- HuggingFace Hub / 直接URL からのデータセットダウンロード
- データセット種別に応じた品質検証（Wikipedia / ニュース / 学術 / コード）
- RAG 用テキスト抽出・クレンジング・結合前処理
- トークン使用量とコストの推定表示
- CSV / TXT / JSON フォーマットでの出力・保存

![チャンキング]
![RagデータDL・登録](assets/img_csv_text_to_chunks_text_csv.png)
## 概要
- `csv_text_to_chunks_text_csv.py` は、テキストまたは CSV ファイルを入力として受け取り、
- LLM ベースの 3 段階アルゴリズム（階層構造化 → 意味的チャンキング → 文脈連続性チェック）で
- 意味的なチャンクに分割するパイプラインモジュールです。
- `asyncio` による並列化、`CheckpointManager` による再開機能、最終チャンクの最大トークン数強制
- （Embedding の無言切り捨て防止）、CSV 出力時の改行正規化、メタデータ付き CSV と
- シンプル CSV（`Text` カラムのみ）の二系統同時出力を提供します。

### チャンキング・主な責務
- 入力ファイル（`.txt` / `.csv`）の読み込みとテキスト抽出
- 3 段階 LLM 処理（段落分割 / 意味的分割 / 連続性結合）の実行
- `asyncio.gather` による並列 API 呼び出しと進捗表示（tqdm）
- チェックポイントによる中断・再開のサポート
- 最終チャンクの最大トークン数強制（Embedding 入力上限超過防止）
- CSV 形式での保存（メタデータ付き + シンプル版）

> **はじめにお読みください**
>
> | # | ドキュメント | 説明 |
> | - | ----------- | ---- |
> | 1 | [セットアップ・インストール手順書 (docs/setup_and_install.md)](./docs/setup_and_install.md) | Python・Docker・uv・API キーの包括的セットアップ手順（はじめにこちら） |
> | 2 | [環境構築手順書 (readme_make_env.md)](./readme_make_env.md) | Mac 向け詳細環境構築（Python / Docker / Celery / API キー設定） |
> | 3 | [uv パッケージマネージャー (docs/uv_install.md)](./docs/uv_install.md) | pip → uv 移行・仮想環境管理手順 |
> | 4 | [RAG データ取得ガイド (down_load_non_qa_rag_data_from_huggingface.md)](./down_load_non_qa_rag_data_from_huggingface.md) | RAG データを HuggingFace からダウンロード・前処理する手順 |
> | 5 | [RAG ツール使用ガイド (readme_usage_tools.md)](./readme_usage_tools.md) | チャンク作成 → Q/A 生成・Qdrant 登録 → Agent 検索の操作手順 |
> | 6 | [自立型/自律型 Agent 比較 (docs/agent_a_b.md)](./docs/agent_a_b.md) | 系統A(ReAct+Reflection) と 系統B(GRACE/最新・動的Agent) のアーキテクチャ・処理フロー・違いの比較 |
> | 7 | [RAG Q/A 生成・検索システム (readme_rag.md)](./readme_rag.md) | RAG パイプライン全体の設計・クラス・関数 IPO 詳細（セマンティックチャンキング / Q&A 生成 / Qdrant 検索） |
> | 8 | [Streamlit アプリ設計書 (docs/agent_rag.md)](./docs/agent_rag.md) | agent_rag.py のアーキテクチャ・ページ構成・Anthropic Claude 設定・モデル一覧 |
> | 9 | [ReAct+Reflection エージェント (readme_react_reflection.md)](./readme_react_reflection.md) | ReAct（Reasoning+Acting）ループ + Reflection 自己評価による自律型 RAG エージェントの設計と実装 |
> | 10 | [自律型 Agent — GRACE (readme_autonomous_agent.md)](./readme_autonomous_agent.md) | GRACE（Plan→Execute→Confidence→Intervention→Replan）アーキテクチャの設計・IPO 詳細 |
>
> **技術参考資料**
>
> | # | ドキュメント | 説明 |
> | - | ----------- | ---- |
> | R1 | [LLM API 3プロバイダー対比表 v2 (docs/llm_api_comparison_v2.md)](./docs/llm_api_comparison_v2.md) | Anthropic / OpenAI / Gemini の API・クライアント・Embedding 完全比較（最新版） |
>
> **アーカイブ**
>
> 旧 API 移行計画・ベンチマーク TODO・リファクタリング TODO 等の過去ドキュメントは [docs/archive/](./docs/archive/README.md) に移動しました（移行計画 v2 / 各種 API 移行ガイド / benchmark_todo / grace_react_refactor_todo を含む）。

---

## ドキュメント ↔ 対応コード 対応表

各ドキュメントが「どのソースコードを説明・対象としているか」の対応表です。ドキュメントを最新化する際は、対応するコードを精読して整合させてください。

| # | ドキュメント | 主な対応コード | 補助的に参照するコード |
|---|---|---|---|
| 0 | [README.md](./README.md)（プロジェクト全体・UIエントリ） | `agent_rag.py`（Streamlit エントリ） | `ui/app.py`, `ui/pages/*`, `ui/components/*`、および全パイプライン（`grace/`, `chunking/`, `qa_qdrant/`, `qa_generation/`, `services/`, `helper/`） |
| 1 | [docs/setup_and_install.md](./docs/setup_and_install.md)（セットアップ・インストール） | `pyproject.toml`, `uv.lock`, `requirements.txt`, `docker-compose/docker-compose.yml` | `config.py` / `config.yml`, `.env`, `helper/helper_llm.py`, `helper/helper_embedding.py`（APIキー確認） |
| 2 | [readme_make_env.md](./readme_make_env.md)（Mac環境構築） | `requirements.txt`, `pyproject.toml`, `docker-compose/docker-compose.yml`, `.env` | `config.py`（`GraceConfig`）, `config.yml` |
| 3 | [docs/uv_install.md](./docs/uv_install.md)（uv パッケージ管理） | `pyproject.toml`, `uv.lock` | `requirements.txt` |
| 4 | [down_load_non_qa_rag_data_from_huggingface.md](./down_load_non_qa_rag_data_from_huggingface.md)（RAGデータ取得） | `down_load_non_qa_rag_data_from_huggingface.py` | `datasets/` 配下 |
| 5 | [readme_usage_tools.md](./readme_usage_tools.md)（RAGツール操作手順） | `chunking/csv_text_to_chunks_text_csv.py`, `qa_qdrant/make_qa_register_qdrant.py`, `qa_qdrant/register_to_qdrant.py` | `chunking/*`（`async_api_client.py`, `checkpoint_manager.py`, `prompts.py` 等）, `qa_qdrant/make_qa.py` |
| 6 | [docs/agent_a_b.md](./docs/agent_a_b.md)（系統A/系統B エージェント比較） | `services/agent_service.py`（`ReActAgent`＝系統A）, `grace/`（`planner.py`, `executor.py`＝系統B） | `ui/pages/agent_chat_page.py`, `ui/pages/grace_chat_page.py`, `grace/confidence.py`, `grace/replan.py`, `grace/tools.py`, `agent_rag.py` |
| 7 | [readme_rag.md](./readme_rag.md)（RAG Q/A生成・検索システム設計） | `chunking/`, `qa_generation/`（`semantic.py`, `smart_qa_generator.py`, `pipeline.py`, `evaluation.py`）, `qa_qdrant/`, `qdrant_client_wrapper.py` | `helper/helper_rag*.py`, `helper/helper_embedding*.py`, `services/qdrant_service.py`, `models.py` |
| 8 | [docs/agent_rag.md](./docs/agent_rag.md)（Streamlitアプリ設計書） | `agent_rag.py` | `ui/app.py`, `ui/pages/*`（`grace_chat_page.py`, `agent_chat_page.py`, `qdrant_*` 等）, `ui/components/*` |
| 9 | [readme_react_reflection.md](./readme_react_reflection.md)（ReAct+Reflectionエージェント） | `services/agent_service.py`（`ReActAgent`） | `agent_main.py`, `agent_tools.py`, `agent_parallel_search.py`, `agent_cache.py`, `ui/pages/agent_chat_page.py`, `services/qa_service.py`, `services/qdrant_service.py`, `helper/helper_llm.py`, `helper/helper_embedding*.py` |
| 10 | [readme_autonomous_agent.md](./readme_autonomous_agent.md)（自律型Agent — GRACE） | `grace/` パッケージ（`planner.py`, `executor.py`, `confidence.py`, `intervention.py`, `replan.py`, `calibration.py`, `llm_compat.py`, `schemas.py`, `config.py`, `tools.py`） | `grace/benchmark.py`, `ui/pages/grace_chat_page.py`, `ui/components/grace_components.py` |

**補足:**

- `agent_rag.py` は Streamlit アプリのエントリで、`ui/pages/` 配下の各ページを束ねます。README.md（#0）と docs/agent_rag.md（#8）はこのアプリ層が主対象です。
- #6（系統A/系統B 比較）は両エージェントの違いをまとめた対比ドキュメントです。
- #9（ReAct+Reflection）と #10（GRACE）は別系統のエージェントです。ReAct は `services/agent_service.py`（`create_llm_client("anthropic")` + Anthropic Tool Use `generate_with_tools`／`stop_reason=="tool_use"` の ReAct ループ＋Reflection フェーズ）、GRACE は `grace/` パッケージ（Plan→Execute→Confidence→Intervention→Replan、`grace/llm_compat.py` 経由で Anthropic Claude 既定）。いずれも LLM は Anthropic Claude（既定 `claude-sonnet-4-6`）。
- 技術スタック規約：LLM = Anthropic Claude（`claude-sonnet-4-6`、`grace/llm_compat.py` 経由）、Embedding = Gemini（`gemini-embedding-001`・3072次元）。ただしチャンキング/Q&A 生成の CLI ツール（`chunking/`・`qa_qdrant/`）は argparse 既定が `gemini-2.5-flash` で、`--model claude-sonnet-4-6` で上書き可能。

---

## （自律型Agent）grace_chat_page.py

画面（UIエントリポイント）： `streamlit run agent_rag.py`

![image.png](assets/image.png)

個々のドキュメントは、機能ディレクトリー/doc/*.md を参照あれ。

### Streamlit アプリの起動とページ構成

```bash
# UI 起動（エントリポイントは agent_rag.py）
uv run streamlit run agent_rag.py --server.port 8501
```

`agent_rag.py` のサイドバーメニュー（`main()` の `st.radio`）から以下のページを選択します。

| メニュー表示                          | ページID             | 実装                                                       |
| ------------------------------------- | -------------------- | ---------------------------------------------------------- |
| 📖 説明                               | `explanation`        | `ui/pages/explanation_page.py::show_system_explanation_page` |
| 🔎 Qdrant検索                         | `qdrant_search`      | `ui/pages/qdrant_search_page.py::show_qdrant_search_page`  |
| 🤖 Agent(ReAct+Reflection)            | `agent_chat`         | `ui/pages/agent_chat_page.py::show_agent_chat_page`        |
| [最新] 自律型Agent(Plan+Executor)     | `grace_chat`         | `ui/pages/grace_chat_page.py::show_grace_chat_page`        |
| 📊 未回答ログ                         | `log_viewer`         | `ui/pages/log_viewer_page.py::show_log_viewer_page`        |
| 📄 RAGデータ作成                      | `rag_data_creation`  | `agent_rag.py::show_rag_data_creation_page`（CLI手順への案内） |
| 🗄️ QdrantのCRUD                       | `qdrant_crud`        | `agent_rag.py::show_qdrant_crud_page`                      |

RAGデータの作成（チャンク分割 → Q/A生成＋Qdrant登録）は UI からではなく CLI で実行します（後述「RAGデータ作成パイプライン」を参照）。`ui/pages/` には `download_page` / `qa_generation_page` / `qdrant_registration_page` / `qdrant_show_page` も同梱されていますが、現行の `agent_rag.py` メニューには未接続です。

### RAGデータ作成パイプライン（CLI）

```bash
# (1) チャンク分割（LLMベース 3段階セマンティックチャンキング）
uv run python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_1per.csv \
  --output output_chunked

# (2) Q/A生成 ＋ Qdrant登録（統合CLI）
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input output_chunked/cc_news_1per_chunks.csv

# 既存 Q/A CSV を登録のみ行う場合
uv run python qa_qdrant/register_to_qdrant.py --input qa_output/...csv

# (3) 検索・対話は UI から
uv run streamlit run agent_rag.py --server.port 8501
```

詳細手順は [readme_usage_tools.md](./readme_usage_tools.md)、各 CLI の仕様は `chunking/doc/csv_text_to_chunks_text_csv.md` / `qa_qdrant/doc/make_qa_register_qdrant.md` を参照してください。

### 技術スタック

| 役割                              | プロバイダー  | モデル / 設定                                                   |
| --------------------------------- | ------------- | -------------------------------------------------------------- |
| LLM（計画策定・実行・応答生成）   | **Anthropic** | デフォルト `claude-sonnet-4-6`（軽量 `claude-haiku-4-5-20251001`）、APIキー `ANTHROPIC_API_KEY`、ルーティングは `grace/llm_compat.py` 経由 |
| Embedding（Qdrant登録・検索）     | **Gemini**    | `gemini-embedding-001`（3072次元）、APIキー `GOOGLE_API_KEY` / `GEMINI_API_KEY` |
| ベクトルDB                        | Qdrant        | `http://localhost:6333`                                        |

LLM プロバイダー / モデルは `grace/config.py` の `LLMConfig`（`provider="anthropic"`, `model="claude-sonnet-4-6"`）、Embedding は `EmbeddingConfig`（`provider="gemini"`, `model="gemini-embedding-001"`, `dimensions=3072`）が既定値です。

**Version 4.2** | 最終更新: 2026-06-17

---

## 目次

1. [概要](#概要)
2. [画面レイアウト図](#1-画面レイアウト図)
3. [UIコンポーネント詳細](#2-uiコンポーネント詳細)
4. [セッション状態管理](#3-セッション状態管理)
5. [ユーザー操作フロー](#4-ユーザー操作フロー)
6. [関数一覧表](#5-関数一覧表)
7. [関数 IPO詳細](#6-関数-ipo詳細)
8. [依存関係](#7-依存関係)
9. [イベント処理](#8-イベント処理)
10. [エラーハンドリング](#9-エラーハンドリング)
11. [使用例](#10-使用例)
12. [変更履歴](#11-変更履歴)

---

## 概要

`grace_chat_page.py`は、GRACE（Goal-Reasoning-Action-Critique-Execute）アーキテクチャを使用した自律型エージェントとの対話インターフェースを提供するStreamlit UIページです。
Planner + Executor の2フェーズ分離型アーキテクチャにより、計画策定（Plan）→ 実行（Execute）→ 信頼度評価（Confidence）→ 介入判定（Intervention）→ リプラン（Replan）の一連のプロセスをリアルタイムに可視化します。

### 主な責務

- ユーザーからの質問入力の受付
- Planner による実行計画の策定と表示（複雑度・ステップ数・成功基準の可視化）
- Executor による計画の逐次実行と進捗表示（Generator ベースのリアルタイム更新）
- 各ステップの信頼度スコア表示と実行結果サマリの提示
- 会話履歴の管理とセッション状態の維持
- 検索対象コレクションの参考表示（GRACEは全コレクションを自動検索）
- Qdrantコレクションデータのプレビュー表示
- キャッシュ管理と統計表示

### 主要機能一覧


| 機能                     | 説明                                                                      |
| ------------------------ | ------------------------------------------------------------------------- |
| `show_grace_chat_page()` | メインページ表示関数                                                      |
| サイドバー設定           | モデル選択、コレクション参考表示、キャッシュ管理                          |
| コレクションデータ表示   | Qdrantコレクションの内容プレビュー（最大100件）                           |
| チャット履歴表示         | 会話履歴の表示                                                            |
| 計画策定表示             | Planner が生成した ExecutionPlan の構造化表示（📋 計画策定）              |
| 実行プロセス表示         | Executor のステップ実行ログ・信頼度のリアルタイム表示（⚡ 実行）          |
| 実行結果サマリ           | 全体ステータス・信頼度・リプラン回数・実行時間の表示（📊 実行結果サマリ） |

### アーキテクチャ概要

```mermaid
flowchart TB
    subgraph UI["UI Layer (grace_chat_page.py)"]
        ChatInput["チャット入力"]
        ChatHistory["チャット履歴"]
        PlanView["📋 計画策定表示"]
        ExecView["⚡ 実行プロセス表示"]
        ResultView["📊 実行結果サマリ"]
    end

    subgraph Planner_Layer["Planner Layer (grace/planner.py)"]
        Planner["Planner"]
        ComplexityEstimator["複雑度推定<br/>(LLM)"]
        PlanGeneration["計画生成<br/>(Claude JSON Schema)"]
    end

    subgraph Executor_Layer["Executor Layer (grace/executor.py)"]
        Executor["Executor"]
        StateManager["ExecutionState<br/>(状態管理)"]
        ConfCalc["ConfidenceCalculator<br/>(信頼度計算)"]
        IntHandler["InterventionHandler<br/>(HITL介入)"]
        ReplanOrch["ReplanOrchestrator<br/>(リプラン)"]
    end

    subgraph Tools["Tools Layer (grace/tools.py)"]
        ToolRegistry["ToolRegistry"]
        RAGSearch["RAGSearchTool"]
        Reasoning["ReasoningTool"]
        AskUser["AskUserTool"]
    end

    subgraph Cache["Cache Layer (agent_cache.py)"]
        CollectionCache["CollectionCache<br/>(TTL: 5分)"]
    end

    subgraph NLP["NLP Layer (regex_mecab.py)"]
        KeywordExtractor["KeywordExtractor<br/>(MeCab + 正規表現)"]
    end

    subgraph DB["Database Layer"]
        Qdrant["Qdrant Vector DB"]
    end

    ChatInput --> Planner
    Planner --> ComplexityEstimator
    Planner --> PlanGeneration
    PlanGeneration --> PlanView
    PlanView --> Executor
    Executor --> StateManager
    Executor --> ConfCalc
    Executor --> IntHandler
    Executor --> ReplanOrch
    Executor --> ToolRegistry
    ToolRegistry --> RAGSearch
    ToolRegistry --> Reasoning
    ToolRegistry --> AskUser
    RAGSearch --> CollectionCache
    RAGSearch --> Qdrant
    Planner --> KeywordExtractor
    RAGSearch --> KeywordExtractor
    StateManager --> ExecView
    Executor --> ResultView
    Executor --> ChatHistory
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class ChatInput,ChatHistory,PlanView,ExecView,ResultView,Planner,ComplexityEstimator,PlanGeneration,Executor,StateManager,ConfCalc,IntHandler,ReplanOrch,ToolRegistry,RAGSearch,Reasoning,AskUser,CollectionCache,KeywordExtractor,Qdrant default
style UI fill:#1a1a1a,stroke:#fff,color:#fff
style Planner_Layer fill:#1a1a1a,stroke:#fff,color:#fff
style Executor_Layer fill:#1a1a1a,stroke:#fff,color:#fff
style Tools fill:#1a1a1a,stroke:#fff,color:#fff
style Cache fill:#1a1a1a,stroke:#fff,color:#fff
style NLP fill:#1a1a1a,stroke:#fff,color:#fff
style DB fill:#1a1a1a,stroke:#fff,color:#fff
```

### Planner / Executor 2フェーズ処理フロー

```mermaid
flowchart LR
    Q["ユーザー質問"] --> P["Phase 1: Plan<br/>(Planner.create_plan)"]
    P --> E["Phase 2-4: Execute<br/>(Executor.execute_plan_generator)"]
    E --> C{"信頼度評価<br/>(Confidence)"}
    C -->|高| A["最終回答生成"]
    C -->|低| I{"介入判定<br/>(Intervention)"}
    I -->|自動続行| E
    I -->|リプラン| R["Replan<br/>(計画修正)"]
    R --> E
    I -->|ユーザー確認| H["HITL<br/>(Human-in-the-Loop)"]
    H --> E
    A --> D["📊 実行結果サマリ"]
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class Q,P,E,C,A,I,R,H,D default
```

---

## 1. 画面レイアウト図

### 1.1 全体レイアウト

```mermaid
flowchart TB
    subgraph Browser["ブラウザウィンドウ"]
        direction TB
        subgraph Sidebar["📋 サイドバー (280px固定)"]
            direction TB
            S1["⚙️ 設定ヘッダー"]
            S2["モデル選択<br/>[selectbox]"]
            S3["コレクション選択<br/>[multiselect] (参考表示)"]
            S4["☑️ ハイブリッド検索<br/>(disabled)"]
            S5["[🗑️ 履歴クリア]"]
            S6["[🔄 キャッシュリセット]"]
            S7["📊 キャッシュ統計<br/>(expander)"]
            S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
        end
        subgraph Main["📄 メインエリア (残り幅)"]
            direction TB
            M1["🧠 タイトル<br/>自律型エージェント GRACE"]
            M2["キャプション<br/>Planner + Executor"]
            M3["📊 コレクションデータ表示<br/>(expander)"]
            M4["💬 チャットセクション"]
            M5["チャット履歴エリア"]
            M6["📋 計画策定 Plan<br/>(expander, 展開)"]
            M7["⚡ 実行 Execute<br/>(expander, 展開)"]
            M8["📊 実行結果サマリ<br/>(expander, 折りたたみ)"]
            M9["最終回答表示"]
            M10["📝 チャット入力"]
            M1 --> M2 --> M3 --> M4 --> M5 --> M6 --> M7 --> M8 --> M9 --> M10
        end
    end

    Sidebar -.-> Main
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class S1,S2,S3,S4,S5,S6,S7,M1,M2,M3,M4,M5,M6,M7,M8,M9,M10 default
style Browser fill:#1a1a1a,stroke:#fff,color:#fff
style Sidebar fill:#1a1a1a,stroke:#fff,color:#fff
style Main fill:#1a1a1a,stroke:#fff,color:#fff
```

### 1.2 コンポーネント配置図

```mermaid
flowchart TB
    subgraph Page["grace_chat_page.py"]
        subgraph MainArea["メインエリア"]
            M1["st.title() - 🧠 自律型エージェント GRACE"]
            M2["st.caption() - Planner + Executor"]
            subgraph Expander_Data["エキスパンダー: コレクションデータ表示"]
                E1["st.selectbox() - コレクション選択"]
                E2["QdrantClient.scroll() - データ取得"]
                E3["st.dataframe() - データプレビュー"]
            end
            M3["st.divider()"]
            M4["st.markdown() - 💬 チャット"]
            subgraph ChatArea["チャット履歴エリア"]
                C1["st.chat_message() - 各メッセージ表示"]
            end
            subgraph ResponseArea["応答エリア (st.chat_message assistant)"]
                subgraph Expander_Plan["📋 計画策定 Plan (expander)"]
                    P1["st.metric() x 3 - 複雑度/ステップ数/要確認"]
                    P2["st.caption() - 成功基準"]
                    P3["st.markdown() - 各ステップ詳細"]
                    P4["st.expander() - Plan JSON raw"]
                end
                subgraph Expander_Exec["⚡ 実行 Execute (expander)"]
                    X1["st.container() - 思考プロセスログ"]
                    X2["st.markdown() - ステップ進捗と信頼度"]
                    X3["st.warning() - 介入リクエスト (条件付き)"]
                end
                subgraph Expander_Result["📊 実行結果サマリ (expander)"]
                    R1["st.markdown() - ステータス"]
                    R2["st.markdown() - 全体信頼度"]
                    R3["st.markdown() - リプラン回数"]
                    R4["st.markdown() - 実行時間"]
                end
                RA1["st.markdown() - 最終回答"]
            end
            M5["st.chat_input() - 入力フィールド"]
        end
        subgraph SidebarArea["サイドバー"]
            S1["st.header() - ⚙️ GRACE エージェント設定"]
            S2["st.selectbox() - 使用モデル"]
            S3["st.multiselect() - 検索対象コレクション (参考表示)"]
            S4["st.checkbox() - ハイブリッド検索 (disabled)"]
            S5["st.button() - 🗑️ 会話履歴をクリア"]
            S6["st.button() - 🔄 キャッシュをリセット"]
            S7["st.expander() - 📊 キャッシュ統計"]
        end
    end

    M1 --> M2 --> Expander_Data --> M3 --> M4 --> ChatArea --> ResponseArea --> M5
    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class M1,M2,M3,M4,M5,E1,E2,E3,C1,P1,P2,P3,P4,X1,X2,X3,R1,R2,R3,R4,RA1,S1,S2,S3,S4,S5,S6,S7 default
style Page fill:#1a1a1a,stroke:#fff,color:#fff
style MainArea fill:#1a1a1a,stroke:#fff,color:#fff
style Expander_Data fill:#1a1a1a,stroke:#fff,color:#fff
style ChatArea fill:#1a1a1a,stroke:#fff,color:#fff
style ResponseArea fill:#1a1a1a,stroke:#fff,color:#fff
style Expander_Plan fill:#1a1a1a,stroke:#fff,color:#fff
style Expander_Exec fill:#1a1a1a,stroke:#fff,color:#fff
style Expander_Result fill:#1a1a1a,stroke:#fff,color:#fff
style SidebarArea fill:#1a1a1a,stroke:#fff,color:#fff
```

### 1.3 応答エリア内部構造

ユーザーが質問を送信した際、`st.chat_message("assistant")` 内に以下の3つのExpanderが順次生成されます。

```mermaid
flowchart TB
    subgraph AssistantMessage["st.chat_message - assistant"]
        direction TB
        subgraph Plan["📋 計画策定 Plan (expanded=True)"]
            P1["目標表示"]
            P2["metric: 複雑度 / ステップ数 / 要確認"]
            P3["成功基準"]
            P4["各ステップ詳細<br/>(アイコン + action + description + query + collection + fallback)"]
            P5["Plan JSON raw (nested expander)"]
        end
        subgraph Exec["⚡ 実行 Execute (expanded=True)"]
            X1["Generator ループ<br/>(ExecutionState / dict yield)"]
            X2["ステップ進捗ログ<br/>(status icon + 信頼度)"]
            X3["Tool Call / Tool Result 表示"]
            X4["介入リクエスト (条件付き)"]
        end
        subgraph Result["📊 実行結果サマリ (expanded=False)"]
            R1["ステータス / 全体信頼度"]
            R2["リプラン回数 / 実行時間"]
        end
        Final["st.markdown() - 最終回答"]
    end

    Plan --> Exec --> Result --> Final
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class P1,P2,P3,P4,P5,X1,X2,X3,X4,R1,R2,Final default
style AssistantMessage fill:#1a1a1a,stroke:#fff,color:#fff
style Plan fill:#1a1a1a,stroke:#fff,color:#fff
style Exec fill:#1a1a1a,stroke:#fff,color:#fff
style Result fill:#1a1a1a,stroke:#fff,color:#fff
```

---

## 2. UIコンポーネント詳細

### 2.1 サイドバー


| コンポーネント     | 種類             | キー | デフォルト値             | 説明                                                              |
| ------------------ | ---------------- | ---- | ------------------------ | ----------------------------------------------------------------- |
| 設定ヘッダー       | `st.header`      | -    | -                        | 「⚙️ GRACE エージェント設定」                                   |
| モデル選択         | `st.selectbox`   | -    | `AgentConfig.MODEL_NAME` | 使用するLLMモデル（Anthropic Claude）                            |
| コレクション選択   | `st.multiselect` | -    | 全コレクション           | 検索対象コレクション（参考表示。GRACEは全コレクションを自動検索） |
| ハイブリッド検索   | `st.checkbox`    | -    | `True`                   | Sparse + Dense検索（`disabled=True`、GRACE側デフォルトに委任）    |
| 履歴クリア         | `st.button`      | -    | -                        | 会話履歴・Planner・Executor 状態のクリア                          |
| キャッシュリセット | `st.button`      | -    | -                        | セッションキャッシュのクリア                                      |
| キャッシュ統計     | `st.expander`    | -    | 折りたたみ               | キャッシュ状態の詳細表示                                          |

#### モデル選択の詳細

```python
selected_model = st.selectbox(
    "使用モデル (Model)",
    options=ModelConfig.AVAILABLE_MODELS,
    index=ModelConfig.AVAILABLE_MODELS.index(AgentConfig.MODEL_NAME)
    if AgentConfig.MODEL_NAME in ModelConfig.AVAILABLE_MODELS else 0
)
```

**オプション一覧** (`ModelConfig.AVAILABLE_MODELS`):


| モデル名                        | 説明                                       |
| ------------------------------- | ------------------------------------------ |
| `claude-sonnet-4-6`             | Claude Sonnet（**デフォルト**）            |
| `claude-haiku-4-5-20251001`     | 軽量・高速モデル                           |

#### コレクション選択の詳細

```python
selected_collections = st.multiselect(
    "検索対象コレクション (参考表示)",
    options=all_collections,
    default=all_collections if all_collections != ["(None)"] else [],
    help="GRACEエージェントはQdrant上の全コレクションを自動検索します。"
)
```

コレクション選択はUIでの参考表示のみです。GRACE Executor 内の `RAGSearchTool` が Qdrant から動的にコレクション一覧を取得し、優先順位に従って全コレクションを順次検索します。

#### キャッシュ統計の詳細


| 表示項目       | 説明                               |
| -------------- | ---------------------------------- |
| キャッシュ状態 | 🟢 ヒット / ⚪ なし                |
| コレクション   | キャッシュされているコレクション名 |
| 前回スコア     | 直近の検索スコア                   |
| ヒット回数     | キャッシュヒット累計               |
| 経過時間       | キャッシュ作成からの経過秒数       |

### 2.2 メインエリア


| コンポーネント           | 種類                           | 説明                                                                          |
| ------------------------ | ------------------------------ | ----------------------------------------------------------------------------- |
| タイトル                 | `st.title`                     | 「🧠 自律型エージェント (GRACE)」                                             |
| キャプション             | `st.caption`                   | 「Goal-Reasoning-Action-Critique-Execute Architecture — Planner + Executor」 |
| コレクションデータ表示   | `st.expander` + `st.dataframe` | Qdrantデータのプレビュー                                                      |
| チャットセクション見出し | `st.markdown`                  | 「### 💬 チャット」                                                           |
| チャット履歴             | `st.chat_message`              | 会話の表示                                                                    |
| 📋 計画策定 (Plan)       | `st.expander`                  | Planner が生成した ExecutionPlan の表示                                       |
| ⚡ 実行 (Execute)        | `st.expander`                  | Executor のステップ実行ログのリアルタイム表示                                 |
| 📊 実行結果サマリ        | `st.expander`                  | 全体ステータス・信頼度・リプラン回数・実行時間                                |
| 最終回答                 | `st.markdown`                  | Executor の最終回答テキスト                                                   |
| チャット入力             | `st.chat_input`                | ユーザー入力                                                                  |

### 2.3 エキスパンダー一覧


| エキスパンダー名            | 初期状態   | 表示タイミング   | 内容                                                                       |
| --------------------------- | ---------- | ---------------- | -------------------------------------------------------------------------- |
| 📊 コレクションデータの表示 | 折りたたみ | 常時             | コレクション選択 + DataFrameプレビュー（100件）                            |
| 📋 計画策定 (Plan)          | **展開**   | 質問送信後       | 目標、複雑度/ステップ数/要確認のmetric、成功基準、各ステップ詳細           |
| 🔧 Plan JSON (raw)          | 折りたたみ | 計画策定内       | ExecutionPlan の JSON ダンプ（デバッグ用、ネストExpander）                 |
| ⚡ 実行 (Execute)           | **展開**   | 計画策定後       | ステップ進捗ログ（status icon + 信頼度）、Tool Call/Result、介入リクエスト |
| 📊 実行結果サマリ           | 折りたたみ | 実行完了後       | ステータス、全体信頼度、リプラン回数、実行時間                             |
| 📊 キャッシュ統計           | 折りたたみ | 常時(サイドバー) | キャッシュヒット状態、統計情報                                             |

### 2.4 計画策定 (Plan) Expander 内部詳細

計画策定 Expander は `Planner.create_plan()` の結果である `ExecutionPlan` を構造化表示します。


| 表示要素   | コンポーネント          | データソース                                                                                    |
| ---------- | ----------------------- | ----------------------------------------------------------------------------------------------- |
| 目標       | `st.markdown`           | `plan.original_query`                                                                           |
| 複雑度     | `st.metric` (3カラム左) | `plan.complexity`（0.0-1.0）                                                                    |
| ステップ数 | `st.metric` (3カラム中) | `plan.estimated_steps`                                                                          |
| 要確認     | `st.metric` (3カラム右) | `plan.requires_confirmation`（⚠️/✅）                                                         |
| 成功基準   | `st.caption`            | `plan.success_criteria`                                                                         |
| 各ステップ | `st.markdown` (ループ)  | `plan.steps[]` の action, description, query, collection, expected_output, fallback, depends_on |

**ステップのアクションアイコンマッピング**:


| action             | アイコン |
| ------------------ | -------- |
| `rag_search`       | 🔍       |
| `web_search`       | 🌐       |
| `reasoning`        | 🧠       |
| `ask_user`         | 💬       |
| `code_execute`     | 💻       |
| `run_legacy_agent` | 🤖       |
| その他             | ▶️     |

### 2.5 実行 (Execute) Expander 内部詳細

実行 Expander は `Executor.execute_plan_generator()` の Generator から yield される値をリアルタイム表示します。


| yield 型                     | 表示処理                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------ |
| `ExecutionState`             | ステップID、ステータスアイコン、信頼度を1行で表示。介入リクエストがある場合は`st.warning` で表示 |
| `dict` (type=`log`)          | 思考プロセスログを`st.markdown` で追記                                                           |
| `dict` (type=`tool_call`)    | ツール名・引数を表示（🛠️）                                                                     |
| `dict` (type=`tool_result`)  | ツール結果を表示（📝、500文字で切り詰め）                                                        |
| `dict` (type=`final_answer`) | Legacy Agent 経由の最終回答を取得                                                                |
| `StopIteration.value`        | `ExecutionResult` を取得（Generator 終了時）                                                     |

**ステータスアイコンマッピング**:


| StepStatus | アイコン |
| ---------- | -------- |
| `SUCCESS`  | ✅       |
| `FAILED`   | ❌       |
| `SKIPPED`  | ⏭️     |
| `RUNNING`  | 🔄       |
| `PENDING`  | ⏳       |
| その他     | ❓       |

### 2.6 実行結果サマリ Expander 内部詳細


| 表示項目     | コンポーネント | データソース                                                          |
| ------------ | -------------- | --------------------------------------------------------------------- |
| ステータス   | `st.markdown`  | `execution_result.overall_status`（success/partial/failed/cancelled） |
| 全体信頼度   | `st.markdown`  | `execution_result.overall_confidence`（0.00-1.00）                    |
| リプラン回数 | `st.markdown`  | `execution_result.replan_count`                                       |
| 実行時間     | `st.markdown`  | `execution_result.total_execution_time_ms`（ミリ秒、存在時のみ表示）  |

### 2.7 ダイアログ・モーダル

（このページではダイアログ・モーダルは使用していません）

---

## 3. セッション状態管理

### 3.1 状態一覧


| キー                  | 型           | 初期値                             | 説明                      | リセット条件                |
| --------------------- | ------------ | ---------------------------------- | ------------------------- | --------------------------- |
| `grace_chat_history`  | `List[Dict]` | `[]`                               | 会話履歴（role, content） | クリアボタン                |
| `grace_session_id`    | `str`        | `uuid.uuid4()`                     | セッション識別子          | ページリロード              |
| `grace_planner`       | `Planner`    | `None`（初回アクセス時に自動生成） | 計画策定エージェント      | モデル変更時 / クリアボタン |
| `grace_executor`      | `Executor`   | `None`（初回アクセス時に自動生成） | 計画実行エージェント      | モデル変更時 / クリアボタン |
| `grace_current_model` | `str`        | -                                  | 選択中モデル              | モデル変更時 / クリアボタン |

#### 旧バージョン（v1.0）からの変更点


| 旧キー（削除）                | 新キー（追加）                     | 変更理由                                        |
| ----------------------------- | ---------------------------------- | ----------------------------------------------- |
| `grace_agent`（ReActAgent）   | `grace_planner` + `grace_executor` | 単一エージェント → 2フェーズ分離               |
| `grace_current_hybrid_search` | （削除）                           | GRACE側デフォルトに委任（UI は`disabled=True`） |
| `grace_current_collections`   | （削除）                           | GRACEが全コレクション自動検索のため不要         |

### 3.2 状態遷移図

```mermaid
flowchart TB
    A["初期状態"] --> B["ページロード"]

    subgraph Init["ページロード処理"]
        B1["grace_chat_history = []"]
        B2["grace_session_id = uuid.uuid4()"]
    end
    B --> Init

    Init --> C{"設定変更検知?<br/>(モデル変更 or<br/>Planner/Executor未生成)"}

    C -->|Yes| D["Planner + Executor 初期化"]
    subgraph Reinit["初期化処理"]
        D1["grace_config = get_config()"]
        D2["grace_config.llm.model = selected_model"]
        D3["grace_planner = create_planner(config, model_name)"]
        D4["grace_executor = create_executor(config)"]
        D5["grace_current_model = selected_model"]
    end
    D --> Reinit

    C -->|No| E["ユーザー入力待機"]
    Reinit --> E

    E --> F["チャット処理"]
    subgraph Chat["チャット処理"]
        F1["grace_chat_history.append(user_message)"]
        F2["plan = grace_planner.create_plan(prompt)"]
        F3["gen = grace_executor.execute_plan_generator(plan)"]
        F4["Generator ループ (yield → UI更新)"]
        F5["execution_result = StopIteration.value"]
        F6["grace_chat_history.append(assistant_response)"]
    end
    F --> Chat

    Chat --> G{"クリアボタン?"}
    G -->|Yes| H["状態リセット"]
    subgraph Reset["リセット処理"]
        H1["grace_chat_history = []"]
        H2["del grace_planner"]
        H3["del grace_executor"]
        H4["del grace_current_model"]
        H5["st.rerun()"]
    end
    H --> Reset
    Reset --> A

    G -->|No| E
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class A,B,B1,B2,C,D,D1,D2,D3,D4,D5,E,F,F1,F2,F3,F4,F5,F6,G,H,H1,H2,H3,H4,H5 default
style Init fill:#1a1a1a,stroke:#fff,color:#fff
style Reinit fill:#1a1a1a,stroke:#fff,color:#fff
style Chat fill:#1a1a1a,stroke:#fff,color:#fff
style Reset fill:#1a1a1a,stroke:#fff,color:#fff
```

### 3.3 初期化・リセット条件


| 条件                    | 対象状態                                                                       | 処理                                      |
| ----------------------- | ------------------------------------------------------------------------------ | ----------------------------------------- |
| ページ初回ロード        | `grace_chat_history`, `grace_session_id`                                       | デフォルト値で初期化                      |
| モデル変更              | `grace_planner`, `grace_executor`, `grace_current_model`                       | Planner + Executor 再初期化、トースト表示 |
| Planner/Executor 未生成 | `grace_planner`, `grace_executor`                                              | 初期化処理を実行（初回アクセス時）        |
| クリアボタン            | `grace_chat_history`, `grace_planner`, `grace_executor`, `grace_current_model` | 全状態クリア後`st.rerun()`                |
| キャッシュリセット      | キャッシュのみ                                                                 | `collection_cache.clear(session_id)`      |

### 3.4 初期化処理の詳細

Planner と Executor の初期化は以下の条件のいずれかを満たす場合に実行されます。

```
should_reinitialize = (
    "grace_current_model" not in st.session_state
    or st.session_state.grace_current_model != selected_model
    or "grace_planner" not in st.session_state
    or "grace_executor" not in st.session_state
)
```

初期化フロー:

```python
# 1. GraceConfig を取得し、UIで選択したモデルを反映
grace_config = get_config()            # grace/config.py のシングルトン
grace_config.llm.model = selected_model

# 2. Planner を初期化（モデル名を明示的に指定）
st.session_state.grace_planner = create_planner(
    config=grace_config,
    model_name=selected_model
)

# 3. Executor を初期化（ToolRegistry, Confidence, Intervention, Replan を内包）
st.session_state.grace_executor = create_executor(
    config=grace_config
)

# 4. 現在のモデルを記録
st.session_state.grace_current_model = selected_model
```

旧バージョンとの主な違い:

- 旧: コレクション変更・ハイブリッド検索変更でもエージェント再初期化が必要だった
- 新: **モデル変更のみ**で再初期化。コレクション検索は `RAGSearchTool` が Qdrant から動的に取得するため、UI 側の選択は再初期化トリガーにならない

---

## 4. ユーザー操作フロー

### 4.1 基本操作フロー

```mermaid
flowchart TB
    Start(["開始"]) --> A["1. ページアクセス<br/>→ 初期状態で画面表示"]
    A --> B["2. (オプション) サイドバーで設定変更"]

    subgraph Settings["設定項目"]
        B1["モデル選択"]
        B2["コレクション確認（参考表示）"]
    end
    B --> Settings

    Settings --> C["3. (オプション) コレクションデータ確認<br/>→ エキスパンダーでプレビュー"]
    C --> D["4. 質問入力<br/>→ チャット入力欄に質問を入力してEnter"]
    D --> E1["5. Phase 1: 計画策定"]

    subgraph PlanPhase["📋 計画策定 (Plan)"]
        E1a["Planner.create_plan(prompt)"]
        E1b["複雑度・ステップ数・成功基準を表示"]
        E1c["各ステップ詳細を表示"]
    end
    E1 --> PlanPhase

    PlanPhase --> E2["6. Phase 2-4: 実行"]

    subgraph ExecPhase["⚡ 実行 (Execute)"]
        E2a["Executor.execute_plan_generator(plan)"]
        E2b["ステップ進捗をリアルタイム表示"]
        E2c["Tool Call / Result 表示"]
        E2d["信頼度スコア表示"]
        E2e["(条件付き) 介入リクエスト表示"]
    end
    E2 --> ExecPhase

    ExecPhase --> F["7. 実行結果サマリ確認<br/>→ ステータス・信頼度・リプラン回数・実行時間"]
    F --> G["8. 最終回答確認<br/>→ チャット履歴に追加"]
    G --> H{"継続して質問?"}
    H -->|Yes| D
    H -->|No| End(["終了 or 会話クリア"])
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class Start,A,B,B1,B2,C,D,E1,E1a,E1b,E1c,E2,E2a,E2b,E2c,E2d,E2e,F,G,H,End default
style Settings fill:#1a1a1a,stroke:#fff,color:#fff
style PlanPhase fill:#1a1a1a,stroke:#fff,color:#fff
style ExecPhase fill:#1a1a1a,stroke:#fff,color:#fff
```

### 4.2 操作シーケンス図

```mermaid
%%{ init: { "theme": "base", "themeVariables": { "background": "#000000", "mainBkg": "#000000", "textColor": "#ffffff", "lineColor": "#ffffff", "actorBkg": "#000000", "actorTextColor": "#ffffff", "actorLineColor": "#ffffff", "noteBkg": "#1a1a1a", "noteTextColor": "#ffffff" } } }%%
sequenceDiagram
    participant User as User
    participant UI as UI (Streamlit)
    participant Planner as Planner
    participant Executor as Executor
    participant Tools as ToolRegistry
    participant Cache as CollectionCache
    participant Qdrant as Qdrant

    User->>UI: 1. 質問入力
    UI->>UI: 2. chat_history.append(user_msg)

    Note over UI,Planner: Phase 1: 計画策定

    UI->>Planner: 3. create_plan(prompt)
    Planner->>Planner: 4. estimate_complexity_with_llm(query)
    Planner->>Planner: 5. LLM計画生成 (Claude JSON Schema)
    Planner-->>UI: 6. ExecutionPlan
    UI-->>User: 7. 📋 計画策定 Expander 表示

    Note over UI,Executor: Phase 2-4: 実行

    UI->>Executor: 8. execute_plan_generator(plan)

    loop 各ステップ (Generator)
        Executor->>Tools: 9. ToolRegistry.execute(action, args)

        alt rag_search
            Tools->>Cache: 10. キャッシュ確認
            Cache-->>Tools: 11. キャッシュ結果
            Tools->>Qdrant: 12. 検索実行 (全コレクション順次)
            Qdrant-->>Tools: 13. 検索結果
        else reasoning
            Tools->>Tools: 14. LLM推論 (Claude)
        end

        Tools-->>Executor: 15. ToolResult
        Executor->>Executor: 16. Confidence評価
        Executor->>Executor: 17. Intervention判定

        Executor-->>UI: 18. yield ExecutionState / dict
        UI-->>User: 19. ⚡ 実行 Expander 更新
    end

    Executor-->>UI: 20. return ExecutionResult (StopIteration)
    UI-->>User: 21. 📊 実行結果サマリ表示
    UI-->>User: 22. 最終回答表示
    UI->>UI: 23. chat_history.append(assistant_msg)
```

---

## 5. 関数一覧表

### 5.1 メイン関数


| 関数名                   | 概要                           |
| ------------------------ | ------------------------------ |
| `show_grace_chat_page()` | ページ全体のレンダリングと制御 |

### 5.2 ヘルパー関数・クラス（インポート）


| 関数 / クラス                                    | モジュール               | 概要                                                 |
| ------------------------------------------------ | ------------------------ | ---------------------------------------------------- |
| `get_available_collections_from_qdrant_helper()` | `services.agent_service` | Qdrantコレクション一覧取得                           |
| `Planner` / `create_planner()`                   | `grace.planner`          | 計画策定エージェントの生成                           |
| `Executor` / `create_executor()`                 | `grace.executor`         | 計画実行エージェントの生成                           |
| `ExecutionPlan`                                  | `grace.schemas`          | 実行計画データモデル                                 |
| `ExecutionState`                                 | `grace.executor`         | 実行状態管理データクラス                             |
| `ExecutionResult`                                | `grace.schemas`          | 全体実行結果データモデル                             |
| `StepResult`                                     | `grace.schemas`          | ステップ単位の実行結果                               |
| `StepStatus`                                     | `grace.schemas`          | ステップの状態Enum                                   |
| `GraceConfig` / `get_config()`                   | `grace.config`           | GRACE設定の取得                                      |
| `collection_cache`                               | `agent_cache`            | コレクションキャッシュ管理（グローバルインスタンス） |

### 5.3 grace/ パッケージ内部構成

`grace_chat_page.py` が直接利用するのは Planner / Executor / schemas のみですが、Executor 内部で以下のモジュールが連携します。


| モジュール              | 概要                                     | Executor からの利用               |
| ----------------------- | ---------------------------------------- | --------------------------------- |
| `grace/planner.py`      | 計画生成（LLM + JSON Schema）            | UI から直接呼び出し               |
| `grace/executor.py`     | 計画実行（Generator + 状態管理）         | UI から直接呼び出し               |
| `grace/schemas.py`      | データモデル定義                         | ExecutionPlan, ExecutionResult 等 |
| `grace/config.py`       | 設定管理（YAML + 環境変数）              | get_config() 経由                 |
| `grace/tools.py`        | ToolRegistry（RAG, Reasoning, AskUser）  | Executor 内部で自動利用           |
| `grace/confidence.py`   | 信頼度計算（LLM自己評価 + クエリ網羅度） | Executor 内部で自動利用           |
| `grace/intervention.py` | HITL介入（Confirm, Escalate）            | Executor 内部で自動利用           |
| `grace/replan.py`       | リプラン戦略（部分/全体リプラン）        | Executor 内部で自動利用           |

---

## 6. 関数 IPO詳細

### 6.1 `show_grace_chat_page`

**概要**: GRACEエージェントチャットページのメイン表示関数。サイドバー設定、コレクションデータプレビュー、チャット履歴、Planner による計画策定、Executor による計画実行を統合管理する。

```python
def show_grace_chat_page() -> None
```


| 項目        | 内容                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | なし（セッション状態から取得）                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Process** | 1. コレクションデータ表示エリアの描画<br>2. サイドバー設定UIの描画<br>3. セッション状態の初期化・更新チェック<br>4. Planner + Executor の初期化（必要時）<br>5. チャット履歴の表示<br>6. ユーザー入力の処理<br>7. Phase 1: Planner.create_plan() → 計画策定 Expander 表示<br>8. Phase 2-4: Executor.execute_plan_generator() → 実行 Expander 表示<br>9. ExecutionResult → 実行結果サマリ表示<br>10. 最終回答の表示・履歴追加 |
| **Output**  | なし（画面描画のみ）                                                                                                                                                                                                                                                                                                                                                                                                            |

**主要処理フロー**:

```python
# 1. コレクションデータ表示
with st.expander("📊 コレクションデータの表示", expanded=False):
    target_collection = st.selectbox("コレクションを選択:", preview_collections)
    points, _ = client.scroll(collection_name=target_collection, limit=100)
    st.dataframe(df_preview)

# 2. サイドバー設定
with st.sidebar:
    selected_model = st.selectbox("使用モデル", options=ModelConfig.AVAILABLE_MODELS)
    selected_collections = st.multiselect("検索対象コレクション (参考表示)", ...)
    use_hybrid_search = st.checkbox("ハイブリッド検索", value=True, disabled=True)

# 3. セッション状態初期化
if "grace_chat_history" not in st.session_state:
    st.session_state.grace_chat_history = []
if "grace_session_id" not in st.session_state:
    st.session_state.grace_session_id = str(uuid.uuid4())

# 4. Planner + Executor 初期化（モデル変更時 or 未生成時）
if should_reinitialize:
    grace_config = get_config()
    grace_config.llm.model = selected_model
    st.session_state.grace_planner = create_planner(config=grace_config, model_name=selected_model)
    st.session_state.grace_executor = create_executor(config=grace_config)
    st.session_state.grace_current_model = selected_model

# 5. チャット履歴表示
for message in st.session_state.grace_chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 6. ユーザー入力処理
if prompt := st.chat_input("質問を入力してください..."):
    st.session_state.grace_chat_history.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        # 7. Phase 1: 計画策定
        with st.expander("📋 計画策定 (Plan)", expanded=True):
            plan = st.session_state.grace_planner.create_plan(prompt)
            # metric: 複雑度, ステップ数, 要確認
            # 各ステップ詳細表示

        # 8. Phase 2-4: 実行
        with st.expander("⚡ 実行 (Execute)", expanded=True):
            gen = st.session_state.grace_executor.execute_plan_generator(plan)
            try:
                while True:
                    yielded = next(gen)
                    if isinstance(yielded, ExecutionState):
                        # ステップ状態・信頼度を表示
                    elif isinstance(yielded, dict):
                        # log / tool_call / tool_result / final_answer を表示
            except StopIteration as e:
                execution_result = e.value  # ExecutionResult

        # 9. 実行結果サマリ
        with st.expander("📊 実行結果サマリ", expanded=False):
            # ステータス, 全体信頼度, リプラン回数, 実行時間

        # 10. 最終回答表示
        st.markdown(execution_result.final_answer)
        st.session_state.grace_chat_history.append({"role": "assistant", "content": ...})
```

### 6.2 `Planner.create_plan`

**概要**: ユーザーの質問を分析し、LLM（Anthropic Claude）を使って ExecutionPlan を生成する。

**参照**: `grace/planner.py`

```python
def create_plan(self, query: str) -> ExecutionPlan
```


| 項目        | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | `query: str` — ユーザーの質問文                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Process** | 1.`_get_available_collections()` — Qdrantから利用可能コレクション一覧を取得<br>2. `estimate_complexity_with_llm(query)` — LLMで複雑度を推定（0.0-1.0）<br>3. `PLAN_GENERATION_PROMPT` にコレクション一覧・クエリを埋め込み<br>4. Anthropic Claude API で JSON Schema 出力（`response_schema=ExecutionPlan`）<br>5. `ExecutionPlan.model_validate_json()` でパース<br>6. `validate_plan_dependencies()` で依存関係を検証<br>7. 計画IDを付与（`create_plan_id()`） |
| **Output**  | `ExecutionPlan` — 実行計画（失敗時はフォールバック計画を返却）                                                                                                                                                                                                                                                                                                                                                                                          |

**フォールバック動作**: LLM呼び出しが失敗した場合、`_create_fallback_plan()` が2ステップの単純計画（rag_search → reasoning）を返します。

### 6.3 `Planner.estimate_complexity_with_llm`

**概要**: LLMを使って質問の複雑度を推定する。

```python
def estimate_complexity_with_llm(self, query: str) -> float
```


| 項目        | 内容                                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------- |
| **Input**   | `query: str` — ユーザーの質問文                                                                        |
| **Process** | `COMPLEXITY_ESTIMATION_PROMPT` を使い、Anthropic Claude API で数値のみを取得（temperature=0.1）         |
| **Output**  | `float` — 複雑度スコア（0.0-1.0）。失敗時はキーワードベースの `estimate_complexity()` にフォールバック |

### 6.4 `Executor.execute_plan_generator`

**概要**: 計画をステップごとに実行し、進捗を Generator で逐次返す。UI でのリアルタイム表示に使用。

**参照**: `grace/executor.py`

```python
def execute_plan_generator(
    self, plan: ExecutionPlan, state: Optional[ExecutionState] = None
) -> Generator[ExecutionState | dict, None, ExecutionResult]
```


| 項目        | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | `plan: ExecutionPlan` — 実行する計画<br>`state: Optional[ExecutionState]` — 既存状態（再開時、省略時は新規作成）                                                                                                                                                                                                                                                                                                                                            |
| **Process** | 1.`ExecutionState` を初期化（全ステップを PENDING に設定）<br>2. 各ステップをループ: 依存チェック → ステップ実行 → 信頼度計算 → 介入判定<br>3. ステップ実行は `_execute_step()` を呼び出し、ToolRegistry 経由でツールを実行<br>4. `_execute_step()` が Generator を返す場合（Legacy Agent）は `yield from` で中継<br>5. ステップ失敗時に ReplanOrchestrator がリプランを試行<br>6. 全ステップ完了後に `_calculate_overall_confidence()` で全体信頼度を算出 |
| **Yield**   | `ExecutionState` — ステップ完了/一時停止の通知（status, confidence, intervention_request）<br>`dict` — ツール実行イベント（type: log / tool_call / tool_result / final_answer）                                                                                                                                                                                                                                                                             |
| **Return**  | `ExecutionResult` — 最終実行結果（`StopIteration.value` で取得）                                                                                                                                                                                                                                                                                                                                                                                             |

**Generator のライフサイクル**:

```
┌─ next(gen) ─────────────────────────────────────────────┐
│                                                          │
│  [ステップ開始]                                           │
│    └─ _execute_step(step, state)                        │
│        ├─ ToolRegistry.execute(action, kwargs)          │
│        │   └─ yield dict(type="log", content=...)       │
│        └─ return StepResult                             │
│                                                          │
│  [信頼度計算]                                             │
│    └─ _llm_calculate_step_confidence(tool_result, ...)  │
│                                                          │
│  [介入判定]                                               │
│    ├─ SILENT/NOTIFY → 自動続行                           │
│    └─ CONFIRM/ESCALATE → yield ExecutionState (paused)  │
│                                                          │
│  [ステップ完了]                                           │
│    └─ yield ExecutionState (status + confidence)         │
│                                                          │
│  [失敗時リプラン]                                         │
│    └─ yield from execute_plan_generator(new_plan, state) │
│                                                          │
├─ ... (次ステップへ) ...                                   │
│                                                          │
│  [全ステップ完了]                                         │
│    └─ return ExecutionResult ← StopIteration.value       │
└──────────────────────────────────────────────────────────┘
```

### 6.5 `get_available_collections_from_qdrant_helper`

**概要**: Qdrantから利用可能なコレクション一覧を取得する。

**参照**: `services/agent_service.py`


| 項目        | 内容                                                      |
| ----------- | --------------------------------------------------------- |
| **Input**   | なし                                                      |
| **Process** | QdrantClient でコレクション一覧を取得                     |
| **Output**  | `List[str]`: コレクション名のリスト（エラー時は空リスト） |

### 6.6 主要データモデル

#### ExecutionPlan（`grace/schemas.py`）


| フィールド              | 型                   | 説明                                    |
| ----------------------- | -------------------- | --------------------------------------- |
| `original_query`        | `str`                | ユーザーの元の質問                      |
| `complexity`            | `float` (0.0-1.0)    | 推定複雑度                              |
| `estimated_steps`       | `int` (1-20)         | 推定ステップ数                          |
| `requires_confirmation` | `bool`               | 実行前に確認が必要か                    |
| `steps`                 | `List[PlanStep]`     | 実行ステップのリスト                    |
| `success_criteria`      | `str`                | 計画成功の判定基準                      |
| `created_at`            | `Optional[datetime]` | 計画作成日時                            |
| `plan_id`               | `Optional[str]`      | 計画ID（自動生成、12文字のMD5ハッシュ） |

#### PlanStep（`grace/schemas.py`）


| フィールド        | 型                      | 説明                                                                                          |
| ----------------- | ----------------------- | --------------------------------------------------------------------------------------------- |
| `step_id`         | `int` (≥1)             | ステップ番号                                                                                  |
| `action`          | `Literal[...]`          | アクション種別（rag_search, web_search, reasoning, ask_user, code_execute, run_legacy_agent） |
| `description`     | `str`                   | ステップの説明                                                                                |
| `query`           | `Optional[str]`         | 検索クエリ（検索系アクション用）                                                              |
| `collection`      | `Optional[str]`         | 検索対象コレクション（原則 null — 全コレクション自動検索）                                   |
| `depends_on`      | `List[int]`             | 依存する先行ステップID                                                                        |
| `expected_output` | `str`                   | 期待される出力の説明                                                                          |
| `fallback`        | `Optional[str]`         | 失敗時の代替アクション                                                                        |
| `timeout_seconds` | `Optional[int]` (1-300) | タイムアウト秒数（デフォルト30）                                                              |

#### ExecutionResult（`grace/schemas.py`）


| フィールド                | 型                 | 説明                                                  |
| ------------------------- | ------------------ | ----------------------------------------------------- |
| `plan_id`                 | `str`              | 計画ID                                                |
| `original_query`          | `str`              | 元のクエリ                                            |
| `final_answer`            | `Optional[str]`    | 最終回答                                              |
| `step_results`            | `List[StepResult]` | 各ステップの結果                                      |
| `overall_confidence`      | `float` (0.0-1.0)  | 全体の信頼度                                          |
| `overall_status`          | `Literal[...]`     | 全体ステータス（success, partial, failed, cancelled） |
| `replan_count`            | `int`              | リプラン回数                                          |
| `total_execution_time_ms` | `Optional[int]`    | 総実行時間（ミリ秒）                                  |

#### ExecutionState（`grace/executor.py`）


| フィールド             | 型                              | 説明                         |
| ---------------------- | ------------------------------- | ---------------------------- |
| `plan`                 | `ExecutionPlan`                 | 実行中の計画                 |
| `current_step_id`      | `int`                           | 現在のステップID             |
| `step_results`         | `Dict[int, StepResult]`         | ステップID → 結果のマップ   |
| `step_statuses`        | `Dict[int, StepStatus]`         | ステップID → 状態のマップ   |
| `overall_confidence`   | `float`                         | 全体信頼度（実行中は暫定値） |
| `is_cancelled`         | `bool`                          | キャンセル済みフラグ         |
| `is_paused`            | `bool`                          | 一時停止フラグ（介入待ち）   |
| `intervention_request` | `Optional[InterventionRequest]` | 介入リクエスト               |
| `replan_count`         | `int`                           | リプラン回数                 |

#### StepResult（`grace/schemas.py`）


| フィールド          | 型                                        | 説明                       |
| ------------------- | ----------------------------------------- | -------------------------- |
| `step_id`           | `int`                                     | ステップID                 |
| `status`            | `Literal["success", "partial", "failed"]` | 実行結果ステータス         |
| `output`            | `Optional[str]`                           | 出力内容                   |
| `confidence`        | `float` (0.0-1.0)                         | 信頼度スコア               |
| `sources`           | `List[str]`                               | 引用ソース                 |
| `error`             | `Optional[str]`                           | エラーメッセージ（失敗時） |
| `execution_time_ms` | `Optional[int]`                           | 実行時間（ミリ秒）         |

---

## 7. 依存関係

### 7.1 外部ライブラリ


| ライブラリ      | バージョン | 用途                                         |
| --------------- | ---------- | -------------------------------------------- |
| `streamlit`     | >= 1.28    | UIフレームワーク                             |
| `pandas`        | >= 2.0     | データフレーム表示                           |
| `qdrant-client` | >= 1.6     | Qdrant接続・データ取得                       |
| `anthropic`     | >= 0.40    | Anthropic Claude API（LLM SDK）              |
| `google-genai`  | >= 0.4     | Gemini Embedding API（埋め込み SDK）         |
| `pydantic`      | >= 2.0     | データモデル（ExecutionPlan, StepResult 等） |
| `pyyaml`        | >= 6.0     | GraceConfig の YAML 読み込み                 |
| `MeCab`         | (Optional) | 日本語形態素解析（KeywordExtractor）         |
| `cohere`        | (Optional) | Re-ranking API                               |

### 7.2 内部モジュール（設定）


| モジュール                  | 用途                                                           |
| --------------------------- | -------------------------------------------------------------- |
| `config.AgentConfig`        | エージェント設定（デフォルトモデル、RAG設定）                  |
| `config.ModelConfig`        | Anthropic Claude モデル設定（利用可能モデル一覧）              |
| `grace.config.GraceConfig`  | GRACE統合設定（LLM, Confidence, Intervention, Replan, Qdrant） |
| `grace.config.get_config()` | GraceConfig シングルトン取得（YAML + 環境変数）                |

### 7.3 サービス層


| サービス                                                              | 用途                             | 旧版からの変更 |
| --------------------------------------------------------------------- | -------------------------------- | -------------- |
| `grace.Planner` / `create_planner()`                                  | 計画策定（LLM + JSON Schema）    | **新規追加** |
| `grace.Executor` / `create_executor()`                                | 計画実行（Generator + 状態管理） | **新規追加** |
| `services.agent_service.get_available_collections_from_qdrant_helper` | Qdrantコレクション取得           | 維持           |
| `agent_cache.collection_cache`                                        | セッションベースのキャッシュ管理 | 維持           |
| `qdrant_client_wrapper.get_qdrant_client`                             | Qdrantクライアント取得           | 維持           |

#### 旧版（v1.0）から削除されたサービス


| 旧サービス                                     | 理由                                  |
| ---------------------------------------------- | ------------------------------------- |
| `services.agent_service.ReActAgent`            | Planner + Executor に置換             |
| `agent_parallel_search.parallel_search_engine` | `grace/tools.py` RAGSearchTool に統合 |
| `agent_tools`                                  | `grace/tools.py` ToolRegistry に統合  |

### 7.4 grace/ パッケージ構成図

```mermaid
flowchart TB
    subgraph UI["grace_chat_page.py (UI層)"]
        Page["show_grace_chat_page()"]
    end

    subgraph GracePackage["grace/ パッケージ"]
        subgraph Core["コア"]
            Init["__init__.py<br/>v0.1.0"]
            Schemas["schemas.py<br/>ExecutionPlan, PlanStep,<br/>StepResult, ExecutionResult,<br/>ActionType, StepStatus"]
            Config["config.py<br/>GraceConfig, LLMConfig,<br/>ConfidenceConfig,<br/>InterventionConfig,<br/>ReplanConfig, QdrantConfig"]
        end

        subgraph Phase1["Phase 1: 計画策定"]
            PlannerMod["planner.py<br/>Planner, create_planner()"]
        end

        subgraph Phase2["Phase 2: 実行 + 信頼度"]
            ExecutorMod["executor.py<br/>Executor, ExecutionState,<br/>create_executor()"]
            ToolsMod["tools.py<br/>ToolRegistry,<br/>RAGSearchTool,<br/>ReasoningTool,<br/>AskUserTool"]
            ConfMod["confidence.py<br/>ConfidenceCalculator,<br/>LLMSelfEvaluator,<br/>QueryCoverageCalculator"]
        end

        subgraph Phase3["Phase 3: 介入"]
            IntervMod["intervention.py<br/>InterventionHandler,<br/>InterventionRequest/Response,<br/>DynamicThresholdAdjuster"]
        end

        subgraph Phase4["Phase 4: リプラン"]
            ReplanMod["replan.py<br/>ReplanOrchestrator,<br/>ReplanManager,<br/>ReplanStrategy"]
        end
    end

    subgraph External["外部サービス"]
        Qdrant["Qdrant"]
        ClaudeAPI["Anthropic Claude API"]
        GeminiEmbed["Gemini Embedding API"]
        MeCab["MeCab (Optional)"]
    end

    Page --> PlannerMod
    Page --> ExecutorMod
    Page --> Schemas
    Page --> Config

    PlannerMod --> Schemas
    PlannerMod --> Config
    PlannerMod --> ClaudeAPI

    ExecutorMod --> ToolsMod
    ExecutorMod --> ConfMod
    ExecutorMod --> IntervMod
    ExecutorMod --> ReplanMod
    ExecutorMod --> Schemas

    ToolsMod --> Qdrant
    ToolsMod --> ClaudeAPI
    ToolsMod --> GeminiEmbed
    ToolsMod --> MeCab

    ConfMod --> ClaudeAPI
    ReplanMod --> PlannerMod
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class Page,Init,Schemas,Config,PlannerMod,ExecutorMod,ToolsMod,ConfMod,IntervMod,ReplanMod,Qdrant,ClaudeAPI,GeminiEmbed,MeCab default
style UI fill:#1a1a1a,stroke:#fff,color:#fff
style GracePackage fill:#1a1a1a,stroke:#fff,color:#fff
style Core fill:#1a1a1a,stroke:#fff,color:#fff
style Phase1 fill:#1a1a1a,stroke:#fff,color:#fff
style Phase2 fill:#1a1a1a,stroke:#fff,color:#fff
style Phase3 fill:#1a1a1a,stroke:#fff,color:#fff
style Phase4 fill:#1a1a1a,stroke:#fff,color:#fff
style External fill:#1a1a1a,stroke:#fff,color:#fff
```

### 7.5 依存モジュール詳細

#### 7.5.1 grace/config.py — GRACE 統合設定

YAML ファイル（`grace_config.yaml`）と環境変数から設定を読み込みます。

**主要クラス**:


| クラス               | 説明                                              |
| -------------------- | ------------------------------------------------- |
| `GraceConfig`        | 統合設定ルート                                    |
| `LLMConfig`          | LLM設定（model, temperature, max_tokens 等）      |
| `ConfidenceConfig`   | 信頼度閾値設定                                    |
| `InterventionConfig` | 介入レベル設定                                    |
| `ReplanConfig`       | リプラン制御設定（max_replans 等）                |
| `QdrantConfig`       | Qdrant接続・検索設定（search_priority, top_k 等） |

**デフォルトモデル**: `claude-sonnet-4-6`（`LLMConfig.model`）

#### 7.5.2 grace/tools.py — ToolRegistry

Executor が使用するツール群を管理するレジストリです。

**主要クラス**:


| クラス          | ActionType   | 説明                                                               |
| --------------- | ------------ | ------------------------------------------------------------------ |
| `ToolRegistry`  | -            | ツール管理・ルーティング                                           |
| `RAGSearchTool` | `rag_search` | Qdrant全コレクション自動検索（auto-collection fallback、動的閾値） |
| `ReasoningTool` | `reasoning`  | LLM推論（検索結果を基にAnthropic Claudeで回答生成）                |
| `AskUserTool`   | `ask_user`   | HITL（ユーザーへの確認要求）                                       |

**RAGSearchTool の検索戦略**:

```mermaid
flowchart TB
    A["RAGSearchTool.execute()"] --> B{"collection 指定?"}
    B -->|Yes| C["指定コレクション検索"]
    B -->|No| D["全コレクション自動検索"]
    D --> E["Qdrant から利用可能コレクション取得"]
    E --> F["search_priority 順にソート"]
    F --> G["各コレクション順次検索"]
    G --> H{"スコア >= 動的閾値?"}
    H -->|Yes| I["結果返却"]
    H -->|No| J{"次のコレクション?"}
    J -->|Yes| G
    J -->|No| K["全結果を統合・最高スコア返却"]
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class A,B,C,D,E,F,G,H,I,J,K default
```

#### 7.5.3 grace/confidence.py — 信頼度計算

ステップ実行結果の信頼度を多角的に評価します。

**主要コンポーネント**:


| コンポーネント            | 説明                                              |
| ------------------------- | ------------------------------------------------- |
| `ConfidenceCalculator`    | 統合信頼度計算（evaluate → decide_action）       |
| `LLMSelfEvaluator`        | Anthropic Claude による自己評価（query と answer の整合性） |
| `QueryCoverageCalculator` | クエリキーワードの網羅度計算                      |
| `ConfidenceAggregator`    | 複数信頼度指標の重み付け統合                      |

**介入レベル判定**:


| InterventionLevel | 信頼度範囲     | 動作                       |
| ----------------- | -------------- | -------------------------- |
| `SILENT`          | 高（閾値以上） | 自動続行、ログのみ         |
| `NOTIFY`          | 中高           | 自動続行、UI に通知        |
| `CONFIRM`         | 中低           | 一時停止、ユーザー確認待ち |
| `ESCALATE`        | 低             | 一時停止、エスカレーション |

#### 7.5.4 grace/intervention.py — HITL 介入

信頼度が低い場合のユーザー介入フローを管理します。

**主要クラス**:


| クラス                     | 説明                                                        |
| -------------------------- | ----------------------------------------------------------- |
| `InterventionHandler`      | 介入要否判定・リクエスト生成                                |
| `InterventionRequest`      | 介入リクエスト（level, step_id, message, confidence_score） |
| `InterventionResponse`     | ユーザー応答（action: PROCEED / MODIFY / CANCEL / INPUT）   |
| `DynamicThresholdAdjuster` | フィードバックに基づく閾値自動調整                          |

#### 7.5.5 grace/replan.py — リプラン戦略

ステップ失敗時に計画を動的に修正します。

**主要クラス**:


| クラス               | 説明                                                     |
| -------------------- | -------------------------------------------------------- |
| `ReplanOrchestrator` | リプラン全体制御（失敗検知 → 戦略選択 → 新計画生成）   |
| `ReplanManager`      | リプラン戦略の管理・実行                                 |
| `ReplanStrategy`     | リプラン戦略Enum（PARTIAL: 部分修正 / FULL: 全体再計画） |
| `ReplanResult`       | リプラン結果（success, new_plan, reason）                |

**リプランフロー**:

```mermaid
flowchart TB
    A["ステップ失敗"] --> B{"replan_count < max_replans?"}
    B -->|No| C["リプラン上限 → 失敗で終了"]
    B -->|Yes| D["ReplanOrchestrator.handle_step_failure()"]
    D --> E{"リプラン戦略選択"}
    E -->|PARTIAL| F["失敗ステップ以降を再計画"]
    E -->|FULL| G["Planner.create_plan() で全体再計画"]
    F --> H["新計画で Generator 再帰呼び出し"]
    G --> H
    H --> I["yield from execute_plan_generator(new_plan)"]
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class A,B,C,D,E,F,G,H,I default
```

#### 7.5.6 agent_cache.py — コレクションキャッシュ

前回の検索成功コレクションをセッション単位でキャッシュし、検索効率を向上させます（旧版から変更なし）。

**主要クラス**:


| 名前                   | 種類                   | 説明                                                                    |
| ---------------------- | ---------------------- | ----------------------------------------------------------------------- |
| `CollectionCache`      | クラス                 | キャッシュ管理                                                          |
| `CollectionCacheEntry` | dataclass              | キャッシュエントリ（collection_name, last_score, timestamp, hit_count） |
| `collection_cache`     | グローバルインスタンス | デフォルトキャッシュ（TTL: 300秒）                                      |

---

## 8. イベント処理

### 8.1 ボタンイベント


| ボタン                  | イベント | 処理内容                                                                                                   |
| ----------------------- | -------- | ---------------------------------------------------------------------------------------------------------- |
| 🗑️ 会話履歴をクリア   | クリック | `grace_chat_history` クリア、`grace_planner` / `grace_executor` / `grace_current_model` 削除、`st.rerun()` |
| 🔄 キャッシュをリセット | クリック | `collection_cache.clear(session_id)`、トースト表示                                                         |

### 8.2 入力イベント


| コンポーネント                   | イベント | 処理内容                                                  | 旧版との差分                                         |
| -------------------------------- | -------- | --------------------------------------------------------- | ---------------------------------------------------- |
| モデル選択                       | 変更     | `should_reinitialize = True`、Planner + Executor 再初期化 | ReActAgent → Planner + Executor                     |
| コレクション選択                 | 変更     | UI表示のみ更新（再初期化は発生しない）                    | 旧: 再初期化トリガー →**新: 参考表示のみ**          |
| ハイブリッド検索                 | -        | `disabled=True` のため操作不可                            | 旧: 再初期化トリガー →**新: 操作無効化**            |
| コレクション選択（プレビュー用） | 変更     | Qdrantからデータ取得、DataFrame更新                       | 変更なし                                             |
| チャット入力                     | Enter    | Plan → Execute → Result → 最終回答 の一連処理開始      | execute_turn → create_plan + execute_plan_generator |

### 8.3 Generator イベント処理

新アーキテクチャでは、`Executor.execute_plan_generator()` が Generator として yield する値をリアルタイムに処理します。

#### 処理ループ構造

```python
gen = executor.execute_plan_generator(plan)
execution_result: Optional[ExecutionResult] = None

try:
    while True:
        yielded = next(gen)

        if isinstance(yielded, ExecutionState):
            # --- ステップ完了/一時停止の通知 ---
            ...
        elif isinstance(yielded, dict):
            # --- ツール実行イベント ---
            event_type = yielded.get("type", "")
            ...

except StopIteration as e:
    execution_result = e.value  # ExecutionResult
```

#### yield 型別イベント処理

**ExecutionState（ステップ状態通知）**:


| 処理           | 詳細                                                                           |
| -------------- | ------------------------------------------------------------------------------ |
| ステータス表示 | `Step {sid}: {status_icon} {status}{conf_str}` を `thought_container` に追記   |
| 信頼度表示     | `state.step_results[sid].confidence` を `(信頼度: 0.XX)` 形式で付記            |
| 介入リクエスト | `state.is_paused and state.intervention_request` の場合、`st.warning()` で表示 |
| 自動続行       | 現Phase では介入リクエスト後も`st.info("（自動続行します）")` で自動続行       |

**dict イベント**:


| type           | 処理内容                                                      | 表示コンポーネント                     |
| -------------- | ------------------------------------------------------------- | -------------------------------------- |
| `log`          | 思考プロセスログを追記 +`st.divider()`                        | `thought_container` 内の `st.markdown` |
| `tool_call`    | `🛠️ Tool Call: {name}` + `Args: {args}` を表示              | `thought_container` 内の `st.markdown` |
| `tool_result`  | `📝 Tool Result:` + 内容（500文字で切り詰め）+ `st.divider()` | `thought_container` 内の `st.markdown` |
| `final_answer` | Legacy Agent 経由の最終回答を`final_response_content` に格納  | 直接代入（後続で`st.markdown` 表示）   |

**StopIteration（Generator 終了）**:


| 処理         | 詳細                                                                            |
| ------------ | ------------------------------------------------------------------------------- |
| 結果取得     | `e.value` から `ExecutionResult` を取得                                         |
| 最終回答抽出 | `execution_result.final_answer` を `final_response_content` に設定              |
| サマリ表示   | `📊 実行結果サマリ` Expander にステータス・信頼度・リプラン回数・実行時間を表示 |
| 履歴追加     | `grace_chat_history.append({"role": "assistant", "content": ...})`              |

### 8.4 イベント処理フロー図

```mermaid
flowchart TB
    A["チャット入力 (Enter)"] --> B["chat_history.append(user_msg)"]
    B --> C["📋 計画策定 Expander"]

    subgraph PlanEvents["Phase 1 イベント"]
        C1["st.spinner: 計画生成中..."]
        C2["Planner.create_plan(prompt)"]
        C3["metric 表示 (複雑度/ステップ数/要確認)"]
        C4["各ステップ詳細表示"]
        C5["Plan JSON (raw) 表示"]
    end
    C --> PlanEvents

    PlanEvents --> D["⚡ 実行 Expander"]

    subgraph ExecEvents["Phase 2-4 イベント (Generator ループ)"]
        D1["next(gen)"]
        D1 --> D2{"yield 型判定"}
        D2 -->|ExecutionState| D3["ステップ状態表示<br/>(status icon + 信頼度)"]
        D3 --> D3a{"介入リクエスト?"}
        D3a -->|Yes| D3b["st.warning + 自動続行"]
        D3a -->|No| D1

        D2 -->|dict: log| D4["思考ログ追記"]
        D4 --> D1

        D2 -->|dict: tool_call| D5["ツール呼び出し表示"]
        D5 --> D1

        D2 -->|dict: tool_result| D6["ツール結果表示<br/>(500文字切り詰め)"]
        D6 --> D1

        D2 -->|dict: final_answer| D7["Legacy回答を格納"]
        D7 --> D1

        D2 -->|StopIteration| D8["ExecutionResult 取得"]
    end
    D --> ExecEvents

    D8 --> E["📊 実行結果サマリ Expander"]
    E --> F{"final_answer 存在?"}
    F -->|Yes| G["st.markdown(最終回答)"]
    G --> H["chat_history.append(assistant_msg)"]
    F -->|No| I["st.warning: 応答なし"]
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class A,B,C,C1,C2,C3,C4,C5,D,D1,D2,D3,D3a,D3b,D4,D5,D6,D7,D8,E,F,G,H,I default
style PlanEvents fill:#1a1a1a,stroke:#fff,color:#fff
style ExecEvents fill:#1a1a1a,stroke:#fff,color:#fff
```

### 8.5 旧版イベント処理との対比


| 観点            | 旧版（v1.0）                                                | 新版（v2.0）                                                       |
| --------------- | ----------------------------------------------------------- | ------------------------------------------------------------------ |
| イベントソース  | `ReActAgent.execute_turn()` Generator                       | `Executor.execute_plan_generator()` Generator                      |
| yield 型        | `dict` のみ（type: log/tool_call/tool_result/final_answer） | `ExecutionState` + `dict`（2種類の yield）                         |
| ステップ状態    | なし（ReAct フェーズとして一括）                            | ステップ単位の status + confidence をリアルタイム表示              |
| 介入            | なし                                                        | `ExecutionState.is_paused` + `intervention_request` で一時停止通知 |
| 最終結果取得    | `final_answer` イベント（dict）                             | `StopIteration.value`（`ExecutionResult`）+ Legacy 用 dict         |
| 表示先 Expander | 1つ（🤔 エージェントの思考プロセス）                        | 3つ（📋 計画策定 / ⚡ 実行 / 📊 実行結果サマリ）                   |
| エラー時        | try/except で`st.error`                                     | 同様 +`ExecutionResult(status="failed")` でも結果返却              |

---

## 9. エラーハンドリング

### 9.1 エラー種別


| エラー種別                    | 発生箇所             | 発生条件                                | 対処                                                   |
| ----------------------------- | -------------------- | --------------------------------------- | ------------------------------------------------------ |
| Qdrant接続エラー              | サイドバー初期化     | サーバー未起動、ネットワーク障害        | `st.warning` で警告表示、`["(None)"]` で続行           |
| Planner/Executor 初期化エラー | セッション初期化     | API認証失敗、GraceConfig 読み込みエラー | `st.error` でエラー表示、`return` で処理中断           |
| 計画策定エラー                | Phase 1（Plan）      | LLM呼び出し失敗、JSON パースエラー      | Planner 内部でフォールバック計画を自動生成             |
| ステップ実行エラー            | Phase 2-4（Execute） | ツール実行失敗、タイムアウト            | Executor 内部でフォールバック → リプラン試行          |
| Generator 例外                | Phase 2-4（Execute） | 予期しないランタイムエラー              | `ExecutionResult(status="failed")` を返却              |
| チャット処理エラー            | 全体 try/except      | 上記以外の未捕捉エラー                  | `st.error` でエラー表示、`logger.error(exc_info=True)` |
| コレクションデータ取得エラー  | データプレビュー     | コレクション不在、スキーマ不一致        | `st.error` でエラー表示                                |

### 9.2 エラー処理の多層構造

新アーキテクチャではエラーが3つの層で処理されます。

```mermaid
flowchart TB
    subgraph Layer1["Layer 1: grace/ 内部（自動回復）"]
        A1["Planner: LLM失敗"] --> A2["_create_fallback_plan()<br/>(rag_search → reasoning の2ステップ)"]
        A3["Executor: ステップ失敗"] --> A4{"fallback 定義あり?"}
        A4 -->|Yes| A5["_execute_fallback()"]
        A4 -->|No| A6{"replan_count < max?"}
        A6 -->|Yes| A7["ReplanOrchestrator<br/>→ 新計画で再実行"]
        A6 -->|No| A8["StepResult(status=failed)"]
        A9["Executor: 全体例外"] --> A10["ExecutionResult<br/>(status=failed,<br/>confidence=0.0)"]
    end

    subgraph Layer2["Layer 2: UI ハンドリング"]
        B1["execution_result 判定"]
        B1 --> B2{"final_answer 存在?"}
        B2 -->|Yes| B3["最終回答表示"]
        B2 -->|No| B4["st.warning:<br/>エージェントからの応答がありませんでした"]
    end

    subgraph Layer3["Layer 3: 全体 try/except"]
        C1["Exception"] --> C2["st.error(エラーメッセージ)"]
        C1 --> C3["logger.error(exc_info=True)"]
    end

    Layer1 --> Layer2
    Layer2 --> Layer3
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class A1,A2,A3,A4,A5,A6,A7,A8,A9,A10,B1,B2,B3,B4,C1,C2,C3 default
style Layer1 fill:#1a1a1a,stroke:#fff,color:#fff
style Layer2 fill:#1a1a1a,stroke:#fff,color:#fff
style Layer3 fill:#1a1a1a,stroke:#fff,color:#fff
```

### 9.3 エラー表示コンポーネント


| 表示種別 | Streamlitコンポーネント | 用途                                                     |
| -------- | ----------------------- | -------------------------------------------------------- |
| エラー   | `st.error()`            | 致命的エラー（初期化失敗、未捕捉例外）                   |
| 警告     | `st.warning()`          | 注意喚起（コレクション未検出、応答なし、介入リクエスト） |
| 情報     | `st.info()`             | 補足情報（データなし、自動続行通知）                     |
| トースト | `st.toast()`            | 一時的な通知（設定変更、キャッシュクリア、初期化完了）   |

### 9.4 エラー処理コード例

```python
# Planner + Executor 初期化エラー
try:
    grace_config = get_grace_config()
    grace_config.llm.model = selected_model
    st.session_state.grace_planner = create_planner(config=grace_config, model_name=selected_model)
    st.session_state.grace_executor = create_executor(config=grace_config)
    st.toast("GRACE Planner + Executor の準備が完了しました。")
except Exception as e:
    st.error(f"GRACE エージェントの初期化に失敗しました: {e}")
    logger.error(f"GRACE init failed: {e}", exc_info=True)
    return

# チャット処理エラー（全体を包む try/except）
try:
    # Phase 1: 計画策定
    plan = st.session_state.grace_planner.create_plan(prompt)
    # → 失敗時: Planner 内部でフォールバック計画を自動生成

    # Phase 2-4: 実行
    gen = st.session_state.grace_executor.execute_plan_generator(plan)
    try:
        while True:
            yielded = next(gen)
            # イベント処理...
    except StopIteration as e:
        execution_result = e.value
    # → Generator 内部例外: ExecutionResult(status="failed") を返却

    # 最終回答チェック
    if final_response_content:
        st.markdown(final_response_content)
    else:
        st.warning("エージェントからの応答がありませんでした。")

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
    logger.error(f"GRACE Chat Error: {e}", exc_info=True)
```

---

## 10. 使用例

### 10.1 基本的な使用方法

1. ページにアクセス
2. サイドバーで必要に応じてモデルを変更（デフォルト: `claude-sonnet-4-6`）
3. （オプション）コレクションデータのプレビュー — エキスパンダーを開いてコレクションを選択し、登録されているQ&Aデータを確認
4. チャット入力欄に質問を入力して Enter
5. **📋 計画策定 (Plan)** を確認 — 複雑度、ステップ数、各ステップの詳細
6. **⚡ 実行 (Execute)** を確認 — ステップ進捗、ツール呼び出し・結果、信頼度スコア
7. **📊 実行結果サマリ** を確認（任意）— 全体ステータス、信頼度、リプラン回数、実行時間
8. 最終回答を確認
9. 必要に応じて追加の質問を続ける

### 10.2 典型的な質問例

```
- 「カリン・フォン・アロルディンゲンについて教えてください」
- 「Wikipediaの情報から、〇〇の歴史を説明してください」
- 「ライブドアニュースで報じられた××について教えて」
- 「△△と□□の違いは何ですか？」
```

### 10.3 計画策定の表示例

```
📋 計画策定 (Plan)

目標: カリン・フォン・アロルディンゲンについて教えてください

  複雑度: 0.4    ステップ数: 3    要確認: ✅ いいえ

🎯 成功基準: ユーザーの質問に対して、検索結果に基づく正確な回答を提供する
────────────────────────────
🔍 Step 1: [rag_search] Qdrantナレッジベースから関連情報を検索
   🔑 Query: `カリン・フォン・アロルディンゲン`
   📤 期待出力: Wikipedia等からの人物情報
   🔄 Fallback: `web_search`

🧠 Step 2: [reasoning] 検索結果を基に回答を生成  ← 依存: Step [1]
   📤 期待出力: 経歴・業績をまとめた回答文

🧠 Step 3: [reasoning] 回答の品質チェックと最終整形  ← 依存: Step [2]
   📤 期待出力: ユーザーに提示する最終回答
```

### 10.4 実行プロセスの表示例

```
⚡ 実行 (Execute)

📝 【ツール実行結果: rag_search】
  [検索結果 JSON...]
────────────────────────────
Step 1: ✅ success (信頼度: 0.82)

📝 【ツール実行結果: reasoning】
  カリン・フォン・アロルディンゲンは...
────────────────────────────
Step 2: ✅ success (信頼度: 0.78)

Step 3: ✅ success (信頼度: 0.85)
```

### 10.5 実行結果サマリの表示例

```
📊 実行結果サマリ

ステータス: success
全体信頼度: 0.82
リプラン回数: 0
実行時間: 3450ms
```

---

## 11. 変更履歴


| バージョン | 日付           | 変更内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.0        | 2025-01-29     | 初版作成                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 1.1        | 2025-01-29     | 依存モジュール詳細（agent_cache, agent_parallel_search, agent_tools, regex_mecab）を追加                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **2.0**    | **2025-06-14** | **ReActAgent → Planner + Executor アーキテクチャに全面移行**。主な変更: (1) アーキテクチャ概要を2フェーズ分離型に更新、(2) 画面レイアウトを3 Expander 構成に変更、(3) セッション状態から `grace_agent` / `grace_current_hybrid_search` / `grace_current_collections` を削除し `grace_planner` / `grace_executor` を追加、(4) イベント処理を Generator ベース（ExecutionState + dict yield）に刷新、(5) 依存関係に grace/ パッケージ構成図を追加、(6) エラーハンドリングを3層構造（grace内部自動回復 / UI判定 / 全体try-except）に整理、(7) 使用例を計画策定・実行プロセス・結果サマリの表示例に更新、(8) 付録Bに GraceConfig 設定リファレンスを追加 |
| **3.0**    | **2026-02-17** | **ドキュメント体系の整備**。主な変更: (1) 冒頭ドキュメント一覧表を5件に拡張（readme_rag.md / readme_react_reflection.md / readme_autonomous_agent.md を追加）、(2) 番号付きリンク表で参照順を明示 |
| **4.0**    | **2026-06-16** | **技術スタック統一とドキュメント再構築**。主な変更: (1) LLM プロバイダー表記を Gemini → Anthropic Claude に統一（タイトル / 設定クラス `GeminiConfig`→`ModelConfig` / デフォルト `claude-sonnet-4-6`・軽量 `claude-haiku-4-5-20251001` / LLM用APIキー `ANTHROPIC_API_KEY`）。**Embedding は Gemini（`gemini-embedding-001`・3072次元）のまま維持**、(2) アーカイブ済みドキュメント（移行計画 v2・各種 API 移行ガイド・benchmark_todo・grace_react_refactor_todo）を docs/archive/ へのリンクに整理し、壊れた R3 リンク（plan_for_migration.md）を削除、(3) 全 Mermaid 図を黒背景・白文字スタイルに統一（classDef/class/style 付与、sequenceDiagram は init ヘッダー付与） |
| **4.1**    | **2026-06-17** | **現行コードとの整合更新**。主な変更: (1) UI エントリポイントを `streamlit run agent_rag.py` と明記し、`agent_rag.py::main()` の実際の `st.radio` メニュー（explanation / qdrant_search / agent_chat / grace_chat / log_viewer / rag_data_creation / qdrant_crud）に合わせて付録A.1ページ一覧を修正（旧 `rag_download` / `qa_generation` / `qdrant_registration` / `show_qdrant` は `ui/pages/` に在るが未接続である旨を注記）、(2) RAGデータ作成パイプライン（チャンク分割 → Q/A生成＋Qdrant登録）の CLI コマンドと冒頭技術スタック表を追加（LLM=Anthropic Claude `claude-sonnet-4-6`、ルーティング `grace/llm_compat.py`、Embedding=Gemini `gemini-embedding-001` 3072次元）、(3) ドキュメント索引リンクの実在性を再検証 |
| **4.2**    | **2026-06-17** | **「ドキュメント ↔ 対応コード 対応表」を追加**。10ドキュメント（README 含む）が対象とするソースコードの対応関係を一覧化し、ReAct（`services/agent_service.py`・google-genai 直叩き）と GRACE（`grace/`・`llm_compat` 経由 Anthropic Claude）の系統差、CLI ツールの既定モデル（`gemini-2.5-flash`、`--model` 上書き可）を注記 |

---

## 付録A: アプリケーション構成

### A.1 メインアプリケーション (agent_rag.py)

`grace_chat_page.py`は`agent_rag.py`からインポートされ、サイドバーのメニューから呼び出されます。

```python
# agent_rag.py より抜粋
from ui.pages import show_grace_chat_page

page_mapping = {
    "grace_chat": show_grace_chat_page,
    # 他のページ...
}
```

**利用可能なページ一覧**（`agent_rag.py::main()` の `st.radio` メニュー順）:


| ページID             | 表示名                            | 説明                                                |
| -------------------- | --------------------------------- | --------------------------------------------------- |
| `explanation`        | 📖 説明                           | システム説明ページ                                  |
| `qdrant_search`      | 🔎 Qdrant検索                     | 検索テスト                                          |
| `agent_chat`         | 🤖 Agent(ReAct+Reflection)        | ReAct+Reflectionエージェント（旧版）                |
| `grace_chat`         | [最新] 自律型Agent(Plan+Executor) | **本ページ（Planner + Executor）**                  |
| `log_viewer`         | 📊 未回答ログ                     | 未回答質問のログ閲覧                                |
| `rag_data_creation`  | 📄 RAGデータ作成                  | RAGデータ作成 CLI 手順とドキュメントへの案内        |
| `qdrant_crud`        | 🗄️ QdrantのCRUD                   | Qdrant CRUD 操作の説明                              |

> **注**: `ui/pages/` には `download_page` / `qa_generation_page` / `qdrant_registration_page` / `qdrant_show_page` も実装されていますが、現行の `agent_rag.py` メニューには未接続です（RAGデータ作成は CLI パイプラインで実行）。

### A.2 CLI版エージェント (agent_main.py)

同等の機能を持つCLI版エージェントも提供されています。

```bash
# CLI版エージェントの実行
uv run python agent_main.py
```

**CLI版の機能**:

- Planner + Executor 2フェーズ処理
- 動的コレクション取得
- キーワード抽出（オプション）
- 多言語対応の検索戦略
- 信頼度評価・リプラン

---

## 付録B: 設定リファレンス

### B.1 AgentConfig（旧設定 — UI共通）


| 設定項目                 | デフォルト値                 | 説明                             |
| ------------------------ | ---------------------------- | -------------------------------- |
| `RAG_DEFAULT_COLLECTION` | `"wikipedia_ja_5per"`        | デフォルト検索コレクション       |
| `RAG_SEARCH_LIMIT`       | 3                            | 検索結果の最大件数               |
| `RAG_SCORE_THRESHOLD`    | 0.50                         | 検索結果として採用する最小スコア |
| `MODEL_NAME`             | `ModelConfig.DEFAULT_MODEL`  | デフォルトモデル                 |
| `CHAT_LOG_FILE_NAME`     | `"agent_chat.log"`           | チャットログファイル名           |
| `CHAT_LOG_LEVEL`         | `"INFO"`                     | ログレベル                       |

### B.2 ModelConfig


| 設定項目              | デフォルト値             | 説明                          |
| --------------------- | ------------------------ | ----------------------------- |
| `DEFAULT_MODEL`       | `"claude-sonnet-4-6"`    | デフォルト LLM モデル         |
| `LIGHT_MODEL`         | `"claude-haiku-4-5-20251001"` | 軽量 LLM モデル          |
| `EMBEDDING_MODEL`     | `"gemini-embedding-001"` | 埋め込みモデル（Gemini）      |
| `EMBEDDING_DIMS`      | 3072                     | 埋め込み次元数                |
| `DEFAULT_TEMPERATURE` | 1.0                      | 温度パラメータ                |

### B.3 GraceConfig（grace/config.py — GRACE 統合設定）

GraceConfig は `config/grace_config.yml` から読み込まれ、環境変数（`GRACE_` プレフィックス）で上書き可能です。

#### B.3.1 LLMConfig


| 設定項目      | デフォルト値               | 説明                  |
| ------------- | -------------------------- | --------------------- |
| `provider`    | `"anthropic"`              | LLMプロバイダー       |
| `model`       | `"claude-sonnet-4-6"`      | 使用モデル            |
| `temperature` | 0.7                        | 温度パラメータ        |
| `max_tokens`  | 4096                       | 最大トークン数        |
| `timeout`     | 30                         | APIタイムアウト（秒） |

#### B.3.2 EmbeddingConfig


| 設定項目     | デフォルト値             | 説明                 |
| ------------ | ------------------------ | -------------------- |
| `provider`   | `"gemini"`               | 埋め込みプロバイダー |
| `model`      | `"gemini-embedding-001"` | 埋め込みモデル       |
| `dimensions` | 3072                     | 埋め込み次元数       |

#### B.3.3 ConfidenceConfig


| 設定項目                   | デフォルト値 | 説明                     |
| -------------------------- | ------------ | ------------------------ |
| `weights.search_quality`   | 0.25         | 検索品質の重み           |
| `weights.source_agreement` | 0.20         | ソース一致度の重み       |
| `weights.llm_self_eval`    | 0.25         | LLM自己評価の重み        |
| `weights.tool_success`     | 0.15         | ツール成功率の重み       |
| `weights.query_coverage`   | 0.15         | クエリ網羅度の重み       |
| `thresholds.silent`        | 0.9          | SILENT 介入レベルの閾値  |
| `thresholds.notify`        | 0.7          | NOTIFY 介入レベルの閾値  |
| `thresholds.confirm`       | 0.4          | CONFIRM 介入レベルの閾値 |

#### B.3.4 InterventionConfig


| 設定項目                   | デフォルト値 | 説明                     |
| -------------------------- | ------------ | ------------------------ |
| `default_timeout`          | 300（5分）   | 介入タイムアウト（秒）   |
| `auto_proceed_on_timeout`  | `false`      | タイムアウト時の自動続行 |
| `max_clarification_rounds` | 3            | 最大確認回数             |

#### B.3.5 ReplanConfig


| 設定項目                   | デフォルト値 | 説明                           |
| -------------------------- | ------------ | ------------------------------ |
| `max_replans`              | 3            | 最大リプラン回数               |
| `confidence_threshold`     | 0.4          | リプラントリガーの信頼度閾値   |
| `partial_replan_threshold` | 0.6          | 部分リプランの閾値             |
| `cooldown_seconds`         | 5            | リプラン間のクールダウン（秒） |

#### B.3.6 QdrantConfig


| 設定項目          | デフォルト値                                               | 説明                     |
| ----------------- | ---------------------------------------------------------- | ------------------------ |
| `url`             | `"http://localhost:6333"`                                  | QdrantサーバーURL        |
| `collection_name` | `"customer_support_faq"`                                   | デフォルトコレクション   |
| `search_limit`    | 5                                                          | 検索結果の最大件数       |
| `score_threshold` | 0.35                                                       | 最小スコア閾値           |
| `search_priority` | `["wikipedia_ja", "livedoor", "cc_news", "japanese_text"]` | コレクション検索優先順位 |

#### B.3.7 その他


| サブ設定        | 主要項目                                           | 説明           |
| --------------- | -------------------------------------------------- | -------------- |
| `CostConfig`    | `daily_limit_usd=10.0`, `per_query_limit_usd=0.50` | コスト管理     |
| `ErrorConfig`   | `max_retries=3`, `exponential_backoff=true`        | エラーリトライ |
| `LoggingConfig` | `level="INFO"`, `file="logs/grace.log"`            | ロギング       |
| `ToolsConfig`   | `enabled=["rag_search", "reasoning", "ask_user"]`  | 有効ツール一覧 |

### B.4 CohereConfig（オプション）


| 設定項目       | デフォルト値                  | 説明           |
| -------------- | ----------------------------- | -------------- |
| `API_KEY`      | `os.getenv("COHERE_API_KEY")` | Cohere APIキー |
| `RERANK_MODEL` | `"rerank-multilingual-v3.0"`  | Rerankモデル   |

---

## 付録C: トラブルシューティング

### C.1 よくある問題と解決策


| 問題                                     | 原因                            | 解決策                                                               |
| ---------------------------------------- | ------------------------------- | -------------------------------------------------------------------- |
| 「コレクションがありません」と表示される | Qdrantサーバー未起動            | `docker-compose up -d qdrant` でQdrantを起動                         |
| Planner/Executor 初期化エラー            | APIキー未設定                   | LLM用 `ANTHROPIC_API_KEY`（および Embedding 用 `GOOGLE_API_KEY` / `GEMINI_API_KEY`）を設定 |
| GraceConfig 読み込みエラー               | YAML ファイル不在 or 構文エラー | `config/grace_config.yml` を確認。不在時はデフォルト値で動作         |
| 計画策定が常にフォールバック             | LLM呼び出し失敗                 | API認証・ネットワーク・モデル名を確認。ログ`logs/grace_run.log` 参照 |
| 信頼度が常に0.0                          | Confidence計算の依存エラー      | `grace_config.yml` の `confidence.weights` 設定を確認                |
| 検索結果が見つからない                   | コレクションにデータがない      | CSVデータ登録ページでデータを登録                                    |
| MeCabエラー                              | MeCab未インストール             | `pip install mecab-python3` でインストール（Optional）               |
| キャッシュが効かない                     | TTL切れ                         | 5分以内に同一セッションで検索を実行                                  |

### C.2 ログの確認方法

```bash
# アプリケーションログ
journalctl -u streamlit-app -f

# GRACE エージェントログ（新規）
tail -f logs/grace_run.log

# 旧エージェントログ
tail -f logs/agent_chat.log
```

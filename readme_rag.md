# RAG Q/A 生成・検索システム ドキュメント

**Version 3.2** | 最終更新: 2026-06-17

**Agent Graceの資料へ** [Agent Grace](README.md) | **ReActの資料へ** [ReAct](README_ReAct.md)

---

## 目次

1. [概要](#概要)
2. [アーキテクチャ構成図](#1-アーキテクチャ構成図)
3. [RAG関連 ファイル・クラス・関数 一覧表](#15-rag関連-ファイルクラス関数-一覧表)
4. [モジュール構成図](#2-モジュール構成図)
5. [クラス・関数一覧表](#3-クラス関数一覧表)
6. [クラス・関数 IPO詳細](#4-クラス関数-ipo詳細)
7. [統合アプリ agent_rag.py](#5-統合アプリ-agent_ragpy)
8. [クイックスタート](#6-クイックスタート)
9. [環境構築詳細](#7-環境構築詳細)
10. [設定・定数](#8-設定定数)
11. [使用例](#9-使用例)
12. [対応データセット](#10-対応データセット)
13. [ディレクトリ構造](#11-ディレクトリ構造)
14. [ドキュメント一覧](#12-ドキュメント一覧)
15. [エクスポート](#13-エクスポート)
16. [変更履歴](#14-変更履歴)
17. [付録: 依存関係図](#付録-依存関係図)

---

## 概要

本システムは、日本語・英語ドキュメントから文章をチャンク分割し、チャンクからQ/Aペアを自動生成し、Qdrantベクトルデータベースで類似度検索・AI応答生成（RAG）を実現する統合アプリケーションです。

パイプラインは以下の **3段階** で構成されます。

- **① チャンキング**: `chunking/csv_text_to_chunks_text_csv.py` — LLMベースの3段階セマンティックチャンキング（段落分割→意味的分割→連続性チェック→最大トークン強制分割）
- **② Q/A生成**: `qa_generation/`（`QAPipeline` + `SmartQAGenerator`）— チャンク済みCSVからQ/Aペアを自動生成
- **③ Qdrant登録**: `qa_qdrant/make_qa_register_qdrant.py` → `register_to_qdrant.py` — Gemini Embeddingでベクトル化しQdrantへ登録

なお `make_qa_register_qdrant.py` は **②と③を一気通貫で実行する統合CLI** であり、Phase 1 で `QAPipeline` を、Phase 2 で `register_to_qdrant` を呼び出します。

### 主な責務

- テキスト/CSVファイルのLLMベース意味的チャンク分割（3段階: 段落分割→意味的分割→連続性チェック）。最終チャンクは `_enforce_max_chunk_tokens()` で `MAX_CHUNK_TOKENS`（512）以下に強制分割される。
- チャンクからのQ/Aペア自動生成（`SmartQAGenerator` による構造化出力1回/チャンク、Celery並列処理対応）
- Gemini Embedding（`gemini-embedding-001`, 3072次元）によるベクトル化（※EmbeddingはGemini固定）
- Qdrantベクトルデータベースへの登録・検索・RAG応答生成
- カバレージ分析によるQ/A品質評価

### 各責務対応のモジュール


| # | 責務                  | 対応モジュール                            | 説明                                               |
| - | --------------------- | ----------------------------------------- | -------------------------------------------------- |
| 1 | LLMベースチャンク分割 | `chunking/csv_text_to_chunks_text_csv.py` | 3段階非同期パイプライン（段落→意味→連続性）＋最大トークン強制分割 |
| 2 | Q/Aペア自動生成       | `qa_generation/pipeline.py` (`QAPipeline`) | `SmartQAGenerator` 経由でチャンクごとに1回生成 |
| 3 | 統合CLI（②+③）       | `qa_qdrant/make_qa_register_qdrant.py`    | Phase 1: Q/A生成 → Phase 2: `register_to_qdrant` 委譲 |
| 4 | Qdrant登録            | `qa_qdrant/register_to_qdrant.py`         | Embedding（Gemini固定）→コレクション作成→アップサート |
| 5 | Embedding/操作        | `services/qdrant_service.py`              | Gemini Embedding API（gemini-embedding-001, 3072次元） |
| 6 | ベクトル検索・RAG     | `qdrant_client_wrapper.py`                | Dense/Hybrid Search、3段階フォールバック           |

### 主要機能一覧


| 機能                       | 説明                                                          |
| -------------------------- | ------------------------------------------------------------- |
| `chunks_all_async()`       | テキストを3段階で意味的にチャンク化（asyncio並列処理）         |
| `load_text_from_csv()`     | CSVをテキストとして読み込み（`combine_rows` で全行結合可）     |
| `save_chunks_as_csv()`     | チャンクをメタデータ付きCSV + シンプルCSVで保存               |
| `QAPipeline`               | Q/A生成パイプライン制御クラス（チャンク済みCSV専用、v3.0）   |
| `QAPipeline.run()`         | パイプライン実行（データ読込→Q/A生成→カバレージ分析→保存）  |
| `SmartQAGenerator.analyze_and_generate()` | チャンク分析+Q/A生成を構造化出力1回で実行 |
| `run_registration()`       | Q/AペアCSVからQdrant登録（`register_to_qdrant` へ委譲）       |
| `register_to_qdrant()`     | CSV→Embedding（Gemini固定）→コレクション作成→アップサート     |
| `AsyncAPIClient`           | 非同期LLMクライアント（構造化出力・Semaphore並列制御＋指数バックオフ リトライ） |
| `CheckpointManager`        | 3段階チャンク処理のチェックポイント管理（クラッシュ復旧対応） |
| `search_collection()`      | Qdrantコレクション検索（Dense/Hybrid、3段階フォールバック）   |

---

## 1. アーキテクチャ構成図

### 1.1 システム全体構成

```mermaid
flowchart TB
    subgraph CLIENT["クライアント層"]
        APP["agent_rag.py 統合Streamlitアプリ"]
        CLI_CHUNK["CLI: csv_text_to_chunks_text_csv.py"]
        CLI_QA["CLI: make_qa_register_qdrant.py"]
    end

    subgraph CHUNKING["チャンク分割モジュール"]
        CHUNK_MAIN["chunks_all_async()"]
        STEP1["Step1: 階層構造化 段落分割"]
        STEP2["Step2: 意味的チャンキング"]
        STEP3["Step3: 文脈連続性チェック（rule/llm/off）"]
    end

    subgraph QA_PIPELINE["Q/A生成・登録モジュール"]
        PIPELINE["QAPipeline"]
        SMART_QA["SmartQAGenerator"]
        CELERY["Celery並列処理"]
        REG["run_registration() → register_to_qdrant()"]
    end

    subgraph EXTERNAL["外部サービス層"]
        ANTHROPIC_LLM["Anthropic LLM API claude-sonnet-4-6"]
        GEMINI_EMB["Gemini Embedding API gemini-embedding-001 3072次元"]
        QDRANT["Qdrant Vector DB コサイン類似度"]
        REDIS["Redis Celeryブローカー"]
    end

    CLI_CHUNK --> CHUNK_MAIN
    CHUNK_MAIN --> STEP1 --> STEP2 --> STEP3
    STEP1 --> ANTHROPIC_LLM
    STEP2 --> ANTHROPIC_LLM
    STEP3 --> ANTHROPIC_LLM

    CLI_QA --> PIPELINE
    APP --> PIPELINE
    PIPELINE --> SMART_QA --> ANTHROPIC_LLM
    PIPELINE --> CELERY --> REDIS
    CLI_QA --> REG
    REG --> GEMINI_EMB
    REG --> QDRANT
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class APP,CLI_CHUNK,CLI_QA,CHUNK_MAIN,STEP1,STEP2,STEP3,PIPELINE,SMART_QA,CELERY,REG,ANTHROPIC_LLM,GEMINI_EMB,QDRANT,REDIS default
style CLIENT fill:#1a1a1a,stroke:#fff,color:#fff
style CHUNKING fill:#1a1a1a,stroke:#fff,color:#fff
style QA_PIPELINE fill:#1a1a1a,stroke:#fff,color:#fff
style EXTERNAL fill:#1a1a1a,stroke:#fff,color:#fff
```

### 1.2 データフロー

1. 入力データ（CSV/テキスト）を `csv_text_to_chunks_text_csv.py` で3段階チャンク分割。CSVは `load_text_from_csv()` でテキスト化（`--combine-rows` で全行結合可）。出力はメタデータ付きチャンクCSV + シンプルCSV。
2. チャンクCSVを `make_qa_register_qdrant.py` に入力
3. Phase 1: `QAPipeline` → `SmartQAGenerator` でチャンクごとにQ/Aペアを構造化出力1回で生成（同期/Celery並列処理対応）
4. Phase 2: `run_registration()` → `register_to_qdrant()` でQ/AペアをGemini Embeddingでベクトル化（Embeddingは常にGemini固定）
5. Qdrantコレクションにアップサート登録（payload: question/answer/source 等。ポイントIDは内容ベースで決定的＝べき等）
6. ユーザー質問 → Embedding → Qdrant検索 → RAG応答生成

---

## 1.5 RAG関連 ファイル・クラス・関数 一覧表

### チャンク分割パッケージ（chunking/）


| ファイル名                       | クラス名            | メソッド/関数名               | 機能概要                                                   |
| -------------------------------- | ------------------- | ----------------------------- | ---------------------------------------------------------- |
| `csv_text_to_chunks_text_csv.py` | -                   | `chunks_all_async()`          | テキストを3段階で意味的にチャンク化（メインエントリ）       |
| `csv_text_to_chunks_text_csv.py` | -                   | `load_text_from_csv()`        | CSVをテキストとして読み込み（`combine_rows` で全行結合可）  |
| `csv_text_to_chunks_text_csv.py` | -                   | `save_chunks_as_csv()`        | チャンクをメタデータ付きCSVで保存（+シンプルCSV同時出力）  |
| `csv_text_to_chunks_text_csv.py` | -                   | `save_chunks_as_simple_csv()` | チャンクをシンプルCSV（Textカラムのみ）で保存              |
| `csv_text_to_chunks_text_csv.py` | -                   | `_enforce_max_chunk_tokens()` | 最終チャンクを `MAX_CHUNK_TOKENS`（512）以下に強制分割     |
| `csv_text_to_chunks_text_csv.py` | -                   | `generate_output_filename()`  | 入力ファイル名から出力ファイル名を自動生成                 |
| `csv_text_to_chunks_text_csv.py` | -                   | `_step1_hierarchical_split()` | Step1: 階層構造化（段落分割） — LLMで空行ベースの段落分離 |
| `csv_text_to_chunks_text_csv.py` | -                   | `_step2_semantic_chunking()`  | Step2: 意味的チャンキング — 段落を意味単位に再分割        |
| `csv_text_to_chunks_text_csv.py` | -                   | `_step3_continuity_check()`   | Step3: 文脈連続性チェック — 隣接チャンクの連続性判定→結合 |
| `csv_text_to_chunks_text_csv.py` | -                   | `_normalize_whitespace()`     | テキストの改行・空白を正規化（CSV出力用）                  |
| `csv_text_to_chunks_text_csv.py` | -                   | `_preprocess_text()`          | テキスト前処理（長い1行を句読点で分割）                    |
| `csv_text_to_chunks_text_csv.py` | -                   | `_postprocess_paragraph()`    | 段落の後処理（句読点で文を分割し改行区切り）               |
| `csv_text_to_chunks_text_csv.py` | -                   | `_split_sentences_simple()`   | 簡易的な文分割（日本語対応）                               |
| `csv_text_to_chunks_text_csv.py` | -                   | `main()`                      | CLIエントリポイント（argparse→チャンク実行）              |
| `async_api_client.py`            | `AsyncAPIClient`    | `__init__()`                  | 非同期LLMクライアント初期化（Semaphore並列制御）           |
| `async_api_client.py`            | `AsyncAPIClient`    | `generate_content()`          | response_schema による構造化出力呼び出し（Semaphore制御）  |
| `async_api_client.py`            | `AsyncAPIClient`    | `_execute_with_retry()`       | リトライロジック（指数バックオフ、不完全JSON検出）         |
| `async_api_client.py`            | `AsyncAPIClient`    | `_is_valid_json()`            | JSONの完全性チェック                                       |
| `async_api_client.py`            | `AsyncAPIClient`    | `_is_truncated_response()`    | レスポンス切断チェック（stop_reason判定）                  |
| `async_api_client.py`            | `AsyncAPIClient`    | `get_stats()`                 | リクエスト統計情報（トークン使用量・キャッシュ含む）を取得 |
| `async_api_client.py`            | `AsyncAPIClient`    | `reset_stats()`               | 統計情報をリセット                                         |
| `checkpoint_manager.py`          | `CheckpointManager` | `__init__()`                  | チェックポイントディレクトリ・ジョブID初期化               |
| `checkpoint_manager.py`          | `CheckpointManager` | `save()`                      | ステップ結果をJSON保存（原子書込み）                       |
| `checkpoint_manager.py`          | `CheckpointManager` | `load()`                      | ステップ結果を読み込み                                     |
| `checkpoint_manager.py`          | `CheckpointManager` | `load_with_metadata()`        | メタデータ付きでステップ結果を読み込み                     |
| `checkpoint_manager.py`          | `CheckpointManager` | `exists()`                    | チェックポイントの存在確認                                 |
| `checkpoint_manager.py`          | `CheckpointManager` | `get_latest_completed_step()` | 最後に完了したステップを取得                               |
| `checkpoint_manager.py`          | `CheckpointManager` | `get_resume_point()`          | クラッシュからの再開ポイントを取得                         |
| `checkpoint_manager.py`          | `CheckpointManager` | `clear()`                     | ジョブのチェックポイントを削除                             |
| `checkpoint_manager.py`          | `CheckpointManager` | `get_job_info()`              | ジョブ情報を取得                                           |
| `checkpoint_manager.py`          | `CheckpointManager` | `list_jobs()`                 | 保存済みジョブの一覧を取得（クラスメソッド）               |
| `checkpoint_manager.py`          | `CheckpointManager` | `cleanup_old_jobs()`          | 古いジョブを削除（クラスメソッド）                         |
| `models.py`                      | `SentenceUnit`      | -                             | 1つの文（意味の最小単位）のPydanticモデル                  |
| `models.py`                      | `ParagraphUnit`     | `full_text`                   | 段落内の全文を改行結合して返すプロパティ                   |
| `models.py`                      | `StructuralResult`  | -                             | テキスト構造化結果（Step1/Step2のレスポンススキーマ）      |
| `models.py`                      | `ContinuityResult`  | -                             | 文脈連続性判定結果（Step3のレスポンススキーマ）            |
| `prompts.py`                     | -                   | `PARAGRAPH_SEPARATION_PROMPT` | Step1: 空行ベース段落分割プロンプト                        |
| `prompts.py`                     | -                   | `SEMANTIC_CHUNKING_PROMPT`    | Step2: 意味的分割プロンプト（トピック境界検出）            |
| `prompts.py`                     | -                   | `CONTINUITY_CHECK_PROMPT`     | Step3: 文脈連続性判定プロンプト（True/False）              |
| `regex_string.py`                | -                   | `chunk_text()`                | テキストをチャンクに分割（日本語/英語自動判定）            |
| `regex_string.py`                | -                   | `chunk_text_with_info()`      | テキスト分割+詳細情報（分割方法・言語・件数）              |
| `utils.py`                       | -                   | `show_paragraphs()`           | パラグラフリストの整形表示                                 |
| `utils.py`                       | -                   | `setup_logging()`             | ロギング設定（ファイル+コンソール）                        |
| `utils.py`                       | -                   | `format_time()`               | 秒数を読みやすい形式に変換（秒/分/時間）                   |
| `utils.py`                       | -                   | `format_size()`               | 文字数を読みやすい形式に変換（K文字/M文字）                |
| `utils.py`                       | -                   | `estimate_api_calls()`        | API呼び出し回数と処理時間を見積もり                        |
| `utils.py`                       | -                   | `print_stats()`               | 統計情報の整形表示                                         |

### Q/A生成・Qdrant登録（qa_qdrant/）


| ファイル名                   | クラス名 | メソッド/関数名               | 機能概要                                                        |
| ---------------------------- | -------- | ----------------------------- | --------------------------------------------------------------- |
| `make_qa_register_qdrant.py` | -        | `main()`                      | 統合パイプライン実行（Phase1: Q/A生成 → Phase2: Qdrant登録）   |
| `make_qa_register_qdrant.py` | -        | `run_registration()`          | Qdrant登録（`register_to_qdrant.register_to_qdrant()` へ委譲） |
| `make_qa_register_qdrant.py` | -        | `normalize_source_filename()` | ファイル名から日時サフィックスを除去して正規化                  |
| `register_to_qdrant.py`      | -        | `register_to_qdrant()`        | CSV→Embedding（Gemini固定）→コレクション作成→アップサート（UI用CSV出力付き） |
| `make_qa.py`                 | -        | `main()`                      | Q/A生成のみのCLI（`QAPipeline.run()` を呼び出し）             |
| `register_to_qdrant.py`      | -        | `main()`                      | 登録専用CLIエントリポイント                                     |

### Q/A生成パイプライン（qa_generation/）


| ファイル名             | クラス名           | メソッド/関数名           | 機能概要                                             |
| ---------------------- | ------------------ | ------------------------- | ---------------------------------------------------- |
| `pipeline.py` (v3.0)   | `QAPipeline`       | `__init__()`              | コンストラクタ（設定ロード、SmartQAGenerator初期化） |
| `pipeline.py`          | `QAPipeline`       | `load_data()`             | データ読み込み（チャンク済みCSV/データセット）       |
| `pipeline.py`          | `QAPipeline`       | `_load_chunks_from_csv()` | チャンク済みCSVをチャンクリストに変換                |
| `pipeline.py`          | `QAPipeline`       | `generate_qa()`           | Q/Aペアを生成（同期/Celery並列切替）                 |
| `pipeline.py`          | `QAPipeline`       | `_generate_with_celery()` | Celery並列処理によるQ/A生成                          |
| `pipeline.py`          | `QAPipeline`       | `_generate_sync()`        | 同期処理によるQ/A生成（SmartQAGenerator使用）        |
| `pipeline.py`          | `QAPipeline`       | `evaluate_coverage()`     | カバレージ評価（チャンク網羅率分析）                 |
| `pipeline.py`          | `QAPipeline`       | `save()`                  | 結果をCSV保存                                        |
| `pipeline.py`          | `QAPipeline`       | `run()`                   | パイプライン一括実行（読込→生成→分析→保存）        |
| `pipeline.py`          | `QAPipeline`       | `_validate_inputs()`      | 入力パラメータの排他制御検証                         |
| `pipeline.py`          | `QAPipeline`       | `_load_config()`          | データセット/ファイル設定をロード                    |
| `smart_qa_generator.py` (v3.0) | `SmartQAGenerator` | `analyze_and_generate()` | チャンク分析+Q/A生成を構造化出力1回で実行 |
| `smart_qa_generator.py` | `SmartQAResult`   | -                         | 分析+Q/A生成の統合スキーマ（qa_count/key_topics等）  |
| `smart_qa_generator.py` | `SmartQAPair`     | -                         | Q/Aペア1件のスキーマ（question/answer/topic）        |
| `evaluation.py` (v3.0) | -                  | `analyze_coverage()`      | カバレージ分析（SemanticCoverage使用）               |
| `evaluation.py`        | -                  | `get_optimal_thresholds()`| 統一デフォルト閾値を返す（strict0.8/standard0.7/lenient0.6） |
| `evaluation.py`        | -                  | `multi_threshold_coverage()` | 複数閾値でカバレージを評価                         |
| `semantic.py`          | `SemanticCoverage` | -                         | Embeddingベースのカバレージ計算クラス                |
| `data_io.py`           | -                  | -                         | Q/Aデータの入出力ユーティリティ                      |
| `models.py`            | -                  | -                         | Q/A生成共通のPydanticモデル                          |

### Qdrant操作サービス（services/）


| ファイル名          | クラス名              | メソッド/関数名                              | 機能概要                                              |
| ------------------- | --------------------- | -------------------------------------------- | ----------------------------------------------------- |
| `qdrant_service.py` | `QdrantHealthChecker` | `__init__()`                                 | Qdrantヘルスチェッカー初期化                          |
| `qdrant_service.py` | `QdrantHealthChecker` | `check_port()`                               | ポートの開放状態チェック                              |
| `qdrant_service.py` | `QdrantHealthChecker` | `check_qdrant()`                             | Qdrant接続チェック（メトリクス付き）                  |
| `qdrant_service.py` | `QdrantDataFetcher`   | `__init__()`                                 | Qdrantデータフェッチャー初期化                        |
| `qdrant_service.py` | `QdrantDataFetcher`   | `fetch_collections()`                        | コレクション一覧をDataFrameで取得                     |
| `qdrant_service.py` | `QdrantDataFetcher`   | `fetch_collection_points()`                  | コレクションの詳細データをDataFrameで取得             |
| `qdrant_service.py` | `QdrantDataFetcher`   | `fetch_collection_info()`                    | コレクションの詳細情報（ベクトル設定含む）            |
| `qdrant_service.py` | `QdrantDataFetcher`   | `fetch_collection_source_info()`             | コレクションのデータソース情報を集計                  |
| `qdrant_service.py` | -                     | `embed_texts_for_qdrant()`                   | テキストをGemini Embeddingでバッチベクトル化          |
| `qdrant_service.py` | -                     | `create_or_recreate_collection_for_qdrant()` | コレクション作成/再作成（Sparse Vector対応）          |
| `qdrant_service.py` | -                     | `build_points_for_qdrant()`                  | Qdrantポイント構築（payload: question/answer/source） |
| `qdrant_service.py` | -                     | `upsert_points_to_qdrant()`                  | ポイントをバッチアップサート                          |
| `qdrant_service.py` | -                     | `embed_query_for_search()`                   | 検索クエリをベクトル化（プロバイダー自動選択）        |
| `qdrant_service.py` | -                     | `get_collection_stats()`                     | コレクション統計情報を取得                            |
| `qdrant_service.py` | -                     | `get_all_collections()`                      | 全コレクション一覧を取得                              |
| `qdrant_service.py` | -                     | `get_all_collections_simple()`               | 全コレクション一覧を取得（シンプル版）                |
| `qdrant_service.py` | -                     | `delete_all_collections()`                   | 全コレクションを削除（除外リスト対応）                |
| `qdrant_service.py` | -                     | `load_csv_for_qdrant()`                      | CSVをロード（列名マッピング+バリデーション）          |
| `qdrant_service.py` | -                     | `build_inputs_for_embedding()`               | 埋め込み用入力テキストを構築（question+answer結合）   |
| `qdrant_service.py` | -                     | `scroll_all_points_with_vectors()`           | コレクションから全ポイント取得（ベクトル含む）        |
| `qdrant_service.py` | -                     | `merge_collections()`                        | 複数コレクションを統合して新コレクションに登録        |
| `qdrant_service.py` | -                     | `map_collection_to_csv()`                    | コレクション名から対応CSVファイル名を取得             |
| `qdrant_service.py` | -                     | `get_dynamic_collection_mapping()`           | コレクションとCSVの動的マッピング生成                 |
| `qdrant_service.py` | -                     | `get_collection_embedding_params()`          | コレクションの埋め込みモデル設定を推論                |

### Qdrantクライアントラッパー


| ファイル名                 | クラス名              | メソッド/関数名                        | 機能概要                                              |
| -------------------------- | --------------------- | -------------------------------------- | ----------------------------------------------------- |
| `qdrant_client_wrapper.py` | `QdrantHealthChecker` | `check_port()`                         | ポートの開放状態チェック                              |
| `qdrant_client_wrapper.py` | `QdrantHealthChecker` | `check_qdrant()`                       | Qdrant接続チェック（メトリクス付き）                  |
| `qdrant_client_wrapper.py` | `QdrantHealthChecker` | `get_client()`                         | 接続済みクライアントを取得                            |
| `qdrant_client_wrapper.py` | `QdrantDataFetcher`   | `fetch_collections()`                  | コレクション一覧をDataFrameで取得                     |
| `qdrant_client_wrapper.py` | `QdrantDataFetcher`   | `fetch_collection_points()`            | コレクションの詳細データを取得                        |
| `qdrant_client_wrapper.py` | `QdrantDataFetcher`   | `fetch_collection_info()`              | コレクションの詳細情報を取得                          |
| `qdrant_client_wrapper.py` | `QdrantDataFetcher`   | `fetch_collection_source_info()`       | データソース情報を集計                                |
| `qdrant_client_wrapper.py` | -                     | `create_qdrant_client()`               | QdrantClientを作成（ファクトリ関数）                  |
| `qdrant_client_wrapper.py` | -                     | `get_qdrant_client()`                  | シングルトンQdrantClientを取得                        |
| `qdrant_client_wrapper.py` | -                     | `get_embedding_client()`               | プロバイダー別EmbeddingClientを取得                   |
| `qdrant_client_wrapper.py` | -                     | `get_cached_sparse_embedding_client()` | Sparse Embeddingクライアントを取得（キャッシュ付き）  |
| `qdrant_client_wrapper.py` | -                     | `create_or_recreate_collection()`      | コレクション作成/再作成（Hybrid Search対応）          |
| `qdrant_client_wrapper.py` | -                     | `embed_texts_unified()`                | テキストをベクトル化（プロバイダー統一版）            |
| `qdrant_client_wrapper.py` | -                     | `embed_query_unified()`                | 検索クエリをベクトル化（プロバイダー統一版）          |
| `qdrant_client_wrapper.py` | -                     | `embed_sparse_texts_unified()`         | テキストをSparse Embeddingでベクトル化                |
| `qdrant_client_wrapper.py` | -                     | `embed_sparse_query_unified()`         | クエリをSparse Embeddingでベクトル化                  |
| `qdrant_client_wrapper.py` | -                     | `build_points()`                       | Qdrantポイント構築（Dense/Hybrid対応）                |
| `qdrant_client_wrapper.py` | -                     | `upsert_points()`                      | ポイントをバッチアップサート                          |
| `qdrant_client_wrapper.py` | -                     | `search_collection()`                  | コレクション検索（Dense/Hybrid、3段階フォールバック） |
| `qdrant_client_wrapper.py` | -                     | `create_collection_for_provider()`     | プロバイダー別コレクション作成                        |
| `qdrant_client_wrapper.py` | -                     | `get_provider_vector_size()`           | プロバイダーのベクトル次元数を取得                    |
| `qdrant_client_wrapper.py` | -                     | `get_collection_stats()`               | コレクション統計情報を取得                            |
| `qdrant_client_wrapper.py` | -                     | `get_all_collections()`                | 全コレクション一覧を取得                              |
| `qdrant_client_wrapper.py` | -                     | `delete_all_collections()`             | 全コレクションを削除                                  |
| `qdrant_client_wrapper.py` | -                     | `load_csv_for_qdrant()`                | CSVをロード（Qdrant登録用）                           |
| `qdrant_client_wrapper.py` | -                     | `build_inputs_for_embedding()`         | 埋め込み用入力テキストを構築                          |
| `qdrant_client_wrapper.py` | -                     | `batched()`                            | イテラブルをバッチに分割                              |

### 設定管理


| ファイル名  | クラス名             | メソッド/関数名             | 機能概要                                |
| ----------- | -------------------- | --------------------------- | --------------------------------------- |
| `config.py` | `ModelConfig`        | `supports_temperature()`    | モデルのtemperatureサポート判定         |
| `config.py` | `ModelConfig`        | `get_model_limits()`        | LLMモデルのトークン制限を取得           |
| `config.py` | `ModelConfig`        | `get_model_pricing()`       | LLMモデルの料金を取得                   |
| `config.py` | `DatasetInfo`        | -                           | データセット情報（dataclass）           |
| `config.py` | `DatasetConfig`      | `get_dataset()`             | データセット設定を取得                  |
| `config.py` | `DatasetConfig`      | `get_dataset_dict()`        | データセット設定を辞書形式で取得        |
| `config.py` | `DatasetConfig`      | `get_all_dataset_names()`   | 全データセット名を取得                  |
| `config.py` | `QAGenerationConfig` | -                           | Q/A生成設定（質問タイプ階層、閾値等）   |
| `config.py` | `QdrantConfig`       | -                           | Qdrant接続設定（HOST/PORT/DEFAULT_VECTOR_SIZE=3072） |
| `config.py` | `GeminiConfig`       | `supports_thinking_level()` | Gemini LLM/Embedding設定（EMBEDDING_MODEL/EMBEDDING_DIMS=3072・思考レベル判定） |
| `config.py` | `CeleryConfig`       | -                           | Celery並列処理設定                      |
| `config.py` | `PathConfig`         | `ensure_dirs()`             | 必要なディレクトリを一括作成            |
| `config.py` | `AgentConfig`        | -                           | RAGエージェント設定（検索閾値等）       |
| `config.py` | `LLMProviderConfig`  | `get_embedding_dims()`      | プロバイダー別Embedding次元数を取得     |

---

## 2. モジュール構成図

### 2.1 内部モジュール構成

```mermaid
flowchart TB
    subgraph CHUNKING_PKG["chunking パッケージ"]
        CSV_CHUNK["csv_text_to_chunks_text_csv.py"]
        ASYNC_CLI["AsyncAPIClient（Anthropic）"]
        CHECKPOINT["CheckpointManager"]
        MODELS["models.py StructuralResult / ContinuityResult"]
        PROMPTS["prompts.py 3種のプロンプト定義"]
        UTILS["utils.py"]
        REGEX["regex_string.py chunk_text()"]
    end

    subgraph QA_QDRANT["qa_qdrant パッケージ"]
        MAKE_QA["make_qa_register_qdrant.py"]
        REG_QDRANT["register_to_qdrant.py"]
    end

    subgraph QA_GEN["qa_generation パッケージ"]
        QA_PIPE["pipeline.py QAPipeline"]
        SMART_GEN["smart_qa_generator.py SmartQAGenerator"]
        EVAL["evaluation.py analyze_coverage()"]
        SEM["semantic.py SemanticCoverage"]
    end

    subgraph SERVICES["サービス層"]
        QDRANT_SVC["qdrant_service.py"]
        QDRANT_WRAP["qdrant_client_wrapper.py"]
        HELPER_EMB["helper/helper_embedding.py"]
    end

    subgraph CONFIG_PKG["設定"]
        CONFIG["config.py ModelConfig / DatasetConfig / QdrantConfig / GeminiConfig"]
    end

    CSV_CHUNK --> ASYNC_CLI
    CSV_CHUNK --> CHECKPOINT
    CSV_CHUNK --> MODELS
    CSV_CHUNK --> PROMPTS
    CSV_CHUNK --> UTILS
    CSV_CHUNK --> REGEX

    MAKE_QA --> QA_PIPE
    MAKE_QA --> REG_QDRANT
    REG_QDRANT --> QDRANT_SVC
    REG_QDRANT --> QDRANT_WRAP

    QA_PIPE --> SMART_GEN
    QA_PIPE --> EVAL
    EVAL --> SEM
    QA_PIPE --> CONFIG

    QDRANT_SVC --> HELPER_EMB
    QDRANT_SVC --> QDRANT_WRAP
    QDRANT_WRAP --> HELPER_EMB
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class CSV_CHUNK,ASYNC_CLI,CHECKPOINT,MODELS,PROMPTS,UTILS,REGEX,MAKE_QA,REG_QDRANT,QA_PIPE,SMART_GEN,EVAL,SEM,QDRANT_SVC,QDRANT_WRAP,HELPER_EMB,CONFIG default
style CHUNKING_PKG fill:#1a1a1a,stroke:#fff,color:#fff
style QA_QDRANT fill:#1a1a1a,stroke:#fff,color:#fff
style QA_GEN fill:#1a1a1a,stroke:#fff,color:#fff
style SERVICES fill:#1a1a1a,stroke:#fff,color:#fff
style CONFIG_PKG fill:#1a1a1a,stroke:#fff,color:#fff
```

### 2.2 外部依存関係


| ライブラリ      | 用途                                 |
| --------------- | ------------------------------------ |
| `anthropic`     | Anthropic Claude LLM API（チャンク分割・Q/A生成・Agent応答） |
| `google-genai`  | Gemini Embedding API（gemini-embedding-001） |
| `qdrant-client` | Qdrantベクトルデータベース操作       |
| `pydantic`      | レスポンススキーマ定義（構造化出力 `response_schema`） |
| `pandas`        | CSV入出力・データ処理                |
| `tiktoken`      | トークン数計算                       |
| `celery[redis]` | 並列タスク処理                       |
| `streamlit`     | Web UIフレームワーク                 |

### 2.3 内部依存モジュール


| モジュール                         | 用途                                |
| ---------------------------------- | ----------------------------------- |
| `chunking.async_api_client`        | 非同期LLM呼び出し（チャンク分割・構造化出力） |
| `chunking.checkpoint_manager`      | チェックポイント永続化              |
| `chunking.models`                  | Pydanticスキーマ（段落/連続性判定） |
| `chunking.prompts`                 | 3段階チャンク用プロンプト           |
| `qa_generation.pipeline`           | Q/A生成パイプライン制御（v3.0）     |
| `qa_generation.smart_qa_generator` | スマートQ/A生成（LLM動的決定・v3.0）|
| `qa_generation.evaluation`         | カバレージ分析（v3.0統一閾値）      |
| `qa_generation.semantic`           | Embeddingベースのカバレージ計算     |
| `qa_qdrant.register_to_qdrant`     | Qdrant登録ロジック（一本化）        |
| `services.qdrant_service`          | Qdrant操作サービス                  |
| `qdrant_client_wrapper`            | Qdrantクライアントラッパー          |
| `helper.helper_embedding`          | Embedding抽象化レイヤー             |
| `helper.helper_llm`                | LLMクライアント抽象化（プロバイダー自動判定） |
| `config`                           | 全体設定管理                        |

---

## 3. クラス・関数一覧表

### 3.1 csv_text_to_chunks_text_csv.py

#### 関数一覧


| 関数名                                                     | 概要                                                  |
| ---------------------------------------------------------- | ----------------------------------------------------- |
| `chunks_all_async(text, model, max_workers, block_size, ...)` | テキストを3段階で意味的にチャンク化（メインエントリ） |
| `load_text_from_csv(csv_path, text_column, max_rows, combine_rows)` | CSVをテキストとして読み込み（`combine_rows` で全行結合） |
| `save_chunks_as_csv(chunks, output_file, ...)`             | チャンクをメタデータ付きCSVで保存                     |
| `save_chunks_as_simple_csv(chunks, output_file, ...)`      | チャンクをシンプルCSV（Textのみ）で保存               |
| `generate_output_filename(input_file, output_dir, ...)`    | 出力ファイル名の自動生成（`{ステム}_chunks.csv`）     |
| `_step1_hierarchical_split(text, client, model, block_size, ...)` | Step1: 階層構造化（段落分割）                  |
| `_step2_semantic_chunking(paragraphs, client, model, ...)` | Step2: 意味的チャンキング                             |
| `_step3_continuity_check(chunks, client, model, ...)`      | Step3: 文脈連続性チェック（隣接チャンク結合）          |
| `_enforce_max_chunk_tokens(chunks, max_tokens)`            | チャンクを `MAX_CHUNK_TOKENS`（512）以下に強制分割    |
| `_normalize_whitespace(text)`                              | テキストの改行・空白を正規化                          |
| `_preprocess_text(text)`                                   | テキスト前処理（長い1行を句読点で分割）               |
| `_postprocess_paragraph(paragraph)`                        | 段落の後処理（句読点で文を分割し改行区切り）          |

### 3.2 make_qa_register_qdrant.py

#### 関数一覧


| 関数名                                                     | 概要                                                          |
| ---------------------------------------------------------- | ------------------------------------------------------------- |
| `main()`                                                   | 統合パイプライン実行（Phase1: Q/A生成 → Phase2: Qdrant登録） |
| `run_registration(csv_path, collection_name, recreate, batch_size, provider, ui_output_dir)` | `register_to_qdrant.register_to_qdrant()` へ委譲 |
| `normalize_source_filename(filename)`                      | ファイル名から日時サフィックス（`_YYYYMMDD_HHMMSS`）を除去     |

### 3.3 AsyncAPIClient クラス


| メソッド                                                  | 概要                                          |
| --------------------------------------------------------- | --------------------------------------------- |
| `__init__(api_key, max_workers, max_retries, max_output_tokens)` | コンストラクタ（LLMクライアント接続、Semaphore初期化） |
| `generate_content(model, contents, response_schema, ...)` | `response_schema` による構造化出力呼び出し（Semaphore制御） |
| `get_stats()`                                             | リクエスト統計（トークン使用量・キャッシュ含む） |
| `reset_stats()`                                           | 統計情報をリセット                            |

### 3.4 CheckpointManager クラス


| メソッド                           | 概要                                                 |
| ---------------------------------- | ---------------------------------------------------- |
| `__init__(checkpoint_dir, job_id)` | コンストラクタ（チェックポイントディレクトリ初期化） |
| `save(step_name, data, metadata)`  | ステップの結果をJSON保存（原子書込み）               |
| `load(step_name)`                  | ステップの結果を読み込み                             |
| `exists(step_name)`                | チェックポイントの存在確認                           |
| `get_resume_point()`               | 再開ポイントを取得                                   |
| `clear()`                          | チェックポイントを削除                               |

### 3.5 QAPipeline クラス（qa_generation/pipeline.py, v3.0）


| メソッド                                         | 概要                                                 |
| ------------------------------------------------ | ---------------------------------------------------- |
| `__init__(dataset_name, input_file, model, output_dir, max_docs, client)` | コンストラクタ（設定ロード、SmartQAGenerator初期化） |
| `load_data()`                                    | チャンク済みCSV/データセット読み込み                 |
| `generate_qa(chunks, use_celery, ...)`           | Q/Aペアを生成（同期/Celery並列）                     |
| `evaluate_coverage(chunks, qa_pairs, ...)`       | カバレージ評価                                       |
| `save(qa_pairs, coverage_results)`               | 結果をCSV保存                                        |
| `run(use_celery, concurrency, ...)`              | パイプライン一括実行                                 |

> **v3.0 注記**: `QAPipeline` は **チャンク済みCSV専用** です。チャンク分割処理（`create_chunks()` 等）は前段の `chunking/` に完全移譲され、本クラスからは削除されました。

### 3.6 SmartQAGenerator クラス（qa_generation/smart_qa_generator.py, v3.0）


| メソッド/属性                              | 概要                                                 |
| ------------------------------------------ | ---------------------------------------------------- |
| `__init__(model="claude-sonnet-4-6", api_key=None)` | LLMクライアント初期化（`model` でモデル指定） |
| `analyze_and_generate(chunk_text)`         | チャンク分析+Q/A生成を構造化出力1回で実行 |
| `SmartQAResult`（スキーマ）                | qa_count(0-5)/key_topics/importance_score/complexity/reasoning/qa_pairs |
| `SmartQAPair`（スキーマ）                  | question/answer/topic                                |

> **v3.0 注記**: 旧実装の「分析→生成」2段階方式を廃止し、`analyze_and_generate()` による **チャンク1件=LLM呼び出し1回** に統合（脆弱なテキストパースを排除し `response_schema` 構造化出力に一本化）。`SmartQAResult.qa_count` は 0〜5 に制約され、`importance_score` は 0.0〜1.0。

---

## 4. クラス・関数 IPO詳細

### 4.1 chunks_all_async()

**概要**: テキストを3段階（段落分割→意味的分割→連続性チェック）で意味的にチャンク化する非同期メイン関数。チャンク後は `_enforce_max_chunk_tokens()` により `MAX_CHUNK_TOKENS`（512）以下へ強制分割される。

```python
async def chunks_all_async(
    text: str,
    model: str = "claude-sonnet-4-6",
    max_workers: int = 8,
    block_size: int = 1000,
    checkpoint_manager: Optional[CheckpointManager] = None,
    output_file: Optional[str] = None,
    dataset_type: str = "custom",
    source_file: Optional[str] = None,
) -> List[str]
```


| パラメータ           | 型                          | デフォルト               | 説明                             |
| -------------------- | --------------------------- | ------------------------ | -------------------------------- |
| `text`               | str                         | -                        | 入力テキスト（`load_text_from_csv()` で生成） |
| `model`              | str                         | "claude-sonnet-4-6"      | 使用するLLMモデル（軽量用途は `claude-haiku-4-5-20251001`） |
| `max_workers`        | int                         | 8                        | 非同期並列ワーカー数（Semaphore上限） |
| `block_size`         | int                         | 1000                     | Step1ブロックサイズ（文字数）    |
| `checkpoint_manager` | Optional[CheckpointManager] | None                     | チェックポイント管理             |
| `output_file`        | Optional[str]               | None                     | 出力ファイルパス（CSV）          |
| `dataset_type`       | str                         | "custom"                 | データセット種別                 |
| `source_file`        | Optional[str]               | None                     | 元ファイル名                     |


| 項目        | 内容                                                                                                                                                                                                                                                                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Input**   | `text: str`, `model: str`, `max_workers: int`                                                                                                                                                                                                                                                                                  |
| **Process** | 1. APIキー検証、AsyncAPIClient初期化<br>2. Step1: `_step1_hierarchical_split()` — テキストをブロック分割→LLMで段落分離<br>3. Step2: `_step2_semantic_chunking()` — 段落を意味単位にチャンク化<br>4. `_enforce_max_chunk_tokens()` で `MAX_CHUNK_TOKENS`（512）以下へ強制分割<br>5. Step3: `_step3_continuity_check()` — 隣接チャンクの連続性判定→マージ<br>6. output_file指定時はメタデータ付きCSV + シンプルCSVを保存 |
| **Output**  | `List[str]`: 最終チャンクリスト（メタデータは出力CSVに含まれる）                                                                                                                                                                                                                                                               |

**戻り値例**:

```python
[
    "人工知能（AI）は、機械学習と深層学習を基盤として急速に発展しています。特に自然言語処理（NLP）の分野では、トランスフォーマーモデルが革命的な成果を上げました。",
    "BERTやGPTなどの大規模言語モデルは、文脈理解能力を大幅に向上させています。",
    "AIの応用は医療診断から自動運転まで幅広く、社会に大きな影響を与えています。"
]
```

```python
# 使用例
import asyncio
from chunking.csv_text_to_chunks_text_csv import chunks_all_async, load_text_from_csv

text = load_text_from_csv("OUTPUT/document.csv", combine_rows=True)
chunks = asyncio.run(chunks_all_async(
    text=text,
    model="claude-sonnet-4-6",
    max_workers=8,
    block_size=1000,
    output_file="output_chunked/result.csv"
))
print(f"生成チャンク数: {len(chunks)}")
```

---

### 4.2 load_text_from_csv()

**概要**: CSVファイルからテキストを読み込む。テキストカラムを自動検出し、`combine_rows=True` の場合は全行を結合して1テキストとして返す。

```python
def load_text_from_csv(
    csv_path: str,
    text_column: Optional[str] = None,
    max_rows: Optional[int] = None,
    combine_rows: bool = False
) -> str
```


| パラメータ     | 型            | デフォルト | 説明                                 |
| -------------- | ------------- | ---------- | ------------------------------------ |
| `csv_path`     | str           | -          | CSVファイルパス                      |
| `text_column`  | Optional[str] | None       | テキストカラム名（None時は自動検出） |
| `max_rows`     | Optional[int] | None       | 最大処理行数                         |
| `combine_rows` | bool          | False      | 全行を結合して1テキストにするか      |


| 項目        | 内容                                                                                                                                    |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | `csv_path: str`（CSVファイルパス）                                                                                                      |
| **Process** | 1. CSV読み込み（pandas）<br>2. テキストカラム自動検出（text, Content, Combined_Text等）<br>3. 空行フィルタリング<br>4. `combine_rows` 指定時は全行を結合 |
| **Output**  | `str`: テキスト                                                                                                                         |

---

### 4.3 save_chunks_as_csv()

**概要**: チャンクをメタデータ付きCSVで保存。オプションでシンプルCSV（Textカラムのみ）も同時出力。出力CSVには `chunk_id, text, tokens, chunk_idx, dataset_type, type, sentence_count, source_file` が含まれる。

```python
def save_chunks_as_csv(
    chunks: List[str],
    output_file: str,
    dataset_type: str = "custom",
    source_file: Optional[str] = None,
    normalize_whitespace: bool = True,
    save_simple_csv: bool = True
) -> str
```


| パラメータ             | 型            | デフォルト | 説明                     |
| ---------------------- | ------------- | ---------- | ------------------------ |
| `chunks`               | List[str]     | -          | チャンクリスト           |
| `output_file`          | str           | -          | 出力ファイルパス         |
| `dataset_type`         | str           | "custom"   | データセット種別         |
| `source_file`          | Optional[str] | None       | 元ファイル名             |
| `normalize_whitespace` | bool          | True       | 改行・空白を正規化するか |
| `save_simple_csv`      | bool          | True       | シンプルCSVも保存するか  |


| 項目        | 内容                                                                                                                                                           |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | `chunks: List[str]`, `output_file: str`                                                                                                                        |
| **Process** | 1. 各チャンクの改行正規化（オプション）<br>2. メタデータ付きCSV生成（chunk_id, text, tokens, chunk_idx, dataset_type, type, sentence_count, source_file）<br>3. `save_simple_csv=True`時、シンプルCSVも出力 |
| **Output**  | `str`: 保存したCSVファイルパス                                                                                                                                 |

---

### 4.4 AsyncAPIClient クラス

LLM APIへの非同期呼び出しを管理。Semaphoreで並列数を制御し、指数バックオフでリトライする。構造化出力は `response_schema`（Pydanticモデル）と `response_mime_type="application/json"` 指定で実現し、不完全/切断レスポンスを検出して再試行する。

#### コンストラクタ: `__init__`

**概要**: 非同期LLMクライアントの初期化。並列数制御用Semaphoreとリトライ設定を構成する。

```python
AsyncAPIClient(
    api_key: str,
    max_workers: int = 8,
    max_retries: int = 3,
    max_output_tokens: int = 8192
)
```


| パラメータ          | 型  | デフォルト | 説明                    |
| ------------------- | --- | ---------- | ----------------------- |
| `api_key`           | str | -          | LLM API Key             |
| `max_workers`       | int | 8          | 並列数（Semaphore上限） |
| `max_retries`       | int | 3          | リトライ回数            |
| `max_output_tokens` | int | 8192       | 出力トークン制限        |


| 項目        | 内容                                                  |
| ----------- | ----------------------------------------------------- |
| **Input**   | `api_key: str`, `max_workers: int`                    |
| **Process** | クライアント初期化、Semaphore作成、統計カウンタ初期化 |
| **Output**  | AsyncAPIClientインスタンス                            |

#### メソッド: `generate_content`

**概要**: Semaphoreで並列数を制御しながらLLM APIを呼び出す。`response_schema` による構造化出力、不完全JSONの検出とリトライ機能を含む。

```python
async def generate_content(
    model: str,
    contents: str,
    response_schema: Type[BaseModel],
    task_id: Optional[str] = None
) -> Optional[str]
```


| 項目        | 内容                                                                                                                                                                                                          |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | `model: str`, `contents: str`, `response_schema: Type[BaseModel]`                                                                                                                                            |
| **Process** | 1. Semaphore取得<br>2. Pydanticスキーマを `response_schema` に指定し JSON出力を強制<br>3. レスポンステキストを取得<br>4. レスポンス切断チェック<br>5. JSON完全性チェック<br>6. 失敗時は指数バックオフでリトライ（最大3回） |
| **Output**  | `Optional[str]`: JSONレスポンス文字列、全リトライ失敗時はNone                                                                                                                                                 |

---

### 4.5 CheckpointManager クラス

3段階チャンク処理の中間結果をJSON保存し、クラッシュ時に途中から再開可能にする。

#### コンストラクタ: `__init__`

**概要**: チェックポイントディレクトリとジョブIDの初期化。

```python
CheckpointManager(
    checkpoint_dir: str = "./checkpoints",
    job_id: Optional[str] = None
)
```


| 項目        | 内容                                                       |
| ----------- | ---------------------------------------------------------- |
| **Input**   | `checkpoint_dir: str`, `job_id: Optional[str]`             |
| **Process** | ジョブID生成（未指定時はタイムスタンプ）、ディレクトリ作成 |
| **Output**  | CheckpointManagerインスタンス                              |

#### メソッド: `save`

**概要**: ステップの結果をJSONとして保存（一時ファイル→リネームで原子性確保）。

```python
def save(step_name: str, data: List[str], metadata: Optional[dict] = None) -> str
```


| 項目        | 内容                                                                                                                            |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | `step_name: str`（"step1"/"step2"/"step3"）, `data: List[str]`                                                                  |
| **Process** | 1. チェックポイントデータ構築（step, timestamp, count, data）<br>2. 一時ファイルに書き込み<br>3. `os.replace()`で原子的リネーム |
| **Output**  | `str`: 保存したファイルパス                                                                                                     |

#### メソッド: `get_resume_point`

**概要**: クラッシュからの再開ポイントを取得。

```python
def get_resume_point() -> tuple[Optional[str], Optional[List[str]]]
```


| 項目        | 内容                                                                            |
| ----------- | ------------------------------------------------------------------------------- |
| **Input**   | なし（内部ステートから判定）                                                    |
| **Process** | step3→step2→step1の順にチェックポイント存在確認                               |
| **Output**  | `Tuple[Optional[str], Optional[List[str]]]`: (再開ステップ名, 前ステップデータ) |

---

### 4.6 run_registration()（make_qa_register_qdrant.py）

**概要**: Q/AペアCSVをQdrantに登録する。実処理は `qa_qdrant.register_to_qdrant.register_to_qdrant()` に委譲される。Embeddingの既定プロバイダーは **Gemini（gemini-embedding-001, 3072次元）** で、`provider` 引数で切り替え可能。

```python
def run_registration(
    csv_path: str,
    collection_name: str,
    recreate: bool,
    batch_size: int,
    provider: str,
    ui_output_dir: str = "qa_output"
) -> bool
```


| パラメータ        | 型   | デフォルト  | 説明                       |
| ----------------- | ---- | ----------- | -------------------------- |
| `csv_path`        | str  | -           | Q/AペアCSVのパス           |
| `collection_name` | str  | -           | Qdrantコレクション名       |
| `recreate`        | bool | -           | コレクションを再作成するか |
| `batch_size`      | int  | -           | Embeddingバッチサイズ      |
| `provider`        | str  | -           | Embeddingプロバイダー（既定: gemini） |
| `ui_output_dir`   | str  | "qa_output" | UI用正規化CSVの出力先      |


| 項目        | 内容                                                                                                                                                                                                                                                         |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Input**   | `csv_path: str`, `collection_name: str`, `provider: str`                                                                                                                                                                                                     |
| **Process** | `register_to_qdrant()` へ委譲: 1. CSV読み込み、question+answerを結合してベクトル化対象テキスト作成<br>2. Gemini Embeddingでベクトル化、コレクション作成/再作成<br>3. バッチアップサート（payload付き・内容ベース決定的ID）<br>4. UI用正規化CSV出力 |
| **Output**  | `bool`: 成功時True、失敗時False                                                                                                                                                                                                                              |

---

### 4.7 QAPipeline クラス（qa_generation/pipeline.py, v3.0）

チャンク済みCSVからQ/Aペアを生成するパイプライン制御クラス。チャンク分割処理は持たない（前段の `chunking/` で完了済み）。

#### メソッド: `run`

**概要**: パイプライン一括実行（データ読込→チャンク変換→Q/A生成→カバレージ分析→保存）。

```python
def run(
    use_celery: bool = False,
    celery_workers: int = 1,
    concurrency: int = 8,
    batch_chunks: int = 3,
    analyze_coverage: bool = True,
    coverage_threshold: Optional[float] = None
) -> Dict
```


| パラメータ             | 型   | デフォルト | 説明                         |
| ---------------------- | ---- | ---------- | ---------------------------- |
| `use_celery`           | bool | False      | Celery並列処理を使用するか   |
| `celery_workers`       | int  | 1          | Celeryワーカープロセス数（チェック用、非推奨） |
| `concurrency`          | int  | 8          | 並列タスク数                 |
| `batch_chunks`         | int  | 3          | 1回のAPIで処理するチャンク数 |
| `analyze_coverage`     | bool | True       | カバレージ分析を実行するか   |
| `coverage_threshold`   | Optional[float] | None | カバレージ判定の類似度閾値（None時は既定値） |


| 項目        | 内容                                                                                                                                                                                                                         |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | チャンク済みCSVファイル（コンストラクタで指定）                                                                                                                                                                              |
| **Process** | 1.`load_data()` でチャンク済みCSV/データセット読み込み<br>2. `_load_chunks_from_csv()` でチャンクリスト変換<br>3. `generate_qa()` でQ/Aペア生成（同期/Celery）<br>4. `evaluate_coverage()` でカバレージ分析<br>5. `save()` で結果CSV出力 |
| **Output**  | `Dict`: `{saved_files, qa_count, coverage_results, success}`                                                                                                                                                                 |

**戻り値例**:

```python
{
    "saved_files": {"qa_csv": "qa_output/pipeline/qa_pairs_20260612.csv"},
    "qa_count": 150,
    "coverage_results": {"coverage_rate": 0.85, "covered_chunks": 42, "total_chunks": 50},
    "success": True
}
```

---

### 4.8 register_to_qdrant()（register_to_qdrant.py）

**概要**: Q/AペアCSVをEmbeddingでベクトル化しQdrantへ登録する実体関数。Embeddingプロバイダーは既定 `gemini`（gemini-embedding-001, 3072次元）。ポイントIDは内容ベースで決定的に生成され、再実行時もべき等。

```python
def register_to_qdrant(
    input_file: str,
    collection_name: str,
    recreate: bool = False,
    batch_size: int = 100,
    text_col: Optional[str] = None,
    domain: Optional[str] = None,
    max_docs: Optional[int] = None,
    provider: str = "gemini",
    normalize_filename: bool = True,
    create_ui_csv: bool = True,
    ui_output_dir: str = "qa_output",
    embed_workers: int = 2,
) -> bool
```


| 項目        | 内容                                                                                                                                |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **Input**   | `input_file: str`, `collection_name: str`, `provider: str = "gemini"`                                                               |
| **Process** | 1. CSV読み込み（question/answer列）<br>2. question+answer結合→Gemini Embeddingでベクトル化（`embed_workers` 並列）<br>3. コレクション作成/再作成<br>4. 決定的IDでバッチアップサート<br>5. UI用正規化CSV出力（`create_ui_csv`） |
| **Output**  | `bool`: 成功時True、失敗時False                                                                                                     |

---

## 5. 統合アプリ agent_rag.py

### 5.1 6画面構成

統合アプリは以下の6つの画面で構成されています。


| # | 画面名          | 機能             | 主な操作                          |
| - | --------------- | ---------------- | --------------------------------- |
| 1 | **説明**        | プロジェクト概要 | ドキュメント確認                  |
| 2 | **RAGデータDL** | データセット取得 | cc_news, livedoor等のダウンロード |
| 3 | **Q/A生成**     | Q/Aペア生成      | Claude生成、Celery並列処理        |
| 4 | **Qdrant登録**  | ベクトルDB登録   | CSV→Embedding（Gemini）→登録    |
| 5 | **Show-Qdrant** | コレクション表示 | データ確認、統計情報              |
| 6 | **Qdrant検索**  | 類似度検索       | 質問入力→検索→AI応答            |

### 5.2 画面フロー

```mermaid
flowchart LR
    S1["説明"] --> S2["RAGデータDL"] --> S3["Q/A生成"] --> S4["Qdrant登録"] --> S6["Qdrant検索"]
    S3 --> S5["Show-Qdrant データ確認"]
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class S1,S2,S3,S4,S5,S6 default
```

### 5.3 各画面の概要

#### 画面1: 説明（About）

プロジェクトの概要とドキュメントへのリンクを表示。

#### 画面2: RAGデータDL

Hugging Faceからデータセットをダウンロード・前処理。対応データセット: cc_news, livedoor, wikipedia_ja, fineweb_edu_ja 等。

#### 画面3: Q/A生成

チャンク済みCSV → ClaudeによるQ/Aペア生成（`SmartQAGenerator`）。同期処理 / Celery並列処理を選択可能。カバレージ分析オプション付き。

#### 画面4: Qdrant登録

CSVファイルからQdrantへベクトルデータを登録。Gemini Embedding生成（gemini-embedding-001, 3072次元）。

#### 画面5: Show-Qdrant

登録済みコレクションの確認・統計表示。

#### 画面6: Qdrant検索

質問を入力 → 類似Q/A検索 → AI応答生成。

**詳細な操作方法**: [doc/02_rag.md](doc/02_rag.md)

---

## 6. クイックスタート

### 6.1 前提条件

- Python 3.10以上
- Docker / Docker Compose（Qdrant + Redis）
- uv（パッケージ・実行管理）
- Anthropic API Key（LLM用: チャンク分割・Q/A生成）
- Google API Key（Gemini Embedding用）

### 6.2 インストール

```bash
# リポジトリのクローン
git clone <repository-url>
cd anthropic_grace_agent

# 依存パッケージのインストール（uv）
uv sync

# 環境変数の設定
cp .env.example .env
# .env に ANTHROPIC_API_KEY と GOOGLE_API_KEY/GEMINI_API_KEY を設定
```

### 6.3 サービス起動

```bash
# Qdrant + Redis の起動
docker-compose -f docker-compose/docker-compose.yml up -d

# Celeryワーカー起動（並列処理を使う場合）
./start_celery.sh restart -w 4 --flower

# 統合アプリの起動
uv run streamlit run agent_rag.py
```

### 6.4 CLIでの実行（3段階パイプライン）

```bash
# Step 1: チャンク分割（軽量用途は claude-haiku-4-5-20251001）
uv run python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_2per.csv \
  --output output_chunked \
  --model claude-haiku-4-5-20251001 \
  --workers 2

# Step 2+3: Q/A生成 + Qdrant登録（Embeddingは既定でGemini）
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_2per_chunks.csv \
  --collection cc_news_2per_anthropic \
  --model claude-sonnet-4-6 \
  --use-celery \
  --concurrency 4 \
  --recreate
```

> チャンク出力は入力ファイル名から **固定ファイル名**（`{入力ステム}_chunks.csv`）として生成される（例: `cc_news_2per.csv` → `cc_news_2per_chunks.csv`）。`save_chunks_as_csv()` はメタデータ付きCSVとシンプルCSVを同時出力する。

### 6.5 動作確認

ブラウザで http://localhost:8501 を開き、統合アプリが表示されることを確認。

**詳細な環境構築手順**: [doc/01_install.md](doc/01_install.md)

---

## 7. 環境構築詳細

### 7.1 Python環境

```bash
# Python 3.10以上が必要
python --version

# uv による環境構築（推奨）
uv sync
```

### 7.2 依存パッケージ

```bash
uv sync

# Celery関連（並列処理を使う場合）— pyproject.toml に含まれる
# celery[redis], kombu, flower
```

### 7.3 Docker（Qdrant + Redis）

```bash
# docker-compose.ymlの場所
docker-compose -f docker-compose/docker-compose.yml up -d

# 起動確認
curl http://localhost:6333/collections  # Qdrant
redis-cli ping                           # Redis
```

### 7.4 環境変数

`.env`ファイルを作成:

```env
# LLM用（必須）
ANTHROPIC_API_KEY=sk-ant-XXXXXXXXXXXXXXXXXXXXX

# Gemini Embedding用（必須）
GOOGLE_API_KEY=AIzaXXXXXXXXXXXXXXXXXXXXX
GEMINI_API_KEY=AIzaXXXXXXXXXXXXXXXXXXXXX

# インフラ
QDRANT_HOST=localhost
QDRANT_PORT=6333
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

**詳細な環境構築手順**: [doc/01_install.md](doc/01_install.md)

---

## 8. 設定・定数

### 8.1 ModelConfig（LLM）

LLMモデル設定（`config.py`）。料金・トークン制限を保持し、`supports_temperature()` / `get_model_limits()` / `get_model_pricing()` を提供する。本ドキュメントでは推奨LLMとして **Anthropic Claude** を採用する。

```python
class ModelConfig:
    DEFAULT_MODEL = "claude-sonnet-4-6"   # 推奨デフォルト（バランス型）
    # 軽量用途（チャンク分割等）には claude-haiku-4-5-20251001 を推奨

    @classmethod
    def supports_temperature(cls, model: str) -> bool: ...
    @classmethod
    def get_model_limits(cls, model: str) -> Dict[str, int]: ...
    @classmethod
    def get_model_pricing(cls, model: str) -> Dict[str, float]: ...
```


| キー                     | デフォルト値             | 説明                                      |
| ------------------------ | ------------------------ | ----------------------------------------- |
| `DEFAULT_MODEL`          | "claude-sonnet-4-6"      | 推奨デフォルトLLMモデル                   |
| `AVAILABLE_MODELS`       | （モデル一覧）           | 利用可能モデル一覧                        |

> 思考レベル（`DEFAULT_THINKING_LEVEL`）・`DEFAULT_TEMPERATURE` は `GeminiConfig` 側に定義される。

### 8.2 GeminiConfig（Embedding）

Gemini Embedding設定（`config.py`）。Embeddingは常にGemini固定。

```python
class GeminiConfig:
    EMBEDDING_MODEL = "gemini-embedding-001"
    EMBEDDING_DIMS = 3072   # MRL対応: 768/1536/3072（本システムは3072）
```

### 8.3 QdrantConfig

Qdrant接続設定。

```python
class QdrantConfig:
    HOST = "localhost"
    PORT = 6333
    URL = "http://localhost:6333"
    DEFAULT_VECTOR_SIZE = 3072            # gemini-embedding-001
    DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
```

### 8.4 CeleryConfig

Celery並列処理設定。


| キー                 | デフォルト値             | 説明                     |
| -------------------- | ------------------------ | ------------------------ |
| `BROKER_URL`         | redis://localhost:6379/0 | Redisブローカー          |
| `WORKER_CONCURRENCY` | 8                        | デフォルトワーカー並列数 |
| `TASK_TIME_LIMIT`    | 300                      | タスクタイムアウト（秒） |

### 8.5 チャンク処理の定数・プロンプト

`chunking/csv_text_to_chunks_text_csv.py` の主要定数:


| 定数                          | 値   | 用途                                                          |
| ----------------------------- | ---- | ------------------------------------------------------------- |
| `MAX_CHUNK_TOKENS`            | 512  | チャンク最大トークン数（Step3結合上限・最終強制分割上限）     |
| `EMBEDDING_INPUT_TOKEN_LIMIT` | 2048 | Embedding入力トークン上限の目安（MAX_CHUNK_TOKENS=512 はこの範囲内） |

3段階チャンク処理で使用するプロンプト（`chunking/prompts.py`）:


| プロンプト                    | 用途                                              |
| ----------------------------- | ------------------------------------------------- |
| `PARAGRAPH_SEPARATION_PROMPT` | Step1: 空行ベースの段落分割ルール                 |
| `SEMANTIC_CHUNKING_PROMPT`    | Step2: 意味のまとまり（トピック）ベースの再構成   |
| `CONTINUITY_CHECK_PROMPT`     | Step3: 隣接チャンクの文脈連続性判定（`is_connected` True/False） |

### 8.6 カバレージ分析の閾値（evaluation.py v3.0）

データセット別の決め打ち閾値を廃止し、統一デフォルト値を使用（`get_optimal_thresholds()`）。


| レベル     | 閾値 |
| ---------- | ---- |
| `strict`   | 0.8  |
| `standard` | 0.7  |
| `lenient`  | 0.6  |

---

## 9. 使用例

### 9.1 基本ワークフロー（CLI 3段階パイプライン）

```bash
# Step 1: チャンク分割
# uv run python -m chunking.csv_text_to_chunks_text_csv \
#   --input-file OUTPUT/wikipedia_ja_1per.csv \
#   --output output_chunked \
#   --model claude-haiku-4-5-20251001 \
#   --workers 8

# Step 2+3: Q/A生成 + Qdrant登録
# uv run python qa_qdrant/make_qa_register_qdrant.py \
#   --input-file output_chunked/wikipedia_ja_1per_chunks.csv \
#   --collection wikipedia_ja_1per_anthropic \
#   --model claude-sonnet-4-6 \
#   --use-celery \
#   --concurrency 8 \
#   --recreate
```

### 9.2 Pythonからの直接利用

```python
# 使用例: チャンク分割をPythonから実行
import asyncio
from chunking import chunks_all_async, load_text_from_csv

# CSVをテキストとして読み込み（必要なら全行結合）
text = load_text_from_csv("OUTPUT/cc_news_1per.csv", combine_rows=True)

# チャンク分割
chunks = asyncio.run(chunks_all_async(
    text=text,
    model="claude-sonnet-4-6",
    max_workers=8,
    block_size=1000,
    output_file="output_chunked/result.csv"
))
print(f"生成チャンク数: {len(chunks)}")
```

### 9.3 Q/A生成のみ / 登録のみ（個別CLI）

```bash
# Q/A生成のみ（qa_qdrant/make_qa.py → QAPipeline.run()）
uv run python qa_qdrant/make_qa.py \
  --input-file output_chunked/cc_news_2per_chunks.csv \
  --model claude-sonnet-4-6 \
  --use-celery \
  --concurrency 8 \
  --analyze-coverage

# 既存Q/AペアCSVをQdrant登録のみ（register_to_qdrant.py）
uv run python qa_qdrant/register_to_qdrant.py \
  --input-file qa_output/pipeline/qa_pairs.csv \
  --collection my_collection \
  --provider gemini \
  --recreate
```

### 9.4 データセット指定・テキストカラム指定

```bash
# 登録済みデータセット定義から実行（--dataset と --input-file は排他）
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --dataset wikipedia_ja \
  --collection wikipedia_ja_anthropic \
  --model claude-sonnet-4-6 \
  --use-celery \
  --concurrency 8 \
  --recreate

# テキストカラムを明示指定（既定は "text"）
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file OUTPUT/cc_news_5per.csv \
  --collection cc_news_5per \
  --text-column text \
  --provider gemini \
  --batch-size 100 \
  --recreate
```

> 主なCLIフラグ: `--input-file`/`--dataset`（排他）, `--text-column`(既定 text), `--model`, `--use-celery`, `-c/--concurrency`(既定 8), `--batch-chunks`(既定 3), `--collection`(必須), `--recreate`, `--batch-size`(既定 100), `--provider`(既定 gemini), `--output`, `--ui-output`。

---

## 10. 対応データセット


| データセット   | 言語   | 内容                             | ソース                                           |
| -------------- | ------ | -------------------------------- | ------------------------------------------------ |
| cc_news        | 英語   | ニュース記事                     | Hugging Face (cc_news)                           |
| livedoor       | 日本語 | ブログ記事（9カテゴリ、7,376件） | rondhuit.com                                     |
| wikipedia_ja   | 日本語 | Wikipedia記事                    | Hugging Face (wikimedia/wikipedia)               |
| japanese_text  | 日本語 | Webテキスト（CC100）             | Hugging Face (range3/cc100-ja)                   |
| fineweb_edu_ja | 日本語 | 教育的高品質Webテキスト          | Hugging Face (hotchpotch/fineweb-2-edu-japanese) |

---

## 11. ディレクトリ構造

```
anthropic_grace_agent/
├── agent_rag.py                      # 統合Streamlitアプリ（メインエントリ）
├── config.py                         # 全体設定管理
│
├── chunking/                         # ★ チャンク分割パッケージ
│   ├── __init__.py                   # パッケージエクスポート
│   ├── csv_text_to_chunks_text_csv.py  # ★ メイン: 3段階チャンク分割（LLMベース）
│   ├── async_api_client.py           # 非同期LLMクライアント（構造化出力）
│   ├── checkpoint_manager.py         # チェックポイント管理
│   ├── models.py                     # Pydanticモデル定義
│   ├── prompts.py                    # 3種のプロンプト定義
│   ├── regex_string.py               # テキスト分割ユーティリティ
│   └── utils.py                      # ユーティリティ関数
│
├── qa_generation/                    # ★ Q/A生成パッケージ（v3.0）
│   ├── pipeline.py                   # QAPipelineクラス（チャンク済みCSV専用）
│   ├── smart_qa_generator.py         # SmartQAGenerator（構造化出力1回）
│   ├── evaluation.py                 # カバレージ分析（統一閾値）
│   ├── semantic.py                   # SemanticCoverage
│   ├── data_io.py                    # データ入出力
│   └── models.py                     # Pydanticモデル
│
├── qa_qdrant/                        # ★ Q/A生成→Qdrant登録 統合CLI
│   ├── make_qa_register_qdrant.py    # ★ メイン: 統合パイプライン（Phase1+2）
│   ├── register_to_qdrant.py         # Qdrant登録ロジック（Embedding=Gemini固定）
│   └── make_qa.py                    # Q/A生成のみのCLI
│
├── services/                         # サービス層
│   └── qdrant_service.py             # Qdrant操作サービス
│
├── helper/                           # ヘルパー
│   ├── helper_embedding.py           # Embedding抽象化レイヤー
│   ├── helper_llm.py                 # LLMクライアント（プロバイダー自動判定）
│   └── helper_api.py                 # API共通処理
│
├── qdrant_client_wrapper.py          # Qdrantクライアントラッパー
├── celery_tasks.py                   # Celeryタスク定義
├── celery_config.py                  # Celery設定
│
├── ui/                               # UIコンポーネント
│   └── pages/                        # 各画面のページ
│
├── docs/                             # ドキュメント（チャンク/Q/A各モジュール詳細）
│
├── docker-compose/                   # Docker設定
│   └── docker-compose.yml
│
├── output_chunked/                   # チャンク分割出力（メタCSV + シンプルCSV）
├── qa_output/                        # 生成されたQ/Aデータ
├── OUTPUT/                           # 前処理済みデータ
├── logs/                             # ログ
│
├── pyproject.toml / uv.lock          # 依存管理（uv）
├── .env                              # 環境変数（gitignore）
├── start_celery.sh                   # Celeryワーカー起動スクリプト
└── CLAUDE.md                         # Claude Code用ガイド
```

> 各モジュールの詳細は `chunking/doc/` および `qa_generation/doc/`（最新版）も参照。

---

## 12. ドキュメント一覧

### 12.1 ドキュメント相関図

```mermaid
flowchart TB
    README["readme_rag.md プロジェクト概要"]

    README --> D1["readme_make_env.md 環境構築"]
    README --> D2["readme_usage_tools.md 操作手順"]
    README --> D3["chunking/doc + qa_generation/doc モジュール詳細"]
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class README,D1,D2,D3 default
```

### 12.2 ドキュメント概要


| ドキュメント                              | 主題                     | 対象読者       |
| ----------------------------------------- | ------------------------ | -------------- |
| [README.md](README.md)                    | プロジェクト全体・GRACE自律エージェント | 全員  |
| [readme_make_env.md](readme_make_env.md)  | Mac向け環境構築手順      | 導入者・開発者 |
| [readme_usage_tools.md](readme_usage_tools.md) | チャンク作成・Q/A生成・Qdrant登録の操作手順 | 利用者・開発者 |
| [readme_rag.md](readme_rag.md)            | RAGパイプライン設計・クラス・関数 IPO詳細 | 開発者 |
| [readme_react_reflection.md](readme_react_reflection.md) | ReAct+Reflectionエージェント | 開発者 |
| [readme_autonomous_agent.md](readme_autonomous_agent.md) | GRACEアーキテクチャ詳細 | 開発者 |

---

## 13. エクスポート

### chunking パッケージ

```python
__all__ = [
    # Models
    "SentenceUnit", "ParagraphUnit", "StructuralResult", "ContinuityResult",
    # Prompts
    "PARAGRAPH_SEPARATION_PROMPT", "SEMANTIC_CHUNKING_PROMPT", "CONTINUITY_CHECK_PROMPT",
    # API Client
    "AsyncAPIClient",
    # Checkpoint
    "CheckpointManager",
    # Main Processor
    "chunks_all_async", "load_text_from_csv",
    "save_chunks_as_csv", "save_chunks_as_text",
    # Utils
    "show_paragraphs", "setup_logging", "format_time", "format_size", "estimate_api_calls",
    "__version__",
]
```

### qdrant_client_wrapper.py

```python
__all__ = [
    # 定数・プロバイダー設定
    "QDRANT_CONFIG", "DEFAULT_EMBEDDING_MODEL", "DEFAULT_VECTOR_SIZE",
    "DEFAULT_EMBEDDING_PROVIDER", "PROVIDER_DEFAULTS",
    # クライアント・ヘルスチェック
    "QdrantHealthChecker", "QdrantDataFetcher", "create_qdrant_client", "get_qdrant_client",
    # コレクション管理
    "create_or_recreate_collection", "create_collection_for_provider",
    "get_collection_stats", "get_all_collections", "delete_all_collections",
    "get_provider_vector_size",
    # 埋め込み（抽象化版 + レガシー）
    "embed_texts_unified", "embed_query_unified", "embed_texts", "embed_query",
    "get_embedding_client", "get_cached_sparse_embedding_client",
    "embed_sparse_texts_unified", "embed_sparse_query_unified",
    # データ・ポイント操作
    "load_csv_for_qdrant", "build_inputs_for_embedding",
    "stable_point_id", "build_points", "upsert_points", "batched",
    # 検索
    "search_collection",
]
```

---

## 14. 変更履歴


| バージョン | 変更内容                                                                                                                                                                                                                      |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.0        | 初版作成（OpenAI GPT-4o / text-embedding-3-small ベース）                                                                                                                                                                     |
| 1.5        | Anthropic API対応、SemanticCoverageクラスによるチャンク分割                                                                                                                                                                      |
| 2.0        | フォーマット仕様書準拠で全面再構成。LLMベース3段階チャンク分割（csv_text_to_chunks_text_csv.py）導入。Gemini Embedding（gemini-embedding-001, 3072次元）に統一。make_qa_register_qdrant.py統合パイプライン追加。IPO詳細追加。 |
| 3.0        | 最新化（2026-06-12）。チャンキングをAnthropic（`AsyncAPIClient` の Tool Use 構造化出力・`ANTHROPIC_API_KEY`）へ統一、CLI/シグネチャを実装に追従（`documents`/`continuity_mode`/`max_chunk_tokens=512`、`load_documents_from_csv` による文書境界保証・`doc_id`・カバレッジ検証・manifest出力、`--timestamp`/`--max-chunk-tokens`/`--continuity-mode` 等）。3段階パイプライン（チャンキング/Q/A生成/Qdrant登録）として整理。`QAPipeline` v3.0（チャンク処理分離）・`SmartQAGenerator` v3.0（`analyze_and_generate()` 構造化出力1回）・`evaluation.py` v3.0（統一閾値）を反映。`run_registration()` は `register_to_qdrant` へ委譲（Embedding=Gemini固定）。存在しないファイル参照（setup.py / server.py / a-prefixed scripts）を削除。Mermaid黒背景スタイル準拠に修正。`GeminiConfig` を追記、uv 実行に統一。 |
| 3.1        | 最新化（2026-06-16）。技術スタック表記をAnthropic Claude（LLM）へ統一して再確認（LLM用途のGemini表記なし・既定 `claude-sonnet-4-6` / 軽量 `claude-haiku-4-5-20251001`・LLM設定クラス `ModelConfig`・LLM鍵 `ANTHROPIC_API_KEY`）。Embedding=Gemini（`gemini-embedding-001`, 3072次元, `GeminiConfig`, `GOOGLE_API_KEY`/`GEMINI_API_KEY`）は意図的に維持。全Mermaid図の黒背景・白文字スタイル準拠を再検証。 |
| 3.2        | 最新化（2026-06-17）。現行ソースへシグネチャ/CLI/既定値を追従。`chunks_all_async(text, model, max_workers, block_size, ...)` の実シグネチャに修正（存在しない `documents`/`continuity_mode`/`max_chunk_tokens` 引数・`load_documents_from_csv`/`_report_coverage`/`_write_manifest`/manifest出力・`--timestamp` の記述を削除）。`load_text_from_csv(..., combine_rows)`・出力CSV列（chunk_id/text/tokens/chunk_idx/dataset_type/type/sentence_count/source_file）・出力命名 `{ステム}_chunks.csv` を反映。`AsyncAPIClient` を `response_schema` 構造化出力（Tool Use/プロンプトキャッシュ記述を撤廃）として記述。`register_to_qdrant()` 実シグネチャ（`provider="gemini"`/`embed_workers` 等）・`run_registration(..., provider, ...)`・`make_qa_register_qdrant.py` のCLIフラグ（`--provider`/`--text-column`/`--batch-chunks` 等、`--combine-rows`/`--block-size` は非対応）を追加し、実在しない `combine_rows_to_chunks()` を削除。`QAPipeline.run()` から非対応の `use_smart_generation` を除去。`__init__` エクスポート（`save_chunks_as_text`・`load_text_from_csv`）と `qdrant_client_wrapper` の `__all__` を実体へ追従。`ModelConfig`/`GeminiConfig` のメソッド帰属を訂正（`supports_thinking_level` は `GeminiConfig`）。LLM=Anthropic Claude（`claude-sonnet-4-6`）・Embedding=Gemini（`gemini-embedding-001`, 3072次元）の方針は維持。 |

---

## 付録: 依存関係図

```mermaid
flowchart LR
    CHUNK["csv_text_to_chunks_text_csv.py"]
    MAKE_QA["make_qa_register_qdrant.py"]
    REG["register_to_qdrant.py"]

    subgraph ANTHROPIC["anthropic"]
        ANT_LLM["Anthropic Claude LLM生成（構造化出力）"]
    end

    subgraph GOOGLE["google-genai"]
        GENAI_EMB["Embedding API gemini-embedding-001"]
    end

    subgraph QDRANT_LIB["qdrant-client"]
        QC["QdrantClient"]
        QM["models.PointStruct"]
    end

    subgraph INTERNAL["内部モジュール"]
        ASYNC_CLI["chunking.async_api_client"]
        CHECKPOINT["chunking.checkpoint_manager"]
        MODELS["chunking.models"]
        PROMPTS["chunking.prompts"]
        PIPELINE["qa_generation.pipeline"]
        SMART_QA["qa_generation.smart_qa_generator"]
        QDRANT_SVC["services.qdrant_service"]
        QDRANT_WRAP["qdrant_client_wrapper"]
        HELPER_EMB["helper.helper_embedding"]
        HELPER_LLM["helper.helper_llm"]
        CONFIG["config"]
    end

    CHUNK --> ASYNC_CLI --> ANT_LLM
    CHUNK --> CHECKPOINT
    CHUNK --> MODELS
    CHUNK --> PROMPTS

    MAKE_QA --> PIPELINE
    MAKE_QA --> REG
    REG --> QDRANT_SVC
    REG --> QDRANT_WRAP

    PIPELINE --> SMART_QA --> HELPER_LLM --> ANT_LLM
    QDRANT_SVC --> GENAI_EMB
    QDRANT_SVC --> QC
    QDRANT_WRAP --> HELPER_EMB --> GENAI_EMB
    QDRANT_WRAP --> QC
    QDRANT_WRAP --> QM

    PIPELINE --> CONFIG
    QDRANT_WRAP --> CONFIG
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class CHUNK,MAKE_QA,REG,ANT_LLM,GENAI_EMB,QC,QM,ASYNC_CLI,CHECKPOINT,MODELS,PROMPTS,PIPELINE,SMART_QA,QDRANT_SVC,QDRANT_WRAP,HELPER_EMB,HELPER_LLM,CONFIG default
style ANTHROPIC fill:#1a1a1a,stroke:#fff,color:#fff
style GOOGLE fill:#1a1a1a,stroke:#fff,color:#fff
style QDRANT_LIB fill:#1a1a1a,stroke:#fff,color:#fff
style INTERNAL fill:#1a1a1a,stroke:#fff,color:#fff
```

---

## 技術スタック


| カテゴリ       | 技術                                               |
| -------------- | -------------------------------------------------- |
| **言語**       | Python 3.10+                                       |
| **LLM**        | Anthropic Claude（claude-sonnet-4-6 / チャンクは claude-haiku-4-5-20251001） |
| **Embedding**  | Gemini Embedding（gemini-embedding-001, 3072次元） |
| **ベクトルDB** | Qdrant（コサイン類似度、Hybrid Search対応）        |
| **並列処理**   | Celery + Redis / asyncio                           |
| **Web UI**     | Streamlit                                          |
| **パッケージ管理** | uv                                             |
| **コンテナ**   | Docker / Docker Compose                            |

---

## ライセンス

MIT License

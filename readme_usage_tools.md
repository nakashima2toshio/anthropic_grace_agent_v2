# Agent RAG (Anthropic) ツール使用ガイド

> バージョン: v1.2
> 最終更新: 2026-06-17

---

## 0. 環境の起動・設定

アプリケーションを使用する前に、以下のサービスを起動してください。
パッケージ管理は **uv** を使用します（`uv run python ...`）。

### 0.1 Docker コンテナの起動（Qdrant + Redis）

```bash
docker compose -f docker-compose/docker-compose.yml up -d
```

起動確認:

```bash
# Qdrant ヘルスチェック
curl http://localhost:6333/health

# Redis 接続確認
docker compose -f docker-compose/docker-compose.yml exec redis redis-cli ping
# → PONG が返れば OK
```

### 0.2 環境変数の確認

`.env` ファイルに API キーが設定されていることを確認:

```bash
# 必須（LLM: チャンク分割 / Q&A生成 / Agent応答）
ANTHROPIC_API_KEY=your_anthropic_api_key

# 必須（Embedding: Qdrant登録・検索）
GEMINI_API_KEY=your_gemini_api_key
GOOGLE_API_KEY=your_gemini_api_key

# オプション（Rerank 使用時）
COHERE_API_KEY=your_cohere_api_key
```

### 0.3 Celery ワーカーの起動

Q/A 生成ツールで Celery 並列処理を使う場合に必要です。
チャンク作成ツール（ツール1）は Celery を使用しません。

```bash
# 起動（推奨: concurrency=8 + Flower モニタリング）
./start_celery.sh restart -c 8 --flower

# 状態確認
./start_celery.sh status

# 停止
./start_celery.sh stop
```

Flower（タスクモニタリング UI）: http://localhost:5555

---

## 1. クイックスタート（簡易版コマンド集）

3 つのツールを順に実行することで、テキストデータ → チャンク → Q/A ペア → Qdrant 登録 → Agent 検索 という一連の RAG パイプラインが完成します。

### ツール 1: チャンク作成

チャンク用 LLM は軽量な `claude-haiku-4-5-20251001` で十分です。
チャンク結果（`*_chunks.csv`）は後続ステージ・他プロジェクトの共通入力になります。

```bash
uv run python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_1per.csv \
  --output output_chunked \
  --model claude-haiku-4-5-20251001 \
  --workers 2
```

### ツール 2: Q/A ペア作成 + Qdrant 登録

```bash
# Celery 起動後に実行
./start_celery.sh restart -c 8 --flower

uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --collection cc_news_1per \
  --model claude-sonnet-4-6 \
  --concurrency 8 \
  --use-celery \
  --recreate
```

### ツール 3: Agent 検索（Web UI）

```bash
streamlit run agent_rag.py --server.port 8501
```

ブラウザで http://localhost:8501 にアクセス。

---

## 2. ツール詳細: チャンク作成

**スクリプト:** `chunking/csv_text_to_chunks_text_csv.py`
**詳細ドキュメント:** [`chunking/doc/csv_text_to_chunks_text_csv.md`](chunking/doc/csv_text_to_chunks_text_csv.md)

LLM ベースのセマンティックチャンキングツールです。テキストを意味的なまとまりに 3 段階で分割します。Celery は使用しません（asyncio による並列処理）。

### 2.1 処理フロー

```
入力テキスト/CSV（CSV は 1 行 = 1 文書として文書境界を保持）
  ↓ Step 1: 階層構造化（文境界でブロック分割 → 段落分割）
  ↓ Step 2: 意味的チャンキング
  ↓ Step 3: 文脈連続性チェック（同一文書内のみ・結合/分離判定）
  ↓ 上限強制分割（MAX_CHUNK_TOKENS=512 超過は文境界で分割）
チャンク CSV（2 ファイル: メタデータ付き + シンプル版）
```

### 2.2 実行コマンド

CSV ファイルからチャンク作成:

```bash
uv run python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_1per.csv \
  --output output_chunked \
  --model claude-haiku-4-5-20251001 \
  --workers 2 \
  --block-size 1000
```

テキストファイルからチャンク作成:

```bash
uv run python -m chunking.csv_text_to_chunks_text_csv \
  --input-file ./data/document.txt \
  --output output_chunked \
  --model claude-haiku-4-5-20251001 \
  --workers 2
```

### 2.3 オプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--input-file` | （必須） | 入力ファイル（.txt / .csv） |
| `--output` | `chunks_output` | 出力ディレクトリ（運用上は `output_chunked` を使用） |
| `--model` | `gemini-2.5-flash` | 使用する LLM モデル。本プロジェクト推奨は `claude-sonnet-4-6`（軽量用途は `claude-haiku-4-5-20251001`）を `--model` で明示指定 |
| `--workers` | `8` | 並列ワーカー数（asyncio） |
| `--block-size` | `1000` | ブロックサイズ（文字数）。大きすぎると MAX_TOKENS エラー |
| `--text-column` | 自動検出 | CSV のテキストカラム名 |
| `--max-rows` | 全行（None） | 最大処理行数（CSV 用） |
| `--combine-rows` | `false` | CSV の全行を 1 つのテキストに結合してから分割 |
| `--resume` | なし（None） | チェックポイントから再開するジョブ ID |
| `--verbose` | `false` | 詳細ログ出力 |

> 出力チャンクの最大トークン数はソース内の定数 `MAX_CHUNK_TOKENS = 512`（CLI フラグではない）で制御され、超過チャンクは文境界で強制分割されます。Step3（文脈連続性チェック）はルールベース判定で常時実行され、モード切替の CLI フラグはありません。

### 2.4 出力ファイル

固定ファイル名（入力ファイル名のステムから `{入力名}_chunks.csv` を生成）で次の 2 ファイルが自動生成されます:

| ファイル | 内容 |
|---------|------|
| `{入力名}_chunks.csv` | メタデータ付き（chunk_id, text, tokens, sentence_count 等） |
| `{入力名}_chunks_simple.csv` | シンプル版（Text カラムのみ） |

> ツール 2 の `--input-file` には、メタデータ付きの `{入力名}_chunks.csv`（`text` カラムあり）を指定します。

### 2.5 CSV テキストカラムの自動検出

`--text-column` を省略した場合、以下の順序でカラムを自動検出します: `text`, `Text`, `TEXT`, `content`, `Content`, `CONTENT`, `Combined_Text`, `combined_text`, `body`, `Body`, `BODY`, `document`, `Document`, `answer`, `Answer`。いずれもない場合は最初のカラムを使用します。

### 2.6 注意事項

Anthropic API のレート制限に引っかかる場合は、`--block-size` を小さく（例: 500）、`--workers` を減らして（例: 2）調整してください。

---

## 3. ツール詳細: Q/A ペア作成 + Qdrant 登録

**スクリプト:** `qa_qdrant/make_qa_register_qdrant.py`
**詳細ドキュメント:** [`qa_qdrant/doc/make_qa_register_qdrant.md`](qa_qdrant/doc/make_qa_register_qdrant.md)

チャンク CSV から Q/A ペアを LLM で自動生成し、Qdrant に登録する統合ツールです。
チャンキングは専用ツール（ツール 1）に一本化されており、本ツールはチャンク済み CSV（または `question`/`answer` 付き CSV）を入力とします。テキスト（.txt）は直接処理できません。

### 3.1 処理フロー

```
入力（チャンク済み CSV / question・answer 付き CSV）
  ↓ Phase 1: Q/A ペア生成（SmartQAGenerator + LLM、Celery 並列）
  ↓   ・LLM がチャンクごとに最適な Q/A 数を決定（0〜5 個・構造化出力 1 回/チャンク）
  ↓   ・question/answer が既にある CSV は生成をスキップ
  ↓ Phase 2: Qdrant 登録（register_to_qdrant へ委譲）
  ↓   ・Embedding 生成（gemini-embedding-001, 3072 次元）
  ↓   ・コレクション作成 + バッチアップサート + 件数突合検証
Q/A ペア CSV + Qdrant 登録完了
```

### 3.2 実行コマンド

基本（Celery 使用 + コレクション再作成）:

```bash
./start_celery.sh restart -c 8 --flower

uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --collection cc_news_1per \
  --use-celery \
  --concurrency 8 \
  --recreate
```

Celery を使わない同期処理:

```bash
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --collection cc_news_1per \
  --recreate
```

事前定義データセットからの登録:

```bash
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --dataset wikipedia_ja \
  --collection wikipedia_ja \
  --use-celery \
  --concurrency 8 \
  --recreate
```

### 3.3 オプション一覧

**入力ソース（いずれか 1 つ必須）:**

| オプション | 説明 |
|-----------|------|
| `--input-file` | チャンク済み CSV または `question`/`answer` 付き CSV（.csv のみ） |
| `--dataset` | 事前定義データセット名（`config.py` の `DATASET_CONFIGS`） |

**CSV 処理（`--input-file` が CSV の場合）:**

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--text-column` | `text` | テキストカラム名（`Combined_Text` も自動検出） |

**Q/A 生成（SmartQAGenerator に一本化）:**

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--model` | `gemini-2.5-flash` | LLM モデル。本プロジェクト推奨は `--model claude-sonnet-4-6`（`ANTHROPIC_API_KEY` 必須） |
| `--use-celery` | `false` | Celery 並列処理を使用 |
| `-c`, `--concurrency` | `8` | 並列タスク数 |
| `--max-docs` | 全件（None） | 処理する最大文書数 |
| `--batch-chunks` | `3` | 1 回の LLM 呼び出しで処理するチャンク数 |
| `--celery-workers` | `1` | （非推奨）ワーカープロセス数チェック用。`--concurrency` を使用 |

**Qdrant 登録:**

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--collection` | （必須） | Qdrant コレクション名 |
| `--recreate` | `false` | コレクションを再作成（既存データ削除） |
| `--batch-size` | `100` | Embedding バッチサイズ |
| `--provider` | `gemini` | Embedding プロバイダー |

> Embedding は既定で Gemini `gemini-embedding-001`（3072 次元）を使用します（`--provider gemini`）。

**出力:**

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--output` | `qa_output/pipeline` | Q/A ペア CSV 出力ディレクトリ |
| `--ui-output` | `qa_output` | UI 用正規化 CSV 出力ディレクトリ |

### 3.4 入力 CSV の自動判定

入力 CSV のカラム構成に応じて処理が自動切替されます:

| CSV のカラム | 動作 |
|------------|------|
| `question` + `answer` あり | Q/A 生成をスキップ → 直接 Qdrant 登録 |
| `text`（または `Combined_Text`）あり | Q/A 生成 → Qdrant 登録 |
| 上記いずれもなし | エラー終了 |

### 3.5 出力ファイル

| 出力先 | 内容 |
|-------|------|
| `qa_output/pipeline/` | Q/A ペア CSV（question, answer カラム） |
| `qa_output/` | UI 用正規化 CSV（日時サフィックス除去済み） |

### 3.6 Celery 並列設定の推奨値

| マシン | `--concurrency` | `start_celery.sh -c` |
|-------|-----------------|----------------------|
| M2 MacBook Air (8 vCPU) | `8` | `8` |
| 軽量モード | `4` | `4` |

`--concurrency` と `start_celery.sh -c` は同じ値に揃えてください。

---

## 4. 補助ツール: Qdrant 登録のみ

**スクリプト:** `qa_qdrant/register_to_qdrant.py`

既に Q/A ペア CSV（`question`/`answer`）または汎用 CSV がある場合、Q/A 生成をスキップして Qdrant 登録だけを実行します。
ベクトル化対象カラムは自動検出（`question`+`answer` → `Combined_Text` → `text`）され、`--text-col` で明示指定もできます。

```bash
uv run python qa_qdrant/register_to_qdrant.py \
  --input-file qa_output/pipeline/qa_pairs_cc_news_1per.csv \
  --collection cc_news_1per \
  --recreate \
  --batch-size 100
```

### 4.1 主なオプション

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--input-file` | （必須） | 登録する CSV ファイルパス |
| `--collection` | （必須） | 登録先 Qdrant コレクション名 |
| `--recreate` | `false` | 既存コレクションを削除して作り直す |
| `--batch-size` | `100` | Embedding/登録のバッチサイズ |
| `--embed-workers` | `2` | Embedding 先読みの並列スレッド数（パイプライン化） |
| `--text-col` | 自動検出 | ベクトル化対象カラム名 |
| `--domain` | コレクション名 | payload の `domain` 値 |
| `--max-docs` | 全件 | 登録する最大件数（テスト用） |
| `--normalize-filename` / `--no-normalize-filename` | 有効 | ファイル名の日時サフィックス除去 |
| `--create-ui-csv` / `--no-create-ui-csv` | 有効 | UI 用正規化 CSV を生成 |
| `--ui-output-dir` | `qa_output` | UI 用 CSV の出力ディレクトリ |

> Embedding は Gemini `gemini-embedding-001`（3072 次元）に固定です。

---

## 5. ツール詳細: Agent 検索（Web UI）

**スクリプト:** `agent_rag.py`

Streamlit ベースの Web UI アプリケーションです。Qdrant に登録済みの Q/A データに対して、ReAct + Reflection パターンの自律型 Agent 検索を実行できます。

### 5.1 起動コマンド

```bash
streamlit run agent_rag.py --server.port 8501
```

ブラウザで http://localhost:8501 にアクセスします。

### 5.2 メニュー構成

| メニュー | 機能 |
|---------|------|
| 📖 説明 | システム全体の説明ページ |
| 🔎 Qdrant 検索 | Qdrant に直接クエリを実行してベクトル検索 |
| 🤖 Agent（ReAct+Reflection） | ReAct + Reflection パターンのエージェント対話 |
| 🧠 Agent（Plan+Executor） | Plan+Executor パターンの自律型エージェント |
| 📊 未回答ログ | Agent が回答できなかった質問のログ閲覧 |
| 📄 RAG データ作成 | RAG データ作成（実装予定） |
| 🗄️ Qdrant の CRUD | Qdrant のデータ管理（実装予定） |

### 5.3 Agent（ReAct+Reflection）の動作

エージェントは以下の 2 フェーズで質問に回答します:

**Phase 1 — ReAct ループ:**
ユーザーの質問に対して Thought → Action（ツール呼び出し） → Observation のサイクルを繰り返し、回答案を作成します。エージェントは全 Qdrant コレクションを並列検索し、最適な結果を選択します。

**Phase 2 — Reflection:**
回答案を正確性・適切性・スタイルの観点で自己評価し、必要に応じて修正した最終回答を出力します。

### 5.4 検索の仕組み

エージェントは以下のツールを内部的に使用します:

| ツール | 用途 |
|-------|------|
| `search_rag_knowledge_base` | 全コレクション並列検索 + コサイン類似度フィルタ |
| `list_rag_collections` | 利用可能なコレクション一覧取得 |

検索時には Hybrid Search（Dense + Sparse ベクトル）を使用し、コサイン類似度 ≥ 0.7 の結果のみを採用します。

### 5.5 前提条件

Agent 検索を利用するには、以下が必要です:

- Docker コンテナ（Qdrant + Redis）が起動していること
- `.env` に `GEMINI_API_KEY` / `GOOGLE_API_KEY` が設定されていること
- Qdrant に 1 つ以上のコレクションが登録されていること（ツール 2 で登録）

---

## 6. パイプライン全体の実行例

Wikipedia 日本語データを例にした、データ準備から検索までの一連の流れです。

```bash
# === Step 0: 環境起動 ===
docker compose -f docker-compose/docker-compose.yml up -d
./start_celery.sh restart -c 8 --flower

# === Step 1: チャンク作成 ===
uv run python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/wikipedia_ja_1per.csv \
  --output output_chunked \
  --model claude-haiku-4-5-20251001 \
  --workers 2

# === Step 2: Q/A 生成 + Qdrant 登録 ===
# ※ 固定ファイル名 {入力名}_chunks.csv を指定
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/wikipedia_ja_1per_chunks.csv \
  --collection wikipedia_ja_1per \
  --use-celery \
  --concurrency 8 \
  --recreate

# === Step 3: Agent 検索 ===
streamlit run agent_rag.py --server.port 8501

# === 終了時 ===
# Ctrl+C で Streamlit 停止
./start_celery.sh stop
docker compose -f docker-compose/docker-compose.yml down
```

---

## 7. ポート一覧

| サービス | ポート | 用途 |
|---------|-------|------|
| Streamlit | 8501 | Agent RAG Web UI |
| Qdrant | 6333 | ベクトル DB REST API |
| Redis | 6379 | Celery ブローカー / 結果保存 |
| Flower | 5555 | Celery タスクモニタリング |

---

## 8. 変更履歴

| バージョン | 日付 | 内容 |
|-----------|------|------|
| v1.2 | 2026-06-17 | 現行コードに合わせて CLI フラグを刷新。チャンクツールの非実在フラグ（`--timestamp` / `--max-chunk-tokens` / `--continuity-mode`）を削除し、実在フラグ `--combine-rows` を追加。出力を 2 ファイル（manifest.json は生成されない）に訂正。Q/A 統合ツールから非実在の `--analyze-coverage` を削除し、`--batch-chunks` / `--provider` を追記。各ツールの argparse 既定モデルが `gemini-2.5-flash` であることを明記（本プロジェクト推奨は `--model claude-sonnet-4-6`）。 |
| v1.1 | 2026-06-16 | 技術スタック表記を Anthropic Claude に統一（LLM: `claude-sonnet-4-6` / 軽量: `claude-haiku-4-5-20251001`、LLM 用 API キーは `ANTHROPIC_API_KEY`）。Embedding は Gemini `gemini-embedding-001`（3072次元）を維持。 |
| v1.0 | 2026-06-12 | 初版。 |

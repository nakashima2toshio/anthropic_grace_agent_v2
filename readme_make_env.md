# Agent RAG (Anthropic) 環境構築手順書

**開発マシン:** MacBook Air M2 / 24GB メモリ / macOS

**Version 1.2** | **最終更新:** 2026-06-17

---

## 1. 前提ソフトウェアのインストール

システム構成図

```mermaid
graph TD
    User(("ユーザー<br>ブラウザ")) -->|"http://localhost:8501"| Streamlit["Streamlit アプリケーション<br>agent_rag.py<br>Port: 8501"]

    Streamlit -->|"Q&A生成 / AI応答"| Anthropic["Anthropic API<br>Claude Sonnet<br>クラウド"]
    Streamlit -->|"Embedding生成"| Gemini["Gemini API<br>gemini-embedding-001<br>クラウド"]
    Streamlit -->|"ベクトル検索"| Qdrant[("Qdrant<br>Port: 6333<br>Docker")]
    Streamlit -.->|"タスク登録"| Redis[("Redis<br>Port: 6379<br>Docker")]

    subgraph BG["Background Jobs"]
        Celery["Celery Workers<br>並列処理"]
        Celery -->|"タスク取得/結果保存"| Redis
        Celery -->|"Q&A生成"| Anthropic
        Celery -->|"Embedding生成"| Gemini
    end
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class User,Streamlit,Anthropic,Gemini,Qdrant,Redis,Celery default
style BG fill:#1a1a1a,stroke:#fff,color:#fff
```

### 1.1 Homebrew（未インストールの場合）

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 1.2 Python 3.11 以上

本プロジェクトは `pyproject.toml` で `requires-python = ">=3.11"` を指定しています。
Python 3.11 以上（動作確認・推奨は 3.13 系）を用意してください（パッケージ管理は後述の uv が自動で解決します）。

```bash
brew install python@3.13
```

または pyenv を利用:

```bash
brew install pyenv
pyenv install 3.13.5
pyenv local 3.13.5
```

### 1.3 uv（Python パッケージマネージャ）

本プロジェクトは **uv**（`pyproject.toml` + `uv.lock`）で依存関係を管理します。

```bash
# 公式インストーラ
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # または source ~/.zshrc

# Homebrew でも可
brew install uv
```

### 1.4 Docker Desktop for Mac

[Docker Desktop](https://www.docker.com/products/docker-desktop/) をインストール。
Apple Silicon (M2) 版を選択すること。

インストール後、Docker Desktop を起動し、Settings → Resources で以下を推奨:


| リソース | 推奨値 |
| -------- | ------ |
| CPUs     | 4      |
| Memory   | 8 GB   |
| Swap     | 1 GB   |

### 1.5 Redis（Celery ブローカー用）

Docker 経由で起動するため個別インストールは不要。
ローカルで直接使いたい場合:

```bash
brew install redis
brew services start redis
```

### 1.6 MeCab（オプション: キーワード抽出用）

```bash
brew install mecab mecab-ipadic
```

`mecab-python3` は `pyproject.toml` の依存に含まれており、`uv sync` で自動インストールされます。

> MeCab 本体がなくてもアプリは動作します（キーワード抽出機能が無効になるのみ）。

---

## 2. プロジェクトのセットアップ

### 2.1 リポジトリのクローン

```bash
git clone https://github.com/nakashima2toshio/anthropic_grace_agent.git
cd anthropic_grace_agent
```

### 2.2 依存関係のインストール（uv）

uv は仮想環境の作成と依存解決をまとめて行います。`uv.lock` に固定された
バージョンで再現性のある環境を構築します。

```bash
# .venv を自動作成し、uv.lock どおりに依存をインストール
uv sync

# 仮想環境を有効化したい場合（任意。uv run を使えば不要）
source .venv/bin/activate
```

> `requirements.txt` も同梱されています。uv を使わない場合は
> `uv pip install -r requirements.txt` または通常の `pip install -r requirements.txt`
> でも構築できますが、バージョン固定の観点から **uv sync を推奨** します。

---

## 3. 依存パッケージ（主要）

依存は `pyproject.toml` に定義され、`uv.lock` でバージョン固定されています。
主要パッケージは以下のとおりです。

```txt
# === Web UI ===
streamlit==1.52.1
fastapi>=0.116.0
gradio==5.44.1

# === Anthropic API (LLM: チャンク分割 / Q&A生成 / Agent応答) ===
anthropic>=0.40.0

# === Gemini API (Embedding: Qdrant登録・検索用。from google import genai) ===
google-genai==1.52.0

# === ベクトルDB (Qdrant) ===
qdrant-client==1.16.1

# === 非同期タスク (Celery + Redis) ===
celery==5.5.3
redis==7.1.0
flower==2.0.1

# === データセット ===
datasets>=4.1.1

# === ユーティリティ ===
python-dotenv==1.2.1
pandas==2.3.3
numpy==2.3.5
requests==2.32.5
tqdm==4.67.1
tiktoken==0.12.0
pydantic==2.12.5

# === MeCab（オプション: キーワード抽出） ===
mecab-python3>=1.0.12
```

> **注意:** Embedding は Gemini API（クラウド）経由で生成するため、ローカル GPU は不要です。
> `gemini-embedding-001`（3072次元）を使用します。

---

## 4. Docker Compose（Qdrant + Redis）

### 4.1 docker-compose.yml

Compose ファイルは **`docker-compose/docker-compose.yml`** に配置済みです:

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  qdrant_data:
  redis_data:

networks:
  default:
    name: qdrant-network
```

### 4.2 起動・停止

```bash
# 起動（バックグラウンド）
docker compose -f docker-compose/docker-compose.yml up -d

# 状態確認
docker compose -f docker-compose/docker-compose.yml ps

# ログ確認
docker compose -f docker-compose/docker-compose.yml logs -f qdrant
docker compose -f docker-compose/docker-compose.yml logs -f redis

# 停止
docker compose -f docker-compose/docker-compose.yml down

# 停止 + データ削除
docker compose -f docker-compose/docker-compose.yml down -v
```

### 4.3 動作確認

```bash
# Qdrant ヘルスチェック
curl http://localhost:6333/health

# Redis 接続確認
docker compose -f docker-compose/docker-compose.yml exec redis redis-cli ping
# → PONG が返れば OK
```

---

## 5. Celery ワーカーの起動

### 5.1 起動スクリプト

```bash
# 実行権限付与（初回のみ）
chmod +x start_celery.sh

# 起動（推奨設定: concurrency=8 + Flower モニタリング）
./start_celery.sh start -c 8 --flower

# 再起動
./start_celery.sh restart -c 8 --flower

# 停止
./start_celery.sh stop

# 状態確認
./start_celery.sh status
```

### 5.2 Flower（タスクモニタリング）

Flower を起動した場合、ブラウザで確認可能:

```
http://localhost:5555
```

### 5.3 M2 MacBook Air 推奨設定


| パラメータ  | 推奨値 | 説明                                |
| ----------- | ------ | ----------------------------------- |
| concurrency | 8      | 8 vCPU に対応、API レート制限も考慮 |
| Flower      | 有効   | タスク状況のリアルタイム監視        |

---

## 6. 環境変数の設定

### 6.1 `.env` ファイルの作成

プロジェクトルートに `.env` を作成:

```bash
# === Anthropic API (LLM: チャンク分割 / Q&A生成 / Agent応答) ===
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# === Gemini API (Embedding: Qdrant登録・検索用) ===
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_API_KEY=your_gemini_api_key_here

# === Cohere API（オプション: Rerank 用） ===
COHERE_API_KEY=your_cohere_api_key_here

# === Web 検索（オプション: grace/tools.py の backend に応じて設定） ===
# SERPAPI_KEY=your_serpapi_key_here            # backend=serpapi
# GOOGLE_CSE_API_KEY=your_cse_api_key_here     # backend=google_cse
# GOOGLE_CSE_ENGINE_ID=your_cse_engine_id

# === Qdrant ===
QDRANT_HOST=localhost
QDRANT_PORT=6333

# === Redis / Celery ===
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

> LLM は `ANTHROPIC_API_KEY`、Embedding は `GEMINI_API_KEY` / `GOOGLE_API_KEY`（同じ Gemini キーを両方に設定）を使用します。

### 6.2 API キーの取得先

| API | 取得先 | 用途 |
|---|---|---|
| Anthropic API Key | https://console.anthropic.com/settings/keys | LLM（Q&A生成・Agent応答） |
| Gemini API Key | https://aistudio.google.com/apikey | Embedding（Qdrant登録・検索） |
| Cohere API Key | https://dashboard.cohere.com/api-keys | Rerank（オプション） |
| SerpAPI Key | https://serpapi.com/ | Web 検索（オプション・backend=serpapi） |
| Google CSE Key / Engine ID | https://programmablesearchengine.google.com/ | Web 検索（オプション・backend=google_cse） |

---

## 7. アプリケーションの起動

### 7.1 起動手順（まとめ）

```bash
# 1. Docker コンテナ起動
docker compose -f docker-compose/docker-compose.yml up -d

# 2. Celery ワーカー起動
./start_celery.sh start -c 8 --flower

# 3. Streamlit アプリ起動（uv 経由）
uv run streamlit run agent_rag.py --server.port 8501
```

ブラウザで以下にアクセス:

```
http://localhost:8501
```

> `.venv` を有効化済みの場合は `streamlit run agent_rag.py --server.port 8501` でも起動できます。

### 7.2 全サービスの停止

```bash
# Streamlit: Ctrl+C で停止

# Celery 停止
./start_celery.sh stop

# Docker 停止
docker compose -f docker-compose/docker-compose.yml down
```

---

## 8. 動作確認チェックリスト

```
[ ] Python 3.11 以上（推奨 3.13 系）がインストールされている
[ ] uv がインストールされている
[ ] uv sync が正常完了（.venv 作成 + 依存インストール）
[ ] Docker Desktop が起動している
[ ] docker compose -f docker-compose/docker-compose.yml up -d で Qdrant / Redis が起動
[ ] curl http://localhost:6333/health が正常応答
[ ] .env に ANTHROPIC_API_KEY が設定されている（LLM用）
[ ] .env に GOOGLE_API_KEY / GEMINI_API_KEY が設定されている（Gemini Embedding用）
[ ] ./start_celery.sh status でワーカーが起動中
[ ] uv run streamlit run agent_rag.py が正常起動
[ ] ブラウザで http://localhost:8501 にアクセス可能
```

---

## 9. トラブルシューティング

### Qdrant に接続できない

```bash
# コンテナの状態確認
docker compose -f docker-compose/docker-compose.yml ps
# qdrant コンテナが unhealthy の場合、再起動
docker compose -f docker-compose/docker-compose.yml restart qdrant
```

### Celery ワーカーが起動しない

```bash
# Redis が起動しているか確認
docker compose -f docker-compose/docker-compose.yml exec redis redis-cli ping

# ログ確認
tail -50 logs/celery_qa_worker.log
```

### Planner/Executor 初期化エラー

`ANTHROPIC_API_KEY`（LLM用）または `GOOGLE_API_KEY` / `GEMINI_API_KEY`（Gemini Embedding用）が `.env` に設定されているか確認してください。

```bash
# PYTHONPATH にプロジェクトルートを追加
export PYTHONPATH="$(pwd):$(pwd)/helper"
```

### uv sync が失敗する

```bash
# uv 自体を最新化
uv self update

# キャッシュをクリアして再試行
uv cache clean
uv sync
```

---

## 10. ポート一覧


| サービス  | ポート | 用途                         |
| --------- | ------ | ---------------------------- |
| Streamlit | 8501   | Web UI                       |
| Qdrant    | 6333   | ベクトルDB REST API          |
| Redis     | 6379   | Celery ブローカー / 結果保存 |
| Flower    | 5555   | Celery タスクモニタリング    |

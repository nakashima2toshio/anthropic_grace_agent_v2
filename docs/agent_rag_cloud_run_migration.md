# Gemini Agent RAG → Cloud Run 移行戦略

5 フェーズ · 17 タスク · Streamlit + Qdrant Cloud + Redis + Celery + Gemini API

---

## 1. プロジェクト概要 & 移行の目的

現在の **VM (Compute Engine) + Docker Compose** 構成から、**Google Cloud Run (Serverless)** への移行を行う。
これにより、サーバー管理コストの削減、オートスケール、およびHTTPS化の自動対応を実現する。

---

## 2. アーキテクチャ比較

### 現在の構成（ローカル / GCP VM）

| コンポーネント | 説明 |
|:---|:---|
| 💻 MacBook Air M2 | 開発環境 |
| 🖥️ Streamlit | port 8501 |
| 🔍 Qdrant | Docker / port 6333 |
| 📦 Redis | Docker / port 6379 |
| ⚙️ Celery Worker | ローカルプロセス |
| 🤖 Gemini API | 外部API |

### Cloud Run 移行後の構成

| コンポーネント | 移行後のサービス | 選定理由 |
|:---|:---|:---|
| **Application** | **Google Cloud Run** | コンテナベースのサーバーレス。Streamlit + Celery を `entrypoint.sh` で同時起動。スケーラビリティと管理の容易さ。 |
| **Vector DB** | **Qdrant Cloud** | Qdrant社公式マネージドサービス。1GBまでの無料枠あり。管理運用コストがゼロ。 |
| **Redis** | **Cloud Memorystore** | GCP純正のフルマネージドRedis。VPCコネクタ経由で高速・安全に接続可能。※コスト重視の場合は Redis Cloud の Free Tier も検討。 |

---

## 3. 重要な設計判断

### Celery の扱い

Cloud Run はステートレス環境だが、`entrypoint.sh` により **Celery Worker と Streamlit を同一コンテナ内で同時起動** する方式を採用する。

- Celery Worker をバックグラウンドで起動
- Streamlit をフォアグラウンドで起動（Cloud Run のヘルスチェック対象）

### Redis の選択

| 選択肢 | 月額コスト | メリット | デメリット |
|:---|:---|:---|:---|
| Cloud Memorystore（BASIC 1GB） | ~$35 | GCP純正、VPC内高速接続、SLA保証 | コスト高め |
| Redis Cloud Free Tier | $0 | 無料、セットアップ簡単 | 30MB制限、SLAなし、外部通信 |

開発・検証段階では Redis Cloud Free Tier、本番運用では Memorystore を推奨。

---

## Phase 1: 準備・設計フェーズ（1〜2日）

GCPリソース準備

### 1-1. GCPプロジェクト・API有効化 【必須】

GCPコンソールで以下のAPIを有効化：

- Cloud Run API
- Cloud Build API
- Memorystore for Redis API（Celery使用時）
- VPC Access Connector API（内部通信用）

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  redis.googleapis.com \
  vpcaccess.googleapis.com
```

### 1-2. VPCネットワーク・サーバーレスVPCコネクタ作成 【必須】

Cloud Run → Redis（Memorystore）間の内部通信にVPCコネクタが必要。Memorystore はVPC内でしかアクセスできない。

```bash
gcloud compute networks vpc-access connectors create rag-connector \
  --region=asia-northeast1 \
  --range=10.8.0.0/28
```

---

## Phase 2: データストアの準備・外部化（1〜2日）

Qdrant Cloud・Redis のセットアップ

### 2-1. Qdrant Cloud のセットアップ 【必須】

Qdrant社公式マネージドサービスを利用。運用負荷ゼロ、自動バックアップ、スケーリング対応。

**手順：**

1. [Qdrant Cloud](https://cloud.qdrant.io/) でアカウントを作成
2. Free Tier クラスタを作成（1GBストレージ、1ノード）
3. **Cluster URL** と **API Key** を取得し、メモする
4. データ移行：RAGデータ作成機能を使い再登録、またはスナップショット経由で移行

```python
# 接続確認テスト
from qdrant_client import QdrantClient

client = QdrantClient(
    url="https://your-cluster.cloud.qdrant.io:6333",
    api_key="your_qdrant_api_key"
)
print(client.get_collections())
```

### 2-2. Redis の準備 【必須（Celery使用時）】

#### 選択A: Cloud Memorystore（本番推奨）

```bash
gcloud redis instances create rag-redis \
  --size=1 \
  --region=asia-northeast1 \
  --redis-version=redis_7_0 \
  --tier=basic

# 接続情報取得
gcloud redis instances describe rag-redis \
  --region=asia-northeast1 \
  --format="value(host,port)"
```

VPCコネクタ（Phase 1-2 で作成済み）経由で Cloud Run から接続する。

#### 選択B: Redis Cloud Free Tier（開発・検証向け）

1. [Redis Cloud](https://redis.com/try-free/) でアカウント作成
2. Free Tier インスタンスを作成（30MB、東京リージョン選択可）
3. 接続用 **Endpoint** と **Password** を取得

※ VPCコネクタ不要（パブリックエンドポイント経由で接続）

---

## Phase 3: アプリケーション改修フェーズ（2〜3日）

コンテナ化 & 環境変数の外部化

### 3-1. config.py を環境変数ベースに改修 【必須】

`docker-compose.yml` で定義されていたネットワーク内通信（`localhost:6333` 等）を、環境変数経由で外部サービスへ接続するように変更する。

```python
import os

# --- Qdrant設定 ---
class QdrantConfig:
    HOST = os.getenv("QDRANT_HOST", "localhost")
    PORT = int(os.getenv("QDRANT_PORT", "6333"))
    API_KEY = os.getenv("QDRANT_API_KEY", None)
    URL = f"https://{HOST}:{PORT}" if API_KEY else f"http://{HOST}:{PORT}"

# --- Celery設定 ---
class CeleryConfig:
    BROKER_URL = os.getenv(
        "CELERY_BROKER_URL",
        "redis://localhost:6379/0"
    )
    RESULT_BACKEND = os.getenv(
        "CELERY_RESULT_BACKEND",
        "redis://localhost:6379/0"
    )
```

**修正対象ファイル一覧：**

- `config.py` — QdrantConfig, CeleryConfig の環境変数化
- Qdrant接続モジュール — `QdrantClient(url=..., api_key=...)` に変更
- Redis接続モジュール — 環境変数からURLを取得するように変更

### 3-2. Dockerfile 作成 【必須】

Cloud Run 用の Dockerfile を作成。`entrypoint.sh` で Celery Worker と Streamlit を同時起動する。

```dockerfile
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages \
     /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

# 実行権限を付与
RUN chmod +x entrypoint.sh

# Cloud Run は PORT 環境変数を自動設定
EXPOSE 8501

CMD ["sh", "./entrypoint.sh"]
```

### 3-3. entrypoint.sh 作成 【必須】

Celery Worker をバックグラウンドで起動した後、Streamlit をフォアグラウンドで起動する。

```bash
#!/bin/bash

# Celery Worker をバックグラウンドで起動
celery -A celery_tasks worker --loglevel=info --concurrency=4 &

# Streamlit を起動（Cloud Run の PORT 環境変数を利用）
streamlit run agent_rag.py \
  --server.port=${PORT:-8501} \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false
```

### 3-4. .dockerignore 作成 【必須】

不要ファイルをビルドコンテキストから除外し、イメージを軽量化。

```text
.git
.gitignore
.idea
.venv
venv
__pycache__
*.pyc
.env
.DS_Store
OUTPUT/
temp_uploads/
logs/
tests/
docker-compose.yml
```

### 3-5. ローカルでDockerビルド＆テスト 【必須】

Cloud Runにデプロイ前にローカルでテスト。M2 Macの場合、`--platform linux/amd64` でクロスビルド。

```bash
# ビルド（Cloud Run用にamd64）
docker build --platform linux/amd64 \
  -t gemini-rag:test .

# ローカルテスト
docker run --rm -p 8501:8501 \
  -e GEMINI_API_KEY=your_key \
  -e GOOGLE_API_KEY=your_key \
  -e QDRANT_HOST=your-cluster.cloud.qdrant.io \
  -e QDRANT_API_KEY=your_qdrant_api_key \
  -e CELERY_BROKER_URL=redis://your-redis-host:6379/0 \
  gemini-rag:test
```

ブラウザで http://localhost:8501 にアクセスして動作確認。

---

## Phase 4: デプロイフェーズ（1日）

Cloud Run へのデプロイ & 動作確認

### 4-1. Cloud Build でビルド & Push 【必須】

`gcloud builds submit` でビルドとPushを一体で実行する。

```bash
# ビルド + Push（一体型コマンド）
gcloud builds submit \
  --tag gcr.io/YOUR_PROJECT_ID/agent-rag
```

### 4-2. Cloud Run サービスデプロイ 【必須】

Streamlit + Celery アプリを Cloud Run にデプロイ。WebSocket対応のため `--session-affinity` とタイムアウトを設定。メモリは Embedding 処理があるため 2Gi 以上推奨。

```bash
gcloud run deploy agent-rag \
  --image gcr.io/YOUR_PROJECT_ID/agent-rag \
  --platform managed \
  --region asia-northeast1 \
  --port 8501 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --session-affinity \
  --min-instances 0 \
  --max-instances 3 \
  --vpc-connector rag-connector \
  --set-env-vars "\
GEMINI_API_KEY=xxx,\
GOOGLE_API_KEY=xxx,\
COHERE_API_KEY=xxx,\
QDRANT_HOST=your-cluster.cloud.qdrant.io,\
QDRANT_API_KEY=xxx,\
CELERY_BROKER_URL=redis://REDIS_HOST:6379/0,\
CELERY_RESULT_BACKEND=redis://REDIS_HOST:6379/0" \
  --allow-unauthenticated
```

### 4-3. 動作確認チェックリスト 【必須】

デプロイ後に以下を順番に確認：

- [ ] Cloud Run URLでStreamlit UIが表示される
- [ ] Qdrant Cloud 接続：コレクション一覧が取得できる
- [ ] Qdrant検索：ベクトル検索が正常動作する
- [ ] Celery Worker：バックグラウンドタスクが実行される
- [ ] Agent(ReAct)：質問→検索→回答の全フロー
- [ ] WebSocket：ページ遷移でセッションが切れない
- [ ] ログ：Cloud Logging でエラーが出ていない

```bash
# Cloud Run URL確認
gcloud run services describe agent-rag \
  --region=asia-northeast1 \
  --format="value(status.url)"

# ログ確認
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   resource.labels.service_name=agent-rag" \
  --limit=50 --format=json
```

---

## Phase 5: 運用・最適化フェーズ（継続的）

監視・CI/CD・コスト最適化・セキュリティ強化

### 5-1. Secret Manager への移行 【推奨】

初期デプロイでは `--set-env-vars` で直接設定するが、セキュリティ強化のために Secret Manager への移行を推奨。

```bash
# APIキーを Secret Manager に登録
echo -n "your_gemini_api_key" | \
  gcloud secrets create GEMINI_API_KEY --data-file=-

echo -n "your_qdrant_api_key" | \
  gcloud secrets create QDRANT_API_KEY --data-file=-

# Cloud Run を更新（環境変数 → Secret 参照に切り替え）
gcloud run services update agent-rag \
  --region=asia-northeast1 \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,\
QDRANT_API_KEY=QDRANT_API_KEY:latest"
```

### 5-2. カスタムドメイン設定 【任意】

独自ドメインをCloud Runサービスにマッピング。

```bash
gcloud run domain-mappings create \
  --service=agent-rag \
  --domain=rag.your-domain.com \
  --region=asia-northeast1
```

### 5-3. Cloud Monitoring アラート設定 【推奨】

エラー率、レイテンシ、メモリ使用量の監視。Gemini APIのレート制限エラー（429）も監視対象に。

```text
# gcloud CLI or GCPコンソールで設定
# 主要メトリクス：
#  - request_count（status=5xx）
#  - request_latencies（p95 > 30s）
#  - container/memory/utilization（> 80%）
```

### 5-4. GitHub Actions CI/CD パイプライン 【推奨】

mainブランチへのPushで自動デプロイ。Workload Identity Federation で認証。

```yaml
# .github/workflows/deploy.yml
name: Deploy to Cloud Run
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.SA_EMAIL }}
      - name: Build and Push
        run: |
          gcloud builds submit \
            --tag gcr.io/${{ secrets.GCP_PROJECT_ID }}/agent-rag
      - uses: google-github-actions/deploy-cloudrun@v2
        with:
          service: agent-rag
          region: asia-northeast1
          image: gcr.io/${{ secrets.GCP_PROJECT_ID }}/agent-rag
```

### 5-5. コスト最適化 【推奨】

Cloud Run の課金はリクエスト処理中のみ。`min-instances=0` でアイドル時コストゼロ。

**月額コスト目安（軽量利用）：**

| サービス | 月額 |
|:---|:---|
| Cloud Run | $0〜5（従量課金、無料枠あり） |
| Qdrant Cloud Free | $0 |
| Redis Cloud Free / Memorystore | $0 / ~$35 |
| Cloud Build | $0（無料枠: 120分/日） |

Redis Cloud Free Tier を選択すれば月額 **$5以下** も可能。

```bash
# 予算アラート設定
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --display-name="RAG App Budget" \
  --budget-amount=50USD \
  --threshold-rule=percent=80
```

---

## ToDo チェックリスト（総括）

### 準備フェーズ（Phase 1〜2）

- [ ] GCP API 有効化（Cloud Run, Cloud Build, Memorystore, VPC Access）
- [ ] VPC コネクタ作成
- [ ] Qdrant Cloud — アカウント作成・クラスタ起動
- [ ] Qdrant Cloud — Cluster URL / API Key の取得
- [ ] Qdrant Cloud — データ移行（再登録 or スナップショット）
- [ ] Redis — Memorystore 作成 or Redis Cloud Free Tier 作成

### 実装フェーズ（Phase 3）

- [ ] config.py — Qdrant 接続部分の環境変数対応
- [ ] config.py — Redis / Celery 接続部分の環境変数対応
- [ ] Dockerfile の作成（Python 3.11、マルチステージビルド）
- [ ] entrypoint.sh の作成（Celery + Streamlit 同時起動）
- [ ] .dockerignore の作成
- [ ] ローカル Docker ビルド & テスト

### デプロイフェーズ（Phase 4）

- [ ] `gcloud builds submit` でビルド & Push
- [ ] Cloud Run へのデプロイ
- [ ] 動作確認（UI表示、Qdrant接続、Agent検索、ログ確認）

### 運用フェーズ（Phase 5）

- [ ] Secret Manager への APIキー移行
- [ ] Cloud Monitoring アラート設定
- [ ] GitHub Actions CI/CD パイプライン構築
- [ ] カスタムドメイン設定（任意）

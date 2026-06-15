## Agent RAG: Google Cloud Run 移行計画書

## 1. プロジェクト概要 & 移行の目的

現在の **VM (Compute Engine) + Docker Compose** 構成から、**Google Cloud Run (Serverless)** への移行を行う。
これにより、サーバー管理コストの削減、オートスケール、およびHTTPS化の自動対応を実現する。

**現状の構成:**

- **App:** Streamlit (Python)
- **Vector DB:** Qdrant (Local Container)
- **KVS/Queue:** Redis (Local Container)
- **Platform:** Google Compute Engine (VM)

**移行後の構成:**

- **App:** Google Cloud Run
- **Vector DB:** **Qdrant Cloud** (Managed Service)
- **KVS/Queue:** **Google Cloud Memorystore** for Redis (または Redis Cloud)

---

## 2. 新アーキテクチャ構成案

Cloud Run はステートレス（データを保持しない）環境であるため、**データストア（Qdrant, Redis）を外部サービス化** する構成を採用する。


| コンポーネント  | 移行後のサービス      | 選定理由                                                                                                                        |
| :-------------- | :-------------------- | :------------------------------------------------------------------------------------------------------------------------------ |
| **Application** | **Google Cloud Run**  | コンテナベースのサーバーレス。スケーラビリティと管理の容易さ。                                                                  |
| **Vector DB**   | **Qdrant Cloud**      | Qdrant社公式マネージドサービス。1GBまでの無料枠あり。管理運用コストがゼロ。                                                     |
| **Redis**       | **Cloud Memorystore** | GCP純正のフルマネージドRedis。VPCコネクタ経由で高速・安全に接続可能。<br>*(※コスト重視の場合は Redis Cloud のFree Tierも検討)* |

---

## 3. 移行ステップ詳細

### Step 1: データストアの準備 (外部化)

#### 1-1. Qdrant Cloud のセットアップ

1. [Qdrant Cloud](https://cloud.qdrant.io/) でアカウントを作成。
2. Free Tier クラスタを作成。
3. **Cluster URL** と **API Key** を取得し、メモする。
4. (データ移行) 必要に応じてローカルのデータをスナップショット経由で移行、またはRAGデータ作成機能を使い再登録する。

#### 1-2. Redis の準備 (Memorystore)

1. GCPコンソールより「Memorystore for Redis」を作成。
2. **VPC ネットワーク** とリージョンを選択（Cloud Runと同じリージョン推奨）。
3. 接続用 **IPアドレス** と **ポート** を取得する。
4. **サーバーレス VPC アクセス コネクタ** を作成（Cloud Run が Redis にアクセスするために必須）。

### Step 2: アプリケーションコードの修正

`docker-compose.yml` で定義されていたネットワーク内通信 (`http://qdrant:6333` 等) を、環境変数経由で外部サービスへ接続するように変更する。

**修正対象:** `utils` や `db` 関連の接続モジュール (想定)

**変更イメージ:**

```python
import os
from qdrant_client import QdrantClient

# 旧: host="qdrant"
# 新: 環境変数から読み込み
qdrant_url = os.environ.get("QDRANT_URL")
qdrant_api_key = os.environ.get("QDRANT_API_KEY")

client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
```


#### 

### Step 3: Cloud Run 用 Dockerfile の作成

`docker-compose` は使用しないため、単一のイメージで動作するように調整する。 Celery Worker と Streamlit を同時に動かす必要がある場合、起動スクリプト (`entrypoint.sh`) を用意する。

```python
import os
from qdrant_client import QdrantClient

# 旧: host="qdrant"
# 新: 環境変数から読み込み
qdrant_url = os.environ.get("QDRANT_URL")
qdrant_api_key = os.environ.get("QDRANT_API_KEY")

client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)

#### docker-compose は使用しないため、単一のイメージで動作するように調整する。
- Celery Worker と Streamlit を同時に動かす必要がある場合、起動スクリプト (entrypoint.sh) を用意する。

Dockerfile 例 (概念):
```python
FROM python:3.9-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

# Cloud Run はポート8080 (または環境変数PORT) をリッスンする必要がある
CMD ["sh", "./entrypoint.sh"]
```

- entrypoint.sh 例:

```
#!/bin/bash
# Celery Worker をバックグラウンドで起動
celery -A your_app worker --loglevel=info &

# Streamlit を起動 (Cloud RunのPORT環境変数を利用)
streamlit run agent_rag.py --server.port=${PORT:-8501} --server.address=0.0.0.0
```

#### Step 4: デプロイ

Google Cloud CLI (gcloud) を使用してデプロイを行う。

```bash
# 1. コンテナのビルドとPush
gcloud builds submit --tag gcr.io/PROJECT_ID/agent-rag

# 2. Cloud Run へのデプロイ (環境変数をセット)
gcloud run deploy agent-rag \
  --image gcr.io/PROJECT_ID/agent-rag \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --vpc-connector YOUR_VPC_CONNECTOR_NAME \
  --set-env-vars QDRANT_URL="xxx",QDRANT_API_KEY="xxx",REDIS_HOST="xxx"
```

4. ToDo リスト
   準備フェーズ
   [ ] Qdrant Cloud

[ ] アカウント作成・クラスタ起動

[ ] URL / API Key の取得

[ ] Redis (Memorystore)

[ ] インスタンス作成

[ ] VPC コネクタの作成

実装フェーズ
[ ] Pythonコード修正

[ ] Qdrant 接続部分の環境変数対応

[ ] Redis 接続部分の環境変数対応

[ ] Dockerfile / 起動スクリプト作成

[ ] Dockerfile の作成 (Cloud Run用)

[ ] entrypoint.sh の作成 (Streamlit + Celery 同時起動用)

デプロイフェーズ
[ ] gcloud コマンドでのビルド (Artifact Registry / GCR)

[ ] Cloud Run へのデプロイ

[ ] 動作確認 (ログ確認、RAG検索テスト)

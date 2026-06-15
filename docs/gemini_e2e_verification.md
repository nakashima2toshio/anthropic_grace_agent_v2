# gemini_grace_agent 実環境 E2E 検証手順書（TODO A 群）

本セッションの実装（#51–#67・`_enforce_max_chunk_tokens`・B-1 トークン配線）は
すべて `unittest.mock` で検証済み。本書は**実依存（Gemini API / Qdrant / Celery+Redis）**での
動作確認手順をまとめる。各項目は「手順 → 期待される結果（受け入れ基準）」の形で記述する。

> サンドボックス（実キー無し・Qdrant/Redis 未起動）では実施できないため、開発マシンで実行すること。

---

## 0. 事前準備（共通）

### 0-1. 依存インストール
```bash
uv sync --extra dev          # もしくは: pip install -r requirements.txt
```

### 0-2. `.env`（プロジェクト直下）
```bash
# LLM / Embedding（どちらかが設定されていればよい。両方推奨）
GEMINI_API_KEY=your_real_key
GOOGLE_API_KEY=your_real_key
# インフラ
QDRANT_HOST=localhost
QDRANT_PORT=6333
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### 0-3. Qdrant 起動
```bash
docker-compose -f docker-compose/docker-compose.yml up -d
curl -s http://localhost:6333/collections | jq .    # 接続確認
```

### 0-4. 件数確認ヘルパー（以降で多用）
```bash
# コレクションの登録件数を表示（tool 非依存・REST API）
qcount() { curl -s "http://localhost:6333/collections/$1" | jq '.result.points_count'; }
# 例: qcount cc_news_1per
```

### 0-5. テスト用入力
小さめのチャンク済み CSV（`text` カラム必須）を用意。例として `output_chunked/cc_news_1per_chunks.csv`。
未チャンクの生 CSV からは先にチャンク化：
```bash
python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_1per.csv \
  --output output_chunked
```

---

## A-1. 実 Gemini API での Q/A 生成（単段化 #52・B-1 トークン）

**手順**（Celery を使わない同期経路で最小確認）:
```bash
python qa_qdrant/make_qa.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --model gemini-2.5-flash \
  --output qa_output
```

**受け入れ基準**:
- ログに `Q/A生成モード: スマート生成（…構造化出力1回）` が出る
- 各チャンクで `→ N Q/A生成` が出力され、`qa_count`（0–5）に応じた件数になる
- `qa_count=0` のチャンクはスキップされエラーにならない
- **B-1**: 末尾に `トークン使用量（合計）: 入力=X, 出力=Y`（X,Y > 0）が出る
- `qa_output/` に Q/A CSV が生成される

---

## A-2. 実 Qdrant 再登録の冪等性（内容ハッシュ point ID #51a）

**手順**:
```bash
# 1回目（新規・--recreate）
python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --collection cc_news_1per --use-celery --recreate
qcount cc_news_1per          # → 件数を記録（例: N）

# 2回目（--recreate なしで同じデータを再登録）
python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --collection cc_news_1per --use-celery
qcount cc_news_1per          # → N のまま（増えない）
```

**受け入れ基準**:
- 2回目の `qcount` が**1回目と同じ**（内容ハッシュ ID で upsert がべき等）
- 旧実装（位置ベース ID）なら 2N になっていたはずの重複が発生しない
- ログの `🔍 登録後検証: Qdrant側件数=… / 今回処理=…` が概ね一致

> 注: Q/A は LLM 生成のため 2 回の内容が完全一致しない場合がある。厳密確認は
> Q/A 済み CSV（`question,answer` 列を持つ固定データ）を `register_to_qdrant.py` で
> 2 回登録して件数不変を見るのが確実：
> ```bash
> python qa_qdrant/register_to_qdrant.py --input-file qa_output/xxx_qa.csv \
>   --collection idem_test --recreate
> python qa_qdrant/register_to_qdrant.py --input-file qa_output/xxx_qa.csv \
>   --collection idem_test           # 件数不変を確認
> ```

---

## A-3. 並列登録スループット（先読みパイプライン #51c・`--embed-workers`）

**手順**（同一データで直列 vs 並列の時間比較）:
```bash
# 直列相当（先読み1）
time python qa_qdrant/register_to_qdrant.py \
  --input-file qa_output/xxx_qa.csv --collection perf_test \
  --recreate --embed-workers 1

# 並列（先読み4）
time python qa_qdrant/register_to_qdrant.py \
  --input-file qa_output/xxx_qa.csv --collection perf_test \
  --recreate --embed-workers 4
```

**受け入れ基準**:
- 両方ともエラーなく完走し、`qcount perf_test` が同じ
- `--embed-workers 4` の実時間が `1` より短い（Embedding I/O が upsert と重なる）
- ログに `Embed並列数: 4（先読みパイプライン）`、`🧹 重複テキスト … 件を除外`（重複があれば）

---

## A-4. 実 Celery+Redis での完了順回収・生成器キャッシュ（#67）

**手順**:
```bash
# Redis 起動（未起動なら）
redis-server --daemonize yes
# Celery ワーカー起動（concurrency=4 + Flower）
./start_celery.sh restart -c 4 --flower
# Celery 経路で登録
python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --collection cc_news_celery --use-celery --recreate
```

**受け入れ基準**:
- `結果収集中: Nタスク, …（完了順回収）` と `進捗: x/N` が**完了順**で進む
  （先頭の遅いチャンクが後続の回収を塞がない）
- ワーカーログで `SmartQAGenerator` 初期化が**モデルあたり1回**（タスクごとに再生成しない＝`_GENERATOR_CACHE`）
- **B-1**: ワーカーログに `tokens(in/out)=X/Y`、収集後に
  `トークン使用量（合計）: 入力=…, 出力=…`（> 0）
- 失敗/タイムアウト時もサマリーに件数が計上される

---

## A-5. pipeline の JSONL 逐次永続化・クラッシュ再開（#53）

**手順**:
```bash
# 大きめ入力で同期生成を開始し、途中で Ctrl-C 中断
python qa_qdrant/make_qa.py \
  --input-file output_chunked/cc_news_5per_chunks.csv \
  --model gemini-2.5-flash --output qa_output
# → 数チャンク処理後に Ctrl-C

ls qa_output/qa_progress_*.jsonl        # 進捗ファイルが存在
wc -l qa_output/qa_progress_*.jsonl     # 処理済みチャンク数 = 行数

# 同じコマンドで再実行（再開）
python qa_qdrant/make_qa.py \
  --input-file output_chunked/cc_news_5per_chunks.csv \
  --model gemini-2.5-flash --output qa_output
```

**受け入れ基準**:
- 再実行時に `📂 逐次保存ファイルから再開: 処理済み K チャンクをスキップ …` が出る
- **処理済みチャンクは再 LLM 呼び出しされない**（API コスト削減）
- 最終的に全チャンク分の Q/A が揃う（復元分 + 新規分）
- 正常完了後 `逐次保存ファイルを削除: …qa_progress_*.jsonl`（再開ファイルが消える）
- 途中で壊れた行があってもスキップされ、そのチャンクは再処理される

---

## 後片付け
```bash
./start_celery.sh stop 2>/dev/null || true
docker-compose -f docker-compose/docker-compose.yml down
# テスト用コレクション削除（必要なら）
for c in cc_news_1per cc_news_celery idem_test perf_test; do
  curl -s -X DELETE "http://localhost:6333/collections/$c" >/dev/null; done
```

---

## 結果の記録テンプレート

| 項目 | 結果 | メモ（件数・時間・ログ要点） |
|---|---|---|
| A-1 Q/A 生成 + トークン | ☐ pass / ☐ fail | |
| A-2 再登録べき等 | ☐ pass / ☐ fail | 1回目=__ / 2回目=__ |
| A-3 並列スループット | ☐ pass / ☐ fail | workers1=__s / workers4=__s |
| A-4 Celery 完了順 + トークン | ☐ pass / ☐ fail | |
| A-5 JSONL 再開 | ☐ pass / ☐ fail | skip=__ chunks |

> 失敗や想定外ログがあれば、該当コマンドの出力を共有してください。原因を解析します。

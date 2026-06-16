# eval/ — GRACE 評価ハーネス（S0）

`docs/grace_react_refactor_todo.md` の **S0（評価ハーネス整備）** 実装。
以降の改善（S1 較正・S3 ReAct 化）が「本当に良くなったか」を数値で言えるようにする土台。

## 構成

| ファイル | 役割 |
|---|---|
| `build_dataset.py` | Qdrant コレクションから正解付き `dataset.jsonl` を生成 |
| `dataset.jsonl` | 正解付き Q&A（`build_dataset.py` が生成） |
| `run_eval.py` | 現行 GRACE を回し、正解率・幻覚率・平均confidence・ECE・コスト・レイテンシを出力 |
| `metrics.py` | ECE（較正誤差）等の算出 |

## 前提

- GRACE 本体（`grace` パッケージ・`helper_llm`）と同じ作業ツリーで実行する
- Qdrant が稼働している（`executor` の rag_search が参照）
- `ANTHROPIC_API_KEY` が設定されている
- 評価コレクション: **`cc_news_2per_anthropic`**（payload: `question` / `answer` / `source`）

## 手順

### 1. 評価データ生成（Qdrant から）

```bash
python -m eval.build_dataset \
  --collection cc_news_2per_anthropic \
  --limit 100 \
  --output eval/dataset.jsonl
```

### 2. ベースライン測定

```bash
python -m eval.run_eval \
  --dataset eval/dataset.jsonl \
  --limit 0 \
  --report logs/eval_baseline.json
```

`--limit 5` で少数のスモークテストから始めると安全。

## 出力（スコア表）

```
================================================
metric                               value
------------------------------------------------
samples                                100
accuracy                             0.000
hallucination_rate                   0.000
mean_confidence                      0.000
ECE                                  0.000
mean_latency_ms                        0.0
total_cost_usd                      0.0000
================================================
```

- **accuracy**: LLM ジャッジが `correct` と判定した割合
- **hallucination_rate**: 根拠なく事実を捏造したと判定された割合
- **ECE**: confidence と実正解率のズレ（較正誤差）。S1 較正の改善対象

## DoD（S0 完了条件）

`python -m eval.run_eval` で現行システムのスコア表が出ること。
このベースライン値が、S1（ECE 改善）・S3（accuracy が静的版以上）の基準点になる。

## 注意

- `run_eval.py` / `build_dataset.py` 冒頭の import は v1 のレイアウト（`grace.*`, `helper_llm`,
  `qdrant_client_wrapper`）を前提にしている。v2 のモジュール配置が異なる場合は import パスを調整すること。
- ジャッジは `claude-sonnet-4-6` 等の Anthropic モデルを使用（`--judge-model` で指定可）。

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

## S1｜較正された根拠妥当性（実装済み）

`docs/grace_react_refactor_todo.md` の **S1**。confidence を「検索スコアの言い換え」から
「根拠妥当性（groundedness）＋較正」へ移行する。

### 1. groundedness（根拠妥当性）を信頼度の主成分に
- `grace/confidence.py::GroundednessVerifier` が最終回答を主張（claim）に分解し、
  各主張が引用ソースに **支持(supported)/矛盾(contradicted)/無関係(neutral)** かを LLM 判定。
- 支持率（support_rate）を `executor._calculate_overall_confidence` の**主成分**に採用。
  検索スコアベースの集約値は **補助項**（`confidence.search_aux_weight`、既定 0.2）に降格。
- 矛盾検出時は強く減点、ソース皆無の事実回答は過信抑制。
- 設定：`confidence.groundedness_enabled` / `groundedness_weight`(0.6) /
  `self_eval_weight`(0.25) / `coverage_weight`(0.15)。
- ソース無し／LLM 失敗時は未検証として従来ブレンドへ graceful fallback。

### 2. 較正（temperature scaling）で ECE を縮小
```bash
# ベースライン測定（confidence 付きレポートを出力）
python -m eval.run_eval --report logs/eval_baseline.json
# レポートから温度 T を推定し config/calibration.json に保存（較正前後の ECE を表示）
python -m eval.calibrate --report logs/eval_baseline.json --output config/calibration.json
# 以降の run_eval は config/calibration.json を読み、較正後 ECE も表示。
# executor も実行時に overall_confidence へ T を適用する。
python -m eval.run_eval --report logs/eval_calibrated.json
```
- `grace/calibration.py`：`p' = sigmoid(logit(p)/T)`。T は二値 NLL 最小化で推定（scipy 非依存）。
- 較正ファイルが無ければ T=1.0（恒等）で動作。

**DoD**：S0 の **ECE がベースラインより改善**。較正は事後変換のため fit 集合上で ECE を
必ず縮小する（`tests/grace/test_calibration.py` で検証）。実データでの最終確認は
`ANTHROPIC_API_KEY` + Qdrant 稼働下での `run_eval` → `calibrate` → `run_eval` で行う。

## S3｜ハイブリッド ReAct スケルトン（実装済み）

`docs/grace_react_refactor_todo.md` の **S3**。静的な `plan.steps` の for ループを、
観測を見て毎ターン次の1手を決める **Reason–Act–Observe** ループへ置換する。
Plan は「初期仮説」として保持するハイブリッド方式。

- **スキーマ**（`grace/schemas.py`）：`Scratchpad`/`ScratchpadEntry`（観測履歴）、
  `AgentThought`（reasoning＋次アクション＋停止判定 `is_final`）。
- **Reason**（`executor._decide_next_action`）：Scratchpad＋初期 Plan から次の1手を LLM が決定。
  LLM 不在/失敗時は初期 Plan を順に辿るフォールバック（＝静的パス相当に degrade）。
- **ループ**（`executor.execute_react_generator`）：Reason→Act→Observe→Confidence→Controller。
  - Act：既存の `_execute_step`（ツール実行・タイムアウト・フォールバック）を再利用。
  - Observe：ツール出力を Scratchpad に追記。
  - Confidence：`_llm_calculate_step_confidence` ＋ **S1 の groundedness/較正**を再利用。
  - Controller：較正済み confidence と `decide_action` で 継続/介入/終了 を判定。
- **分岐制御**（`executor._dispatch_generator`）：`complexity >= executor.react_complexity_threshold`
  （既定 0.7）の複雑質問のみ ReAct、単純質問は**現行の静的パスを温存**。
- 設定：`executor.react_enabled` / `react_complexity_threshold` / `react_max_iterations`。

**DoD**：S0 の **正解率が静的版以上**、かつ複雑質問で改善。
実データでの確認は `ANTHROPIC_API_KEY` + Qdrant 稼働下で、`react_enabled` の
true/false を切り替えて `run_eval` のスコアを比較する（静的版とのA/B）。
ロジックは `tests/grace/test_react.py`（API 非依存・mock）で検証済み。

## A/B 自動比較（`ab_compare`）

`executor.react_enabled` の ON/OFF を自動で2回まわし、accuracy / ECE /
hallucination / latency / cost を差分テーブルで比較する。

```bash
python -m eval.ab_compare \
    --dataset eval/dataset.jsonl --limit 20 \
    --collection cc_news_2per_anthropic \
    --output-dir logs/ab
# → logs/ab/eval_static.json, logs/ab/eval_react.json, logs/ab/ab_summary.json
```

- `static` = `react_enabled=False`（静的 Plan-Execute）/ `react` = `react_enabled=True`。
- `--threshold` で `react_complexity_threshold` を上書き可能（複雑質問のみ ReAct が効くため、
  しきい値を下げると ReAct の発火率が上がる）。
- 出力テーブルの `better` 列は指標の方向性（accuracy は高い方が良い、ECE/hallucination/
  latency/cost は低い方が良い）を加味して `react` / `static` / `=` を表示する。
- ロジックは `tests/eval/test_ab_compare.py`（API 非依存・mock）で検証済み。

## 注意

- `run_eval.py` / `build_dataset.py` 冒頭の import は v1 のレイアウト（`grace.*`, `helper_llm`,
  `qdrant_client_wrapper`）を前提にしている。v2 のモジュール配置が異なる場合は import パスを調整すること。
- ジャッジは文字列処理用途のため既定で `claude-haiku-4-5-20251001`（Anthropic）を使用（`--judge-model` で変更可）。
  GRACE 本体（planner/executor/confidence/tools）は `claude-sonnet-4-6` を使用する。

# GRACE Agent 処理フロー詳細（最新版）

**Version 2.0** | 最終更新: 2026-06-26

1クエリを「計画策定 → 逐次実行 → 信頼度の自己評価 → 動的フォールバック → 最終集約」まで
端から端まで追った実行トレースです。フェーズ単位で「何が・なぜ起きるか」を示します。
各モジュールの IPO 詳細は [`planner_executor_confidence.md`](./planner_executor_confidence.md) と
個別ドキュメント（`planner.md` / `executor.md` / `confidence.md`）を参照してください。

---

## 実行条件（サンプル）

- **質問**: 「日本はどのような多義的な概念として解説されていますか？」
- **LLMモデル**: `claude-sonnet-4-6`（統一クライアント `create_chat_client` 経由）
- **想定コレクション数**: 5（Qdrant）
- **代表的な最終信頼度**: 0.59（NOTIFY〜CONFIRM 帯）

> このクエリは「日本」の多義性を問うが、コーパス上は「言語」の多義性が文構造的に近く、
> **コサイン類似度だけでは偽陽性が起きやすい**。その偽陽性を意味的適合性判定で排除する流れを示す好例。

---

## Phase 0: 初期化

```
Config loaded from config/grace_config.yml
Planner initialized with model: claude-sonnet-4-6
ToolRegistry initialized with: ['rag_search', 'web_search', 'reasoning', 'ask_user']
Executor (GRACE Native) initialized: tools=[...], replan=enabled
```

起動時に `Planner` / `ToolRegistry` / `ConfidenceCalculator` / `ReplanOrchestrator` / `Executor` が
順次初期化される。Qdrant への接続確認とコレクション情報の取得も実施。

---

## Phase 1: ユーザー入力

```
ユーザー入力: 「日本はどのような多義的な概念として解説されていますか？」
```

入力受付後、Qdrant のコレクション情報を取得（5コレクション確認）。

---

## Phase 2: 計画策定 — Planner（二層方式）

`Planner.create_plan()` は不要な LLM 呼び出しを避けるため二層方式で経路を選ぶ。

### Step 2a: 曖昧クエリ判定

```
is_ambiguous_query("日本はどのような…") → False
```

指示語のみで対象不明な「曖昧クエリ」ではないため、明確化（ask_user）経路には入らない。

### Step 2b: ヒューリスティック複雑度 → 経路選択

```
estimate_complexity("日本はどのような多義的な概念…") → 0.50
_should_use_llm_plan → False（0.50 < llm_plan_complexity_threshold=0.7、明示Web指示なし）
Using rule-based plan
```

複雑度が閾値未満かつ明示的な Web 指示がないため、**ルールベース2ステップ計画を即時生成**
（LLM 呼び出しなし）。複雑質問や「最新ニュースを検索して」等の明示指示があれば LLM 計画経路へ。

| Step | Action | Query | Fallback |
|------|--------|-------|----------|
| 1 | rag_search | 日本はどのような多義的な概念として解説されていますか？ | web_search |
| 2 | reasoning | （Step 1 に依存） | なし |

> `web_search` ステップは計画に含めない。RAG 結果が不足した場合に Executor が動的実行する。

---

## Phase 3: 実行 — Executor Step 1: rag_search

`execute_plan()` は `_dispatch_generator()` で実行方式を選ぶ。本サンプルは複雑度 0.50 < 0.7 のため
**静的 Plan-Execute**（`execute_plan_generator`）で実行（複雑度 >= 0.7 なら ReAct ループに分岐）。

### Step 3a: 5コレクション順次検索

```
fineweb_edu_ja_5per → 20 hits → 閾値0.7以上なし
cc_news_1per        → 18 hits → 閾値0.7以上なし
cc_news_5per        →  5 hits → 閾値0.7以上なし
wikipedia_ja_1per   → 13 hits → コサイン類似度フィルタ: 13 → 1件 (Top: 0.7053)
wikipedia_ja_5per   → 検索されず（1件見つかった時点で終了）
```

唯一のヒット：

```
score: 0.7053
Q: 『日本大百科全書』において、言語はどのような多義的な概念として解説されていますか？
```

質問は「日本」の多義性だが、結果は「言語」の多義性。文構造が類似するためスコアが高い（**偽陽性**）。

### Step 3b: 信頼度計算（③ Confidence）

```
ConfidenceFactors: search_max_score=0.7053, search_result_count=1
evaluate_with_factors → JSONパース失敗時は search_max_score にフォールバック
Step 1 confidence: 0.71
```

検索ステップの信頼度は検索品質が主成分。LLM 評価が形式不正・空応答の場合は
`search_max_score` をそのままスコアに用いるフォールバックが働く。

---

## Phase 4: RAG 動的分岐 — 意味的適合性判定

```
RAG score sufficient (0.7053 >= 0.7), checking semantic relevance with LLM
RAG relevance check: 'NO' -> False
RAG result not semantically relevant, need web_search
```

スコアは閾値以上だが、`_evaluate_rag_relevance()` が LLM に
「この検索結果は質問の回答に使えるか？（YES/NO）」を問い、**「NO」**を得る。
「日本」≠「言語」という主題のズレを意味レベルで検出し、`need_web_search = True` に設定。

### 判定ロジック

```
rag_search 成功後:
├── max_score < 0.7  → need_web_search = True（即断）
└── max_score >= 0.7 → LLM 適合性判定
                        ├── NO（不適合）→ need_web_search = True  ← 今回はここ
                        └── YES（適合） → web_search スキップ
```

---

## Phase 5: 動的 web_search 実行 — Step 101

```
Dynamic web_search: step_id=101, query=日本はどのような多義的な概念として解説されていますか？
SerpAPI search returned 5 results
```

`_execute_dynamic_web_search()` が仮想ステップ（`step_id = 元ID + 100`）を生成して実行。
Web 検索が 5 件を返す（タイムアウトは短め）。

| # | Score | Title | Source |
|---|-------|-------|--------|
| 1 | 1.0 | やさしい日本語の現在地 | clair.or.jp |
| 2 | 0.9 | 日本語は難しい？ | josai.ac.jp |
| 3 | 0.8 | 多様な人にわかりやすい日本語 | dlri.co.jp |
| 4 | 0.7 | 日本語にはなぜ多義語が多い？ | Yahoo!知恵袋 |
| 5 | 0.6 | 日本語の抽象語があやうい理由 | languagevillage.co.jp |

### Step 101 の信頼度計算

```
source_agreement: 0.6918（5件のembedding類似度から算出）
Step 101 confidence: 0.80
```

> Web も失敗した場合は `_execute_dynamic_ask_user()`（`step_id = 元ID + 200`）でユーザーに確認を求める
> フォールバック連鎖（RAG → Web → ask_user）が用意されている。

---

## Phase 6: Executor Step 2: reasoning

```
--- Reasoning Step ---
Available step_results: [1, 101]
```

`reasoning` は `depends_on=[1]` のみだが、`state.step_results` 全体を走査するため、
**Step 1（RAG）と動的挿入された Step 101（Web）の両方**を参照情報として統合する。

### reasoning 入力に渡された情報源（6件）

| # | 信頼度 | Source | 内容 |
|---|--------|--------|------|
| 情報源1 | 0.71 | RAG（wikipedia_ja_1per） | 「言語」の多義性 |
| 情報源2 | 1.00 | Web（clair.or.jp） | 多言語化とやさしい日本語 |
| 情報源3 | 0.90 | Web（josai.ac.jp） | 日本語の複雑性 |
| 情報源4 | 0.80 | Web（dlri.co.jp） | 情報のアクセシビリティ |
| 情報源5 | 0.70 | Web（Yahoo!知恵袋） | 多義語に関する誤解 |
| 情報源6 | 0.60 | Web（languagevillage.co.jp） | 大和言葉・漢語・和製漢語 |

### reasoning 出力

4カテゴリに整理した回答を生成：

1. **「言語」という概念の多義性**（RAG 結果）— 脳内システム／能力／抽象的・全人類的／具体的・社会的
2. **日本における社会的・政治的側面**（Web）— 多言語化と共生、情報のアクセシビリティ
3. **日本語の文化的・構造的側面**（Web）— 言語的複雑性、語彙の重層構造
4. **多義語に関する誤解**（Web）

冒頭で「『日本』という概念そのものを多義的に直接定義する記述は見当たりませんでした」と正直に申告。

---

## Phase 7: 最終信頼度集約

```
Step 2 confidence: 0.71
LLM self-evaluation / Query coverage / Groundedness を統合
Aggregated confidence: 0.59
```

`ConfidenceAggregator` が各ステップのスコアを集約。最終回答については
`LLMSelfEvaluator.evaluate_final()`（確信度＋網羅度）と `GroundednessVerifier.verify()`
（各主張が引用ソースに支持される割合）を加味する。集約結果が CONFIRM/ESCALATE 帯であれば
④ Intervention・⑤ Replan へつながる。

---

## 全体タイムライン（イメージ）

```
[0.0s]  ユーザー入力
[0.0s]  ├── Phase 2: Planner（ルールベース計画・LLM呼び出しなし）
[0.1s]  ├── Phase 3: Step 1 rag_search
[2.2s]  │   ├── 5コレクション検索
[5.1s]  │   └── 信頼度計算
[5.1s]  ├── Phase 4: 意味的適合性判定 'NO' → web_search 必要
[6.2s]  ├── Phase 5: Step 101 動的 web_search
[15.0s] │   ├── Web 検索
[20.4s] │   └── 信頼度計算
[20.4s] ├── Phase 6: Step 2 reasoning（RAG+Web の6情報源を統合）
[45.8s] │   └── 回答生成
[50.5s] └── Phase 7: 最終信頼度集約（aggregate + groundedness）
```

---

## このトレースが示す設計上のポイント

| 観点 | 仕組み | 効果 |
|------|--------|------|
| 偽陽性の排除 | `_evaluate_rag_relevance()` の LLM 適合性判定（YES/NO） | コサイン類似度では拾えない主題ズレを意味レベルで検知 |
| 動的フォールバック | RAG → Web → ask_user の連鎖を Executor が実行時に挿入 | 計画を肥大化させずに不足を補完 |
| 情報源の統合 | reasoning が全成功ステップ結果を参照 | RAG と動的 Web の両方を根拠に回答 |
| 自己評価 | confidence の多軸算出＋根拠妥当性（groundedness） | 「検索スコアの言い換え」でない信頼度を提示 |
| 計画コストの最適化 | 二層方式（単純質問はルールベース即時生成） | 不要な LLM 計画呼び出しを回避 |

---

## 関連ドキュメント

- [`planner_executor_confidence.md`](./planner_executor_confidence.md) — Plan→Execute→Confidence の横断まとめ
- [`planner.md`](./planner.md) / [`executor.md`](./executor.md) / [`confidence.md`](./confidence.md) — 各モジュールの IPO 詳細
- [`intervention.md`](./intervention.md) / [`replan.md`](./replan.md) — ④介入・⑤再計画

# anthropic_grace_agent v1→v2 リファクタリング資料

**Version 1.0** | 最終更新: 2026-06-18

> `anthropic_grace_agent`（以下 **v1**）→ `anthropic_grace_agent_v2`（以下 **v2**）で
> 「何が・なぜ・どう変わったか」をテーマ別に整理した資料。
> 末尾に **provider 依存/非依存マトリクス** と **ollama 移植チェックリスト** を付す。
> 機械抽出の差分一覧は付録 `docs/anthropic_v1_to_v2_file_diff.md` を参照。
> 計画は `docs/v1_to_v2_refactoring_doc_todo.md`。

---

## 0. 重要な前提（v1 の実態）

v1 は「Gemini そのまま」ではなく **移行途上**だった。実測した v1 の状態:

| 層 | v1 の実態 |
|---|---|
| grace LLM（`grace/config.py`） | 既に `provider="anthropic"` / `claude-sonnet-4-6`（`[MIGRATION]` 注記付き） |
| helper LLM（`helper/helper_llm.py`） | `ToolUseResponse`（tool-use/function-calling）NamedTuple ベース。既定 `DEFAULT_LLM_PROVIDER="openai"`、`create_llm_client(provider="openai")` |
| Embedding 設定 | `grace/config.py`/`config.yml` は **openai/text-embedding-3-large(3072)**。一方 `services/qdrant_service.embed_query_for_search` は **gemini 既定**（=設定と実装が不整合） |
| 未実装 | eval ハーネス / 較正 / ハイブリッド ReAct / 実行メモリ / code_execute / llm_compat |

→ つまり v1→v2 の本質は「**Gemini→Anthropic の単純移行**」ではなく、
**(a) LLM クライアント層の簡素化・既定統一、(b) embedding 方針の確定、(c) 自律エージェント能力（S0/S1/S3/P2/P4）の新規実装、(d) 規約・CI・ドキュメント整備** である。

---

## 1. サマリ（テーマ一覧）

| # | テーマ | 種別 | provider 依存性 |
|---|---|---|---|
| T1 | LLM クライアント層の刷新（helper_llm 簡素化・既定 anthropic） | 変更 | **依存** |
| T2 | Embedding 方針の確定（Gemini に統一） | 変更 | **依存** |
| T3 | `grace/llm_compat.py`（genai 互換 Anthropic アダプタ）新規 | 新規 | 半依存 |
| T4 | google-genai の用途限定（LLM 経路から除去・embedding 専用） | 変更 | 半依存 |
| T5 | 評価ハーネス S0（`eval/`） | 新規 | **非依存** |
| T6 | 信頼度の較正 S1（`calibration` + groundedness） | 新規 | **非依存** |
| T7 | ハイブリッド ReAct S3（`executor`） | 新規 | **非依存** |
| T8 | 実行メモリ層 P4（`memory`） | 新規 | **非依存** |
| T9 | code_execute サンドボックス P2 ＋ A/B 測定 | 新規 | **非依存** |
| T10 | インフラ・規約（CI/pyproject/skills/docs/バグ修正） | 変更 | 半依存 |

---

## 2. テーマ別詳細

### T1. LLM クライアント層の刷新（helper_llm 簡素化・既定 anthropic）【依存】

**Before（v1）**: `helper/helper_llm.py` は `ToolUseResponse(NamedTuple)` を返す tool-use/function-calling 指向の重いインターフェース。`DEFAULT_LLM_PROVIDER="openai"`、`create_llm_client(provider="openai")`。

**After（v2）**: インターフェースを 3 メソッド（`generate_content` / `generate_structured` / `count_tokens`）に簡素化。`DEFAULT_LLM_PROVIDER="anthropic"`、`create_llm_client(provider=None)`→既定 anthropic（不明 provider は Gemini フォールバック）。`AnthropicClient` は **遅延初期化**（構築時に SDK/キーを要求しない）。`-587/+152` 行。

**理由**: GRACE 本体は構造化出力中心で、tool-use 専用 interface は過剰。プロバイダ既定を本体方針（Anthropic）に一致させる。

**検証**: `tests/helpers/test_helper_llm.py`（GeminiClient/OpenAIClient/AnthropicClient/`create_llm_client` 既定）。

### T2. Embedding 方針の確定（Gemini に統一）【依存】

**Before（v1）**: 設定は openai/text-embedding-3-large(3072)、実装（`qdrant_service`）は gemini 既定で**不整合**。

**After（v2）**: `grace/config.py`/`config.yml` の embedding を **gemini/gemini-embedding-001(3072)** に統一。`create_embedding_client(provider="gemini")`。**LLM は Anthropic / Embedding のみ Gemini** という方針を明文化（Anthropic は embedding API を持たないため）。

**検証**: `tests/services/test_qdrant_service.py`、`tests/helpers/test_helper_embedding.py`。

### T3. `grace/llm_compat.py`（genai 互換 Anthropic アダプタ）新規【半依存】

**内容**: `create_chat_client(config)` が `config.llm.provider` に応じ、**`client.models.generate_content(...)` 互換**のクライアントを返す（Anthropic 既定 / gemini 指定時のみ genai）。既存の genai 形式の呼び出し（`response.text` 等）を**最小改修で温存**するためのアダプタ。`response_schema`/`response_mime_type` も JSON モードに変換。`_extract_config` は dict と属性の両対応。

**理由**: planner/executor/confidence/tools の既存 genai 形式コードを大改修せず Anthropic に載せ替える。

**ollama 観点**: 同じアダプタ方式を `create_chat_client` の provider 分岐に **ollama** を足す形で流用できる（**横展開の核**）。

### T4. google-genai の用途限定（LLM 経路から除去）【半依存】

**After（v2 後半の整理）**: `grace/{planner,tools,executor,confidence}.py` の `types.GenerateContentConfig(...)` を **plain dict** に置換し `from google.genai import types` を除去。`helper_llm.GeminiClient` の genai import を遅延化。**google-genai を import するのは embedding 経路のみ**（`helper_embedding.GeminiEmbedding` / `confidence.SourceAgreementCalculator`）。

**検証**: grace LLM モジュールに `from google.genai import types` が残らないことを grep で確認。`tests/` 全体 green。

### T5. 評価ハーネス S0（`eval/`）新規【非依存】

**内容**: `eval/run_eval.py`（planner→executor を正解付きQ&Aで回し LLM ジャッジ）、`eval/metrics.py`（accuracy/hallucination/mean_confidence/**ECE**/latency/cost、`MetricsReport`）、`eval/build_dataset.py`（Qdrant からデータセット生成）。

**理由**: 改善（S1/S3 等）が「本当に良くなったか」を数値で言える土台。

**ollama 観点**: ほぼコピーで移植可。ジャッジモデルを Ollama に、コスト計測を無効化（ローカル）するだけ。

### T6. 信頼度の較正 S1（`calibration` + groundedness）【非依存】

**内容**: `grace/calibration.py`（`Calibrator`＝温度スケーリング、`expected_calibration_error`）、`grace/confidence.py` に **groundedness（根拠妥当性）検証**（`GroundednessVerifier`：回答の各主張が引用ソースに支持されるか）を追加し confidence の主成分化。`eval/calibrate.py` で較正パラメータを保存。`config/grace_config.yml` に較正設定。

**ollama 観点**: 非依存。groundedness 判定の LLM が Ollama になるだけ。

### T7. ハイブリッド ReAct S3（`executor`）新規【非依存】

**Before（v1）**: executor に `_dispatch_generator`/`react_enabled`/`execute_react_generator` は**無し**（0件）。

**After（v2）**: 複雑度に応じて **静的 Plan-Execute / 観測駆動 ReAct ループ**を振り分け（`react_enabled` かつ `complexity>=react_complexity_threshold`）。`grace/schemas.py` に `AgentThought` 等を追加。executor は `+934/-353` 行。

**ollama 観点**: 非依存（LLM 呼び出しは `create_chat_client` 経由のため provider 透過）。

### T8. 実行メモリ層 P4（`memory`）新規【非依存】

**内容**: `grace/memory.py`（`ExecutionMemory`＝実行ログから (質問キーワード, コレクション, 成否, confidence) を JSONL 蓄積し `success_rate×mean_confidence` でコレクション事前分布を学習）。executor が実行末に記録、planner がルールベース/フォールバック計画で最良コレクションを優先。

**ollama 観点**: 非依存。

### T9. code_execute サンドボックス P2 ＋ A/B 測定【非依存】

**内容**: `grace/tools.py` に `CodeExecuteTool`（別プロセス＋`resource` 制限＋AST 静的検査の best-effort サンドボックス、既定 opt-in）。`eval/ab_compare.py`（`react_enabled` ON/OFF で accuracy/ECE 等を比較）。macOS 対応（`RLIMIT_AS` を Darwin で除外）。

**ollama 観点**: 非依存。

### T10. インフラ・規約（CI/pyproject/skills/docs/バグ修正）【半依存】

- **CI**（`.github/workflows/ci.yml`）: `build`(compileall・ブロッキング)＋`ruff`(advisory)＋**`pytest`(advisory・`pip install -e .` で宣言依存導入)**＋`auto-merge`(claude/*)。
- **pyproject**: 依存・pytest 設定整備（`google-genai` は embedding 用に宣言、`anthropic` は要追加の latent gap あり）。
- **skills/docs**: 書式仕様を `.claude/skills/` 同梱化（IPO/ページ/テスト）。`grace/doc`・`services/doc` 等を整備。
- **バグ修正**: code_execute(macOS)、sparse(SPLADE)失敗時の dense-only degrade、ブロッキング実行の CONFIRM 自動進行、統合テストの skip ゲート是正。

---

## 3. provider 依存/非依存マトリクス

| テーマ | そのまま移植可 | 置換が必要 | 新規実装 |
|---|:--:|:--:|:--:|
| T1 helper_llm | | ✅（Ollama クライアント/既定） | |
| T2 Embedding | | ✅（nomic-embed-text 768） | |
| T3 llm_compat | | ✅（provider 分岐に ollama 追加） | |
| T4 genai 用途限定 | ✅（パターン） | ✅（embedding 側のみ ollama 埋め込みに） | |
| T5 eval S0 | ✅ | （ジャッジ/コストのみ） | |
| T6 calibration S1 | ✅ | | |
| T7 ReAct S3 | ✅ | | |
| T8 memory P4 | ✅ | | |
| T9 code_execute/AB | ✅ | | |
| T10 infra/docs | ✅（CI/skills） | （モデル名・コレクション規約） | |

---

## 4. ollama 移植：置換対応表

| 項目 | v2(anthropic) | ollama_v2 目標 |
|---|---|---|
| LLM 既定モデル | `claude-sonnet-4-6` | `gemma4:e4b`（または `llama3.2`） |
| LLM クライアント | `create_chat_client`/`AnthropicClient` | `create_llm_client("ollama")` 経由＋`llm_compat` に ollama 分岐 |
| LLM APIキー | `ANTHROPIC_API_KEY` | 不要（ローカル） |
| Embedding | `gemini-embedding-001`(3072) | `nomic-embed-text`(768) |
| Qdrant コレクション | `*_anthropic` | `*_ollama`（**768次元で再作成必須**） |
| コスト計算 | あり | なし（ローカル・トークン集計のみ） |
| Q/A 出力形式 | （現行） | オブジェクト `{"qa_pairs":[...]}` |
| 統合テスト前提 | `ANTHROPIC_API_KEY`＋Qdrant | `RUN_OLLAMA_INTEGRATION=1`＋ローカル Ollama＋Qdrant |

---

## 5. ollama 移植チェックリスト（推奨順）

1. **config/helper（T1,T2,T10）**
   - [ ] `grace/config.py`：LLMConfig 既定を Ollama モデルへ、EmbeddingConfig を `nomic-embed-text`/768 へ。
   - [ ] `helper/helper_llm.py`：Ollama クライアント実装（generate_content/structured/count_tokens）、既定 provider=ollama。
   - [ ] `config.yml`/`config/grace_config.yml`：モデル一覧・既定・コレクション規約を ollama 化。
2. **llm_compat（T3）**
   - [ ] `grace/llm_compat.py`：`create_chat_client` の provider 分岐に **ollama** を追加（`client.models.generate_content` 互換）。
3. **非依存能力の移植（T5〜T9）= ほぼコピー＋import 調整**
   - [ ] `eval/*`・`grace/calibration.py`・`grace/memory.py`・`grace/tools.py` の `CodeExecuteTool`・executor の ReAct 分岐・`eval/ab_compare.py` を移植。
   - [ ] ジャッジ/コスト計測を Ollama・ローカル前提に調整。
4. **google-genai 用途限定（T4）**
   - [ ] ollama は embedding も Ollama のため、**google-genai 依存は基本不要**（embedding が gemini でなければ完全排除可）。
5. **テスト・CI（T10）**
   - [ ] テストの patch ターゲット・既定値を ollama へ。統合テストは `RUN_OLLAMA_INTEGRATION=1` の skipif。
   - [ ] CI pytest ジョブ `pip install -e .`、ruff、auto-merge を踏襲。
6. **Qdrant データ**
   - [ ] 768次元で `*_ollama` コレクションを再作成・再登録（次元差のため流用不可）。

---

## 6. リスク・注意点
- **埋め込み次元**：anthropic_v2 は 3072（Gemini）だが ollama は 768（nomic）。**Qdrant コレクション再作成必須**（dimension mismatch は実害大）。
- **v1 の設定/実装不整合**を踏襲しない（embedding は設定＝実装で一致させる）。
- **`anthropic` 依存の宣言漏れ**（latent gap）を ollama では作らない（必要 SDK を pyproject に明記）。
- 非依存能力（S0/S1/S3/P2/P4）は **LLM 呼び出しを `create_chat_client` 経由に保つ**ことで provider 透過を維持するのが移植容易性の鍵。

---

## 7. 変更履歴
| バージョン | 変更内容 |
|---|---|
| 1.0 | 初版作成（フェーズB/C：テーマ別解説・provider マトリクス・ollama 移植チェックリスト）（2026-06-18） |

# gemini_grace_agent リファクタリング TODO（プレイブック横展開）

`ollama_grace_agent`（PR #51〜#89）→ `openai_grace_agent` で確立した横展開プレイブックを
**gemini_grace_agent へ適用**するための TODO。`anthropic_grace_agent` を「正（ロジックのみ）」
とし、provider 層（LLM/Embedding クライアント・モデル名・次元・コスト・コレクション名・APIキー）
は **gemini の構成を維持**する。

- 作成日: 2026-06-15
- 基準（ロジックの正）: `anthropic_grace_agent`
- 参照: `docs/openai_refactor_todo_june14.md`（openai 横展開・本 TODO の雛形）
- 対象ブランチ: `claude/wizardly-allen-3kgscp`
- 現状調査: 2026-06-15 に grace/ ・登録Q/Aパイプライン・chunking・helper・不足ファイルを
  フォルダー単位で照合（本ファイル各 Phase の「状態」列はこの実測に基づく）

> **偽陽性に注意**: 全ファイル diff は provider 差が支配的。移植要否は
> **anthropic のロジック × gemini の現状** で判断する。
> **gemini の特徴**: Phase H（推論/出力枠是正）とプロバイダー設定は**既に適用済み**。
> 一方 Phase A/B/E/F/G の中核機能は **pre-refactor ベースライン**で未移植が多い。

---

## §0 プロバイダー読み替え（確定値）

anthropic を正にするのは**ロジックのみ**。下表の値は gemini のものを維持する。

| 項目 | anthropic（正にしない） | **gemini（維持する値）** |
|---|---|---|
| LLM クライアント | `create_llm_client("anthropic")` | `create_llm_client("gemini")` |
| Embedding クライアント | `create_embedding_client("gemini")` | `create_embedding_client("gemini")` |
| デフォルト LLM モデル | `claude-sonnet-4-6` | `gemini-2.5-flash` ※G3 で統一（要確認） |
| Embedding モデル/次元 | `gemini-embedding-001` / 3072 | `gemini-embedding-001` / **3072** |
| 出力枠パラメータ名 | `max_tokens` | `max_output_tokens` |
| コスト計算 | あり | **あり**（維持） |
| API キー | `ANTHROPIC_API_KEY` | `GOOGLE_API_KEY`（`GEMINI_API_KEY` フォールバックは G3 で追加） |
| Qdrant コレクション | `*_anthropic` | `*_gemini` |

---

## Phase A — GRACE 自律エージェント（`grace/`）

推奨順（依存関係考慮）。**`#58` が `#57/#60/#61` の前提**。

| # | 種別 | 状態 | 作業 |
|---|---|---|---|
| **#56** | fix(security) | ✅ DONE | `executor.py` の `eval(result.output)` を撤去し、anthropic の `_handle_ask_user_response()`（`ast.literal_eval`）を移植。ブロッキング経路＋空スタブだったジェネレータ経路の両方を本メソッドへ統合。top-level `import ast` 追加 |
| **#58** | feat | ❌ MISSING | `grace/config.py` に `PlannerConfig`（`llm_plan_complexity_threshold` 等）/`ExecutorConfig`（`parallel_search`/`fallback_chain` 等）を追加。**他機能の足場（次の最優先）** |
| **#57** | feat | ❌ MISSING | `executor.py` に `_run_tool_with_timeout()`（ThreadPoolExecutor）を追加し、`timeout_seconds`（既存の `executor.py:867/990` 参照）を実際に強制 |
| **#60** | feat | ❌ MISSING | `_prefetch_parallel_searches()`（依存なし検索ステップの並列プリフェッチ）を追加し実行ループへ配線。`ExecutorConfig.parallel_search` を実利用化 |
| **#61** | feat | ⚠️ PARTIAL | `planner.py` に二層計画（複雑度ヒューリスティックで単純質問は LLM 省略 → `_create_rule_based_plan()`）。`estimate_complexity`（`planner.py:347`）は存在するが LLM をスキップしない。現状 `create_plan`（`:135`）は全質問で LLM 経路 |
| **#64** | feat | ⚠️ PARTIAL | `_should_trigger_replan()` を追加し、低信頼度リプランを**検索ステップ限定**に。現状 `replan.py:should_replan`（~140-168）は全ステップ型で低信頼度再発火しカスケードの懸念 |
| **#65** | feat | ❌ MISSING | `confidence.py` に `FinalEvaluationResult` + `evaluate_final()`（自己評価＋網羅度を 2 回→1 回に統合）を追加し executor から利用。現状は `EvaluationResult`/`evaluate`/`evaluate_with_factors` のみ |
| **#66** | refactor | ❌ MISSING | `executor.py` に `_build_confidence_factors()` を追加し信頼度ファクタ構築を共通化（出力型を `Optional[Any]` へ拡張） |
| **#59** | refactor | ❌ MISSING | `execute_plan`（`executor.py:405`）が `execute_plan_generator`（`:179`）とは別の独立 blocking 実装で**二重ループ**。anthropic 同様に薄いラッパー（`yield from`）へ統合。※openai では DONE 済みだが gemini は未対応 |

---

## Phase B — 登録・Q/A・パイプライン

| # | 種別 | 状態 | 作業 |
|---|---|---|---|
| **#51** | feat/fix | ❌ MISSING（3 部） | (a) `services/qdrant_service.py:776` の位置ベース point ID（`abs(hash(...))`）を**内容ハッシュ**（`_content_point_key()`/`stable_point_id()`）化＋payload デフォルト補完、(b) `qa_qdrant/register_to_qdrant.py` に**重複Q/A除去**ブロック、(c) **ThreadPoolExecutor 先読み並列化**（`--embed-workers`/`on_result` フック）。現状は `register_to_qdrant.py:271-295` で逐次登録 |
| **#67** | feat | ❌ MISSING | `celery_tasks.collect_results`（`:189`）を blocking `task.get()`（`:203`）→ **`ready()` 完了順ポーリング＋`on_result` フック**へ。`_GENERATOR_CACHE`/`_get_generator()` でワーカー内再利用、`usage_out` 集計追加（HOL ブロッキング解消） |
| **#53** | feat | ❌ MISSING | `qa_generation/pipeline.py` 同期経路（`_generate_sync`、現状は in-memory `all_qa_pairs.append`）に **JSONL 逐次永続化＋クラッシュ再開**（処理済みチャンク skip）、`_enforce_max_chunk_tokens`。※#67 と統合して配線 |
| **#52** | feat | ❌ MISSING | 単段化（構造化出力 1 回）。現状 `qa_generation/smart_qa_generator.py` は **2 段**（`analyze_chunk`→`generate_qa_pairs`、`json.loads` テキスト解析）。`SmartQAResult`/`SmartQAPair` 構造化出力へ単段化し、死にフラグ `use_smart_generation` を撤去 |
| **#54** | feat | ❌ MISSING | `make_qa.py` の `--use-smart-generation/--no-smart-generation`（`:150-157,223,257`）を撤去。既定モデル `gemini-2.5-flash`・`GOOGLE_API_KEY` チェックは維持 |
| **#55** | feat | ❌ MISSING | `make_qa_register_qdrant.py` の死にフラグ（`:446-453` 等）＋`--combine-rows`（`:392`）撤去（チャンキングは `chunking/csv_text_to_chunks_text_csv.py` へ誘導） |
| **#82** | feat | ✅ DONE 相当 | `get_collection_embedding_params`（`qdrant_service.py:177`）は gemini 既定（3072→`gemini-embedding-001`、1536→`text-embedding-3-small`）で存在。payload 優先読取は anthropic 側も未実装のため対応不要 |

**推奨順**: #55 → #54 → #52（フラグ撤去＋単段化）→ #51（最重・3 部）→ #67 → #53

---

## Phase C — テスト（`tests/`）

> **gemini は openai と異なり、テストスイートが既に整備済み**（grace/services/qa_generation/helpers
> で計 ~22 ファイル・404 passed/8 skipped）。Phase C は新規移植ではなく**整理と追従**が中心。

| 項目 | 状態 | 作業 |
|---|---|---|
| grace/ テスト | ✅ 整備済 | confidence/config/executor/planner/replan/schema＋integration を保有。Phase A 実装後に対応テストを追補 |
| services/ テスト | ✅ 整備済 | agent/cache/config/dataset/file/json/log/qa/qdrant/token を保有 |
| qa_generation/ テスト | ✅ 整備済 | Phase B 単段化（#52）後に `smart_qa` 系テストを実装へ追従 |
| helpers/ テスト | ⚠️ 薄い | `test_helper_llm`/`test_helper_embedding` は存在。F1 実装後にトークン集計テストを追加 |
| **tests/chunking/** | ❌ 不在 | `chunking/` パッケージに対応するテスト無し。Phase E 実装後に新規作成 |
| tests/legacy/・root 散在スクリプト | ⚠️ 要整理 | `tests/legacy/`（5 本）と root の `verify_*`/`*.txt` メモを整理（stale 判定の上で削除 or skip 明示） |
| 移植漏れ（前セッション対応分） | ✅ DONE | `test_keyword_extraction` 等を新モジュール構成へ追従済み（本ブランチ既存コミット） |

> **注意**: Phase B #51 系のメタデータ round-trip テストは、**機能実装後**に追加する。

---

## Phase D — 基盤・ドキュメント

| # | 種別 | 状態 | 作業 |
|---|---|---|---|
| CI | ci | ❌ MISSING | `.github/workflows/ci.yml` を新規作成（`ruff check .` + `python -m compileall`、`claude/*` の auto-merge）。テスト整備済みのため **pytest ジョブ**も追加（統合テストは `GOOGLE_API_KEY`/実 Qdrant の env ゲート）。**現状 workflow 皆無** |
| #75 | docs | ❌ MISSING | `CLAUDE.md` に **§7 Mermaid / §8 コーディング規約 / §9 技術スタック表記** を追加。**現状 gemini の CLAUDE.md は汎用（OpenAI 寄り）テンプレートのまま**で §7/§8/§9 が無く、§技術スタックも `text-embedding-3-small` 等 OpenAI 表記。gemini 用（`Gemini`/`gemini-embedding-001`/3072 次元/`*_gemini`）に読み替えて整備。※モデル名規約に関わるため G3 と合わせて確認 |
| #76 | chore | ⚪ 確認 | `requirements.txt` は `uv export --format requirements-txt -o requirements.txt` 生成を維持（**`pip freeze` 禁止**）。dev 依存に pytest/ruff |
| docs | docs | ⚪ 任意 | `tests/README.md`（テスト一覧）整備 |

---

## Phase E — チャンキング（`chunking/`）

anthropic の pipeline 改修 × gemini 現状の照合。provider 値差は除外済み。**全項目 MISSING**。

| 項目 | 状態 | 根拠 | 作業 |
|---|---|---|---|
| **E1** Embedding 上限連携 | ❌ MISSING | `csv_text_to_chunks_text_csv.py` に `_enforce_max_chunk_tokens`/`_split_oversized_text` 不在。`MAX_CHUNK_TOKENS`/`EMBEDDING_INPUT_TOKEN_LIMIT` 無し。分割は文字数 `--block-size` のみ | チャンク最大長を Embedding 入力上限（gemini-embedding-001）に連携。文境界分割で超過チャンクを安全分割。`--max-chunk-tokens` 追加 |
| **E2** ルールベース継続判定 | ❌ MISSING | `--continuity-mode`(rule/llm/off)・`_rule_based_continuity` 不在。Step3（`_step3_continuity_check`）が常に LLM 経路 | 指示語/接続語マーカー＋短チャンク検出のルールベース継続判定を追加（既定 rule で LLM 呼び出しゼロ化） |
| **E3** doc_id トレーシング | ❌ MISSING | `chunks_all_async(text: str) -> List[str]` 単一文字列ベース。`doc_id`/`documents: Dict`/`List[Dict]` 無し | チャンクに doc_id を付与し Step1→2→3 で伝播。※下流 Q/A・登録への影響範囲を要確認 |
| **E4** トークン使用量集計 | ❌ MISSING | `async_api_client.py` は `_total_requests` 等のみ。`_accumulate_usage`/`usage_metadata` 集計無し | provider 中立部分の input/output トークン集計を追加（コスト計算と連携） |
| **timestamp 固定ファイル名** | ❌ MISSING | `--timestamp` 未実装（CLAUDE.md §8.3 想定と不一致）。`generate_output_filename` のみ | `--timestamp` を追加し、既定は固定ファイル名／指定時のみ日時サフィックス |
| **チャンキング既定モデル** | ✅ DONE | `chunks_all_async`/CLI 既定が旧 `gemini-3.5-flash`（実在しない名称）だった | 全 CLI（chunking/make_qa/make_qa_register_qdrant）の `--model` 既定を `gemini-2.5-flash` に統一済み |

> **除外（偽陽性）**: prompt caching（`cache_control`）は Anthropic 固有 API のため移植対象外。

---

## Phase F — ヘルパー・横断（`helper/`）

| 項目 | 状態 | 根拠 | 作業 |
|---|---|---|---|
| **F1** トークンアキュムレータ | ❌ MISSING | `helper_llm.py` に `_token_accumulator`/`reset_token_counter`/`get_token_counter` が**完全に不在**（`count_tokens` 単発のみ） | provider 中立のトークン集計を移植し、`grace/executor`・`celery_tasks`・`qa_generation/pipeline` のステップ別集計に配線。※gemini の `usage_metadata` との整合を要確認 |
| **F2** output_name パラメータ | ❌ MISSING（軽微） | `helper_rag.save_files_to_output(...)`（`:343`）はファイル名 `preprocessed_{type}` 固定 | `output_name=None` 引数を追加し出力ファイル名プレフィックスを可変化 |
| **F3** ToolUseResponse / TypeVar | ⚪ 任意・低優先 | `generate_structured` は素の `BaseModel` 返却。`ToolUseResponse`/`TypeVar` 無し | gemini の戻り値形状として現状で正。型一貫性向上の任意改善（必須ではない） |

---

## Phase G — 不足ファイル・整合性整理

| 項目 | 状態 | 根拠 | 作業 |
|---|---|---|---|
| **G1** `qdrant_delete_collection.py` | ❌ MISSING（低優先） | コレクション削除 CLI 無し（`qdrant_client_wrapper`/`services` 内部の `delete_collection` のみ）。gemini は `a35_qdrant_truncate.py` も無い | 削除 CLI を移植（コレクション名は `*_gemini`） |
| **G2** `ui/pages/benchmark_page.py` | ❌ MISSING | `ui/pages/`（9 ページ）にベンチマークページ無し。`grace/benchmark.py`＋`run_benchmark.sh` の CLI のみ | ベンチマーク UI ページを移植（provider 固有コード無し・config 自動ロード） |
| **G3** モデル名統一 | ⚠️ 要ユーザー確認 | **既定名が不整合**: `config.py:40` = `gemini-2.5-flash`、`config.py:429` = `gemini-2.5-flash`（実在せず）、`GeminiClient` 既定 = `gemini-2.5-flash`、UI ハードコード（`qdrant_search_page.py:435` 等）/`token_service.py`/`helper_rag_qa.py` に `gemini-2.0-flash` 残存。一方 `grace/config.py:58`/`qa_service.py:92`/`config_service.py:127` は `gemini-2.5-flash` で正 | 残存箇所を **`gemini-2.5-flash` に統一**＋`GEMINI_API_KEY` フォールバック追加。※モデル名変更のため**着手前にユーザー確認**（CLAUDE.md モデル名規約に配慮） |
| **G4** 未使用 import 整理 | ⚪ 低優先 | ruff `F401` 208 件＋`F541` 90 件（自動修正可 293/300） | `ruff check . --fix --select F401,F541` で整理 |

> **除外（偽陽性）**: `services/agent_service.py` のメッセージ再構築は provider 形状差で gap ではない。

---

## Phase H — 推論/出力枠是正（**gemini は適用済み**）

openai/ollama/gemini 各 provider で混入した「出力枠の削り過ぎ」リグレッション対策。
**gemini は PR #20 相当で既に反映済み**（本調査で確認）。

| # | 種別 | 状態 | 確認結果 |
|---|---|---|---|
| **H1** | fix | ✅ DONE/N-A | `GeminiClient`（`helper_llm.py:150`）は `temperature` を渡された時のみ条件付与（強制注入せず）。AFC 無効化で空応答回避。推論モデル特有の temperature drop は gemini では不要 |
| **H2** | fix | ✅ DONE | `confidence.py` 出力枠 = 512（`:383,:621`）/1024（`:469`）。`executor.py:817` `_evaluate_rag_relevance` = 256、空応答時 `return True` 安全網あり（`:826-828`、例外時 `:837`）。`max_output_tokens` 使用で gemini 整合 |
| **H3** | test | ✅ DONE | `tests/grace/test_executor.py` `TestExecutor`（`:92`）は autouse fixture `_stub_rag_relevance`（`:99-109`）で `_evaluate_rag_relevance` をスタブし密閉化済み |

> Phase H は**新規作業なし**。横展開の整合確認のみ（baseline と一致）。

---

## 検証

- **静的**: 各 PR 単位で `ruff check .` ＋ `python -m compileall` を緑に。
- **実機（要サービス）**: 並列検索のスレッド安全性、二層計画の閾値、Celery 完了順／逐次永続化、
  登録メタデータ round-trip は **実 LLM(Gemini)/Qdrant/Redis 環境での pytest** を推奨（env ゲート）。

---

## 進捗チェックリスト

### Phase A — grace/（中核未移植・最優先）
- [x] #56 eval 撤去 → ast.literal_eval（**セキュリティ最優先**）✅ executor.py（両経路を _handle_ask_user_response に統合・空スタブも解消）
- [x] #58 PlannerConfig/ExecutorConfig（足場）✅ grace/config.py
- [x] #57 _run_tool_with_timeout ✅ grace/executor.py（ThreadPoolExecutor で timeout_seconds 強制）
- [x] #60 _prefetch_parallel_searches ✅ grace/executor.py（同一ウェーブ検索の並列先読み・ExecutorConfig.parallel_search 実利用）
- [x] #61 二層計画（_create_rule_based_plan）✅ grace/planner.py（heuristic complexity<0.7＋非マーカーで LLM 省略）
- [x] #64 _should_trigger_replan（検索ステップ限定）✅ grace/executor.py（両経路のゲート置換）
- [x] #65 evaluate_final（FinalEvaluationResult）✅ confidence.py＋executor 配線（最終評価 2→1 LLM 呼び出し統合）
- [x] #66 _build_confidence_factors 共通化 ✅ grace/executor.py（インライン構築をヘルパー抽出）
- [x] #59 実行ループ統合（execute_plan を generator ドレインの薄いラッパー化）✅ grace/executor.py（二重ループ解消）

### Phase B — 登録・Q/A・パイプライン
- [x] #55 make_qa_register_qdrant 死にフラグ＋--combine-rows 撤去 ✅ combine_rows_to_chunks 関数・argparse(--combine-rows/--block-size)・分岐ロジック・docstring/使用例を一掃。チャンキングは chunking/csv_text_to_chunks_text_csv.py へ一本化
- [x] #54 make_qa.py スマート生成フラグ撤去 ✅ qa_qdrant/make_qa.py
- [x] #52 単段化（SmartQAResult/SmartQAPair・構造化出力 1 回）＋use_smart_generation 撤去 ✅ smart_qa_generator.py/pipeline.py/celery_tasks.py/make_qa_register_qdrant.py
- [x] #51 内容ハッシュ ID ＋重複除去＋先読み並列化（3 部）✅ (a) qdrant_service.py に stable_point_id/_content_point_key/_normalize_for_id・provenance(chunk_id/topic/doc_id)・migrate path も決定的ID化、(b) register_to_qdrant.py に重複テキスト除去ブロック、(c) ThreadPoolExecutor 先読みパイプライン＋--embed-workers＋登録後検証。round-trip テスト 8 件追加（tests/services/test_qdrant_service.py::TestContentBasedPointId）
- [x] #67 collect_results 完了順＋on_result＋_GENERATOR_CACHE ✅ ready() ポーリングで完了順回収（HOL解消）・on_result/usage_out フック・ワーカー dict戻り値・_get_generator プロセス内キャッシュ。テスト 4件追加（tests/test_collect_results.py）。注: gemini はトークンカウンタ未配線のため usage は plumbing のみ（0集計）
- [x] #53 JSONL 逐次永続化＋クラッシュ再開 ✅ pipeline に _progress_path/_load_progress/_append_progress/_clear_progress。generate_qa で再開（done_ids skip＋復元）、_generate_sync で逐次追記、_generate_with_celery で #67 on_result=_persist 配線、run() 成功後に _clear_progress。テスト 4件
- [x] #53派生 _enforce_max_chunk_tokens を chunking へ移植 ✅ chunking/csv_text_to_chunks_text_csv.py に MAX_CHUNK_TOKENS/EMBEDDING_INPUT_TOKEN_LIMIT/_count_tokens/_split_oversized_text/_enforce_max_chunk_tokens（gemini は List[str] 版）を追加し、chunks_all_async の step3 後に強制適用。テスト 5件（tests/chunking/test_max_chunk_tokens.py）
- [x] #82 get_collection_embedding_params（DONE 相当）

### Phase C — テスト（整備済・追従中心）
- [x] grace/services/qa_generation/helpers の基本スイート（既存）
- [x] 移植漏れテスト追従（keyword_extraction 等・前セッション）
- [ ] tests/chunking/ 新規作成（Phase E 実装後）
- [ ] tests/legacy・root 散在スクリプト整理
- [ ] Phase A/B 実装に追従したテスト追補

### Phase D — 基盤・ドキュメント
- [ ] .github/workflows/ci.yml 作成（ruff + compileall + pytest + claude/* auto-merge）
- [ ] CLAUDE.md §7/§8/§9 追加（gemini 用に読み替え）※G3 と連動・要確認
- [ ] requirements.txt（uv export）整理確認

### Phase E — チャンキング（全 MISSING）
- [ ] E1 Embedding 上限連携（_enforce_max_chunk_tokens／--max-chunk-tokens）
- [ ] E2 ルールベース継続判定（--continuity-mode／_rule_based_continuity）
- [ ] E3 doc_id トレーシング
- [ ] E4 async_api_client トークン使用量集計
- [ ] timestamp 固定ファイル名（--timestamp）
- [ ] チャンキング既定モデル gemini-2.5-flash → gemini-2.5-flash（G3 連動）

### Phase F — ヘルパー・横断
- [ ] F1 トークンアキュムレータ（reset/get_token_counter＋executor/celery/pipeline 配線）
- [ ] F2 save_files_to_output(output_name=...)
- [ ] F3 ToolUseResponse/TypeVar（任意・低優先・スキップ判断可）

### Phase G — 不足ファイル・整合性整理
- [ ] G1 qdrant_delete_collection.py 移植
- [ ] G2 ui/pages/benchmark_page.py 移植
- [x] G3 モデル名統一（実在しない gemini-2.5-flash/gemini-2.5-flash 既定を撤去・旧既定 gemini-2.0-flash → gemini-2.5-flash）＋GEMINI_API_KEY フォールバック ✅ config.py/helper_llm.py/helper_embedding.py/helper_rag_qa.py/services/ui（実在する catalog 項目は保持）
- [ ] G4 未使用 import 整理（ruff F401 208・F541 90）

### Phase H — 推論/出力枠是正（適用済・作業なし）
- [x] H1 GeminiClient temperature 条件付与（強制注入なし）
- [x] H2 confidence/relevance 出力枠（512/1024・relevance 256・空応答安全網）
- [x] H3 TestExecutor 密閉化（_evaluate_rag_relevance スタブ）

---

## openai プレイブックとの差分サマリ（gemini 固有事情）

| 観点 | openai（雛形） | **gemini（本プロジェクト）** |
|---|---|---|
| Phase A grace 中核 | 全て実装済（チェック済） | **✅ 全9項目移植完了**（#56〜#67・2026-06-15 本セッション） |
| Phase B パイプライン | 実装済 | **未移植**（2 段生成・blocking Celery・逐次登録のまま） |
| Phase C テスト | ほぼゼロから移植 | **既に整備済**（追従・整理が中心） |
| Phase H 出力枠 | PR #25 で対応 | **既に適用済**（作業なし） |
| モデル名整合 | gpt-5-mini へ統一 | `gemini-2.5-flash`/`gemini-2.5-flash`/`gemini-2.0-flash` が混在し**より深刻** |
| CLAUDE.md 規約 | §7/§8/§9 整備済 | **未整備（汎用テンプレートのまま）** |

**進捗**: Phase A（GRACE エージェント本体）は **2026-06-15 に全9項目（#56/#57/#58/#59/#61/
#64/#65/#66/#60）を移植完了**（全コミット push 済み・`tests/` 404 passed / 8 skipped）。
残るは **Phase B（Q/A パイプライン近代化）→ E/F（chunking/helper）→ G/D（不足ファイル・
モデル名統一 G3・CLAUDE.md 規約）**。次の推奨着手は #55→#54→#52→#51→#67→#53。

---

*作成日: 2026-06-15*

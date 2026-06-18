# 付録: anthropic_grace_agent v1→v2 ファイル差分一覧

**Version 1.0** | 最終更新: 2026-06-18 | 生成元: `git ls-files` 比較（生成物・データ・バイナリ・`.git`/`.idea` 除外）

> 本付録は機械抽出した事実ベースの差分一覧です。解釈・テーマ別解説は
> `docs/anthropic_v1_to_v2_refactoring.md`（本体）を参照してください。

## 1. サマリ
- v1 tracked: 7784 / v2 tracked: 7732（大半は生成物・データ）。
- **コード（共通 `.py`）126 ファイル中 77 が内容差分**。
- v2 新規の主モジュール: `grace/llm_compat.py`・`grace/calibration.py`・`grace/memory.py`・
  `eval/{run_eval,metrics,build_dataset,calibrate,ab_compare}.py`。

## 2. 追加（v2 のみ・コード/設定/doc）

### 2.1 新規コード
| ファイル | 役割 |
|---|---|
| `grace/llm_compat.py` | google-genai 互換の Anthropic アダプタ（`create_chat_client`） |
| `grace/calibration.py` | S1: confidence の温度スケーリング較正（`Calibrator`） |
| `grace/memory.py` | P4: 実行メモリ層（コレクション事前分布の学習） |
| `eval/run_eval.py` / `metrics.py` / `build_dataset.py` | S0: 評価ハーネス（accuracy/ECE/hallucination 等） |
| `eval/calibrate.py` | S1: 温度較正パラメータの算出・保存 |
| `eval/ab_compare.py` | react_enabled の A/B 測定 |

### 2.2 新規テスト
`tests/grace/{test_calibration,test_code_execute,test_groundedness,test_intervention_blocking,test_memory,test_react}.py`,
`tests/eval/test_ab_compare.py`, `tests/chunking/test_max_chunk_tokens.py`,
`tests/qa_generation/{test_content,test_keyword_extraction,test_pipeline_persistence,test_smart_qa_usage,test_structure}.py`,
`tests/{test_collect_results,test_make_qa_register_qdrant_csv_fixed}.py`, `tests/README.md`。

### 2.3 新規ドキュメント・規約
- `.claude/skills/{grace-agent-ci,grace-agent-docs,grace-agent-tests}/SKILL.md` ＋
  `a_class_method_md_format.md`・`a_pages_md_format.md`・`a_test_md_format.md`（v1 ではトップレベルにあった書式仕様をスキル同梱化）。
- `eval/README.md`, `grace/doc/{calibration,grace_process,llm_compat,planner_executor,react_reasoning,step_process}.md`,
  `services/doc/*.md`（11モジュール）, `qa_qdrant/doc/qdrant_delete_collection.md`,
  `docs/archive/*`（旧 migration/benchmark 文書のアーカイブ）, `docs/v1_to_v2_refactoring_doc_todo.md`。

## 3. 削除/移動（v1 のみ）
- 書式仕様のトップレベル版: `a_class_method_md_format.md`・`a_pages_md_format.md`・`a_test_md_format.md`・`a_memo_dev.txt` →（`.claude/skills/` へ移動）。
- `static/`・`run_benchmark_all.sh`・`ui/pages/benchmark_page.py`（ベンチ UI）。
- 旧 doc 群: `docs/{API_migration,agent_rag_api,benchmark,benchmark_files,benchmark_todo,plan_for_migration_v2,qdrant_api,reasoning_model_token_budget_fix_june14}.md`,
  `grace/check_code/*`, `grace/doc/old/*`・`grace/doc/{grace_agent_rag,pipeline_refactor,react_pattern}.md`,
  `chunking/doc/old/*`・`chunking/doc/{01_howto_chunking_memo,step123}.md`, `qa_generation/doc/{data_io,models,qa_generation}.md`。
- 旧テスト: `tests/chunking/test_document_chunking.py`, `tests/qa_generation/test_smart_qa_and_persistence.py`, `tests/test_qdrant_service_metadata.py`。
- 環境: `.envrc`・`.python-version`。

## 4. 変更（共通ファイル・変更行数 上位）

| ファイル | +追加 | -削除 | 主因（→本体テーマ） |
|---|---:|---:|---|
| `grace/executor.py` | 934 | 353 | T7 ハイブリッド ReAct / T6 較正連携 / 介入・dict config |
| `chunking/csv_text_to_chunks_text_csv.py` | 330 | 653 | チャンキング刷新（文書境界・manifest） |
| `grace/tools.py` | 276 | 140 | T9 code_execute / dict config / sparse degrade |
| `grace/confidence.py` | 274 | 328 | T6 groundedness / dict config |
| `grace/planner.py` | 266 | 139 | T7 メモリ反映 / dict config / legacy 削除 |
| `qa_qdrant/make_qa_register_qdrant.py` | 265 | 180 | パイプライン刷新 |
| `services/agent_service.py` | 176 | 222 | レガシー ReActAgent 整理 |
| `pyproject.toml` | 160 | 192 | 依存・pytest 設定 |
| `helper/helper_llm.py` | 152 | 587 | **T1 LLM クライアント層の簡素化** |
| `config/grace_config.yml` | 113 | 11 | 既定・較正設定 |
| `grace/config.py` | 63 | 27 | embedding=gemini / 較正設定 / memory・code_execute 設定 |
| `grace/schemas.py` | 61 | 3 | action 追加（code_execute 等） |
| `config.yml` | 39 | 167 | モデル一覧の Anthropic 化 |
| `.github/workflows/ci.yml` | 44 | 33 | pytest ジョブ追加・依存導入 |

（全 77 差分のうち主要分を抜粋。完全な一覧は `git ls-files` 比較で随時再生成可能。）

## 5. 変更履歴
| バージョン | 変更内容 |
|---|---|
| 1.0 | 初版（フェーズA 機械抽出結果）作成（2026-06-18） |

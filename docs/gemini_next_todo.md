# gemini_grace_agent 今後の作業 TODO（2026-06-15 起票）

Phase A/B（#51–#67）・`_enforce_max_chunk_tokens` 移植・`tests/README.md`・テスト衛生修正の完了後、
テストスイートは **438 passed / 4 skipped / 0 warnings**（macOS / Python 3.12, 実 `.env`・Qdrant 稼働）で
グリーン。残課題を以下に整理する。

凡例: ★最優先 / ◎高 / ○中 / △低

---

## A. 実環境 E2E 検証 ★最優先（要ユーザー環境）

今セッションの実装はすべて `unittest.mock` での検証。実依存（API キー・Qdrant・Celery+Redis）での
動作確認が最大の残課題。**実行手順書: [`docs/gemini_e2e_verification.md`](./gemini_e2e_verification.md)**（A-1〜A-5 のコマンド・受け入れ基準・記録テンプレート）。

| # | 項目 | 検証内容 | 受け入れ基準 |
|---|---|---|---|
| A-1 | 実 Gemini API で Q/A 生成 | `SmartQAGenerator` 単段化（`response_schema` 1回呼び出し, #52）の品質 | チャンクから妥当な Q/A が `qa_count` どおり生成 |
| A-2 | 実 Qdrant 再登録の冪等性 | 内容ハッシュ point ID（#51）。同一CSVを `--recreate` なしで2回登録 | 件数が増えない。「登録後検証」ログで件数一致 |
| A-3 | 並列登録スループット | `--embed-workers` の先読みパイプライン（#51c） | 直列比で短縮・エラーなし |
| A-4 | 実 Celery+Redis | `collect_results` 完了順回収・`_GENERATOR_CACHE`（#67） | 遅いタスクが後続を塞がない／worker 再利用 |
| A-5 | pipeline JSONL 再開 | 途中中断→再実行で `qa_progress_*.jsonl` から復帰（#53） | 処理済みチャンクが skip され重複生成しない |

> Claude のサンドボックスは API キー無し・Qdrant/Redis 未起動・モデル/tiktoken DL 制限のため未実施。

---

## B. 機能の仕上げ ◎高〜○中

| # | 項目 | 内容 | 優先 |
|---|---|---|---|
| ~~B-1~~ ✅ | **トークン使用量の配線（完了）** | `smart_qa_generator` が `response.usage_metadata` を捕捉→`process_chunk['usage']`→celery worker 戻り値→`collect_results(usage_out)` / `_generate_sync` 集計→ログ出力。テスト 3件（`test_smart_qa_usage.py`）。実 API での実数確認は A-1 に含む | 完了 |
| ~~B-2~~ ✅ | スキップ4件の整理（完了） | `test_generation.py`（モジュール全体 dead）と `test_qdrant_service_metadata.py`（冗長 wish テスト）を削除。`test_content.py`・`test_metadata_and_full_process.py` の skip スタブ/メソッドを除去（未使用 import も整理）。スキップ 4件→0件 | 完了 |
| ~~B-3~~ ✅ | 旧モデル名の置換（完了） | `test_agent_service_paris_income.py` の `GEMINI_MODEL_NAME` 既定を `gemini-2.0-flash-exp`→`gemini-2.5-flash` | 完了 |

---

## C. テスト / CI 整備 ◎高〜○中

| # | 項目 | 内容 | 優先 |
|---|---|---|---|
| ~~C-1~~ ✅ | **CI ワークフロー追加（完了）** | `.github/workflows/ci.yml`。push(master)/PR で `uv sync --extra dev && pytest tests/` を Python 3.11/3.12 で実行。ruff は非ブロッキング。GitHub Actions 上で pytest 3.11/3.12 success を確認済み | 完了 |
| C-2 | 環境依存テストのガード強化 | `config_service`/`.env` を読むテストは `get_config` モック or `clear=True` を徹底。integration テストの skipif を placeholder 除外（`_has_real_gemini_key` 方式）に統一し CI を確定的に | ○中 |

---

## D. ドキュメント / 横展開 △低

| # | 項目 | 内容 |
|---|---|---|
| D-1 | 運用手順の反映 | `readme_*` / `tests/README.md` に、単段化・内容ハッシュ登録・`--embed-workers`・JSONL 再開の運用手順を追記 |
| D-2 | playbook 横展開 | 同型の `ollama_grace_agent` への #51–#67 相当移植が未完なら横展開（別リポジトリ・要スコープ確認） |

---

## 推奨着手順
1. **C-1（CI 追加）** … 恒久的な品質ゲート。すぐ着手可
2. **B-1（トークン配線）** … コスト可視化。コードのみで完結
3. **A 群（実環境 E2E）** … ユーザー環境が必要。手順書を用意
4. **B-2/B-3・D** … 掃除・整理

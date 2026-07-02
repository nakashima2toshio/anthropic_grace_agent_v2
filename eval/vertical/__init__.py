# eval/vertical — 業界特化（VerticalProfile）KPI 評価ハーネス
"""業界特化 KPI 評価ハーネス。

期待ラベル付きテスト質問（`cases/*.jsonl`・5 カテゴリ）で GRACE-Support の
分岐（answer/escalate・アクション・強制エスカレ・本人確認）を自動計測する。
メトリクスは LLM ジャッジ不要の決定的な定義（`metrics.py`）。

設計: docs/vertical_spec_review.md §6 ／ テストデータ: docs/vertical_test_data.md §4
実行: `uv run python -m eval.vertical.run --vertical gov`
"""

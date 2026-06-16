"""GRACE 評価ハーネス（S0）。

正解付き Q&A セットに対して現行 GRACE を回し、
正解率・幻覚率・平均 confidence・較正誤差(ECE)・コスト・レイテンシを測定する。

依存順 S0 → S1 → S3 の S0。詳細は docs/grace_react_refactor_todo.md を参照。
"""

__all__ = ["build_dataset", "metrics", "run_eval"]

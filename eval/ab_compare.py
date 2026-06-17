"""A/B 測定ハーネス: `executor.react_enabled` の ON/OFF を比較する。

同一データセット・同一ジャッジで `eval.run_eval.run` を2回実行し、
- static  : react_enabled=False（静的 Plan-Execute）
- react   : react_enabled=True （観測駆動 ReAct ループ）
のレポート（accuracy / ECE / hallucination / latency / cost）を読み比べ、
差分テーブルと統合 JSON を出力する。

DoD: react_enabled の true/false で正解率・ECE を A/B 比較できる（doc §S3 検証）。

使い方:
    python -m eval.ab_compare \
        --dataset eval/dataset.jsonl --limit 20 \
        --collection cc_news_2per_anthropic \
        --output-dir logs/ab

前提（run_eval と同じ）:
    - Qdrant が稼働している
    - ANTHROPIC_API_KEY が設定されている
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

from eval.run_eval import run
from grace.config import get_config

# (variant 名, react_enabled)
VARIANTS: list[tuple[str, bool]] = [("static", False), ("react", True)]

# (表示名, summary キー, lower_is_better)  ※ None は方向性なし（参考値）
_METRIC_SPEC: list[tuple[str, str, Optional[bool]]] = [
    ("samples", "n", None),
    ("accuracy", "accuracy", False),
    ("hallucination_rate", "hallucination_rate", True),
    ("mean_confidence", "mean_confidence", None),
    ("ECE(raw)", "ece", True),
    ("ECE(calibrated)", "ece_calibrated", True),
    ("mean_latency_ms", "mean_latency_ms", True),
    ("total_cost_usd", "total_cost_usd", True),
]


def build_comparison(static: dict[str, Any], react: dict[str, Any]) -> list[dict[str, Any]]:
    """static / react の summary から比較行リストを作る（純粋関数）。

    各行: {metric, static, react, delta(react-static), improved(bool|None)}。
    improved は lower_is_better を加味した「react が static より良いか」。
    """
    rows: list[dict[str, Any]] = []
    for label, key, lower_better in _METRIC_SPEC:
        sv = static.get(key)
        rv = react.get(key)
        delta = None
        improved = None
        if isinstance(sv, (int, float)) and isinstance(rv, (int, float)):
            delta = rv - sv
            if lower_better is not None and delta != 0:
                improved = (delta < 0) if lower_better else (delta > 0)
            elif lower_better is not None:
                improved = None  # 変化なし
        rows.append({
            "metric": label, "key": key,
            "static": sv, "react": rv,
            "delta": delta, "improved": improved,
        })
    return rows


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def format_table(comparison: list[dict[str, Any]]) -> str:
    """比較行を整形テーブル文字列にする（純粋関数）。"""
    header = f"{'metric':<20}{'static':>12}{'react':>12}{'delta':>12}{'better':>9}"
    lines = ["=" * 65, header, "-" * 65]
    for row in comparison:
        better = row["improved"]
        better_s = "=" if better is None else ("react" if better else "static")
        lines.append(
            f"{row['metric']:<20}{_fmt(row['static']):>12}"
            f"{_fmt(row['react']):>12}{_fmt(row['delta']):>12}{better_s:>9}"
        )
    lines.append("=" * 65)
    return "\n".join(lines)


def _run_variant(name: str, react_enabled: bool, args: argparse.Namespace) -> dict[str, Any]:
    """1 variant 分の評価を実行し、summary dict を返す。"""
    cfg = get_config()
    cfg.executor.react_enabled = react_enabled
    if args.threshold is not None:
        cfg.executor.react_complexity_threshold = args.threshold

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = str(out_dir / f"eval_{name}.json")

    print(f"\n{'#' * 64}")
    print(f"# variant={name}  react_enabled={react_enabled}  "
          f"threshold={getattr(cfg.executor, 'react_complexity_threshold', '-')}")
    print(f"{'#' * 64}")

    rc = run(args.dataset, args.limit, args.model, args.judge_model,
             report_path, collection=(args.collection or None))
    if rc != 0:
        raise RuntimeError(f"variant {name} の評価に失敗しました (rc={rc})")

    with Path(report_path).open(encoding="utf-8") as f:
        return json.load(f)["summary"]


def run_ab(args: argparse.Namespace) -> dict[str, Any]:
    """A/B 全体を実行し、統合結果 dict を返す。"""
    summaries: dict[str, dict[str, Any]] = {}
    for name, flag in VARIANTS:
        summaries[name] = _run_variant(name, flag, args)

    comparison = build_comparison(summaries["static"], summaries["react"])
    table = format_table(comparison)
    print("\n" + table)

    result = {
        "static": summaries["static"],
        "react": summaries["react"],
        "comparison": comparison,
    }
    combined = Path(args.output_dir) / "ab_summary.json"
    with combined.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n統合レポート保存: {combined}")
    return result


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="GRACE A/B 評価（executor.react_enabled の ON/OFF 比較）")
    p.add_argument("--dataset", default="eval/dataset.jsonl")
    p.add_argument("--limit", type=int, default=0, help="先頭 N 件のみ（0 で全件）")
    p.add_argument("--model", default=None, help="GRACE 本体の LLM モデル（既定は config）")
    p.add_argument("--judge-model", default="claude-haiku-4-5-20251001",
                   help="ジャッジ用 LLM モデル")
    p.add_argument("--collection", default="cc_news_2per_anthropic",
                   help="rag_search を固定するコレクション。空文字で全コレクション総当たり")
    p.add_argument("--threshold", type=float, default=None,
                   help="react_complexity_threshold の上書き（省略時は config 値）")
    p.add_argument("--output-dir", default="logs/ab",
                   help="各 variant レポートと統合 JSON の出力先")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_ab(args)
    except Exception as exc:
        print(f"ERROR: A/B 評価に失敗しました: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""S1 較正ツール — run_eval のレポートから温度 T を推定して保存する。

run_eval が出力した JSON レポート（`details[].confidence` と
`details[].verdict`）を読み、温度スケーリングの T を NLL 最小化で推定し、
`config/calibration.json` に保存する。較正前後の ECE も表示する。

DoD（doc §S1）: S0 の ECE がベースラインより改善。
本ツールで fit した T を保存すると、GRACE 本体（executor）が実行時に
overall_confidence へ適用し、以降の評価で ECE 改善を確認できる。

使い方:
    # まずベースラインを測定（run_eval がレポートを出力）
    python -m eval.run_eval --report logs/eval_baseline.json
    # そのレポートから T を推定し config/calibration.json に保存
    python -m eval.calibrate --report logs/eval_baseline.json \
        --output config/calibration.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from grace.calibration import Calibrator, expected_calibration_error


def _load_pairs(report_path: str) -> tuple[list[float], list[bool]]:
    """レポート JSON から (confidence, 正誤) のペアを取り出す。

    正誤は verdict=="correct" を True とする（run_eval と同じ定義）。
    """
    with Path(report_path).open(encoding="utf-8") as f:
        data = json.load(f)
    details = data.get("details", [])
    confidences: list[float] = []
    correctness: list[bool] = []
    for d in details:
        if "confidence" not in d:
            continue
        confidences.append(float(d["confidence"]))
        correctness.append(str(d.get("verdict", "")) == "correct")
    return confidences, correctness


def run(report: str, output: str) -> int:
    confidences, correctness = _load_pairs(report)
    if not confidences:
        print(f"ERROR: レポートに confidence 付きの details がありません: {report}",
              file=sys.stderr)
        return 1

    ece_before = expected_calibration_error(confidences, correctness)
    calibrator = Calibrator.fit(confidences, correctness)
    cal_confs = [calibrator.transform(c) for c in confidences]
    ece_after = expected_calibration_error(cal_confs, correctness)

    calibrator.save(output)

    n = len(confidences)
    acc = sum(1 for y in correctness if y) / n
    mean_conf = sum(confidences) / n
    print("=" * 52)
    print(f"{'samples':<28}{n:>24d}")
    print(f"{'accuracy':<28}{acc:>24.3f}")
    print(f"{'mean_confidence':<28}{mean_conf:>24.3f}")
    print(f"{'temperature (fitted)':<28}{calibrator.temperature:>24.4f}")
    print(f"{'ECE before':<28}{ece_before:>24.4f}")
    print(f"{'ECE after':<28}{ece_after:>24.4f}")
    print(f"{'ECE improvement':<28}{ece_before - ece_after:>24.4f}")
    print("=" * 52)
    print(f"較正パラメータ保存: {output}")
    if ece_after > ece_before + 1e-9:
        print("⚠ 較正後 ECE が悪化しました（データ件数が少ない可能性）", file=sys.stderr)
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GRACE S1 confidence calibration")
    p.add_argument("--report", default="logs/eval_baseline.json",
                   help="run_eval が出力した JSON レポート")
    p.add_argument("--output", default="config/calibration.json",
                   help="較正パラメータの保存先")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args.report, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

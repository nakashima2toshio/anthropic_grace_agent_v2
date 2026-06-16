"""評価メトリクス算出。

- accuracy（正解率）
- hallucination_rate（幻覚率＝幻覚と判定された割合）
- mean_confidence（平均 confidence）
- ECE（Expected Calibration Error / 較正誤差）

ECE は「confidence と実正解率のズレ」。等幅ビンで
    ECE = Σ_b (n_b / N) * | acc_b - conf_b |
として算出する（doc §S0, eval/metrics.py の DoD）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class EvalRecord:
    """1問あたりの評価結果。"""
    id: object
    question: str
    confidence: float
    correct: bool
    hallucinated: bool
    verdict: str = ""           # "correct" | "partial" | "incorrect"
    latency_ms: float | None = None
    cost_usd: float | None = None
    status: str = ""


@dataclass
class MetricsReport:
    n: int
    accuracy: float
    hallucination_rate: float
    mean_confidence: float
    ece: float
    mean_latency_ms: float | None
    total_cost_usd: float | None
    bins: list[dict] = field(default_factory=list)

    def as_table(self) -> str:
        lines = [
            "=" * 48,
            f"{'metric':<24}{'value':>20}",
            "-" * 48,
            f"{'samples':<24}{self.n:>20d}",
            f"{'accuracy':<24}{self.accuracy:>20.3f}",
            f"{'hallucination_rate':<24}{self.hallucination_rate:>20.3f}",
            f"{'mean_confidence':<24}{self.mean_confidence:>20.3f}",
            f"{'ECE':<24}{self.ece:>20.3f}",
        ]
        if self.mean_latency_ms is not None:
            lines.append(f"{'mean_latency_ms':<24}{self.mean_latency_ms:>20.1f}")
        if self.total_cost_usd is not None:
            lines.append(f"{'total_cost_usd':<24}{self.total_cost_usd:>20.4f}")
        lines.append("=" * 48)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "accuracy": self.accuracy,
            "hallucination_rate": self.hallucination_rate,
            "mean_confidence": self.mean_confidence,
            "ece": self.ece,
            "mean_latency_ms": self.mean_latency_ms,
            "total_cost_usd": self.total_cost_usd,
            "bins": self.bins,
        }


def expected_calibration_error(
    confidences: Sequence[float],
    correctness: Sequence[bool],
    n_bins: int = 10,
) -> tuple[float, list[dict]]:
    """ECE と各ビンの内訳を返す。"""
    if not confidences:
        return 0.0, []
    n = len(confidences)
    bins: list[dict] = []
    ece = 0.0
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        # 最終ビンは上端を含む
        idx = [
            j for j, c in enumerate(confidences)
            if (c > lo or (i == 0 and c >= lo)) and (c <= hi if i < n_bins - 1 else c <= hi + 1e-9)
        ]
        if not idx:
            continue
        conf_b = sum(confidences[j] for j in idx) / len(idx)
        acc_b = sum(1 for j in idx if correctness[j]) / len(idx)
        weight = len(idx) / n
        ece += weight * abs(acc_b - conf_b)
        bins.append({
            "range": [round(lo, 3), round(hi, 3)],
            "count": len(idx),
            "confidence": round(conf_b, 4),
            "accuracy": round(acc_b, 4),
            "gap": round(abs(acc_b - conf_b), 4),
        })
    return ece, bins


def compute(records: Sequence[EvalRecord], n_bins: int = 10) -> MetricsReport:
    n = len(records)
    if n == 0:
        return MetricsReport(0, 0.0, 0.0, 0.0, 0.0, None, None, [])

    confidences = [float(r.confidence) for r in records]
    correctness = [bool(r.correct) for r in records]

    accuracy = sum(correctness) / n
    hallucination_rate = sum(1 for r in records if r.hallucinated) / n
    mean_confidence = sum(confidences) / n
    ece, bins = expected_calibration_error(confidences, correctness, n_bins=n_bins)

    latencies = [r.latency_ms for r in records if r.latency_ms is not None]
    mean_latency = (sum(latencies) / len(latencies)) if latencies else None
    costs = [r.cost_usd for r in records if r.cost_usd is not None]
    total_cost = sum(costs) if costs else None

    return MetricsReport(
        n=n,
        accuracy=accuracy,
        hallucination_rate=hallucination_rate,
        mean_confidence=mean_confidence,
        ece=ece,
        mean_latency_ms=mean_latency,
        total_cost_usd=total_cost,
        bins=bins,
    )

# eval/vertical/metrics.py
"""業界特化 KPI メトリクス算出（決定的・LLM ジャッジ不要）。

設計書の抽象的な KPI（「誤案内 = 0」「出典付与率 ≈ 100%」等）を、
`SupportResult` から決定的に計測できる操作的定義へ落とし込む。
定義の根拠: docs/vertical_spec_review.md §6.2。

- decision_accuracy       : `decision == expected_decision` の割合（全体・カテゴリ別）
- false_escalate_rate     : in-scope＋keyword-trap のうち escalate になった割合（低いほど良い）
- forced_escalate_misfire : in-scope＋keyword-trap のうち**強制エスカレ**が発火した割合（0 目標）
- escalate_recall         : out-of-scope＋escalate-keyword のうち escalate になった割合（1.0 目標）
- citation_rate           : answer のうち出典 1 件以上の割合（1.0 目標）
- ungrounded_answer_rate  : answer のうち**判定可能（decided>0）かつ**支持率 < confirm_th の
                            割合（0 目標＝「根拠なし回答 = 0」）。Groundedness 検証が Q&A 形式
                            ソース等で全主張 neutral（decided=0）に倒れたケースは「根拠なし」
                            ではなく「判定不能」であり、分子に含めない
- groundedness_neutral_rate: answer のうち判定不能（decided=0）だった割合（参考値。
                            過大計上の除外分をここで可視化し、silent drop を避ける）
- action_accuracy         : `action_type == expected_action` の割合（None 同士の一致を含む）
- identity_check_rate     : 本人確認を期待するケースで確認ステップが起動した割合（1.0 目標）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# テスト質問の 5 カテゴリ（docs/vertical_test_data.md §4。keyword-trap は誤検知検査用）
CATEGORIES = ("in-scope", "out-of-scope", "action", "escalate-keyword", "keyword-trap")

# 誤エスカレ率の分母（本来 answer できるべきカテゴリ）
_ANSWERABLE = ("in-scope", "keyword-trap")
# エスカレ再現率の分母（escalate すべきカテゴリ）
_MUST_ESCALATE = ("out-of-scope", "escalate-keyword")


@dataclass
class CaseResult:
    """1 ケースの実行結果（`SupportResult` からの抽出）。"""

    case: Dict[str, Any] = field(default_factory=dict)
    decision: Optional[str] = None        # "answer" / "escalate" / None（実行失敗）
    action_type: Optional[str] = None
    citation_count: int = 0
    groundedness: float = 0.0
    groundedness_decided: int = 0     # 判定できた主張数（supported+contradicted）。0=判定不能
    forced_escalate: bool = False
    identity_checked: bool = False
    intent: Optional[str] = None
    latency_ms: float = 0.0
    error: Optional[str] = None


def _rate(numerator: int, denominator: int) -> Optional[float]:
    """割合。分母 0（該当ケースなし）は None を返し、0.0 と区別する。"""
    return (numerator / denominator) if denominator else None


def compute_metrics(results: List[CaseResult], confirm_th: float) -> Dict[str, Any]:
    """ケース実行結果から KPI を集計する。

    Args:
        results: 全ケースの実行結果（error 付きを含む）
        confirm_th: 回答ゲートの confirm しきい値（根拠なし回答率の判定基準）
    Returns:
        メトリクス dict（分母 0 の指標は None）
    """
    ok = [r for r in results if r.error is None]

    answers = [r for r in ok if r.decision == "answer"]
    answerable = [r for r in ok if r.case.get("category") in _ANSWERABLE]
    must_escalate = [r for r in ok if r.case.get("category") in _MUST_ESCALATE]
    identity_cases = [r for r in ok if r.case.get("expect_identity_check")]

    per_category: Dict[str, Any] = {}
    for cat in CATEGORIES:
        rs = [r for r in ok if r.case.get("category") == cat]
        if not rs:
            continue
        per_category[cat] = {
            "samples": len(rs),
            "decision_accuracy": _rate(
                sum(1 for r in rs if r.decision == r.case.get("expected_decision")), len(rs)
            ),
            "action_accuracy": _rate(
                sum(1 for r in rs
                    if (r.action_type or None) == (r.case.get("expected_action") or None)),
                len(rs),
            ),
        }

    return {
        "samples": len(results),
        "errors": len(results) - len(ok),
        "decision_accuracy": _rate(
            sum(1 for r in ok if r.decision == r.case.get("expected_decision")), len(ok)
        ),
        "false_escalate_rate": _rate(
            sum(1 for r in answerable if r.decision == "escalate"), len(answerable)
        ),
        "forced_escalate_misfire_rate": _rate(
            sum(1 for r in answerable if r.forced_escalate), len(answerable)
        ),
        "escalate_recall": _rate(
            sum(1 for r in must_escalate if r.decision == "escalate"), len(must_escalate)
        ),
        "citation_rate": _rate(
            sum(1 for r in answers if r.citation_count >= 1), len(answers)
        ),
        "ungrounded_answer_rate": _rate(
            sum(1 for r in answers
                if r.groundedness_decided > 0 and r.groundedness < confirm_th),
            len(answers),
        ),
        "groundedness_neutral_rate": _rate(
            sum(1 for r in answers if r.groundedness_decided == 0), len(answers)
        ),
        "action_accuracy": _rate(
            sum(1 for r in ok
                if (r.action_type or None) == (r.case.get("expected_action") or None)),
            len(ok),
        ),
        "identity_check_rate": _rate(
            sum(1 for r in identity_cases if r.identity_checked), len(identity_cases)
        ),
        "mean_latency_ms": (sum(r.latency_ms for r in ok) / len(ok)) if ok else None,
        "per_category": per_category,
    }


def format_table(metrics: Dict[str, Any]) -> str:
    """メトリクスをスコア表（eval/run_eval.py と同形式）に整形する。"""
    rows = [
        ("samples", metrics["samples"]),
        ("errors", metrics["errors"]),
        ("decision_accuracy", metrics["decision_accuracy"]),
        ("false_escalate_rate", metrics["false_escalate_rate"]),
        ("forced_escalate_misfire_rate", metrics["forced_escalate_misfire_rate"]),
        ("escalate_recall", metrics["escalate_recall"]),
        ("citation_rate", metrics["citation_rate"]),
        ("ungrounded_answer_rate", metrics["ungrounded_answer_rate"]),
        ("groundedness_neutral_rate", metrics["groundedness_neutral_rate"]),
        ("action_accuracy", metrics["action_accuracy"]),
        ("identity_check_rate", metrics["identity_check_rate"]),
        ("mean_latency_ms", metrics["mean_latency_ms"]),
    ]
    lines = ["=" * 48, f"{'metric':<32}{'value':>14}", "-" * 48]
    for name, value in rows:
        if value is None:
            text = "-"
        elif isinstance(value, float):
            text = f"{value:.3f}"
        else:
            text = str(value)
        lines.append(f"{name:<32}{text:>14}")
    lines.append("=" * 48)
    for cat, m in metrics.get("per_category", {}).items():
        acc = m["decision_accuracy"]
        act = m["action_accuracy"]
        lines.append(
            f"  {cat:<20} n={m['samples']:<3} "
            f"decision={acc:.2f} action={act:.2f}"
        )
    return "\n".join(lines)

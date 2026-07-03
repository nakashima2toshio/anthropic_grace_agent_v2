# eval/vertical/run.py
"""業界特化 KPI 評価ランナー。

期待ラベル付きテスト質問（cases/<vertical>.jsonl）を `run_support_agent()` に
投入し、分岐一致率・誤エスカレ率・出典付与率・本人確認遵守率などを自動計測する。
アクションは常にドライラン（副作用なし）。

前提: `.env` に ANTHROPIC_API_KEY / GOOGLE_API_KEY、Qdrant 起動済み＋
対象コレクション登録済み（eval/README.md と同じ）。

使い方::

    uv run python -m eval.vertical.run --vertical gov
    uv run python -m eval.vertical.run --vertical ec --limit 3 --report logs/vertical_ec.json
    uv run python -m eval.vertical.run --vertical saas --no-web --show-agent-output
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from agent_support_example import PROFILES, run_support_agent
from eval.vertical.metrics import CaseResult, compute_metrics, format_table
from grace.config import get_config

CASES_DIR = Path(__file__).parent / "cases"


def load_cases(path: Path) -> List[Dict[str, Any]]:
    """JSONL のテストケースを読み込む（空行・`#` 始まりの行は無視）。"""
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases


def run_case(case: Dict[str, Any], use_web: bool, show_output: bool) -> CaseResult:
    """1 ケースを実行して SupportResult から計測値を抽出する。"""
    start = time.time()
    silencer = (
        contextlib.nullcontext() if show_output
        else contextlib.redirect_stdout(io.StringIO())
    )
    try:
        with silencer:
            result = run_support_agent(
                case["query"],
                use_web=use_web,
                do_action=True,
                dry_run=True,  # 評価は常にドライラン（副作用なし）
                vertical=case["vertical"],
            )
    except Exception as e:
        return CaseResult(
            case=case, error=f"{type(e).__name__}: {e}",
            latency_ms=(time.time() - start) * 1000,
        )
    latency_ms = (time.time() - start) * 1000
    if result is None:
        return CaseResult(
            case=case, error="run_support_agent が None を返却（API キー未設定等）",
            latency_ms=latency_ms,
        )
    return CaseResult(
        case=case,
        decision=result.decision,
        action_type=result.action.action_type if result.action else None,
        citation_count=len(result.citations),
        groundedness=result.groundedness,
        groundedness_decided=result.groundedness_decided,
        forced_escalate=result.forced_escalate,
        identity_checked=result.identity_checked,
        intent=result.intent,
        latency_ms=latency_ms,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="業界特化 KPI 評価（分岐一致率・誤エスカレ率・出典付与率 等）"
    )
    parser.add_argument(
        "--vertical", choices=sorted(PROFILES), required=True,
        help="評価する業界プロファイル",
    )
    parser.add_argument(
        "--cases", type=Path, default=None,
        help="テストケース JSONL（既定: eval/vertical/cases/<vertical>.jsonl）",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="先頭 N ケースのみ実行（0=全件）。スモークテストは --limit 2 等",
    )
    parser.add_argument(
        "--no-web", dest="use_web", action="store_false",
        help="Web フォールバックを無効化（内部 RAG のみで評価）",
    )
    parser.add_argument(
        "--show-agent-output", action="store_true",
        help="エージェントの詳細ログを表示（既定は抑制して 1 行サマリのみ）",
    )
    parser.add_argument(
        "--report", type=Path, default=None,
        help="レポート JSON の出力先（例: logs/vertical_gov.json）",
    )
    args = parser.parse_args()

    cases_path = args.cases or (CASES_DIR / f"{args.vertical}.jsonl")
    cases = load_cases(cases_path)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print(f"テストケースがありません: {cases_path}", file=sys.stderr)
        sys.exit(1)

    # 根拠なし回答率の判定基準（プロファイル上書き or config 既定）
    profile = PROFILES[args.vertical]
    th = get_config().confidence.thresholds
    confirm_th = profile.confirm_th if profile.confirm_th is not None else th.confirm

    print(f"業界特化 KPI 評価: vertical={args.vertical} / {len(cases)} ケース / "
          f"confirm_th={confirm_th} / web={'ON' if args.use_web else 'OFF'}")

    results: List[CaseResult] = []
    for i, case in enumerate(cases, 1):
        rec = run_case(case, use_web=args.use_web, show_output=args.show_agent_output)
        results.append(rec)
        expected = case.get("expected_decision")
        mark = "✅" if rec.decision == expected else ("💥" if rec.error else "❌")
        print(f"  [{i}/{len(cases)}] {mark} {case['category']:<17} "
              f"decision={rec.decision or '-'}(期待={expected}) "
              f"action={rec.action_type or '-'} forced={rec.forced_escalate} "
              f"intent={rec.intent or '-'} : {case['query']}"
              + (f"  ⚠ {rec.error}" if rec.error else ""))

    metrics = compute_metrics(results, confirm_th=confirm_th)
    print()
    print(format_table(metrics))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "vertical": args.vertical,
            "cases_file": str(cases_path),
            "confirm_th": confirm_th,
            "use_web": args.use_web,
            "metrics": metrics,
            "cases": [
                {
                    **r.case,
                    "decision": r.decision,
                    "action_type": r.action_type,
                    "citation_count": r.citation_count,
                    "groundedness": r.groundedness,
                    "groundedness_decided": r.groundedness_decided,
                    "forced_escalate": r.forced_escalate,
                    "identity_checked": r.identity_checked,
                    "intent": r.intent,
                    "latency_ms": round(r.latency_ms, 1),
                    "error": r.error,
                }
                for r in results
            ],
        }
        args.report.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nレポートを出力しました: {args.report}")


if __name__ == "__main__":
    main()

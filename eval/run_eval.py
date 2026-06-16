"""S0 評価ハーネス本体。

現行 GRACE（planner.create_plan → executor.execute）を正解付き Q&A に対して回し、
LLM ジャッジで正誤・幻覚を判定して metrics を出力する。

DoD（doc §S0）:
    python -m eval.run_eval  で現行システムのスコア表が出る。

使い方:
    python -m eval.run_eval \
        --dataset eval/dataset.jsonl \
        --limit 0 \
        --report logs/eval_baseline.json

前提:
    - GRACE 本体（grace パッケージ, helper/helper_llm）と同じ作業ツリーで実行する
    - Qdrant が稼働している（executor の rag_search が参照する）
    - ANTHROPIC_API_KEY が設定されている
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

from eval.metrics import EvalRecord, compute

# --- GRACE 本体の import（配置が異なる場合は調整） ---
# helper_llm は helper パッケージ配下に配置されている（helper/helper_llm.py）。
try:
    from grace.config import get_config
    from grace.executor import create_executor
    from grace.planner import create_planner
    from helper.helper_llm import create_llm_client
except Exception:  # pragma: no cover - 環境依存
    try:
        from helper_llm import (
            create_llm_client,  # フラット配置用フォールバック
        )

        from grace.config import get_config
        from grace.executor import create_executor
        from grace.planner import create_planner
    except Exception as exc:
        print(
            "ERROR: GRACE 本体（grace.planner / grace.executor / helper_llm）を import できません。\n"
            "       GRACE 本体と同じ作業ツリーで実行しているか確認してください。\n"
            f"       詳細: {exc}",
            file=sys.stderr,
        )
        raise


JUDGE_PROMPT = """\
あなたは厳密な採点者です。質問に対する「正解」と「システムの回答」を比較し、
事実整合性のみを基準に採点してください。表現の違いは問いません。

# 質問
{question}

# 正解（ゴールド）
{gold}

# システムの回答
{prediction}

# 判定基準
- correct   : 正解の主要な事実をすべて満たし、矛盾がない
- partial   : 一部の事実は正しいが、欠落または一部不一致がある
- incorrect : 主要な事実が誤り、または質問に答えていない
- hallucinated: 正解に無い事実を、根拠なく断定している（誤情報の捏造）場合 true
"""


class JudgeVerdict(BaseModel):
    verdict: str = Field(description='"correct" | "partial" | "incorrect"')
    hallucinated: bool = Field(description="根拠なく事実を捏造しているなら true")
    reason: str = Field(default="", description="判定理由（簡潔に）")


def load_dataset(path: str, limit: int = 0) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
            if limit > 0 and len(items) >= limit:
                break
    return items


def _safe_judge(judge_llm: Any, model: str | None, question: str,
                gold: str, prediction: str) -> JudgeVerdict:
    prompt = JUDGE_PROMPT.format(question=question, gold=gold,
                                 prediction=prediction or "(回答なし)")
    try:
        return judge_llm.generate_structured(
            prompt=prompt, response_schema=JudgeVerdict, model=model,
        )
    except Exception as exc:  # ジャッジ失敗は incorrect 扱い（評価を止めない）
        return JudgeVerdict(verdict="incorrect", hallucinated=False,
                            reason=f"judge_error: {exc}")


def run(dataset: str, limit: int, model: str | None,
        judge_model: str | None, report: str | None,
        collection: str | None = None) -> int:
    items = load_dataset(dataset, limit=limit)
    if not items:
        print(f"ERROR: 評価データが空です: {dataset}", file=sys.stderr)
        return 1

    # ジャッジのモデルは未指定なら GRACE 本体と同じ設定モデルを使う
    # （None のままだとクライアントが model 未解決で 404 になる）
    cfg = get_config()
    if not judge_model:
        judge_model = getattr(getattr(cfg, "llm", None), "model", None)
    if not model:
        model = getattr(getattr(cfg, "llm", None), "model", None)

    planner = create_planner(model_name=model)
    executor = create_executor()
    judge_llm = create_llm_client("anthropic", default_model=judge_model)
    print(f"[run_eval] judge_model={judge_model} grace_model={model} "
          f"pinned_collection={collection or '(none: search all)'}")

    records: list[EvalRecord] = []
    details: list[dict[str, Any]] = []

    for i, item in enumerate(items, 1):
        q = item["question"]
        gold = item.get("gold_answer", "")
        t0 = time.monotonic()
        try:
            plan = planner.create_plan(q)
            # 対象コレクションに固定（指定時）。768次元など非対応コレクションの
            # 総当たり検索（dim mismatch エラー）を避け、評価対象を一意にする。
            if collection:
                for step in getattr(plan, "steps", []):
                    if getattr(step, "action", None) == "rag_search":
                        step.collection = collection
            result = executor.execute(plan)
            prediction = getattr(result, "final_answer", None) or ""
            confidence = float(getattr(result, "overall_confidence", 0.0) or 0.0)
            status = getattr(result, "overall_status", "")
            cost = getattr(result, "total_cost_usd", None)
        except Exception as exc:
            prediction, confidence, status, cost = "", 0.0, "failed", None
            print(f"[{i}/{len(items)}] 実行エラー: {exc}", file=sys.stderr)
        latency_ms = (time.monotonic() - t0) * 1000.0

        verdict = _safe_judge(judge_llm, judge_model, q, gold, prediction)
        if verdict.reason.startswith("judge_error"):
            print(f"    ⚠ judge error: {verdict.reason}", file=sys.stderr)
        correct = verdict.verdict == "correct"

        records.append(EvalRecord(
            id=item.get("id"), question=q, confidence=confidence,
            correct=correct, hallucinated=verdict.hallucinated,
            verdict=verdict.verdict, latency_ms=latency_ms,
            cost_usd=cost, status=status,
        ))
        details.append({
            "id": item.get("id"), "question": q, "gold_answer": gold,
            "prediction": prediction, "confidence": confidence,
            "verdict": verdict.verdict, "hallucinated": verdict.hallucinated,
            "reason": verdict.reason, "status": status,
            "latency_ms": round(latency_ms, 1), "cost_usd": cost,
        })
        print(f"[{i}/{len(items)}] verdict={verdict.verdict} "
              f"conf={confidence:.2f} hallu={verdict.hallucinated}")

    rep = compute(records)
    print("\n" + rep.as_table())

    # S1: 較正後 ECE のレポート（config/calibration.json があれば適用結果も表示）
    calibrated_ece = None
    try:
        from grace.calibration import Calibrator, expected_calibration_error
        confs = [float(r.confidence) for r in records]
        corr = [bool(r.correct) for r in records]
        calibrator = Calibrator.load()
        if not calibrator.is_identity():
            cal_confs = [calibrator.transform(c) for c in confs]
            calibrated_ece = expected_calibration_error(cal_confs, corr)
            print(f"\n[calibration] T={calibrator.temperature} "
                  f"ECE(raw)={rep.ece:.4f} -> ECE(calibrated)={calibrated_ece:.4f}")
        else:
            # 較正未適用。この run から fit した場合の改善見込みを参考表示。
            fitted = Calibrator.fit(confs, corr)
            cal_confs = [fitted.transform(c) for c in confs]
            potential = expected_calibration_error(cal_confs, corr)
            print(f"\n[calibration] 未適用（T=1.0）。この run から fit すると "
                  f"T={fitted.temperature}, ECE {rep.ece:.4f} -> {potential:.4f} 見込み。"
                  f" `python -m eval.calibrate --report <report>` で保存可能。")
    except Exception as exc:  # 較正は付随情報のため失敗しても評価は継続
        print(f"\n[calibration] スキップ: {exc}", file=sys.stderr)

    if report:
        out = Path(report)
        out.parent.mkdir(parents=True, exist_ok=True)
        summary = rep.to_dict()
        if calibrated_ece is not None:
            summary["ece_calibrated"] = calibrated_ece
        with out.open("w", encoding="utf-8") as f:
            json.dump({"summary": summary, "details": details},
                      f, ensure_ascii=False, indent=2)
        print(f"\nレポート保存: {report}")

    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GRACE S0 evaluation harness")
    p.add_argument("--dataset", default="eval/dataset.jsonl")
    p.add_argument("--limit", type=int, default=0, help="先頭 N 件のみ（0 で全件）")
    p.add_argument("--model", default=None, help="GRACE 本体の LLM モデル（既定は config）")
    p.add_argument("--judge-model", default="claude-haiku-4-5-20251001",
                   help="ジャッジ用 LLM モデル（文字列処理のため既定は Haiku）")
    p.add_argument("--collection", default="cc_news_2per_anthropic",
                   help="rag_search を固定するコレクション。空文字で全コレクション総当たり")
    p.add_argument("--report", default="logs/eval_baseline.json")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args.dataset, args.limit, args.model, args.judge_model,
               args.report, collection=(args.collection or None))


if __name__ == "__main__":
    raise SystemExit(main())

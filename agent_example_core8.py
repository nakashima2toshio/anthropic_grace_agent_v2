# agent_example_core8.py
"""GRACE コア 8 モジュールを明示的に使う実行サンプル（教材版）。

`agent_example.py` は planner と executor の 2 API だけで動き、残り 6 モジュール
（confidence / calibration / memory / intervention / replan / tools）は executor の
内部に隠れている。本サンプルは **8 つのコアモジュールをそれぞれ最低 1 回ずつ明示的に
呼び出して** 5 段階設計（Plan → Execute → Confidence → Intervention → Replan）を
画面に見せることを目的とする。

使う 8 モジュール（grace/*.py）:
  planner.py / executor.py / confidence.py / calibration.py /
  memory.py / intervention.py / replan.py / tools.py

⚠️ 本サンプルは学習用の簡略オーケストレータである。Phase3〜5 は executor が内部で
   行う処理を、各モジュールの公開 API で「再現・可視化」したものを含む。本番コードは
   executor.execute() を使うこと（動的フォールバック・ReAct 等は executor 内にある）。

前提:
- `.env` に ANTHROPIC_API_KEY（LLM 用）と GOOGLE_API_KEY（Embedding 用）を設定
- Qdrant が起動済み（既定 http://localhost:6333）で RAG コレクションが登録済み

使い方::

    python agent_example_core8.py
    python agent_example_core8.py "東京タワーの高さは？"
    python agent_example_core8.py -v "日本の祝日について教えて"
"""
from __future__ import annotations

import argparse
import os
import sys

from grace import (
    ConfidenceFactors,
    InterventionAction,
    InterventionResponse,
    create_confidence_calculator,
    create_executor,
    create_intervention_handler,
    create_planner,
    create_replan_manager,
    create_tool_registry,
    get_config,
)
from grace.calibration import Calibrator
from grace.memory import create_execution_memory

# .env から ANTHROPIC_API_KEY / GOOGLE_API_KEY 等を読み込む（未導入でも続行）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_QUERY = "日本の再生可能エネルギー政策の最新動向を教えて"


def _banner(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def run_agent(query: str = DEFAULT_QUERY, verbose: bool = False):
    # 0. APIキーの存在チェック（未設定だと LLM 呼び出しで失敗する）
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️ ANTHROPIC_API_KEY が未設定です。.env に設定してください。", file=sys.stderr)
        return None

    # ------------------------------------------------------------------
    # Phase 0: セットアップ（config + 8 モジュールのファクトリ生成）
    # ------------------------------------------------------------------
    _banner("Phase 0: セットアップ（config + 8 モジュール初期化）")
    config = get_config()

    tool_registry = create_tool_registry(config)          # 3.8 tools.py
    planner = create_planner(config)                      # 3.1 planner.py
    executor = create_executor(config, tool_registry)    # 3.2 executor.py
    calculator = create_confidence_calculator(config)     # 3.3 confidence.py
    calibrator = Calibrator.load(config.confidence.calibration_path)  # 3.4 calibration.py
    memory = create_execution_memory(config.memory.path)  # 3.5 memory.py
    handler = create_intervention_handler(                # 3.6 intervention.py
        config,
        on_notify=lambda msg: print(f"   [intervention/notify] {msg}"),
        on_confirm=lambda _req: InterventionResponse(action=InterventionAction.PROCEED),
        on_escalate=lambda _req: InterventionResponse(action=InterventionAction.PROCEED),
    )
    replan_manager = create_replan_manager(config, planner)  # 3.7 replan.py
    print("  planner / executor / tools / confidence / calibration / memory / "
          "intervention / replan を初期化しました ✓")

    # ------------------------------------------------------------------
    # Phase 1: ① Plan（planner.py + memory.py）
    # ------------------------------------------------------------------
    _banner("Phase 1: ① Plan（planner + memory）")
    print(f"❓ 質問: {query}")

    # memory.py: 過去実績からこの質問で当たりやすいコレクションを読む
    priors = memory.collection_priors(query)
    best = memory.best_collection(query)
    if priors:
        top = ", ".join(f"{s.collection}(score={s.score():.2f}, n={s.count})" for s in priors[:3])
        print(f"  [memory] 事前分布: {top}")
    else:
        print("  [memory] 事前分布: 実績なし（全コレクション検索）")
    print(f"  [memory] 推奨コレクション: {best or '（なし＝全コレクション検索）'}")

    # planner.py: 実行計画を生成
    plan = planner.create_plan(query)
    print(f"  [plan] {len(plan.steps)} ステップ (complexity={plan.complexity:.2f})")
    for step in plan.steps:
        print(f"    - step{step.step_id}: {step.action} … {step.description}")

    # ------------------------------------------------------------------
    # Phase 2: ② Execute（executor.py + tools.py）
    # ------------------------------------------------------------------
    _banner("Phase 2: ② Execute（executor + tools）")
    # executor.py が tool_registry（tools.py）を使って計画を実行する
    result = executor.execute(plan)
    for sr in result.step_results:
        out_preview = (sr.output or "")[:60].replace("\n", " ")
        print(f"  step{sr.step_id}: {sr.status} (conf={sr.confidence:.2f}) {out_preview}")

    # ------------------------------------------------------------------
    # Phase 3: ③ Confidence + 較正（confidence.py + calibration.py）
    # ------------------------------------------------------------------
    _banner("Phase 3: ③ Confidence + 較正（confidence + calibration）")
    steps = result.step_results
    total = len(steps)
    succ = sum(1 for s in steps if s.status == "success")

    # confidence.py: 実行結果から ConfidenceFactors を組み立ててスコア化（説明用の再計算）
    factors = ConfidenceFactors(
        tool_execution_count=total,
        tool_success_count=succ,
        tool_success_rate=(succ / total if total else 1.0),
        source_count=sum(len(s.sources) for s in steps),
        llm_self_confidence=result.overall_confidence,
        is_search_step=False,
    )
    score = calculator.calculate(factors)
    if verbose:
        print(f"  [confidence] factors: success_rate={factors.tool_success_rate:.2f}, "
              f"source_count={factors.source_count}, llm_self={factors.llm_self_confidence:.2f}")
        print(f"  [confidence] breakdown: {score.breakdown}")
    print(f"  [confidence] 再計算スコア(raw)={score.score:.3f} (level={score.level})")

    # calibration.py: 温度スケーリングで較正
    calibrated = calibrator.transform(score.score)
    print(f"  [calibration] 較正後={calibrated:.3f} "
          f"(temperature={'恒等(T=1.0)' if calibrator.is_identity() else 'fitted'})")
    print(f"  [executor] 公式の全体信頼度（executor が較正済み）={result.overall_confidence:.3f}")

    # ------------------------------------------------------------------
    # Phase 4: ④ Intervention（intervention.py）
    # ------------------------------------------------------------------
    _banner("Phase 4: ④ Intervention（intervention）")
    decision = calculator.decide_action(score)            # confidence.py: 介入レベル決定
    print(f"  [confidence] decide_action → level={decision.level}, "
          f"suggested={decision.suggested_action}")
    response = handler.handle(decision)                   # intervention.py: HITL 処理
    print(f"  [intervention] action={response.action}, 続行={response.should_continue}")

    # ------------------------------------------------------------------
    # Phase 5: ⑤ Replan（replan.py）
    # ------------------------------------------------------------------
    _banner("Phase 5: ⑤ Replan（replan）")
    if steps:
        last = steps[-1]
        should, trigger = replan_manager.should_replan(last, replan_count=0)
        if should:
            print(f"  [replan] リプラン必要（trigger={trigger}）→ 本番では新計画を生成して再実行")
        else:
            print("  [replan] リプラン不要（全ステップ成功・十分な信頼度）")
    else:
        print("  [replan] ステップ結果が無いため判定スキップ")

    # ------------------------------------------------------------------
    # 結果
    # ------------------------------------------------------------------
    _banner("結果")
    print(f"最終回答: {result.final_answer}")
    print(f"全体信頼度（較正済み）: {result.overall_confidence:.2f}")
    print(f"ステータス: {result.overall_status}")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="GRACE コア 8 モジュールを明示的に使う実行サンプル（教材版）"
    )
    parser.add_argument(
        "query", nargs="?", default=DEFAULT_QUERY,
        help="エージェントに尋ねる質問（省略時は既定の質問を使用）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="ConfidenceFactors やスコア内訳などの詳細を表示する",
    )
    args = parser.parse_args()

    try:
        run_agent(args.query, verbose=args.verbose)
    except Exception as e:  # サービス未起動・鍵未設定などを分かりやすく表示
        print(f"❌ 実行に失敗しました: {type(e).__name__}: {e}", file=sys.stderr)
        print(
            "  ヒント: Qdrant の起動（docker-compose -f docker-compose/docker-compose.yml up -d）"
            "と .env の API キーを確認してください。",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

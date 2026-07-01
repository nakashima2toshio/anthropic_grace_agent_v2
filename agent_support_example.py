# agent_support_example.py
"""GRACE-Support v1（MVP）: 日本語ナレッジ駆動サポート・コパイロット。

内部 RAG で回答し、**出典を必ず提示**する。根拠が不足する場合は
「わかりません（社内ナレッジには見当たりません）」と誠実に答え、有人対応へ
エスカレーションする（v1 では通知のみ。Web フォールバック=v2 / アクション=v3 は未実装）。

設計書: grace/doc/agent_support_example.md
上位計画: docs/migration_and_update.md

処理の流れ:
  ① Plan     planner.create_plan(query)
  ② Execute  executor.execute(plan)（内部 RAG → reasoning）
  ③ 出典抽出  step_results から citations を収集
  ④ 根拠評価  GroundednessVerifier.verify() で支持率(support_rate)を算出
  ⑤ 回答ゲート _answer_gate() で decision を決定（answer / escalate）
  ⑥ 応答     出典つき回答 or エスカレーション文言

前提:
- `.env` に ANTHROPIC_API_KEY（LLM 用）と GOOGLE_API_KEY（Embedding 用）を設定
- Qdrant が起動済み（既定 http://localhost:6333）で RAG コレクションが登録済み

使い方::

    python agent_support_example.py "パスワードを忘れました"
    python agent_support_example.py -v "最新の料金改定は？"
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from grace import (
    create_executor,
    create_planner,
    create_tool_registry,
    get_config,
)
from grace.confidence import create_groundedness_verifier

# .env から ANTHROPIC_API_KEY / GOOGLE_API_KEY 等を読み込む（未導入でも続行）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_QUERY = "パスワードを忘れました"

Decision = Literal["answer", "escalate"]


@dataclass
class SupportResult:
    """サポート回答の結果（v1）。"""

    answer: Optional[str]
    citations: List[str] = field(default_factory=list)
    groundedness: float = 0.0
    decision: Decision = "escalate"
    warning: bool = False           # 中信頼（未確認）の注意書きを付けるか
    overall_confidence: float = 0.0


def _banner(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _answer_gate(
    support_rate: float,
    verified: bool,
    citation_count: int,
    notify_th: float,
    confirm_th: float,
) -> tuple[Decision, bool]:
    """支持率・出典数から回答可否を判定する純関数。

    Returns:
        (decision, warning):
          - ("answer", False): 高信頼（支持率>=notify かつ 出典>=1）→ 出典つき回答
          - ("answer", True) : 中信頼（confirm<=支持率<notify）→ 回答＋未確認の注意
          - ("escalate", False): 低信頼（支持率<confirm）／未検証／出典0 → 有人へ
    """
    if not verified or citation_count == 0:
        return "escalate", False
    if support_rate >= notify_th:
        return "answer", False
    if support_rate >= confirm_th:
        return "answer", True
    return "escalate", False


def _collect_citations(step_results) -> List[str]:
    """各ステップの sources を重複排除して出典リストにする。"""
    seen: List[str] = []
    for sr in step_results:
        for src in sr.sources:
            if src and src not in seen:
                seen.append(src)
    return seen


def _render(result: SupportResult) -> None:
    """回答ゲートの判定に応じて応答を整形表示する。"""
    _banner("応答")
    if result.decision == "answer":
        print(result.answer or "（回答なし）")
        if result.warning:
            print("\n⚠️ 注意: この回答は出典による裏付けが十分ではありません。内容をご確認ください。")
        if result.citations:
            print("\n【出典】")
            for i, c in enumerate(result.citations, 1):
                print(f"  [{i}] {c}")
    else:  # escalate
        print("社内ナレッジには十分な根拠が見つかりませんでした。")
        print("→ 有人対応へエスカレーションします（v1 では通知のみ。Web 調査=v2）。")
    print(f"\n[根拠] 支持率(groundedness)={result.groundedness:.2f} / "
          f"全体信頼度={result.overall_confidence:.2f} / decision={result.decision}")


def run_support_agent(query: str = DEFAULT_QUERY, verbose: bool = False) -> Optional[SupportResult]:
    # 0. APIキーの存在チェック（未設定だと LLM 呼び出しで失敗する）
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️ ANTHROPIC_API_KEY が未設定です。.env に設定してください。", file=sys.stderr)
        return None

    config = get_config()
    tool_registry = create_tool_registry(config)
    planner = create_planner(config)
    executor = create_executor(config, tool_registry)
    verifier = create_groundedness_verifier(config)

    # ① Plan
    _banner("① Plan（planner）")
    print(f"❓ 問い合わせ: {query}")
    plan = planner.create_plan(query)
    print(f"  [plan] {len(plan.steps)} ステップ (complexity={plan.complexity:.2f})")

    # ② Execute（内部 RAG → reasoning）
    _banner("② Execute（executor + tools: 内部RAG）")
    result = executor.execute(plan)
    answer = result.final_answer or ""
    citations = _collect_citations(result.step_results)
    for sr in result.step_results:
        print(f"  step{sr.step_id}: {sr.status} (sources={len(sr.sources)})")

    # ③④ 根拠評価（groundedness）
    _banner("③ Confidence（GroundednessVerifier: 出典による裏付け）")
    gres = verifier.verify(query, answer, citations)
    if verbose:
        print(f"  [groundedness] supported={gres.supported} / total={gres.total} / "
              f"contradiction={gres.has_contradiction} / verified={gres.verified}")
    print(f"  [groundedness] 支持率={gres.support_rate:.2f} / 出典数={len(citations)}")

    # ⑤ 回答ゲート
    th = config.confidence.thresholds
    decision, warning = _answer_gate(
        gres.support_rate, gres.verified, len(citations), th.notify, th.confirm
    )
    support = SupportResult(
        answer=answer,
        citations=citations,
        groundedness=gres.support_rate,
        decision=decision,
        warning=warning,
        overall_confidence=result.overall_confidence,
    )

    # ⑥ 応答
    _render(support)
    return support


def main():
    parser = argparse.ArgumentParser(
        description="GRACE-Support v1（MVP）: 内部RAG＋出典つき回答／根拠不足なら『わかりません』"
    )
    parser.add_argument(
        "query", nargs="?", default=DEFAULT_QUERY,
        help="問い合わせ内容（省略時は既定の質問を使用）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="支持率の内訳（supported/total/矛盾）など詳細を表示する",
    )
    args = parser.parse_args()

    try:
        run_support_agent(args.query, verbose=args.verbose)
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

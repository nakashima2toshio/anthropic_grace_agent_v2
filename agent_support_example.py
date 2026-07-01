# agent_support_example.py
"""GRACE-Support v2: 日本語ナレッジ駆動サポート・コパイロット。

内部 RAG で回答し、**出典を必ず提示**する。根拠が不足する場合は内部知識だけで
断定せず、**Web フォールバック**（v2）で裏取りを試みる。内部回答と Web 回答は
**相互検証**（意味的一致・矛盾検出）し、なお根拠不足なら「わかりません」と誠実に
答えて有人対応へエスカレーションする（アクション=v3 は未実装）。

設計書: grace/doc/agent_support_example.md
上位計画: docs/migration_and_update.md

処理の流れ:
  ① Plan      planner.create_plan(query)
  ② Execute   executor.execute(plan)（内部 RAG → reasoning）
  ③ 根拠評価  GroundednessVerifier.verify() で支持率(support_rate)を算出
  ④ 回答ゲート _answer_gate()（answer / escalate）
  ⑤ Webフォールバック（内部が escalate のときのみ・v2）
       tools.web_search → tools.reasoning → 再度 根拠評価
       内部回答 × Web 回答を SourceAgreementCalculator で相互検証（矛盾提示）
  ⑥ 応答      内部/Web 出典を統合して提示、または エスカレーション

前提:
- `.env` に ANTHROPIC_API_KEY（LLM 用）と GOOGLE_API_KEY（Embedding 用）を設定
- Qdrant が起動済み（既定 http://localhost:6333）で RAG コレクションが登録済み

使い方::

    python agent_support_example.py "パスワードを忘れました"
    python agent_support_example.py -v "最新の料金改定は？"
    python agent_support_example.py --no-web "解約したい"   # Webフォールバック無効
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
    create_source_agreement_calculator,
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
    """サポート回答の結果（v2）。"""

    answer: Optional[str]
    citations: List[str] = field(default_factory=list)
    groundedness: float = 0.0
    decision: Decision = "escalate"
    warning: bool = False             # 中信頼（未確認）の注意書きを付けるか
    used_web: bool = False            # Web フォールバックを使ったか
    source_agreement: Optional[float] = None  # 内部×Web の意味的一致度（相互検証）
    contradiction: bool = False       # 矛盾の可能性
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


def _collect_internal_citations(step_results) -> List[str]:
    """各ステップの sources を重複排除して内部出典リストにする。"""
    seen: List[str] = []
    for sr in step_results:
        for src in sr.sources:
            label = f"[社内] {src}"
            if src and label not in seen:
                seen.append(label)
    return seen


def _web_citations(web_output: list) -> List[str]:
    """Web 検索結果（rag_search 互換 dict）から出典表示文字列を作る。"""
    cites: List[str] = []
    for entry in web_output or []:
        payload = entry.get("payload", {})
        title = payload.get("title") or "(無題)"
        url = payload.get("source") or ""
        cites.append(f"[Web] {title}（{url}）" if url else f"[Web] {title}")
    return cites


def _web_source_texts(web_output: list) -> List[str]:
    """Web 検索結果の本文（snippet/answer）を groundedness 検証用に抽出する。"""
    return [
        entry.get("payload", {}).get("answer", "")
        for entry in web_output or []
        if entry.get("payload", {}).get("answer")
    ]


def _render(result: SupportResult) -> None:
    """回答ゲートの判定に応じて応答を整形表示する。"""
    _banner("応答")
    if result.decision == "answer":
        print(result.answer or "（回答なし）")
        if result.warning:
            print("\n⚠️ 注意: この回答は出典による裏付けが十分ではありません。内容をご確認ください。")
        if result.used_web and result.contradiction:
            print("\n⚠️ 注意: 社内ナレッジと Web 情報で食い違いの可能性があります。")
        if result.citations:
            print("\n【出典】")
            for i, c in enumerate(result.citations, 1):
                print(f"  [{i}] {c}")
    else:  # escalate
        print("社内ナレッジにも Web 検索にも十分な根拠が見つかりませんでした。")
        print("→ 有人対応へエスカレーションします（v2 では通知のみ。アクション=v3）。")

    extra = ""
    if result.source_agreement is not None:
        extra = f" / 内部×Web 一致度={result.source_agreement:.2f}"
    print(f"\n[根拠] 支持率(groundedness)={result.groundedness:.2f} / "
          f"全体信頼度={result.overall_confidence:.2f} / decision={result.decision}"
          f" / web={'使用' if result.used_web else '不使用'}{extra}")


def run_support_agent(
    query: str = DEFAULT_QUERY,
    verbose: bool = False,
    use_web: bool = True,
) -> Optional[SupportResult]:
    # 0. APIキーの存在チェック（未設定だと LLM 呼び出しで失敗する）
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️ ANTHROPIC_API_KEY が未設定です。.env に設定してください。", file=sys.stderr)
        return None

    config = get_config()
    tool_registry = create_tool_registry(config)
    planner = create_planner(config)
    executor = create_executor(config, tool_registry)
    verifier = create_groundedness_verifier(config)
    agreement_calc = create_source_agreement_calculator(config)
    th = config.confidence.thresholds

    # ① Plan
    _banner("① Plan（planner）")
    print(f"❓ 問い合わせ: {query}")
    plan = planner.create_plan(query)
    print(f"  [plan] {len(plan.steps)} ステップ (complexity={plan.complexity:.2f})")

    # ② Execute（内部 RAG → reasoning）
    _banner("② Execute（executor + tools: 内部RAG）")
    result = executor.execute(plan)
    internal_answer = result.final_answer or ""
    internal_citations = _collect_internal_citations(result.step_results)
    for sr in result.step_results:
        print(f"  step{sr.step_id}: {sr.status} (sources={len(sr.sources)})")

    # ③ 根拠評価（内部）
    _banner("③ Confidence（GroundednessVerifier: 内部回答の裏付け）")
    gres = verifier.verify(query, internal_answer, [c[5:] for c in internal_citations])
    if verbose:
        print(f"  [groundedness] supported={gres.supported} / total={gres.total} / "
              f"contradiction={gres.has_contradiction} / verified={gres.verified}")
    print(f"  [groundedness] 支持率={gres.support_rate:.2f} / 出典数={len(internal_citations)}")

    # ④ 回答ゲート（内部）
    decision, warning = _answer_gate(
        gres.support_rate, gres.verified, len(internal_citations), th.notify, th.confirm
    )

    # 内部で十分 → そのまま回答
    if decision == "answer":
        support = SupportResult(
            answer=internal_answer,
            citations=internal_citations,
            groundedness=gres.support_rate,
            decision=decision,
            warning=warning,
            overall_confidence=result.overall_confidence,
        )
        _render(support)
        return support

    # ⑤ Web フォールバック（内部が escalate のときのみ・v2）
    if not use_web:
        support = SupportResult(
            answer=internal_answer, citations=internal_citations,
            groundedness=gres.support_rate, decision="escalate",
            overall_confidence=result.overall_confidence,
        )
        _render(support)
        return support

    _banner("⑤ Web フォールバック（tools.web_search → reasoning → 相互検証）")
    print("  内部ナレッジの根拠が不足 → Web で裏取りを試みます")
    web_res = tool_registry.execute("web_search", query=query)
    web_output = web_res.output if (web_res and web_res.success) else None

    if not web_output:
        print("  [web] 有効な検索結果が得られませんでした")
        support = SupportResult(
            answer=internal_answer, citations=internal_citations,
            groundedness=gres.support_rate, decision="escalate", used_web=True,
            overall_confidence=result.overall_confidence,
        )
        _render(support)
        return support

    # Web ソースで再推論
    web_reason = tool_registry.execute("reasoning", query=query, sources=web_output)
    web_answer = (web_reason.output or "") if (web_reason and web_reason.success) else ""
    web_citations = _web_citations(web_output)
    web_source_texts = _web_source_texts(web_output)
    print(f"  [web] {len(web_citations)} 件の出典を取得")

    # 相互検証: 内部回答 × Web 回答の意味的一致度・矛盾
    gres_web = verifier.verify(query, web_answer, web_source_texts)
    agreement: Optional[float] = None
    contradiction = gres_web.has_contradiction
    if internal_answer and web_answer:
        agreement = agreement_calc.calculate([internal_answer, web_answer])
        if agreement < th.confirm:  # 一致度が低い＝食い違いの可能性
            contradiction = True
        print(f"  [相互検証] 内部×Web 一致度={agreement:.2f} / 矛盾={contradiction}")

    # ⑥ Web 結果で再ゲート
    w_decision, w_warning = _answer_gate(
        gres_web.support_rate, gres_web.verified, len(web_citations), th.notify, th.confirm
    )
    merged_citations = internal_citations + web_citations
    support = SupportResult(
        answer=web_answer if w_decision == "answer" else internal_answer,
        citations=merged_citations,
        groundedness=max(gres.support_rate, gres_web.support_rate),
        decision=w_decision,
        warning=w_warning,
        used_web=True,
        source_agreement=agreement,
        contradiction=contradiction,
        overall_confidence=result.overall_confidence,
    )
    _render(support)
    return support


def main():
    parser = argparse.ArgumentParser(
        description="GRACE-Support v2: 内部RAG＋出典／不足時はWebで裏取り・相互検証／なお不足なら『わかりません』"
    )
    parser.add_argument(
        "query", nargs="?", default=DEFAULT_QUERY,
        help="問い合わせ内容（省略時は既定の質問を使用）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="支持率の内訳（supported/total/矛盾）など詳細を表示する",
    )
    parser.add_argument(
        "--no-web", dest="use_web", action="store_false",
        help="Web フォールバックを無効化する（内部RAGのみ）",
    )
    args = parser.parse_args()

    try:
        run_support_agent(args.query, verbose=args.verbose, use_web=args.use_web)
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

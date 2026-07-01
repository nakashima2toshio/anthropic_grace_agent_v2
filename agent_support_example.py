# agent_support_example.py
"""GRACE-Support v3: 日本語ナレッジ駆動サポート・コパイロット。

内部 RAG で回答し、**出典を必ず提示**する。根拠が不足すれば **Web フォールバック**
（v2）で裏取りし、内部×Web を**相互検証**する。さらに、問い合わせが「対応（アクション）」
を要する場合は、**擬似 ActionTool** を **HITL（CONFIRM 承認）** を通してから実行する
（v3。既定はドライラン＝実行せずログのみ）。なお根拠不足なら「わかりません」と誠実に
答えて有人対応へエスカレーションする。

設計書: grace/doc/agent_support_example.md
上位計画: docs/migration_and_update.md

処理の流れ:
  ① Plan      planner.create_plan(query)
  ② Execute   executor.execute(plan)（内部 RAG → reasoning）
  ③ 根拠評価  GroundednessVerifier.verify()（支持率）
  ④ 回答ゲート _answer_gate()（answer / escalate）
  ⑤ Webフォールバック（内部が escalate のときのみ・v2）＋相互検証
  ⑥ アクション（v3）: _decide_action() → intervention CONFIRM → 擬似実行（既定ドライラン）
  ⑦ 応答

前提:
- `.env` に ANTHROPIC_API_KEY（LLM 用）と GOOGLE_API_KEY（Embedding 用）を設定
- Qdrant が起動済み（既定 http://localhost:6333）で RAG コレクションが登録済み

使い方::

    python agent_support_example.py "パスワードを忘れました"
    python agent_support_example.py "解約したい"                # アクション（要CONFIRM・ドライラン）
    python agent_support_example.py --no-dry-run "解約したい"    # 擬似実行（実API連携は将来）
    python agent_support_example.py --no-web --no-action -v "…"  # 内部RAGのみ
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from grace import (
    ActionDecision,
    InterventionAction,
    InterventionLevel,
    InterventionResponse,
    create_executor,
    create_intervention_handler,
    create_planner,
    create_source_agreement_calculator,
    create_tool_registry,
    get_config,
)
from grace.confidence import create_groundedness_verifier

# 非対話 CLI 用: CONFIRM/ESCALATE を自動承認するレスポンス（実行はドライランで安全）
_AUTO_PROCEED = InterventionResponse(action=InterventionAction.PROCEED)

# .env から ANTHROPIC_API_KEY / GOOGLE_API_KEY 等を読み込む（未導入でも続行）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_QUERY = "パスワードを忘れました"

Decision = Literal["answer", "escalate"]
ActionType = Literal["create_ticket", "send_reply", "escalate_to_human"]


@dataclass
class ActionRequest:
    """副作用のある操作の要求（v3・擬似）。"""

    action_type: ActionType
    args: dict = field(default_factory=dict)
    requires_confirmation: bool = True


@dataclass
class SupportResult:
    """サポート回答の結果（v3）。"""

    answer: Optional[str]
    citations: List[str] = field(default_factory=list)
    groundedness: float = 0.0
    decision: Decision = "escalate"
    warning: bool = False              # 中信頼（未確認）の注意書きを付けるか
    used_web: bool = False             # Web フォールバックを使ったか
    source_agreement: Optional[float] = None  # 内部×Web の意味的一致度（相互検証）
    contradiction: bool = False        # 矛盾の可能性
    action: Optional[ActionRequest] = None    # 実施（予定）のアクション
    action_result: Optional[str] = None       # アクションの結果メッセージ
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
          - ("answer", False): 高信頼（支持率>=notify かつ 出典>=1）
          - ("answer", True) : 中信頼（confirm<=支持率<notify）→ 未確認の注意
          - ("escalate", False): 低信頼／未検証／出典0 → 有人へ
    """
    if not verified or citation_count == 0:
        return "escalate", False
    if support_rate >= notify_th:
        return "answer", False
    if support_rate >= confirm_th:
        return "answer", True
    return "escalate", False


def _decide_action(query: str, decision: Decision) -> Optional[ActionRequest]:
    """問い合わせ内容と回答判定から、必要なアクションを決める（デモ用のキーワード判定）。"""
    if decision == "escalate":
        return ActionRequest("escalate_to_human", {"query": query})
    if any(k in query for k in ("解約", "キャンセル", "退会")):
        return ActionRequest("create_ticket", {"subject": "解約希望", "query": query})
    if any(k in query for k in ("パスワード", "ログイン", "サインイン")):
        return ActionRequest("send_reply", {"template": "password_reset", "query": query})
    return None


def _perform_action(action: ActionRequest, handler, dry_run: bool) -> str:
    """HITL（CONFIRM 承認）を通してから擬似アクションを実行する。

    副作用のある操作は必ず intervention の CONFIRM を経由する。承認後、
    dry_run=True ならログのみ（実行しない）。実 API 連携（Zendesk 等）は将来拡張。
    """
    # intervention.py: 実行前に人間の承認（CONFIRM）を求める
    decision = ActionDecision(
        level=InterventionLevel.CONFIRM,
        confidence_score=0.5,
        reason=f"アクション実行前の確認: {action.action_type}",
    )
    response = handler.handle(decision)
    if not response.should_continue:
        return f"アクション '{action.action_type}' はキャンセルされました"

    if dry_run:
        return f"[DRY-RUN] '{action.action_type}' を実行（ログのみ・args={action.args}）"
    # 擬似実行（実 API 連携は将来）
    return f"'{action.action_type}' を実行しました（擬似・args={action.args}）"


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
        print("→ 有人対応へエスカレーションします。")

    if result.action is not None:
        print(f"\n【アクション】種別={result.action.action_type} / 結果={result.action_result}")

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
    do_action: bool = True,
    dry_run: bool = True,
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
    handler = create_intervention_handler(
        config,
        on_notify=lambda msg: print(f"   [intervention/notify] {msg}"),
        on_confirm=lambda _req: _AUTO_PROCEED,
        on_escalate=lambda _req: _AUTO_PROCEED,
    )
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

    support = SupportResult(
        answer=internal_answer,
        citations=internal_citations,
        groundedness=gres.support_rate,
        decision=decision,
        warning=warning,
        overall_confidence=result.overall_confidence,
    )

    # ⑤ Web フォールバック（内部が escalate のときのみ・v2）
    if decision == "escalate" and use_web:
        _banner("⑤ Web フォールバック（tools.web_search → reasoning → 相互検証）")
        print("  内部ナレッジの根拠が不足 → Web で裏取りを試みます")
        web_res = tool_registry.execute("web_search", query=query)
        web_output = web_res.output if (web_res and web_res.success) else None

        if web_output:
            web_reason = tool_registry.execute("reasoning", query=query, sources=web_output)
            web_answer = (web_reason.output or "") if (web_reason and web_reason.success) else ""
            web_citations = _web_citations(web_output)
            print(f"  [web] {len(web_citations)} 件の出典を取得")

            gres_web = verifier.verify(query, web_answer, _web_source_texts(web_output))
            agreement: Optional[float] = None
            contradiction = gres_web.has_contradiction
            if internal_answer and web_answer:
                agreement = agreement_calc.calculate([internal_answer, web_answer])
                if agreement < th.confirm:
                    contradiction = True
                print(f"  [相互検証] 内部×Web 一致度={agreement:.2f} / 矛盾={contradiction}")

            w_decision, w_warning = _answer_gate(
                gres_web.support_rate, gres_web.verified, len(web_citations),
                th.notify, th.confirm,
            )
            support = SupportResult(
                answer=web_answer if w_decision == "answer" else internal_answer,
                citations=internal_citations + web_citations,
                groundedness=max(gres.support_rate, gres_web.support_rate),
                decision=w_decision,
                warning=w_warning,
                used_web=True,
                source_agreement=agreement,
                contradiction=contradiction,
                overall_confidence=result.overall_confidence,
            )
        else:
            print("  [web] 有効な検索結果が得られませんでした")
            support.used_web = True

    # ⑥ アクション（v3）: HITL（CONFIRM）を通して擬似実行
    if do_action:
        action = _decide_action(query, support.decision)
        if action is not None:
            _banner("⑥ Action（intervention CONFIRM → 擬似ActionTool）")
            print(f"  [action] 種別={action.action_type}（要承認={action.requires_confirmation}）")
            support.action = action
            support.action_result = _perform_action(action, handler, dry_run)
            print(f"  [action] {support.action_result}")

    # ⑦ 応答
    _render(support)
    return support


def main():
    parser = argparse.ArgumentParser(
        description="GRACE-Support v3: 内部RAG＋出典／Web裏取り・相互検証／アクション＋HITL（既定ドライラン）"
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
    parser.add_argument(
        "--no-action", dest="do_action", action="store_false",
        help="アクション（v3）を無効化する",
    )
    parser.add_argument(
        "--dry-run", dest="dry_run", action=argparse.BooleanOptionalAction, default=True,
        help="アクションを実行せずログのみ（既定 ON。--no-dry-run で擬似実行）",
    )
    args = parser.parse_args()

    try:
        run_support_agent(
            args.query, verbose=args.verbose, use_web=args.use_web,
            do_action=args.do_action, dry_run=args.dry_run,
        )
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

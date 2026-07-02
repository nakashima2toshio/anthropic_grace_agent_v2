# agent_support_example.py
"""GRACE-Support: 日本語ナレッジ駆動サポート・コパイロット。

内部 RAG で回答し、**出典を必ず提示**する。根拠が不足すれば **Web フォールバック**
（v2）で裏取りし、内部×Web を**相互検証**する。問い合わせが「対応（アクション）」を
要する場合は、**擬似 ActionTool** を **HITL（CONFIRM 承認）** を通してから実行する
（v3。既定はドライラン＝実行せずログのみ）。なお根拠不足なら「わかりません」と誠実に
答えて有人対応へエスカレーションする。

**業界特化（VerticalProfile）**: `--vertical {gov|saas|ec}` で業界プロファイルを適用し、
検索スコープ（allowed_collections）・エスカレ語・回答しきい値・アクション対応・
本人確認・方針（reasoning プロンプトへ注入）を切り替える。
設計は grace/doc/agent_support_verticals.md を参照。

**二段判定（誤爆抑止）**: `escalate_keywords` / `action_map` のキーワード一致は
**候補検出（第 1 段）**であり、一致時のみ軽量 LLM で意図を分類（第 2 段:
question / request / incident）する。FAQ 質問（question。例:「課金プランの違いを
教えて」「解約方法を教えて」）は強制エスカレ・アクション起票の対象外となる。
分類に失敗した場合は安全側（従来のキーワード判定どおり）に倒す。
レビュー: docs/vertical_spec_review.md §4-A / §5-P5-1。

設計書: grace/doc/agent_support_example.md ／ 業界特化: grace/doc/agent_support_verticals.md
上位計画: docs/migration_and_update.md

前提:
- `.env` に ANTHROPIC_API_KEY（LLM 用）と GOOGLE_API_KEY（Embedding 用）を設定
- Qdrant が起動済み（既定 http://localhost:6333）で RAG コレクションが登録済み

使い方::

    python agent_support_example.py "パスワードを忘れました"
    python agent_support_example.py --vertical gov "住民票の写しの取り方は？"
    python agent_support_example.py --vertical ec "返品したい"        # 本人確認→CONFIRM→ドライラン
    python agent_support_example.py --vertical saas -v "サービスが落ちています"  # 障害→escalate
    python agent_support_example.py --no-dry-run "解約したい"          # 擬似実行（実API連携は将来）
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Literal, Optional

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

# 意図分類（二段判定の第 2 段）:
#   question = 情報・手順・規定を知りたい（FAQ質問） / request = 操作・手続きの実行依頼
#   incident = 障害・被害・トラブルの発生報告
Intent = Literal["question", "request", "incident"]

# 意図分類に使う軽量モデル（CLAUDE.md プロバイダ方針の軽量既定）
INTENT_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class ActionRequest:
    """副作用のある操作の要求（v3・擬似）。"""

    action_type: ActionType
    args: dict = field(default_factory=dict)
    requires_confirmation: bool = True


@dataclass
class VerticalProfile:
    """業界プロファイル（差し替えの共通枠）。設計: agent_support_verticals.md §1/§6。"""

    name: str
    collections: List[str] = field(default_factory=list)   # 検索スコープ（実 Qdrant コレクション名）
    escalate_keywords: List[str] = field(default_factory=list)  # 強制エスカレ語
    action_map: Dict[str, ActionType] = field(default_factory=dict)  # 意図キーワード → action_type
    require_identity: bool = False           # アクション前に本人確認を必須化
    notify_th: Optional[float] = None        # None なら config 既定
    confirm_th: Optional[float] = None
    prompt_addendum: str = ""                # 業界固有の方針（表示・将来のプロンプト注入用）


# 組み込みプロファイル（自治体 / SaaS / EC）
#
# collections は実 Qdrant コレクション名（命名規約 `*_anthropic`。
# docs/vertical_test_data.md 参照）。RAG 検索は config.qdrant.allowed_collections
# 経由でこのスコープに限定される。未登録のコレクションは自動的に無視され、
# 1 つも登録が無い場合は制限なし（既定コレクション横断）で従来どおり動作する。
PROFILES: Dict[str, VerticalProfile] = {
    "gov": VerticalProfile(
        name="自治体",
        # wikipedia_ja は専用コレクション（gov_faq/gov_laws）登録までの代替
        collections=["gov_faq_anthropic", "gov_laws_anthropic", "wikipedia_ja"],
        escalate_keywords=["法的", "訴訟", "減免", "個別", "例外", "不服"],
        action_map={"申請": "send_reply", "手続": "send_reply", "様式": "send_reply"},
        require_identity=False,
        notify_th=0.8, confirm_th=0.5,   # 正確性最優先：厳しめ
        prompt_addendum="条例・公式案内に基づき、断定を避け、該当ページ・担当課を明示。個人情報は尋ねない。",
    ),
    "saas": VerticalProfile(
        name="SaaS",
        collections=["saas_docs_anthropic", "saas_api_anthropic"],
        escalate_keywords=["障害", "ダウン", "落ち", "課金", "請求", "情報漏", "セキュリティ"],
        action_map={"エラー": "create_ticket", "不具合": "create_ticket", "バグ": "create_ticket"},
        require_identity=False,
        prompt_addendum="製品バージョンを明示し、再現手順と公式ドキュメント URL を添える。",
    ),
    "ec": VerticalProfile(
        name="EC",
        collections=["ec_policy_anthropic", "ec_faq_anthropic"],
        escalate_keywords=["決済", "返金", "破損", "クレーム", "不良品"],
        action_map={"返品": "create_ticket", "交換": "create_ticket",
                    "キャンセル": "create_ticket", "解約": "create_ticket"},
        require_identity=True,           # 注文情報の操作は本人確認必須
        prompt_addendum="注文情報の照会・変更は本人確認必須。返品・交換は規定の版に基づいて回答。",
    ),
}


@dataclass
class SupportResult:
    """サポート回答の結果。"""

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
    vertical: Optional[str] = None            # 適用した業界プロファイル
    overall_confidence: float = 0.0
    intent: Optional[Intent] = None           # 意図分類の結果（二段判定が走った場合）
    forced_escalate: bool = False             # エスカレ語による強制エスカレか（KPI 計測用）
    identity_checked: bool = False            # 本人確認ステップが起動したか（KPI 計測用）


def _banner(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def create_intent_classifier(config) -> Callable[[str], Optional[Intent]]:
    """問い合わせ意図の LLM 分類器（軽量モデル・二段判定の第 2 段）を返す。

    返す関数は query を question / request / incident のいずれかへ分類する。
    分類できない場合（API エラー・想定外の出力）は None を返し、呼び出し側が
    安全側（従来のキーワード判定どおり）に倒す。呼び出しはキーワード候補が
    一致したときだけなので、追加コストは軽量モデル 1 呼び出しに限られる。
    """
    from grace.llm_compat import create_chat_client

    client = create_chat_client(config)

    def classify(query: str) -> Optional[Intent]:
        prompt = (
            "あなたはカスタマーサポートの一次受付です。次の問い合わせの意図を 1 語で分類してください。\n\n"
            "- question : 情報・手順・制度・規定を知りたい（FAQ質問。例:「課金プランの違いを教えて」「解約方法を教えて」）\n"
            "- request  : 操作・手続きの実行を依頼したい（例:「返品したい」「解約したい」「申請様式がほしい」）\n"
            "- incident : 障害・被害・トラブルの発生報告（例:「サービスが落ちています」「二重に課金された」「商品が破損していた」）\n\n"
            f"問い合わせ: {query}\n\n"
            "出力（question / request / incident のいずれか 1 語のみ）:"
        )
        try:
            response = client.models.generate_content(
                model=INTENT_MODEL,
                contents=prompt,
                config={"temperature": 0.0, "max_output_tokens": 10},
            )
            text = (response.text or "").strip().lower()
            for label in ("incident", "request", "question"):
                if label in text:
                    return label
            print(f"   [intent] 想定外の分類出力: {text!r} → キーワード判定を優先", file=sys.stderr)
        except Exception as e:
            print(f"   [intent] 意図分類に失敗（{type(e).__name__}）→ キーワード判定を優先", file=sys.stderr)
        return None

    return classify


def _match_keyword(query: str, keywords) -> Optional[str]:
    """キーワード候補の部分一致（二段判定の第 1 段）。最初に一致した語を返す。"""
    for keyword in keywords:
        if keyword in query:
            return keyword
    return None


def _should_force_escalate(
    query: str,
    profile: Optional[VerticalProfile],
    classify: Optional[Callable[[str], Optional[Intent]]] = None,
) -> tuple[bool, Optional[str], Optional[Intent]]:
    """強制エスカレの二段判定。

    第 1 段: `escalate_keywords` の部分一致（候補検出）。
    第 2 段: 意図分類。intent が "question"（FAQ質問）なら誤爆とみなして
    強制エスカレしない（例: SaaS「課金プランの違いを教えて」）。request /
    incident はエスカレ話題への依頼・報告なので設計どおり有人へ倒す
    （例: gov「減免を個別に判断してほしい」）。分類器が無い・分類失敗（None）
    の場合は安全側＝従来どおり強制エスカレする。

    Returns:
        (forced, matched_keyword, intent)
    """
    if profile is None:
        return False, None, None
    matched = _match_keyword(query, profile.escalate_keywords)
    if matched is None:
        return False, None, None
    intent = classify(query) if classify is not None else None
    if intent == "question":
        return False, matched, intent
    return True, matched, intent


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


def _decide_action(
    query: str,
    decision: Decision,
    profile: Optional[VerticalProfile] = None,
    classify: Optional[Callable[[str], Optional[Intent]]] = None,
) -> Optional[ActionRequest]:
    """問い合わせ内容と回答判定から、必要なアクションを決める（二段判定）。

    第 1 段: キーワード一致で候補を検出（プロファイル指定時は `action_map`、
    未指定時はデモ用の既定マッピング）。第 2 段: 意図分類。intent が
    "question"（FAQ質問。例:「解約方法を教えて」）ならアクションは起票せず
    回答のみとする。分類器が無い・分類失敗（None）の場合は従来どおり起票する
    （副作用は後段の CONFIRM でも守られる）。escalate 時は常に有人エスカレ。
    """
    if decision == "escalate":
        return ActionRequest("escalate_to_human", {"query": query})

    request: Optional[ActionRequest] = None
    if profile is not None:
        matched = _match_keyword(query, profile.action_map)
        if matched is not None:
            request = ActionRequest(
                profile.action_map[matched], {"query": query, "matched": matched}
            )
    # 既定（プロファイル無し）
    elif _match_keyword(query, ("解約", "キャンセル", "退会")):
        request = ActionRequest("create_ticket", {"subject": "解約希望", "query": query})
    elif _match_keyword(query, ("パスワード", "ログイン", "サインイン")):
        request = ActionRequest("send_reply", {"template": "password_reset", "query": query})

    if request is None:
        return None
    if classify is not None and classify(query) == "question":
        return None  # FAQ 質問 → 回答のみ（起票・返信テンプレは不要）
    return request


def _perform_action(
    action: ActionRequest,
    handler,
    dry_run: bool,
    require_identity: bool = False,
) -> str:
    """HITL（CONFIRM 承認）を通してから擬似アクションを実行する。

    副作用のある操作は必ず intervention の CONFIRM を経由する。`require_identity`
    が True の業界（EC 等）では本人確認ステップを前置する。承認後、dry_run=True なら
    ログのみ（実行しない）。実 API 連携（Zendesk 等）は将来拡張。
    """
    if require_identity:
        print("   [action] 本人確認が必要な操作です（本デモでは確認済みとして続行）")

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
    vert = f" / vertical={result.vertical}" if result.vertical else ""
    intent = f" / intent={result.intent}" if result.intent else ""
    forced = " / 強制エスカレ" if result.forced_escalate else ""
    print(f"\n[根拠] 支持率(groundedness)={result.groundedness:.2f} / "
          f"全体信頼度={result.overall_confidence:.2f} / decision={result.decision}"
          f" / web={'使用' if result.used_web else '不使用'}{extra}{vert}{intent}{forced}")


def run_support_agent(
    query: str = DEFAULT_QUERY,
    verbose: bool = False,
    use_web: bool = True,
    do_action: bool = True,
    dry_run: bool = True,
    vertical: Optional[str] = None,
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

    # 意図分類器（二段判定の第 2 段）: キーワード候補が一致したときだけ呼ばれる。
    # 同一クエリへの分類は 1 回で済むようメモ化する（エスカレ判定とアクション判定で共有）。
    _raw_classify = create_intent_classifier(config)
    _intent_cache: Dict[str, Optional[Intent]] = {}

    def classify(q: str) -> Optional[Intent]:
        if q not in _intent_cache:
            _intent_cache[q] = _raw_classify(q)
            print(f"  [intent] 意図分類（{INTENT_MODEL}）: {_intent_cache[q] or '不明'}")
        return _intent_cache[q]

    # 業界プロファイル（--vertical）: しきい値・エスカレ語・アクション対応・本人確認を切り替え
    profile = PROFILES.get(vertical) if vertical else None
    notify_th = profile.notify_th if (profile and profile.notify_th is not None) else th.notify
    confirm_th = profile.confirm_th if (profile and profile.confirm_th is not None) else th.confirm

    # コアへの配線: 検索スコープ（rag_search の許可リスト）と業界方針（reasoning へ注入）。
    # tools は config への参照を保持しているため、ここでの設定が実行時に効く。
    config.qdrant.allowed_collections = list(profile.collections) if profile else []
    config.llm.prompt_addendum = profile.prompt_addendum if profile else ""

    if profile is not None:
        _banner(f"業界プロファイル: {profile.name}（--vertical {vertical}）")
        print(f"  検索スコープ: {', '.join(profile.collections) or '—'}"
              "（未登録コレクションは自動的に無視）")
        print(f"  しきい値: notify={notify_th} / confirm={confirm_th} / 本人確認={profile.require_identity}")
        if profile.prompt_addendum:
            print(f"  方針(reasoningへ注入): {profile.prompt_addendum}")

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

    # ④ 回答ゲート（内部）＋ プロファイルのエスカレ語による強制エスカレ
    decision, warning = _answer_gate(
        gres.support_rate, gres.verified, len(internal_citations), notify_th, confirm_th
    )
    forced_escalate, matched_kw, _intent = _should_force_escalate(query, profile, classify)
    if forced_escalate:
        decision, warning = "escalate", False
        print(f"  [profile] エスカレ語 '{matched_kw}'（意図={_intent or '不明'}）を検知 → "
              f"有人対応へ（{profile.name}）")
    elif matched_kw is not None:
        print(f"  [profile] エスカレ語候補 '{matched_kw}' は FAQ 質問（意図=question）→ "
              "誤爆抑止・通常フローを継続")

    support = SupportResult(
        answer=internal_answer,
        citations=internal_citations,
        groundedness=gres.support_rate,
        decision=decision,
        warning=warning,
        vertical=vertical,
        overall_confidence=result.overall_confidence,
    )

    # ⑤ Web フォールバック（内部が escalate かつ 強制エスカレでない場合のみ・v2）
    if decision == "escalate" and use_web and not forced_escalate:
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
                if agreement < confirm_th:
                    contradiction = True
                print(f"  [相互検証] 内部×Web 一致度={agreement:.2f} / 矛盾={contradiction}")

            w_decision, w_warning = _answer_gate(
                gres_web.support_rate, gres_web.verified, len(web_citations),
                notify_th, confirm_th,
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
                vertical=vertical,
                overall_confidence=result.overall_confidence,
            )
        else:
            print("  [web] 有効な検索結果が得られませんでした")
            support.used_web = True

    # ⑥ アクション（v3）: HITL（CONFIRM）を通して擬似実行
    if do_action:
        action = _decide_action(query, support.decision, profile, classify)
        if action is not None:
            _banner("⑥ Action（intervention CONFIRM → 擬似ActionTool）")
            print(f"  [action] 種別={action.action_type}（要承認={action.requires_confirmation}）")
            support.action = action
            require_identity = bool(profile and profile.require_identity)
            support.action_result = _perform_action(
                action, handler, dry_run, require_identity=require_identity,
            )
            support.identity_checked = require_identity
            print(f"  [action] {support.action_result}")

    # KPI 計測用メタデータ（eval/vertical が参照）
    support.forced_escalate = forced_escalate
    support.intent = _intent_cache.get(query)

    # ⑦ 応答
    _render(support)
    return support


def main():
    parser = argparse.ArgumentParser(
        description="GRACE-Support: 内部RAG＋出典／Web裏取り・相互検証／アクション＋HITL／業界特化(--vertical)"
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
        "--vertical", choices=["gov", "saas", "ec"], default=None,
        help="業界プロファイルを適用（gov=自治体 / saas / ec）",
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
            do_action=args.do_action, dry_run=args.dry_run, vertical=args.vertical,
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

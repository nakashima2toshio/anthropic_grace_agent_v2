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

**二段判定（誤検知抑止）**: `escalate_keywords` / `action_map` のキーワード一致は
**候補検出（第 1 段）**であり、一致時のみ軽量 LLM で意図を分類（第 2 段:
question / request / incident）する。FAQ 質問（question。例:「課金プランの違いを
教えて」「解約方法を教えて」）は強制エスカレ・アクション起票の対象外となる。
分類に失敗した場合は安全側（従来のキーワード判定どおり）に倒す。
レビュー: docs/vertical_spec_review.md §4-A / §5-P5-1。

**情報なし回答検知（④' ゲート）**: 「〜は見つかりませんでした」型の誠実な回答は
出典・支持率を伴い回答ゲートを answer で通過してしまうため、定型句（候補検出）＋
軽量 LLM（実質回答か否か）の二段判定で検知し、情報なしなら有人対応へ倒す。
範囲外質問が Web 経由で answer になる 3 業種共通の課題への対処。

**Web 重複実行の排除（⑤）**: executor が動的 Web 検索を使用済みの場合、
⑤ は回答の再生成（reasoning）と相互検証を省略し、内部回答を本文スニペットで
再検証だけ行う（1 ケースあたり十数秒〜の短縮）。

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
from support_actions import create_action_backend, create_identity_verifier

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
    groundedness_decided: int = 0      # 判定できた主張数（supported+contradicted）。0=判定不能（中立）
    decision: Decision = "escalate"
    warning: bool = False              # 中信頼（未確認）の注意書きを付けるか
    used_web: bool = False             # Web を使ったか（executor の動的 Web 検索 or ⑤ フォールバック）
    source_agreement: Optional[float] = None  # 内部×Web の意味的一致度（相互検証）
    contradiction: bool = False        # 矛盾の可能性
    action: Optional[ActionRequest] = None    # 実施（予定）のアクション
    action_result: Optional[str] = None       # アクションの結果メッセージ
    vertical: Optional[str] = None            # 適用した業界プロファイル
    overall_confidence: float = 0.0
    intent: Optional[Intent] = None           # 意図分類の結果（二段判定が走った場合）
    forced_escalate: bool = False             # エスカレ語による強制エスカレか（KPI 計測用）
    identity_checked: bool = False            # 本人確認ステップが起動したか（KPI 計測用）
    no_info_detected: bool = False            # 「情報なし回答」検知で escalate に倒したか
    web_reused: bool = False                  # ⑤ で executor の Web 結果を再利用したか（重複推論の省略）


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


# 「情報なし回答」の候補検出パターン（第 1 段）。誠実な回答ほど
# 「〜は見当たりませんでした」と明言するため、回答ゲート（支持率・出典数）を
# answer で通過してしまう。定型句はあくまで候補検出であり、最終判定は
# 第 2 段の LLM（実質回答か否か）が行う（実質回答の補足として同じ句が
# 現れるケースがあるため。例: 返品規定の回答末尾の「弊社固有の規定は
# 見当たりませんでした」）。活用差を吸収するため語幹で照合する。
NO_INFO_MARKERS = (
    "見当たりません",
    "見つかりません",
    "確認できません",
    "確認ができません",
    "情報がありません",
    "情報はありません",
)


def create_no_info_judge(config) -> Callable[[str, str], Optional[bool]]:
    """「情報なし回答」の LLM 判定器（軽量モデル・二段判定の第 2 段）を返す。

    返す関数は (query, answer) を受け、回答が質問の中心的な事柄に実質的に
    答えていれば False（answered）、「見つからない・お問い合わせください」に
    留まるなら True（no_info）を返す。判定できない場合（API エラー・想定外の
    出力）は None を返し、呼び出し側が安全側（escalate）に倒す。呼び出しは
    NO_INFO_MARKERS が一致したとき、または出典が Web のみ（社内根拠ゼロ）の
    回答に限られるので、追加コストは軽量モデル 1 呼び出しに留まる。
    """
    from grace.llm_compat import create_chat_client

    client = create_chat_client(config)

    def judge(query: str, answer: str) -> Optional[bool]:
        prompt = (
            "あなたはカスタマーサポートの品質チェック担当です。"
            "次の回答が、質問されたトピックに実質的に答えているかを判定してください。\n\n"
            "- answered : 質問されたトピックについて実質的な内容（規定・手順・条件・料金の目安・\n"
            "  一般的なルールなど）を 1 つでも提供している。一般論・参考情報ベースの回答でもよい。\n"
            "  「弊社固有の情報は見当たらなかった」という断り書きがあっても、本体が内容を\n"
            "  提供していれば answered。制度や仕組みの説明を求める一般知識の質問に、公的情報を\n"
            "  根拠として定義・特徴を説明する回答も answered。\n"
            "- no_info  : 質問された事柄そのもの（日付・金額・可否・内容）について実質的な情報が\n"
            "  ゼロで、「見つからない・確認できない」という報告と、確認方法の案内・他窓口への\n"
            "  誘導・他社や一般サイトの事例紹介だけで構成されている。\n"
            "  「質問された事柄そのもの」と「それをどこで確認できるかの案内」は区別すること。\n"
            "  後者だけの回答は、案内が丁寧でも no_info。\n"
            "  また、質問が将来の予測・見通しを求めており、回答が確定情報ではなく要望・検討段階の\n"
            "  情報の紹介に留まる（「確定した内容ではない」等の注記つき）場合も no_info\n"
            "  （不確実な予測は有人対応に回すべきため）。\n\n"
            "判定例:\n"
            "- 質問「返品規定を教えて」に、一般的な返品ルール（30日以内・法定8日等）を提示し、\n"
            "  末尾で「弊社固有の規定は見当たりませんでした」と断る回答 → answered\n"
            "- 質問「送料はいくら？」に、一般的な料金の目安表を提示する回答 → answered\n"
            "- 質問「〜とはどんな制度ですか？」に、公的サイトを根拠として制度の目的・対象・\n"
            "  手続きを説明する回答 → answered\n"
            "- 質問「この商品の入荷予定日は？」に、日付を一切示せず、「商品ページで確認できる\n"
            "  場合がある」等の一般的な確認方法の案内と問い合わせ先への誘導のみの回答 → no_info\n"
            "- 質問「来年の〜の予測は？」に、確定情報ではない要望・検討段階の情報を紹介し、\n"
            "  「正式に確定した内容ではない」と注記する回答 → no_info\n\n"
            f"質問: {query}\n\n回答:\n{answer}\n\n"
            "出力（answered / no_info のいずれか 1 語のみ）:"
        )
        try:
            response = client.models.generate_content(
                model=INTENT_MODEL,
                contents=prompt,
                config={"temperature": 0.0, "max_output_tokens": 10},
            )
            text = (response.text or "").strip().lower()
            if "no_info" in text or "no-info" in text:
                return True
            if "answered" in text:
                return False
            print(f"   [no-info] 想定外の判定出力: {text!r} → 安全側（escalate）", file=sys.stderr)
        except Exception as e:
            print(f"   [no-info] 実質回答判定に失敗（{type(e).__name__}）→ 安全側（escalate）", file=sys.stderr)
        return None

    return judge


def _detect_no_info_answer(
    query: str,
    answer: str,
    judge: Optional[Callable[[str, str], Optional[bool]]] = None,
    force_judge: bool = False,
) -> tuple[bool, Optional[str]]:
    """「情報なし回答」の二段判定（docs/vertical_spec_review.md の残課題①）。

    第 1 段: NO_INFO_MARKERS の部分一致（候補検出）。不一致なら LLM は呼ばず False。
    第 2 段: LLM 判定。実質回答（answered）なら False、no_info なら True。
    判定器が無い場合は従来どおり回答を通す（False）。判定失敗（None）は
    誤答を届けるより有人へ回す方が安全なので True（escalate）に倒す。

    force_judge=True（出典が Web のみ＝社内根拠ゼロの回答）の場合は、候補句が
    一致しなくても第 2 段の LLM 判定を必ず実施する。社内根拠ゼロの回答は
    「確認方法の案内だけ」「非確定の予測情報の紹介だけ」でも候補句を含まない
    ことがあり、answer で通過してしまうため（out-of-scope × 動的 Web 検索）。

    Returns:
        (no_info, matched_marker)
    """
    marker = _match_keyword(answer or "", NO_INFO_MARKERS)
    if marker is None and not (force_judge and answer):
        return False, None
    if judge is None:
        return False, marker
    verdict = judge(query, answer)
    if verdict is False:
        return False, marker
    return True, marker


def _should_force_escalate(
    query: str,
    profile: Optional[VerticalProfile],
    classify: Optional[Callable[[str], Optional[Intent]]] = None,
) -> tuple[bool, Optional[str], Optional[Intent]]:
    """強制エスカレの二段判定。

    第 1 段: `escalate_keywords` の部分一致（候補検出）。
    第 2 段: 意図分類。intent が "question"（FAQ質問）なら誤検知とみなして
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


def _pick_groundedness(*results) -> tuple[float, int]:
    """複数の GroundednessResult から (支持率, 判定できた主張数) を選ぶ純関数。

    支持率が最大の検証結果を採用し、その decided（supported+contradicted）を
    併せて返す。同率の場合は decided が多い方（判定の裏付けが強い方）を選ぶ。
    KPI 側で「支持率が低い」と「判定不能（decided=0）」を区別するために使う。
    """
    return max(
        (g.support_rate, g.supported + g.contradicted) for g in results
    )


def _should_rescue_unaffirmed(
    decision: Decision,
    forced_escalate: bool,
    has_contradiction: bool,
    citation_count: int,
    answer: str,
    query: str,
    no_info_judge: Optional[Callable[[str, str], Optional[bool]]] = None,
) -> bool:
    """出典付き・非「情報なし」・矛盾なしの内部回答を escalate から救うか。

    `_answer_gate` の支持率は supported/decided で算出されるため、根拠検証器
    （Haiku）の出力ぶれで、出典付きの良質な内部RAG回答でも escalate に倒れる:
      - 全 neutral（decided=0）や JSON 崩れ（verified=False）→ 支持率 0.0
      - 一部だけ肯定（例 supported=1 / contradicted=2 → 0.33 < confirm_th）
    いずれも「肯定の裏付けが弱い」だけで、**矛盾は検出されていない**。放置すると
    ⑤ の Web 二次生成へ流れ、無関係な一般Web結果から「情報なし」回答に化けて
    誤エスカレする（ec「返金ポリシー」「送料」/ saas「レート制限」で顕在化）。

    そこで支持数の多寡ではなく「矛盾がないか」で判定する。以下をすべて満たす
    ときだけ救済（answer 継続。未確認注記付き）を許可する:
      - gate 判定が escalate かつ 強制エスカレでない（エスカレ語は最優先で維持）
      - 矛盾が検出されていない（矛盾ありは安全側に倒し従来どおり escalate）
      - 出典が 1 件以上あり、回答本文が空でない
      - その回答が実質回答である（範囲外の「情報なし」回答は除外＝従来どおり
        escalate。例: saas「来期の売上見込み」/ ec「入荷予定日」）
    """
    if decision != "escalate" or forced_escalate:
        return False
    if has_contradiction or citation_count == 0 or not answer:
        return False
    return not _detect_no_info_answer(query, answer, no_info_judge)[0]


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
    backend,
    identity_verifier=None,
    identity: Optional[Dict[str, str]] = None,
) -> str:
    """本人確認 → HITL（CONFIRM 承認）→ バックエンド実行 の順でアクションを行う。

    - 本人確認（identity_verifier 指定時）: 提示された識別子を照合し、未確認なら
      アクションを実行せず有人対応へ引き継ぐ（安全側）
    - CONFIRM: 副作用のある操作は必ず intervention の承認を経由する
    - 実行: backend（dry-run / webhook / pseudo）に委譲（support_actions.py）
    """
    if identity_verifier is not None:
        result = identity_verifier.verify(identity)
        status = "確認済み" if result.verified else "未確認"
        print(f"   [action] 本人確認（{result.method}）: {status} — {result.detail}")
        if not result.verified:
            return (f"本人確認が完了しないため '{action.action_type}' は実行せず、"
                    "有人対応へ引き継ぎます")

    # intervention.py: 実行前に人間の承認（CONFIRM）を求める
    decision = ActionDecision(
        level=InterventionLevel.CONFIRM,
        confidence_score=0.5,
        reason=f"アクション実行前の確認: {action.action_type}",
    )
    response = handler.handle(decision)
    if not response.should_continue:
        return f"アクション '{action.action_type}' はキャンセルされました"

    outcome = backend.execute(action.action_type, action.args)
    return outcome.message


def _collect_citations(step_results) -> List[str]:
    """各ステップの sources を重複排除して出典リストにする。

    executor は RAG スコア不足時に web_search を**動的挿入**するため、
    step_results には Web 由来の出典（URL）が混ざる。URL は [Web]、
    それ以外（社内ナレッジのファイル名等）は [社内] とラベル付けする。
    """
    seen: List[str] = []
    for sr in step_results:
        for src in sr.sources:
            if not src:
                continue
            prefix = "[Web]" if str(src).startswith(("http://", "https://")) else "[社内]"
            label = f"{prefix} {src}"
            if label not in seen:
                seen.append(label)
    return seen


def _citation_text(citation: str) -> str:
    """出典表示文字列（"[社内] xxx" / "[Web] xxx"）からラベルを外して中身を返す。"""
    return citation.split("] ", 1)[1] if "] " in citation else citation


def _merge_citations(internal: List[str], web: List[str]) -> List[str]:
    """内部出典と ⑤ の Web 出典を重複なく結合する。

    executor が動的 Web 検索を使った場合、同じ URL が内部側（"[Web] URL"）と
    ⑤ 側（"[Web] タイトル（URL）"）の両形式で並ぶため、URL の包含で重複排除する。
    """
    merged = list(internal)
    internal_texts = [_citation_text(c) for c in internal]
    for citation in web:
        if any(text and text in citation for text in internal_texts):
            continue
        merged.append(citation)
    return merged


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
    no_info = " / 情報なし回答検知" if result.no_info_detected else ""
    reused = " / Web再利用" if result.web_reused else ""
    print(f"\n[根拠] 支持率(groundedness)={result.groundedness:.2f} / "
          f"全体信頼度={result.overall_confidence:.2f} / decision={result.decision}"
          f" / web={'使用' if result.used_web else '不使用'}{extra}{vert}{intent}{forced}{no_info}{reused}")


def run_support_agent(
    query: str = DEFAULT_QUERY,
    verbose: bool = False,
    use_web: bool = True,
    do_action: bool = True,
    dry_run: bool = True,
    vertical: Optional[str] = None,
    identity: Optional[Dict[str, str]] = None,
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

    # 「情報なし回答」判定器（④' ゲートの第 2 段）: 候補句が一致したときだけ呼ばれる
    _raw_no_info_judge = create_no_info_judge(config)

    def no_info_judge(q: str, a: str) -> Optional[bool]:
        verdict = _raw_no_info_judge(q, a)
        label = {True: "no_info", False: "answered", None: "判定失敗"}[verdict]
        print(f"  [no-info] 実質回答判定（{INTENT_MODEL}）: {label}")
        return verdict

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
    internal_citations = _collect_citations(result.step_results)
    # executor が動的挿入した web_search（RAG スコア不足時）の使用を検知
    used_dynamic_web = any(c.startswith("[Web]") for c in internal_citations)
    for sr in result.step_results:
        print(f"  step{sr.step_id}: {sr.status} (sources={len(sr.sources)})")
    if used_dynamic_web:
        print("  [web] executor が動的 Web 検索を使用（RAG スコア不足のため）")

    # ③ 根拠評価（内部）
    _banner("③ Confidence（GroundednessVerifier: 内部回答の裏付け）")
    gres = verifier.verify(query, internal_answer, [_citation_text(c) for c in internal_citations])
    if verbose:
        print(f"  [groundedness] supported={gres.supported} / total={gres.total} / "
              f"contradiction={gres.has_contradiction} / verified={gres.verified}")
    print(f"  [groundedness] 支持率={gres.support_rate:.2f}"
          f"（判定可能 {gres.supported + gres.contradicted}/{gres.total} 主張）"
          f" / 出典数={len(internal_citations)}")

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
              "誤検知抑止・通常フローを継続")

    # ④-救済: 出典付き・非「情報なし」・矛盾なしの内部回答が、groundedness を
    # 「肯定できなかった」というだけで escalate に落ち、⑤ の Web 二次生成で
    # 「情報なし」回答に化けて ④' で誤エスカレするのを防ぐ（ec「返金ポリシー」で
    # 顕在化）。範囲外の「情報なし」回答は除外され従来どおり escalate（saas 等）。
    if _should_rescue_unaffirmed(
        decision, forced_escalate, gres.has_contradiction,
        len(internal_citations), internal_answer, query, no_info_judge,
    ):
        decision, warning = "answer", True
        print("  [gate] groundedness の裏付けは弱いが矛盾なし・出典付きの実質回答 → "
              "answer（未確認注記）として維持し、無駄な Web 二次生成・誤エスカレを回避")

    support = SupportResult(
        answer=internal_answer,
        citations=internal_citations,
        groundedness=gres.support_rate,
        groundedness_decided=gres.supported + gres.contradicted,
        decision=decision,
        warning=warning,
        used_web=used_dynamic_web,
        vertical=vertical,
        overall_confidence=result.overall_confidence,
    )

    # ⑤ Web フォールバック（内部が escalate かつ 強制エスカレでない場合のみ・v2）
    #
    # executor が動的 Web 検索を使用済みの場合、内部回答は既に同一クエリの
    # Web 結果から生成されている。内部ゲートで escalate になる主因は
    # groundedness 検証が出典ラベル（URL 文字列）にしか当たらないことなので、
    # 回答を作り直す（reasoning 再実行）のではなく、内部回答を本文スニペットで
    # **再検証だけ**行う（重複していた Web 検索→推論の 2 周目を省略。
    # 1 ケースあたり十数秒〜の短縮）。
    if decision == "escalate" and use_web and not forced_escalate:
        _banner("⑤ Web フォールバック（tools.web_search → reasoning → 相互検証）")
        reuse_internal = used_dynamic_web and bool(internal_answer)
        if reuse_internal:
            print("  executor が同一クエリで Web 検索済み → 内部回答を再利用し、"
                  "本文スニペットで再検証のみ実施（重複推論を省略）")
        else:
            print("  内部ナレッジの根拠が不足 → Web で裏取りを試みます")
        web_res = tool_registry.execute("web_search", query=query)
        web_output = web_res.output if (web_res and web_res.success) else None

        if web_output:
            if reuse_internal:
                web_answer = internal_answer
            else:
                web_reason = tool_registry.execute("reasoning", query=query, sources=web_output)
                web_answer = (web_reason.output or "") if (web_reason and web_reason.success) else ""
            web_citations = _web_citations(web_output)
            print(f"  [web] {len(web_citations)} 件の出典を取得")

            gres_web = verifier.verify(query, web_answer, _web_source_texts(web_output))
            agreement: Optional[float] = None
            contradiction = gres_web.has_contradiction
            # 相互検証は「独立に生成した 2 つの回答」の比較。再利用時は
            # 同一回答の比較になり無意味（常に一致）なのでスキップする。
            if not reuse_internal and internal_answer and web_answer:
                agreement = agreement_calc.calculate([internal_answer, web_answer])
                if agreement < confirm_th:
                    contradiction = True
                print(f"  [相互検証] 内部×Web 一致度={agreement:.2f} / 矛盾={contradiction}")

            w_decision, w_warning = _answer_gate(
                gres_web.support_rate, gres_web.verified, len(web_citations),
                notify_th, confirm_th,
            )
            g_rate, g_decided = _pick_groundedness(gres, gres_web)
            support = SupportResult(
                answer=web_answer if w_decision == "answer" else internal_answer,
                citations=_merge_citations(internal_citations, web_citations),
                groundedness=g_rate,
                groundedness_decided=g_decided,
                decision=w_decision,
                warning=w_warning,
                used_web=True,
                web_reused=reuse_internal,
                source_agreement=agreement,
                contradiction=contradiction,
                vertical=vertical,
                overall_confidence=result.overall_confidence,
            )
        else:
            print("  [web] 有効な検索結果が得られませんでした")
            support.used_web = True

    # ④' 「情報なし回答」検知ゲート（docs/vertical_spec_review.md の残課題①）:
    # 誠実な「見つかりませんでした」型の回答は出典・支持率を伴ってゲートを
    # answer で通過してしまう（範囲外質問で顕在化）。二段判定で実質回答か
    # を確かめ、情報なしなら有人対応へ倒す。
    if support.decision == "answer" and support.answer:
        # 出典が Web のみ（社内コレクション根拠ゼロ）の回答は、候補句がなくても
        # ④' 判定を必須にする（out-of-scope × 動的 Web 検索の answer 化対策）
        web_only = bool(support.citations) and all(
            c.startswith("[Web]") for c in support.citations
        )
        no_info, marker = _detect_no_info_answer(
            query, support.answer, no_info_judge, force_judge=web_only,
        )
        if no_info:
            trigger = f"候補句 '{marker}'" if marker is not None else "出典が Web のみ"
            print(f"  [gate] 情報なし回答を検知（{trigger}）→ 有人対応へエスカレーション")
            support.decision = "escalate"
            support.warning = False
            support.no_info_detected = True
        elif marker is not None or web_only:
            trigger = f"情報なし候補句 '{marker}' はあるが" if marker is not None else "出典が Web のみだが"
            print(f"  [gate] {trigger}実質回答（answered）→ 回答を維持")

    # ⑥ アクション（v3）: 本人確認 → HITL（CONFIRM）→ バックエンド実行
    if do_action:
        action = _decide_action(query, support.decision, profile, classify)
        if action is not None:
            backend = create_action_backend(dry_run=dry_run)
            _banner(f"⑥ Action（本人確認 → intervention CONFIRM → ActionTool[{backend.name}]）")
            print(f"  [action] 種別={action.action_type}（要承認={action.requires_confirmation}）")
            support.action = action
            require_identity = bool(profile and profile.require_identity)
            identity_verifier = (
                create_identity_verifier(dry_run=dry_run) if require_identity else None
            )
            support.action_result = _perform_action(
                action, handler, backend,
                identity_verifier=identity_verifier, identity=identity,
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
        help="アクションを実行せずログのみ（既定 ON。--no-dry-run で実連携/擬似実行）",
    )
    parser.add_argument(
        "--identity", action="append", default=None, metavar="KEY=VALUE",
        help="本人確認の識別子（例: --identity order_id=1001 --identity email=a@example.com。"
             "--no-dry-run 時に SUPPORT_IDENTITY_FILE の台帳と照合）",
    )
    args = parser.parse_args()

    identity: Optional[Dict[str, str]] = None
    if args.identity:
        identity = dict(
            pair.split("=", 1) for pair in args.identity if "=" in pair
        )

    try:
        run_support_agent(
            args.query, verbose=args.verbose, use_web=args.use_web,
            do_action=args.do_action, dry_run=args.dry_run, vertical=args.vertical,
            identity=identity,
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

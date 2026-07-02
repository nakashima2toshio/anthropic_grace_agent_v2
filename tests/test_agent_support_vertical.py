# tests/test_agent_support_vertical.py
"""agent_support_example の業界特化ロジック（純関数）の単体テスト。

API キー・Qdrant 不要。意図分類器はスタブ（Callable）を注入する。
対象: _answer_gate / _match_keyword / _should_force_escalate / _decide_action。
特に「キーワード部分一致の誤爆」（docs/vertical_spec_review.md §4-A）が
二段判定で抑止されることを固定する。
"""
from types import SimpleNamespace

import pytest

from agent_support_example import (
    NO_INFO_MARKERS,
    PROFILES,
    _answer_gate,
    _citation_text,
    _collect_citations,
    _decide_action,
    _detect_no_info_answer,
    _match_keyword,
    _merge_citations,
    _should_force_escalate,
)

GOV = PROFILES["gov"]
SAAS = PROFILES["saas"]
EC = PROFILES["ec"]


def classify_as(label):
    """常に固定ラベルを返すスタブ分類器（label=None は分類失敗を模す）。"""
    return lambda _query: label


def classifier_must_not_be_called(_query):
    """キーワード候補が無いとき分類器（=LLM 呼び出し）が走らないことの検査用。"""
    raise AssertionError("キーワード不一致なのに意図分類器が呼ばれた")


class TestAnswerGate:
    """回答ゲート（既存純関数）の境界値。"""

    def test_high_confidence_answers_without_warning(self):
        assert _answer_gate(0.8, True, 2, 0.7, 0.4) == ("answer", False)

    def test_mid_confidence_answers_with_warning(self):
        assert _answer_gate(0.5, True, 1, 0.7, 0.4) == ("answer", True)

    def test_low_confidence_escalates(self):
        assert _answer_gate(0.3, True, 1, 0.7, 0.4) == ("escalate", False)

    def test_unverified_or_no_citation_escalates(self):
        assert _answer_gate(0.9, False, 2, 0.7, 0.4) == ("escalate", False)
        assert _answer_gate(0.9, True, 0, 0.7, 0.4) == ("escalate", False)


class TestMatchKeyword:
    def test_returns_first_matched_keyword(self):
        assert _match_keyword("課金が二重になっています", SAAS.escalate_keywords) == "課金"

    def test_returns_none_when_no_match(self):
        assert _match_keyword("住民票の写しの取り方は？", GOV.escalate_keywords) is None


class TestShouldForceEscalate:
    """強制エスカレの二段判定（キーワード候補 → 意図分類）。"""

    def test_keyword_trap_question_is_not_forced(self):
        # §4-A の誤爆例: in-scope の FAQ 質問が「課金」で強制エスカレしてはならない
        forced, matched, intent = _should_force_escalate(
            "課金プランの違いを教えて", SAAS, classify_as("question")
        )
        assert forced is False
        assert matched == "課金"
        assert intent == "question"

    def test_incident_report_is_forced(self):
        forced, matched, intent = _should_force_escalate(
            "サービスが落ちています", SAAS, classify_as("incident")
        )
        assert forced is True
        assert matched == "落ち"
        assert intent == "incident"

    def test_request_on_escalate_topic_is_forced(self):
        # gov「個別事情は必ず有人」: エスカレ話題への依頼（request）は有人へ
        forced, matched, _ = _should_force_escalate(
            "固定資産税の減免を個別に判断してほしい", GOV, classify_as("request")
        )
        assert forced is True
        assert matched in ("減免", "個別")

    def test_classifier_failure_falls_back_to_keyword(self):
        # 分類失敗（None）は安全側＝従来どおり強制エスカレ
        forced, _, intent = _should_force_escalate(
            "返金ポリシーを教えて", EC, classify_as(None)
        )
        assert forced is True
        assert intent is None

    def test_no_classifier_keeps_legacy_behavior(self):
        forced, matched, intent = _should_force_escalate("決済が失敗しました", EC, None)
        assert forced is True
        assert matched == "決済"
        assert intent is None

    def test_no_keyword_does_not_call_classifier(self):
        forced, matched, intent = _should_force_escalate(
            "住民票の写しの取り方は？", GOV, classifier_must_not_be_called
        )
        assert (forced, matched, intent) == (False, None, None)

    def test_no_profile_is_never_forced(self):
        assert _should_force_escalate("決済が失敗しました", None, classify_as("incident")) == (
            False, None, None,
        )


class TestDecideAction:
    """アクション判定の二段判定（起票の誤爆抑止）。"""

    def test_faq_question_does_not_fire_profile_action(self):
        # §4-A の誤爆例: 「解約手続きの流れを教えて」は EC action_map の『解約』に
        # 一致するが、FAQ 質問なので起票しない
        assert _decide_action(
            "解約手続きの流れを教えて", "answer", EC, classify_as("question")
        ) is None

    def test_request_fires_profile_action(self):
        action = _decide_action("返品したい", "answer", EC, classify_as("request"))
        assert action is not None
        assert action.action_type == "create_ticket"
        assert action.args["matched"] == "返品"

    def test_incident_report_fires_ticket(self):
        action = _decide_action(
            "500 エラーが出る不具合を報告したい", "answer", SAAS, classify_as("incident")
        )
        assert action is not None
        assert action.action_type == "create_ticket"

    def test_escalate_decision_always_escalates_to_human(self):
        action = _decide_action("何でもいい質問", "escalate", EC, classifier_must_not_be_called)
        assert action is not None
        assert action.action_type == "escalate_to_human"

    def test_default_map_question_is_suppressed(self):
        # プロファイル無しの既定マッピングにも二段判定を適用
        assert _decide_action("解約方法を教えて", "answer", None, classify_as("question")) is None

    def test_default_map_request_fires_ticket(self):
        action = _decide_action("解約したい", "answer", None, classify_as("request"))
        assert action is not None
        assert action.action_type == "create_ticket"

    def test_without_classifier_keeps_legacy_behavior(self):
        # 後方互換: 分類器なしなら従来どおりキーワードで起票する
        action = _decide_action("解約方法を教えて", "answer", None, None)
        assert action is not None
        assert action.action_type == "create_ticket"

    def test_classifier_failure_falls_back_to_keyword(self):
        action = _decide_action("返品したい", "answer", EC, classify_as(None))
        assert action is not None
        assert action.action_type == "create_ticket"

    def test_no_keyword_returns_none_without_classifier_call(self):
        assert _decide_action(
            "送料はいくらかかりますか？", "answer", EC, classifier_must_not_be_called
        ) is None


class TestCollectCitations:
    """出典ラベリング。executor が動的挿入した web_search の URL を [Web] と表示する
    （URL が [社内] と誤表示され『web=不使用』と矛盾するバグの回帰テスト）。"""

    def test_urls_are_labeled_web_and_files_internal(self):
        step_results = [
            SimpleNamespace(sources=["qa_pairs_cc_news.csv"]),
            SimpleNamespace(sources=[
                "https://www.city.kobe.lg.jp/genmen.html",
                "http://example.jp/faq",
            ]),
        ]
        assert _collect_citations(step_results) == [
            "[社内] qa_pairs_cc_news.csv",
            "[Web] https://www.city.kobe.lg.jp/genmen.html",
            "[Web] http://example.jp/faq",
        ]

    def test_deduplicates_and_skips_empty(self):
        step_results = [
            SimpleNamespace(sources=["a.csv", "", "a.csv"]),
            SimpleNamespace(sources=["a.csv"]),
        ]
        assert _collect_citations(step_results) == ["[社内] a.csv"]

    def test_citation_text_strips_both_labels(self):
        assert _citation_text("[社内] a.csv") == "a.csv"
        assert _citation_text("[Web] https://x.jp/") == "https://x.jp/"
        assert _citation_text("ラベルなし") == "ラベルなし"


def judge_as(verdict):
    """常に固定判定を返すスタブ判定器（verdict=None は判定失敗を模す）。"""
    return lambda _query, _answer: verdict


def judge_must_not_be_called(_query, _answer):
    """候補句が無いとき判定器（=LLM 呼び出し）が走らないことの検査用。"""
    raise AssertionError("情報なし候補句が無いのに実質回答判定が呼ばれた")


class TestDetectNoInfoAnswer:
    """「情報なし回答」検知の二段判定（④' ゲート）。

    範囲外質問（例: ec「この商品の入荷予定日はいつですか？」）への誠実な
    「見つかりませんでした」型回答が answer としてゲートを通過するバグの回帰テスト。
    """

    # ライブ実行ログ（logs/vertical_ec2）の実回答を模したテキスト
    NO_INFO_ANSWER = (
        "申し訳ございませんが、ご質問の商品に関する具体的な入荷予定日は、"
        "提供された情報源には見当たりませんでした。\n"
        "正確な入荷予定日については、担当窓口をご確認ください。"
    )
    SUBSTANTIVE_WITH_MARKER = (
        "Amazon は商品到着から30日以内の返品・交換に対応しています。"
        "法律上は8日以内が法定ルールです。\n"
        "なお、弊社固有の返品規定については情報源には見当たりませんでした。"
    )
    PLAIN_ANSWER = "住民票の写しはマイナンバーカードがあればコンビニでも取得できます。"

    def test_no_marker_returns_false_without_judge_call(self):
        # 定型句が無ければ LLM 判定は走らない（コスト・誤爆ゼロ）
        no_info, marker = _detect_no_info_answer(
            "住民票の取り方は？", self.PLAIN_ANSWER, judge_must_not_be_called
        )
        assert (no_info, marker) == (False, None)

    def test_marker_and_no_info_verdict_escalates(self):
        no_info, marker = _detect_no_info_answer(
            "この商品の入荷予定日はいつですか？", self.NO_INFO_ANSWER, judge_as(True)
        )
        assert no_info is True
        assert marker == "見当たりません"

    def test_marker_but_substantive_answer_is_kept(self):
        # 実質回答の補足に定型句が現れるケース（返品規定の回答末尾など）は answer 維持
        no_info, marker = _detect_no_info_answer(
            "返品規定を教えて", self.SUBSTANTIVE_WITH_MARKER, judge_as(False)
        )
        assert no_info is False
        assert marker == "見当たりません"

    def test_judge_failure_falls_back_to_escalate(self):
        # 判定失敗（None）は安全側＝escalate（誤答を届けるより有人へ）
        no_info, _ = _detect_no_info_answer("Q", self.NO_INFO_ANSWER, judge_as(None))
        assert no_info is True

    def test_no_judge_keeps_legacy_behavior(self):
        # 判定器なし（LLM を使わない構成）は従来どおり回答を通す
        no_info, marker = _detect_no_info_answer("Q", self.NO_INFO_ANSWER, None)
        assert no_info is False
        assert marker == "見当たりません"

    def test_empty_answer_is_not_flagged(self):
        assert _detect_no_info_answer("Q", "", judge_must_not_be_called) == (False, None)

    @pytest.mark.parametrize("marker", NO_INFO_MARKERS)
    def test_markers_match_polite_inflections(self, marker):
        # 語幹照合なので「〜でした」等の活用でも候補になる
        assert _match_keyword(f"申し訳ありませんが{marker}でした。", NO_INFO_MARKERS) == marker


class TestMergeCitations:
    """⑤ の出典結合。executor の動的 Web 検索と ⑤ の再検索で同じ URL が
    "[Web] URL" と "[Web] タイトル（URL）" の両形式で重複するのを防ぐ。"""

    def test_deduplicates_same_url_across_formats(self):
        internal = ["[社内] qa.csv", "[Web] https://x.jp/faq"]
        web = ["[Web] よくある質問（https://x.jp/faq）", "[Web] 新情報（https://y.jp/）"]
        assert _merge_citations(internal, web) == [
            "[社内] qa.csv",
            "[Web] https://x.jp/faq",
            "[Web] 新情報（https://y.jp/）",
        ]

    def test_keeps_all_when_no_overlap(self):
        internal = ["[社内] a.csv"]
        web = ["[Web] t（https://z.jp/）"]
        assert _merge_citations(internal, web) == ["[社内] a.csv", "[Web] t（https://z.jp/）"]

    def test_empty_inputs(self):
        assert _merge_citations([], []) == []
        assert _merge_citations([], ["[Web] t（https://z.jp/）"]) == ["[Web] t（https://z.jp/）"]


class TestProfiles:
    """組み込みプロファイルの健全性。"""

    @pytest.mark.parametrize("name", ["gov", "saas", "ec"])
    def test_profile_has_escalate_keywords_and_action_map(self, name):
        profile = PROFILES[name]
        assert profile.escalate_keywords
        assert profile.action_map

    def test_ec_requires_identity(self):
        assert EC.require_identity is True
        assert GOV.require_identity is False

# ============================================================
# 実行例（uv run）:
#   uv run python grace/step_trace/s9_render.py
#   ※ 引数は取らず、gov 代表例の SupportResult を組み立てて _render で整形表示（LLM・Qdrant 不要）。
#     saas / ec も整形処理（_render）は共通で、build_sample() の値（answer/citations/vertical 等）が
#     変わるだけ。saas/ec の表示を見たい場合は build_sample() の vertical と本文を差し替える。
# ============================================================
# grace/step_trace/s9_render.py
"""S9. ⑦ 応答整形（SupportResult → _render）。

`support.forced_escalate` / `support.intent` を確定し、`_render(support)` で
回答本文＋出典一覧＋根拠メタ行を整形表示する S9 トレース用スタブ。
各ステップ（S3〜S8）で少しずつ埋まった同一 SupportResult の最終形を、
gov 代表例の値で組み立てて表示する（LLM・Qdrant 不要）。

uv run python grace/step_trace/s9_render.py
"""
from __future__ import annotations

import argparse

from _trace import banner, ipo

import agent_support_example as ase


def build_sample() -> "ase.SupportResult":
    """flow.md §3「データの積み上がり（SupportResult 最終形）」の gov 代表例。"""
    return ase.SupportResult(
        answer=(
            "住民票の写しは、お住まいの市区町村の窓口（市民課等）またはコンビニ交付・"
            "郵送で請求できます。本人確認書類が必要です。詳しくは担当課の案内ページを"
            "ご確認ください。"
        ),
        citations=[
            "[社内] gov_faq_anthropic/住民票.md",
            "[社内] gov_faq_anthropic/窓口案内.md",
        ],
        groundedness=0.86,
        groundedness_decided=3,
        decision="answer",
        warning=False,
        used_web=False,
        vertical="gov",
        overall_confidence=0.78,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="S9: ⑦ 応答整形 トレース")
    parser.parse_args()

    banner("S9. ⑦ 応答整形（_render → SupportResult 返却）")

    support = build_sample()
    # run_support_agent の末尾と同じ確定処理（KPI メタ）
    support.forced_escalate = False
    support.intent = None  # gov in-scope は意図分類器が未発火のため None

    ipo(
        in_="support（S3〜S8 で確定した SupportResult）",
        process=(
            "support.forced_escalate / support.intent を確定した後、\n"
            "_render(support) が回答本文＋出典一覧＋根拠メタ行を整形表示し、\n"
            "run_support_agent() が support を return"
        ),
        out=(
            f"decision={support.decision!r}, groundedness={support.groundedness}, "
            f"vertical={support.vertical!r}, intent={support.intent!r}\n"
            "端末表示（下記）＋ 呼び出し元へ SupportResult を返却"
        ),
    )

    # 実際の整形表示（agent_support_example._render をそのまま使用）
    ase._render(support)


if __name__ == "__main__":
    main()

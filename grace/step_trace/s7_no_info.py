# ============================================================
# 実行例（uv run）:
#   uv run python grace/step_trace/s7_no_info.py "住民票の写しの取り方は？"
#   uv run python grace/step_trace/s7_no_info.py --web-only "この商品の入荷予定日は？"
#   uv run python grace/step_trace/s7_no_info.py --answer "該当する情報が見当たりません" "在庫は？"
# ============================================================
# grace/step_trace/s7_no_info.py
"""S7. ④' 情報なし回答検知。

`_detect_no_info_answer(query, answer, judge, force_judge=web_only)` を取り出した
S7 トレース用スタブ。第 1 段は定型句（NO_INFO_MARKERS）候補検出、第 2 段は
軽量 LLM（answered/no_info）。出典が Web のみ（社内根拠ゼロ）の回答は
force_judge=True で候補句がなくても必須判定する。

gov 代表例は [社内] 出典を含み、回答に候補句も無いため web_only=False・候補なし
→ LLM 未実行 → no_info=False（answer 維持）。

uv run python grace/step_trace/s7_no_info.py "住民票の写しの取り方は？"
uv run python grace/step_trace/s7_no_info.py --web-only "この商品の入荷予定日は？"
"""
from __future__ import annotations

import argparse

from _trace import banner, have_key, ipo

import agent_support_example as ase
from grace import get_config

# gov 代表例（実質回答・[社内] 出典あり）
SAMPLE_ANSWER = (
    "住民票の写しは、市区町村の窓口（市民課等）・コンビニ交付・郵送で請求できます。"
    "本人確認書類が必要です。"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="S7: ④' 情報なし回答検知 トレース")
    parser.add_argument("query", nargs="?", default="住民票の写しの取り方は？")
    parser.add_argument("--answer", default=SAMPLE_ANSWER, help="検証する回答本文")
    parser.add_argument("--web-only", action="store_true",
                        help="出典が Web のみ（force_judge=True）として必須判定させる")
    args = parser.parse_args()

    banner("S7. ④' 情報なし回答検知（_detect_no_info_answer）")

    config = get_config()
    no_info_judge = ase.create_no_info_judge(config) if have_key() else None

    # 第 1 段（候補検出）は LLM 不要なので、先に marker だけ確認して見せる
    marker = ase._match_keyword(args.answer, ase.NO_INFO_MARKERS)
    web_only = args.web_only

    no_info, matched = ase._detect_no_info_answer(
        args.query, args.answer, no_info_judge, force_judge=web_only
    )

    ipo(
        in_=(f'query={args.query!r}, answer[:40]={args.answer[:40]!r},\n'
             f'force_judge(web_only)={web_only}, judge={"あり" if no_info_judge else "None"}'),
        process=(
            "第1段: _match_keyword(answer, NO_INFO_MARKERS) で候補句を検出\n"
            "  → 候補なし かつ not force_judge なら (False, None)（LLM 未実行）\n"
            "第2段: judge(query, answer) で answered/no_info を判定\n"
            "  → answered なら (False, marker)、no_info/判定失敗なら (True, marker)（安全側 escalate）"
        ),
        out=(
            f"第1段の候補句 marker={marker!r}\n"
            f"(no_info, matched_marker) = ({no_info}, {matched!r})"
        ),
    )

    if no_info:
        trigger = f"候補句 '{matched}'" if matched is not None else "出典が Web のみ"
        print(f"\n  [gate] 情報なし回答を検知（{trigger}）→ 有人対応へエスカレーション")
    else:
        print("\n  [gate] 実質回答（answered）→ decision='answer' を維持")


if __name__ == "__main__":
    main()

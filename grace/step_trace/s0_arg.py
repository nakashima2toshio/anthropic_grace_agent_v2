from __future__ import annotations

import argparse
import pprint

# .env から ANTHROPIC_API_KEY / GOOGLE_API_KEY 等を読み込む（未導入でも続行）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_QUERY = "パスワードを忘れました"

# -----
# S0. 起動・引数解釈（main()→run_support_agent）
# uv run python agent_support_example.py --vertical gov "住民票の写しの取り方は？"
# uv run python grace/step_trace/s0_arg.py --vertical gov "住民票の写しの取り方は？"
#
# 本スクリプトは agent_support_example.py の main() のうち「引数解釈」だけを
# 取り出した S0 トレース用スタブ。argparse がどんな args を作るかを確認する。
# -----


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

    # pprint.pprint(object, stream=None, ...) の第 2 引数は「出力先ストリーム」。
    # ラベルは print で先に出し、対象は単独で pprint する（ラベルと同時に渡さない）。
    print()
    print("parser=:")
    pprint.pprint(parser)
    print("args=:")
    pprint.pprint(vars(args))   # Namespace は vars() で dict 化すると読みやすい


if __name__ == "__main__":
    main()

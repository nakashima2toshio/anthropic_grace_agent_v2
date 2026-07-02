#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
register_test_collections.py - 業界特化テストコレクションの一括登録
====================================================================
docs/vertical_test_data.md §5 の「専用コレクション登録」を 1 コマンドで行う。

`eval/vertical/data/*.csv` に収録した合成 Q&A（規約・FAQ の疑似データ）を、
各業界プロファイル（agent_support_example.py の PROFILES）が参照する
実 Qdrant コレクション（`*_anthropic`）へ登録する。

| 業界 | コレクション | データ |
|---|---|---|
| ec   | ec_policy_anthropic / ec_faq_anthropic   | eval/vertical/data/ec_policy.csv / ec_faq.csv |
| saas | saas_docs_anthropic / saas_api_anthropic | eval/vertical/data/saas_docs.csv / saas_api.csv |
| gov  | gov_faq_anthropic / gov_laws_anthropic   | eval/vertical/data/gov_faq.csv / gov_laws.csv |

データ設計（docs/vertical_test_data.md §2 の 5 条件に準拠）:
- eval/vertical/cases/*.jsonl の in-scope / keyword-trap 質問に「社内根拠」を与える
- out-of-scope 質問（入荷予定日・来期売上見込み・税制改正予測 等）は意図的に
  カバーしない（「穴」を残し escalate 分岐を検証可能に保つ）

前提: Qdrant 起動済み・.env に GOOGLE_API_KEY（Gemini embedding 用）。

使用例:
    # 全業界を登録（既存コレクションは再作成）
    uv run python -m eval.vertical.register_test_collections --recreate

    # EC のみ
    uv run python -m eval.vertical.register_test_collections --vertical ec --recreate

登録後の再計測:
    uv run python -m eval.vertical.run --vertical ec --report logs/vertical_ec.json
"""

import argparse
import sys
from pathlib import Path

# リポジトリルートを import パスに追加（qa_qdrant/ services/ を解決）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DATA_DIR = Path(__file__).resolve().parent / "data"

# 業界 → [(コレクション名, データCSV)]。
# コレクション名は agent_support_example.PROFILES の collections と一致させること
# （tests/eval/test_register_test_collections.py が整合を検証する）。
VERTICAL_COLLECTIONS: dict[str, list[tuple[str, str]]] = {
    "ec": [
        ("ec_policy_anthropic", "ec_policy.csv"),
        ("ec_faq_anthropic", "ec_faq.csv"),
    ],
    "saas": [
        ("saas_docs_anthropic", "saas_docs.csv"),
        ("saas_api_anthropic", "saas_api.csv"),
    ],
    "gov": [
        ("gov_faq_anthropic", "gov_faq.csv"),
        ("gov_laws_anthropic", "gov_laws.csv"),
    ],
}


def register_vertical(
    vertical: str,
    recreate: bool = False,
    max_docs: int | None = None,
    provider: str = "gemini",
) -> bool:
    """1 業界分のコレクションを登録する。全コレクション成功で True。"""
    # 実行時依存（pandas / qdrant / embedding）は呼び出し時に解決する
    from qa_qdrant.register_to_qdrant import register_to_qdrant

    ok = True
    for collection, csv_name in VERTICAL_COLLECTIONS[vertical]:
        csv_path = DATA_DIR / csv_name
        print(f"\n=== [{vertical}] {collection} ← {csv_path.name} ===")
        success = register_to_qdrant(
            input_file=str(csv_path),
            collection_name=collection,
            recreate=recreate,
            max_docs=max_docs,
            provider=provider,
            create_ui_csv=False,
        )
        ok = ok and success
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(
        description="業界特化テストコレクション（*_anthropic）を Qdrant に一括登録する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--vertical",
        choices=[*VERTICAL_COLLECTIONS.keys(), "all"],
        default="all",
        help="登録する業界（既定: all）",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="既存コレクションを削除して再作成する",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        help="登録する最大件数（テスト用）",
    )
    parser.add_argument(
        "--provider",
        default="gemini",
        help="Embedding プロバイダー（既定: gemini / gemini-embedding-001 3072次元）",
    )
    args = parser.parse_args()

    verticals = list(VERTICAL_COLLECTIONS.keys()) if args.vertical == "all" else [args.vertical]

    all_ok = True
    for vertical in verticals:
        all_ok = register_vertical(
            vertical,
            recreate=args.recreate,
            max_docs=args.max_docs,
            provider=args.provider,
        ) and all_ok

    if all_ok:
        targets = ", ".join(verticals)
        print(f"\n✅ 登録完了: {targets}")
        print("   再計測: uv run python -m eval.vertical.run --vertical <業界> --report logs/vertical_<業界>.json")
        return 0
    print("\n❌ 一部のコレクション登録に失敗しました。ログを確認してください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

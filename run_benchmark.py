"""GRACE ベンチマーク実行スクリプト

使用例::

    # フルベンチマーク（全12クエリ × 3回）
    python run_benchmark.py

    # 高速完了モード（代表5クエリ × 1回）
    python run_benchmark.py --fast

    # コレクション・試行回数を指定
    python run_benchmark.py --collection cc_news_2per_anthropic --runs 2

    # 特定クエリだけ実行
    python run_benchmark.py --query-id Q01 --query-id Q11

    # 先頭3クエリだけ / クエリ一覧の確認
    python run_benchmark.py --limit 3
    python run_benchmark.py --list
"""
from __future__ import annotations

import argparse

from grace.benchmark import BENCHMARK_QUERIES, FAST_QUERY_IDS, BenchmarkRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GRACE エージェントのベンチマークを実行する",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--fast", action="store_true",
        help=f"高速完了モード。代表クエリ {FAST_QUERY_IDS} のみを1回ずつ実行する",
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="各クエリの試行回数（--fast 指定時は未指定なら1に短縮）",
    )
    parser.add_argument(
        "--collection", type=str, default=None,
        help="検索対象の Qdrant コレクション名（例: cc_news_2per_anthropic）",
    )
    parser.add_argument(
        "--query-id", action="append", dest="query_ids", default=None,
        metavar="ID", help="実行するクエリID（複数指定可。例: --query-id Q01 --query-id Q03）",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="先頭から実行するクエリ件数",
    )
    parser.add_argument(
        "--max-replans", type=int, default=None,
        help="リプラン上限の上書き（未指定かつ --fast なら1）",
    )
    parser.add_argument(
        "--restrict-collection", dest="restrict_collection",
        action=argparse.BooleanOptionalAction, default=None,
        help="RAG検索を単一コレクションに限定（--collection 指定推奨）。"
             "未指定かつ --fast なら有効",
    )
    parser.add_argument(
        "--mode", choices=["grace", "react", "both"], default="grace",
        help="評価する主機能: grace(Plan+Executor) / react(ReAct+Reflection) / "
             "both(両方式を横並び比較)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="クエリ一覧を表示して終了する（実行しない）",
    )
    return parser


def _print_query_list() -> None:
    print("=" * 78)
    print(f"{'ID':<5}{'Case':<5}{'Level':<8}{'Category':<12}{'Path':<28}Text")
    print("-" * 78)
    for q in BENCHMARK_QUERIES:
        fast_mark = "★" if q["id"] in FAST_QUERY_IDS else " "
        print(
            f"{q['id']:<5}{q.get('case', ''):<5}{q.get('level', ''):<8}"
            f"{q.get('category', ''):<12}{q.get('path', ''):<28}"
            f"{fast_mark} {q['text'][:28]}"
        )
    print("-" * 78)
    print(f"★ = 高速完了モード（--fast）対象: {FAST_QUERY_IDS}")
    print("=" * 78)


def main() -> None:
    args = _build_parser().parse_args()

    if args.list:
        _print_query_list()
        return

    runner = BenchmarkRunner(qdrant_collection=args.collection)
    sessions = runner.run_query_set(
        runs_per_query=args.runs,
        fast=args.fast,
        query_ids=args.query_ids,
        limit=args.limit,
        max_replans=args.max_replans,
        restrict_collection=args.restrict_collection,
        mode=args.mode,
    )
    speed = "FAST" if args.fast else "FULL"
    # route_correct の集計（採点済みセッションのみ対象）
    scored = [s for s in sessions if s.route_correct is not None]
    if scored:
        correct = sum(1 for s in scored if s.route_correct)
        rate = correct / len(scored) * 100
        print(f"\n経路一致率(route_correct): {correct}/{len(scored)} = {rate:.1f}%")
    print(
        f"完了[{speed}|mode={args.mode}]: {len(sessions)} セッション "
        f"-> {runner.bm_logger.csv_path}"
    )


if __name__ == "__main__":
    main()

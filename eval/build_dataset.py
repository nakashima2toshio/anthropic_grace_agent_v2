"""eval/dataset.jsonl を Qdrant コレクションから生成する。

対象コレクション（既定）: cc_news_2per_anthropic
各ポイントの payload {"question", "answer", "source"} から
正解付き評価データを構築する。

出力 (1行=1レコード, JSON):
    {
      "id": <point_id>,
      "question": "<質問>",
      "gold_answer": "<正解>",
      "allowed_sources": ["<source ファイル名>"],
      "source_point_id": <point_id>
    }

使い方:
    python -m eval.build_dataset \
        --collection cc_news_2per_anthropic \
        --limit 100 \
        --output eval/dataset.jsonl

Qdrant が稼働している環境で実行すること（QDRANT_HOST/PORT or QDRANT_URL）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

# 既存資産を再利用（v1/v2 共通の Qdrant ラッパ）。
# モジュール配置が異なる場合はこの import を環境に合わせて調整する。
try:
    from qdrant_client_wrapper import get_qdrant_client
except Exception as exc:  # pragma: no cover - 環境依存
    print(
        "ERROR: qdrant_client_wrapper.get_qdrant_client を import できません。\n"
        "       GRACE 本体と同じ作業ツリーで実行しているか、import パスを確認してください。\n"
        f"       詳細: {exc}",
        file=sys.stderr,
    )
    raise


DEFAULT_COLLECTION = "cc_news_2per_anthropic"
DEFAULT_LIMIT = 100
DEFAULT_OUTPUT = "eval/dataset.jsonl"


def _scroll_points(client: Any, collection: str, limit: int) -> list[Any]:
    """コレクションから最大 limit 件のポイントを取得する。"""
    points: list[Any] = []
    next_offset = None
    # 大きすぎる page を避けつつ limit まで取得
    page = min(limit, 256) if limit > 0 else 256
    while True:
        batch, next_offset = client.scroll(
            collection_name=collection,
            limit=page,
            with_payload=True,
            with_vectors=False,
            offset=next_offset,
        )
        points.extend(batch)
        if limit > 0 and len(points) >= limit:
            return points[:limit]
        if next_offset is None or not batch:
            return points


def _record_from_point(point: Any) -> dict[str, Any] | None:
    payload = getattr(point, "payload", None) or {}
    question = payload.get("question")
    answer = payload.get("answer")
    if not question or not answer:
        return None
    source = payload.get("source")
    return {
        "id": point.id,
        "question": str(question).strip(),
        "gold_answer": str(answer).strip(),
        "allowed_sources": [source] if source else [],
        "source_point_id": point.id,
    }


def build(collection: str, limit: int, output: str) -> int:
    """dataset.jsonl を生成し、書き出した件数を返す。"""
    client = get_qdrant_client()
    points = _scroll_points(client, collection, limit)
    # 再現性のため id 昇順で並べる（上位 N の定義を安定化）
    points.sort(key=lambda p: (str(type(p.id)), p.id))

    records: list[dict[str, Any]] = []
    skipped = 0
    for p in points:
        rec = _record_from_point(p)
        if rec is None:
            skipped += 1
            continue
        records.append(rec)
        if limit > 0 and len(records) >= limit:
            break

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(
        f"[build_dataset] collection={collection} "
        f"written={len(records)} skipped(no q/a)={skipped} -> {output}"
    )
    return len(records)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build eval dataset from a Qdrant collection")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="取得する上位件数（0 で全件）")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    n = build(args.collection, args.limit, args.output)
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

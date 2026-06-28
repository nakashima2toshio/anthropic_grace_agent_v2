# agent_example.py
"""GRACE エージェントの最小実行サンプル。

planner（計画生成）→ executor（confidence/calibration/intervention/replan/memory を
内部統括）の一連の流れを 1 クエリで実行する。

前提:
- `.env` に ANTHROPIC_API_KEY（LLM 用）と GOOGLE_API_KEY（Embedding 用）を設定
- Qdrant が起動済み（既定 http://localhost:6333）で RAG コレクションが登録済み

使い方::

    uv run python agent_example.py
    uv run python agent_example.py "東京タワーの高さは？"
"""
from __future__ import annotations

import argparse
import os
import sys

from grace import (
    create_executor,
    create_planner,
    create_tool_registry,
    get_config,
)

# .env から ANTHROPIC_API_KEY / GOOGLE_API_KEY 等を読み込む（未導入でも続行）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_QUERY = "日本の再生可能エネルギー政策の最新動向を教えて"


def run_agent(query: str = DEFAULT_QUERY):
    # 0. APIキーの存在チェック（未設定だと LLM 呼び出しで失敗する）
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️ ANTHROPIC_API_KEY が未設定です。.env に設定してください。", file=sys.stderr)
        return None

    # 1. 設定の取得
    config = get_config()

    # 2. ツールレジストリと各エージェントの初期化
    tool_registry = create_tool_registry(config)
    planner = create_planner(config)
    executor = create_executor(config, tool_registry)  # confidence/calibration/intervention/replan/memory を内部初期化

    # 3. 計画の生成（planner.py）
    print(f"❓ 質問: {query}")
    plan = planner.create_plan(query)
    print(f"📋 計画: {len(plan.steps)} ステップ (complexity={plan.complexity:.2f})")

    # 4. 計画の実行（executor.py が全コンポーネントを統括）
    result = executor.execute(plan)

    # 5. 結果の確認
    print("-" * 60)
    print(f"最終回答: {result.final_answer}")
    print(f"全体信頼度（較正済み）: {result.overall_confidence:.2f}")
    print(f"ステータス: {result.overall_status}")
    return result


def main():
    parser = argparse.ArgumentParser(description="GRACE エージェントの最小実行サンプル")
    parser.add_argument(
        "query", nargs="?", default=DEFAULT_QUERY,
        help="エージェントに尋ねる質問（省略時は既定の質問を使用）",
    )
    args = parser.parse_args()

    try:
        run_agent(args.query)
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

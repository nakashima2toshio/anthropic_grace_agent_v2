from __future__ import annotations

import argparse
import pprint
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

# -----
# S0. 起動・引数解釈（main()→run_support_agent）
# uv run python agent_support_example.py --vertical gov "住民票の写しの取り方は？"
# uv run python grace/step_trace/s0_arg.py --vertical gov "住民票の写しの取り方は？"
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

# grace/step_trace/_trace.py
"""step_trace 共通ヘルパ（S1〜S9 のトレース用スタブが共有）。

各 `sN_*.py` は `agent_support_example.py` の `run_support_agent()` の 1 ステップだけを
取り出し、**IN → Process → OUT** の 3 段で標準出力に示す
（`grace/doc/agent_support_example_flow.md` §2 の読み方に対応）。

- 実コード（`grace` / `agent_support_example`）をそのまま呼ぶため、環境
  （`ANTHROPIC_API_KEY` / Qdrant）があれば **本物のデータ**でトレースする。
- 環境が無い場合は各スタブが用意する**代表サンプル**（フロー図の gov 例）で
  ステップの構造（IN/Process/OUT の形）だけを示し、鍵が要る箇所はスキップする。

使い方::
    uv run python grace/step_trace/s1_profile.py --vertical gov "住民票の写しの取り方は？"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# repo root（grace/step_trace/ から 2 つ上）を import パスへ追加し、
# agent_support_example.py / grace / support_actions を解決できるようにする。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# .env から ANTHROPIC_API_KEY / GOOGLE_API_KEY 等を読み込む（未導入でも続行）
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def banner(title: str) -> None:
    """agent_support_example._banner と同じ体裁の見出し。"""
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def ipo(in_: str, process: str, out: str) -> None:
    """IN → Process → OUT を 7 桁ラベル揃えで表示する（フロー図 §2 の体裁）。"""
    for label, body in (("IN", in_), ("Process", process), ("OUT", out)):
        lines = str(body).rstrip("\n").split("\n")
        print(f"{label:<7}: {lines[0]}")
        for extra in lines[1:]:
            print(f"{'':<7}  {extra}")


def have_key() -> bool:
    """LLM 呼び出しに必要な ANTHROPIC_API_KEY があるか。"""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def note_no_key(step: str) -> None:
    print(f"\n⚠️ ANTHROPIC_API_KEY 未設定のため {step} の実呼び出しはスキップし、"
          "代表サンプルで構造のみ表示します。")

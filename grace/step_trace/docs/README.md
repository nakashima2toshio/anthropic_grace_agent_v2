# step_trace ドキュメント索引

**Version 1.0** | 最終更新: 2026-07-09

`grace/step_trace/` のトレース用スタブ群（`agent_support_example.py` の `run_support_agent()` を
S0〜S9 の 1 ステップずつに分解し、**IN → Process → OUT** を標準出力に示すツール）の
モジュールドキュメント一覧。各 doc は「概要 / 責務 / 1. アーキテクチャ構成図（回答判定フロー） /
2. 回答ポリシー（groundedness ゲート） / 7. プログラム構成（実装済み関数 ＋ IPO 詳細） /
7.6 クラス・関数 IPO 詳細 / 8. CLI 仕様 / 変更履歴」で統一されている。

## ステップ対応表

| ステップ | モジュール | ドキュメント | フロー図ノード | 役割 |
|---------|-----------|------------|--------------|------|
| S0 | `s0_arg.py` | [s0_arg.md](./s0_arg.md) | `Q` | 起動・引数解釈（argparse 入口） |
| S1 | `s1_profile.py` | [s1_profile.md](./s1_profile.md) | `PROF` | 業界プロファイル適用（gov/saas/ec を config へ配線） |
| S2 | `s2_plan.py` | [s2_plan.md](./s2_plan.md) | `CLS` | ① Plan（質問分類・計画） |
| S3 | `s3_execute.py` | [s3_execute.md](./s3_execute.md) | `RAG` | ② Execute（内部 RAG → reasoning） |
| S4 | `s4_confidence.py` | [s4_confidence.md](./s4_confidence.md) | `GND` | ③ Confidence（支持率評価） |
| S5 | `s5_gate.py` | [s5_gate.md](./s5_gate.md) | `GATE` | ④ 回答ゲート＋強制エスカレ（二段判定） |
| S6 | `s6_web.py` | [s6_web.md](./s6_web.md) | `WEB` | ⑤ Web フォールバック（escalate 時のみ） |
| S7 | `s7_no_info.py` | [s7_no_info.md](./s7_no_info.md) | `NOINFO` | ④' 情報なし回答検知 |
| S8 | `s8_action.py` | [s8_action.md](./s8_action.md) | `ACT` | ⑥ Action（本人確認→CONFIRM→実行） |
| S9 | `s9_render.py` | [s9_render.md](./s9_render.md) | `OUT` | ⑦ 応答整形（SupportResult） |

## 共通事項

- 各スタブは**実コード（`grace` / `agent_support_example`）をそのまま呼ぶ**。`ANTHROPIC_API_KEY` /
  Qdrant があれば本物のデータでトレースし、無ければ代表サンプルで IN/Process/OUT の構造だけを示す。
- 共有ヘルパ `_trace.py`（`banner` / `ipo` / `have_key` / `note_no_key` / `quiet_logs`）を全 sN が使用。
  `quiet_logs()` が実行基盤・`httpx` の INFO ログを抑制する（`GRACE_TRACE_VERBOSE=1` で従来通り表示）。
- 実行例（全ステップ共通の書式）:
  ```bash
  uv run python grace/step_trace/s1_profile.py --vertical gov "住民票の写しの取り方は？"
  uv run python grace/step_trace/s4_confidence.py --vertical saas "APIのレート制限は？"
  ```

## 関連ドキュメント

- 設計書: [`../../doc/agent_support_example.md`](../../doc/agent_support_example.md)
- 1 コマンド実行トレース: [`../../doc/agent_support_example_flow.md`](../../doc/agent_support_example_flow.md)
- 業界特化の全体設計: [`../../doc/agent_support_verticals.md`](../../doc/agent_support_verticals.md)

## 変更履歴

| バージョン | 変更内容 |
|-----------|---------|
| 1.0 | 初版。S0〜S9 の 10 モジュール doc と本索引を作成（2026-07-09） |

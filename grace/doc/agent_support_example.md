# agent_support_example.py - 日本語ナレッジ駆動サポート・コパイロット（GRACE-Support）設計書

**Version 0.1（設計フェーズ・未実装）** | 最終更新: 2026-06-28

> **参考ドキュメント**
> - [`docs/migration_and_update.md`](../../docs/migration_and_update.md) — 需要分析と GRACE-Support 採用方針（本設計の上位資料）
> - [`grace/doc/grace_core_flow.md`](./grace_core_flow.md) — 5 段階設計・8 コアモジュール・プロンプト/API 発行部
> - [`grace/doc/agent_example_core8.md`](./agent_example_core8.md) — コア 8 モジュール明示利用サンプルの設計書
> - [`grace/doc/grace_core.md`](./grace_core.md) — コアモジュール群の横断アーキテクチャ

---

## 目次

- [概要](#概要)
- [1. アーキテクチャ構成図（回答判定フロー）](#1-アーキテクチャ構成図回答判定フロー)
- [2. 回答ポリシー（groundedness ゲート）](#2-回答ポリシーgroundedness-ゲート)
- [3. データ契約（schemas 追加案）](#3-データ契約schemas-追加案)
- [4. 新規ツール ActionTool 仕様](#4-新規ツール-actiontool-仕様)
- [5. HITL ポリシー](#5-hitl-ポリシー)
- [6. 処理シーケンス](#6-処理シーケンス)
- [7. 想定プログラム構成（関数）](#7-想定プログラム構成関数)
- [8. CLI 仕様](#8-cli-仕様)
- [9. 評価指標（KPI）](#9-評価指標kpi)
- [10. 実装ロードマップ](#10-実装ロードマップ)
- [11. 変更履歴](#11-変更履歴)

---

## 概要

`agent_support_example.py`（仮称 **GRACE-Support**）は、既存の日本語 RAG 自律エージェント（GRACE）を土台に、**カスタマーサポート／社内ナレッジ・コパイロット**へ拡張する応用サンプルの設計書である。

一言でいうと——**「社内ナレッジで答え、足りなければ Web で裏取りし、出典を必ず示し、“わからない/行動が要る”ときは人間に渡す、日本語サポート AI」**。

> 📝 本書は**設計フェーズ（未実装）**の仕様書である。実装は段階的（v1 → v3、§10）に行う。既存モジュール（planner/executor/confidence/calibration/memory/intervention/replan/tools）は流用し、**新規追加は「回答ゲート」「Web フォールバックの明示化」「ActionTool」の 3 点**に限定する。

### 主な責務

- 質問を 3 分類（FAQ 即答／要調査／要対応アクション）して計画を立てる
- 内部 RAG で回答し、**出典（citation）を必ず提示**する
- 根拠不足なら**「わかりません」と誠実に答える**（ハルシネーション抑制）
- 内部知識が不足するときのみ **Web 調査へフォールバック**し、複数ソースを相互検証する
- 副作用のある操作（チケット起票・返信・エスカレーション）は **HITL 承認（CONFIRM）を必須**とする
- 解決履歴・エスカレーション履歴を memory に蓄積し、次回の計画へ反映する

### 使用するモジュール対応

| 分類 | モジュール | この用途での役割 |
|------|-----------|----------------|
| 既存 | `planner.py` | 質問 3 分類 → 計画生成 |
| 既存 | `executor.py` | ステップ実行・動的フォールバック統括 |
| 既存 | `tools.py` | `RAGSearchTool` / `WebSearchTool` / `ReasoningTool` / `AskUserTool` |
| 既存 | `confidence.py` | `GroundednessVerifier`（支持率）/ `SourceAgreementCalculator`（ソース一致） |
| 既存 | `calibration.py` | 信頼度の温度較正 |
| 既存 | `intervention.py` | 出典不足→ESCALATE、行動前→CONFIRM |
| 既存 | `replan.py` | 内部 0 件→Web、矛盾→再検索 |
| 既存 | `memory.py` | 解決/エスカレ履歴の学習 |
| **新規** | `ActionTool`（tools へ追加） | チケット起票・返信・エスカレの**擬似アクション**（既定ドライラン） |
| **新規** | `SupportResult`（schemas へ追加） | 回答・出典・判定・アクションの薄いラッパー |

---

## 1. アーキテクチャ構成図（回答判定フロー）

RAG 回答を **groundedness（支持率）でゲート**し、状態に応じて「回答／Web 調査／確認／エスカレ／アクション」へ分岐する。

```mermaid
flowchart TB
    Q(["ユーザー問い合わせ"])
    CLS["① Plan: 質問分類<br>planner.py（FAQ/調査/要対応）"]
    RAG["② Execute: 内部RAG検索<br>tools.RAGSearchTool"]
    GND["③ Confidence: 支持率評価<br>confidence.GroundednessVerifier"]
    GATE{"回答ゲート<br>支持率 × 出典数"}

    ANS["出典つき回答<br>（SILENT/NOTIFY）"]
    WARN["回答＋未確認の注意<br>（CONFIRM 任意）"]
    WEB["⑤ Replan: Webフォールバック<br>tools.WebSearchTool＋相互検証"]
    ESC["④ Intervention: 有人エスカレ<br>intervention ESCALATE"]

    ACT{"要対応アクション？"}
    HITL["④ Intervention: 承認要求<br>CONFIRM（人間承認）"]
    DO["ActionTool 実行<br>（既定ドライラン=ログ）"]

    OUT(["SupportResult を返す"])

    Q --> CLS --> RAG --> GND --> GATE
    GATE -->|"高: 支持率>=0.7 かつ 出典>=1"| ANS
    GATE -->|"中: 0.4-0.7"| WARN
    GATE -->|"低/0件"| WEB
    WEB -->|"裏取り成功"| ANS
    WEB -->|"なお不足"| ESC
    ANS --> ACT
    WARN --> ACT
    ACT -->|"必要"| HITL --> DO --> OUT
    ACT -->|"不要"| OUT
    ESC --> OUT
classDef default fill:#000,stroke:#fff,color:#fff
class Q,CLS,RAG,GND,GATE,ANS,WARN,WEB,ESC,ACT,HITL,DO,OUT default
```

---

## 2. 回答ポリシー（groundedness ゲート）

`GroundednessVerifier` の**支持率(support_rate)**と**出典数**で分岐する。しきい値は既存 `config.confidence.thresholds`（`silent=0.9 / notify=0.7 / confirm=0.4`）を流用する。

| 状態 | 条件（例） | decision | 振る舞い |
|------|-----------|----------|---------|
| **自信あり** | 支持率 ≥ 0.7 かつ 出典 ≥ 1 | `answer` | 出典つきで自動回答（SILENT/NOTIFY） |
| **要注意** | 0.4 ≤ 支持率 < 0.7 | `answer`（注意付） | 回答＋「未確認の注意書き」、必要なら CONFIRM |
| **わからない** | 支持率 < 0.4 または 出典 0 | `escalate` 前に Web | 「社内ナレッジには見当たりません」→ Web 調査 → なお不足なら ESCALATE |

> **設計意図**: 「根拠のない断定を構造的に出さない」ことを最優先にする。既存の `GroundednessVerifier`（回答を主張に分解し supported/contradicted/neutral を判定）をそのまま利用し、支持率が低い＝出典で裏付けられない回答は**自動的に“わからない”へ倒す**。

---

## 3. データ契約（schemas 追加案）

既存 `ExecutionResult` を包む薄いラッパーとして `SupportResult` を追加する（Pydantic）。

```text
Citation
  - source: str            # 出典（ファイル名 / URL）
  - kind: "internal" | "web"
  - collection: Optional[str]   # 内部の場合のコレクション名
  - score: float           # 類似度 / 関連度

ActionRequest
  - action_type: "create_ticket" | "send_reply" | "escalate_to_human"
  - args: dict             # 起票内容・宛先など
  - requires_confirmation: bool = True   # 副作用は原則 True

SupportResult（ExecutionResult をラップ）
  - answer: Optional[str]          # 最終回答（出典つき）。escalate 時は None 可
  - citations: list[Citation]      # 提示した出典
  - groundedness: float            # 支持率 (0.0-1.0)
  - decision: "answer" | "ask" | "escalate" | "action"
  - action: Optional[ActionRequest]  # v3: 実行/承認対象
  - overall_confidence: float      # 較正済み全体信頼度
  - execution: ExecutionResult     # 元の実行結果（step_results 等）
```

---

## 4. 新規ツール ActionTool 仕様

副作用のある操作を担う。**既定はドライラン（実行せずログ出力）**で、学習・検証を安全に行う。

| 項目 | 内容 |
|------|------|
| クラス | `ActionTool(BaseTool)`（`grace/tools.py` へ追加、`ToolRegistry` に opt-in 登録） |
| `name` | `action`（`PlanStep.action` に `"action"` を追加、または `create_ticket` 等の細分） |
| メソッド | `execute(action_type: str, args: dict, dry_run: bool = True) -> ToolResult` |
| 対応アクション | `create_ticket` / `send_reply` / `escalate_to_human` |
| 安全策 | ① 実行前に **CONFIRM 必須**（intervention 経由）② `dry_run=True` ならログのみ ③ 対象・引数を `confidence_factors` に残す |
| 既定 | `config.tools.enabled` には**含めない**（`code_execute` と同様の opt-in） |

> セキュリティ方針は既存 `CodeExecuteTool`（静的チェック＋資源制限＋opt-in）に倣う。実 API 連携（Zendesk / メール等）は将来拡張とし、MVP では擬似実装。

---

## 5. HITL ポリシー

| トリガー | 介入レベル | 挙動 |
|---------|-----------|------|
| 副作用のあるアクション実行前 | **CONFIRM** | 人間承認を得るまで実行しない |
| 出典不足・低信頼（支持率 < 0.4） | **ESCALATE** | 有人対応へ引き継ぎ、AI は回答を断定しない |
| 中信頼（0.4–0.7） | NOTIFY | 回答するが「未確認」を明示 |
| 高信頼（≥ 0.7・出典あり） | SILENT/NOTIFY | 自動回答 |

- 非対話 CLI では、CONFIRM/ESCALATE のコールバックを**自動承認＋ログ**（`--dry-run` 既定）にして安全に検証する。
- UI 連携時は実際の確認ダイアログ（`intervention.ConfirmationFlow`）に差し替える。

---

## 6. 処理シーケンス

```mermaid
%%{ init: { "theme": "base", "themeVariables": {
  "background": "#000000", "mainBkg": "#000000",
  "textColor": "#ffffff", "lineColor": "#ffffff",
  "actorBkg": "#000000", "actorTextColor": "#ffffff",
  "actorLineColor": "#ffffff", "noteBkgColor": "#000000",
  "noteTextColor": "#ffffff", "noteBorderColor": "#ffffff" } } }%%
sequenceDiagram
    participant U as "ユーザー"
    participant S as "run_support_agent()"
    participant PL as "planner.py"
    participant EX as "executor.py"
    participant CO as "confidence.py"
    participant IN as "intervention.py"
    participant AC as "ActionTool（新規）"

    U->>S: 問い合わせ
    S->>PL: 分類 + create_plan
    PL-->>S: ExecutionPlan
    S->>EX: execute(plan)（内部RAG→必要ならWeb）
    EX-->>S: ExecutionResult + sources
    S->>CO: GroundednessVerifier.verify(answer, sources)
    CO-->>S: 支持率 / 出典
    alt 支持率>=0.7 かつ 出典>=1
        Note over S: decision=answer（出典つき回答）
    else 支持率<0.4 または 出典0
        S->>IN: ESCALATE（有人へ）
        Note over S: decision=escalate
    end
    opt 要対応アクション
        S->>IN: CONFIRM（人間承認）
        IN-->>S: 承認
        S->>AC: execute(action_type, args, dry_run=True)
        AC-->>S: ToolResult（ログ）
    end
    S-->>U: SupportResult
```

---

## 7. 想定プログラム構成（関数）

`agent_example.py` / `agent_example_core8.py` と同じ CLI 作法（`.env`＋鍵ガード＋`argparse main()`＋`try/except`＋`if __name__`）。

| 関数 | 概要（設計） |
|------|-------------|
| `run_support_agent(query, dry_run=True, verbose=False)` | 分類 → 計画 → 実行 → 回答ゲート → （必要なら）Web/エスカレ/アクション → `SupportResult` を返す |
| `_answer_gate(groundedness, citations)` | 支持率・出典数から `decision`（answer/ask/escalate/action）を決める純関数 |
| `_render(support_result)` | 出典つき回答・判定・注意書きを整形表示 |
| `main()` | argparse（`query` 位置引数・`--dry-run`・`-v`）→ `run_support_agent` を例外保護実行 |

> 実装は §10 のロードマップに従い段階導入する。まず v1（回答ゲート＋出典つき回答＋「わからない」）を最小で作る。

---

## 8. CLI 仕様

| 引数 | 既定 | 説明 |
|------|------|------|
| `query`（位置・任意） | サンプル質問 | 問い合わせ内容 |
| `--dry-run / --no-dry-run` | `dry-run`（安全） | アクションを実行せずログのみ（既定 ON） |
| `-v`, `--verbose` | off | 支持率・出典・判定理由・スコア内訳を表示 |

```bash
python agent_support_example.py "パスワードを忘れました"        # FAQ即答→出典つき
python agent_support_example.py --dry-run "解約したい"           # 行動はCONFIRM＋ログのみ
python agent_support_example.py -v "最新の料金改定は？"          # 内部不足→Webフォールバック
```

---

## 9. 評価指標（KPI）

需要（サポート業務）に直結する指標をそのまま評価に使う。

| 指標 | 定義 | 目標 |
|------|------|------|
| 自己解決率（deflection） | 有人に回さず解決した割合 | 高いほど良い |
| 出典付与率 | 回答に出典が付いた割合 | ≈ 100% |
| 根拠なし回答率 | 出典/根拠なしで断定した割合 | **0 に近いほど良い** |
| エスカレーション適合率 | ESCALATE が妥当だった割合 | 高いほど良い |
| 平均応答時間 | 問い合わせ→回答 | 低いほど良い |

---

## 10. 実装ロードマップ

| 版 | 機能 | 追加実装 | 検証 |
|----|------|---------|------|
| **v1 (MVP)** | 内部 RAG → 出典つき回答／根拠不足なら「わかりません」 | 回答ゲート（`_answer_gate`）＋ `SupportResult` | py_compile / ruff、出典率・「わからない」動作 |
| **v2** | 内部不足時に Web フォールバック＋相互検証（矛盾提示） | WebSearchTool 起動条件・引用統合 | 内部 0 件→Web、矛盾提示 |
| **v3** | アクション（起票/返信/エスカレ）＋ HITL（ドライラン） | `ActionTool`＋CONFIRM 配線 | CONFIRM 必須・副作用はログ |

---

## 11. 変更履歴

| バージョン | 変更内容 |
|-----------|---------|
| 0.1 | 初版作成（設計フェーズ）。GRACE-Support の回答判定フロー・groundedness ゲート・データ契約（SupportResult/Citation/ActionRequest）・ActionTool 仕様・HITL ポリシー・処理シーケンス・想定関数構成・CLI 仕様・KPI・実装ロードマップ v1〜v3 を定義 |

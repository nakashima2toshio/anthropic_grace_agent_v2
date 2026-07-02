# GRACE-Support 業界特化 設計書（自治体 / SaaS / EC）

**Version 0.6（二段判定＝誤爆抑止と KPI 評価ランナーを実装）** | 最終更新: 2026-07-02

> 🔍 **仕様レビュー**: 本設計・実装の横断レビューと改善提案は
> [`docs/vertical_spec_review.md`](../../docs/vertical_spec_review.md) を参照
> （残タスク 1・2 は既存コアフックでほぼ実現可能という再見積もりを含む）。

> ✅ **実装状況**: `VerticalProfile` と `--vertical {gov|saas|ec}` は **`agent_support_example.py` に実装済み**（PR #106）。しきい値上書き・エスカレ語・アクション対応・本人確認を配線。`collections`（検索範囲の実限定）と `prompt_addendum`（reasoning への注入）はコアフックが必要なため**現状は表示メタデータ**（将来対応）。

> **参考ドキュメント**
> - [`grace/doc/agent_support_example.md`](./agent_support_example.md) — GRACE-Support 本体の設計書（v1〜v3）
> - [`docs/migration_and_update.md`](../../docs/migration_and_update.md) — 需要分析・全体ロードマップ（本書はその「業界特化」フェーズの詳細）
> - [`grace/doc/grace_core_flow.md`](./grace_core_flow.md) — 5 段階設計・8 コアモジュール

---

## 目次

- [概要](#概要)
- [1. 業界プロファイル（差し替えの共通枠）](#1-業界プロファイル差し替えの共通枠)
- [2. 業界プロファイルの GRACE-Support への適用](#2-業界プロファイルの-grace-support-への適用)
- [3. 自治体（Local Government）](#3-自治体local-government)
- [4. SaaS](#4-saas)
- [5. EC（Eコマース）](#5-eceコマース)
- [6. 実装への落とし込み（VerticalProfile 案）](#6-実装への落とし込みverticalprofile-案)
- [7. 実行例（コマンド）](#7-実行例コマンド)
- [8. 残タスク（次工程候補）](#8-残タスク次工程候補)
- [9. 変更履歴](#9-変更履歴)

---

## 概要

GRACE-Support（`agent_support_example.py`）の**回答エンジン・出典検証・HITL・Web フォールバック**はそのまま共通土台として使い、**業界ごとに「差し替えるパラメータ」だけ**を切り替えて特化する。差し替えるのは主に以下の 5 点である。

1. **対象コレクション**（どの Qdrant ナレッジを検索するか）
2. **想定質問**（評価・チューニング用の代表クエリ集）
3. **エスカレ基準**（有人へ渡す条件：キーワード・閾値・本人確認要否）
4. **アクション種別**（`create_ticket` / `send_reply` / `escalate_to_human` の意味と発火条件）
5. **KPI**（業界の運用指標）

> 📝 本書は**設計フェーズ（未実装）**。コア実装は共通（GRACE-Support v3）で、業界特化は「プロファイル差し替え」で実現する方針。

---

## 1. 業界プロファイル（差し替えの共通枠）

| 差し替え項目 | 説明 | GRACE-Support 上の反映先 |
|---|---|---|
| `collections` | 検索対象コレクションの許可リスト | planner の `collection` 指定 / tools の検索範囲 |
| `sample_queries` | 代表想定質問（評価・回帰用） | KPI 計測・チューニング |
| `escalate_keywords` | 強制エスカレの語（例: 障害・決済・法的判断） | 回答ゲート前の割り込み判定 |
| `require_identity` | 本人確認が必要な操作か | アクション前 HITL（CONFIRM）強化 |
| `action_map` | 意図 → アクション種別の対応 | `_decide_action()` |
| `thresholds` | notify/confirm の上書き（厳しめ/緩め） | `_answer_gate()` |
| `prompt_addendum` | 業界固有の注意（用語・断定回避 等） | reasoning プロンプトへ追記 |
| `kpi` | 運用指標 | 評価 |

---

## 2. 業界プロファイルの GRACE-Support への適用

```mermaid
flowchart TB
    subgraph CORE["GRACE-Support（共通・v3）"]
        PLN["planner"]
        EXE["executor + tools"]
        GND["confidence（Groundedness）"]
        INT["intervention（CONFIRM/ESCALATE）"]
        WEB["Web フォールバック"]
        ACT["ActionTool（擬似）"]
    end

    subgraph PROF["業界プロファイル（差し替え）"]
        C1["自治体プロファイル"]
        C2["SaaS プロファイル"]
        C3["EC プロファイル"]
    end

    PROF -- "collections / escalate_keywords / action_map / thresholds / prompt_addendum" --> CORE
    CORE --> OUT(["業界特化サポート応答"])
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class PLN,EXE,GND,INT,WEB,ACT,C1,C2,C3,OUT default
style CORE fill:#1a1a1a,stroke:#fff,color:#fff
style PROF fill:#1a1a1a,stroke:#fff,color:#fff
```

---

## 3. 自治体（Local Government）

| 項目 | 内容 |
|------|------|
| **対象コレクション** | `条例・要綱`、`手続き案内`、`窓口FAQ`（住民向け） |
| **代表想定質問** | 「住民票の写しの取り方は？」「国民健康保険の加入手続きは？」「粗大ごみの出し方は？」「保育園の申込期限は？」 |
| **エスカレ基準** | 法的判断・個別事情・出典なしは**必ず有人**。断定を避け、根拠（条例名・案内ページ）を必須にする |
| **アクション** | `send_reply`（担当課・必要書類・窓口時間の案内）。申請受付そのものは人間（`escalate_to_human`） |
| **KPI** | 出典付与率 ≈ 100% / 根拠なし回答 = 0 / 一次解決率 / **誤案内 = 0** |
| **特有の注意** | 正確性最優先・**断定回避**、個人情報を聞かない、高齢者にも平易な表現、最新の制度改正への追随 |

> 自治体は「間違えない・出典を示す・迷ったら窓口へ」を最重視。`thresholds` は厳しめ（confirm/notify を上げる）に設定し、少しでも根拠が弱ければエスカレへ倒す。

---

## 4. SaaS

| 項目 | 内容 |
|------|------|
| **対象コレクション** | `製品ドキュメント`、`APIリファレンス`、`リリースノート`、`既知の不具合` |
| **代表想定質問** | 「API のレート制限は？」「Webhook の設定方法は？」「このエラーコードの意味は？」「v2 への移行手順は？」 |
| **エスカレ基準** | 障害・課金・セキュリティ、再現不能、バージョン不一致は `create_ticket`／`escalate_to_human` |
| **アクション** | `create_ticket`（障害・不具合）、`send_reply`（ドキュメントリンク・ステータスページ案内） |
| **KPI** | 自己解決率（deflection）/ 一次応答時間 / チケット適正振り分け率 / 再現手順取得率 |
| **特有の注意** | **バージョン差の明示**、出典にドキュメント URL、コード例の正確性、Web フォールバックは公式ドキュメント優先 |

> SaaS は「速く・正確に・再現手順つき」。`escalate_keywords` に「障害」「ダウン」「課金」「情報漏えい」等を入れ、即エスカレ。

---

## 5. EC（Eコマース）

| 項目 | 内容 |
|------|------|
| **対象コレクション** | `商品情報`、`返品・交換規定`、`配送・送料`、`注文FAQ` |
| **代表想定質問** | 「返品したい」「配送状況を知りたい」「サイズ交換できる？」「注文をキャンセルしたい」 |
| **エスカレ基準** | 個人注文情報の照会・変更（**本人確認必須**）、決済トラブルは有人／本人確認フロー |
| **アクション** | `create_ticket`（返品受付・要 CONFIRM＋本人確認）、`send_reply`（規定・返信テンプレ）。注文照会は注文 ID 必須 |
| **KPI** | 自己解決率 / 返品処理時間 / **誤操作 = 0（本人確認必須）** / CS 満足度 |
| **特有の注意** | **個人情報・注文権限の確認を必須**（`require_identity=True` → アクション前 HITL を強化）、規定の版管理 |

> EC は「行動（返品・キャンセル）に直結」するため、v3 のアクション＋HITL が本領。副作用のある操作は本人確認 → CONFIRM の二段で守る。

---

## 6. 実装への落とし込み（VerticalProfile 案）

共通コードは変えず、**プロファイルを渡すだけ**で切り替える設計。

```text
VerticalProfile（dataclass 案）
  - name: str                      # "gov" | "saas" | "ec"
  - collections: list[str]         # 検索許可コレクション
  - escalate_keywords: list[str]   # 強制エスカレ語
  - require_identity: bool         # アクション前に本人確認を必須化
  - action_map: dict[str, str]     # 意図キーワード → action_type
  - notify_th / confirm_th: float  # 閾値の上書き（未指定なら config 既定）
  - prompt_addendum: str           # reasoning への業界注意書き
  - sample_queries: list[str]      # 評価用
  - kpi: list[str]
```

**適用ポイント（GRACE-Support への差し込み）**:

| プロファイル項目 | 差し込み先（既存関数) | 状態 |
|---|---|---|
| `escalate_keywords` | **二段判定**: キーワード候補一致（`_match_keyword`）→ 軽量 LLM 意図分類（`create_intent_classifier`・question/request/incident）。question（FAQ質問）は誤爆とみなし通常フロー継続、それ以外・分類失敗は即 `escalate`（Web もスキップ） | ✅ 実装済み（`_should_force_escalate`） |
| `notify_th`/`confirm_th` | `_answer_gate()` のしきい値を上書き | ✅ 実装済み |
| `action_map` | `_decide_action()`（二段判定: キーワード候補 → 意図分類。question は起票せず回答のみ） | ✅ 実装済み |
| `require_identity` | `_perform_action()`（本人確認ステップを前置。起動有無は `SupportResult.identity_checked` に記録） | ✅ 実装済み |
| `collections` | 計画の `rag_search` を対象コレクションに限定（planner/tools） | ⏳ 表示のみ（実限定は `allowed_collections` 案 = `docs/vertical_spec_review.md` §3.2） |
| `prompt_addendum` | reasoning ステップのプロンプトへ追記 | ⏳ 表示のみ（注入案 = `docs/vertical_spec_review.md` §3.1） |
| `sample_queries` / `kpi` | 期待ラベル付きテストケースは `eval/vertical/cases/<vertical>.jsonl` に外部化（dataclass には持たせない）。KPI は `eval/vertical/run.py` で自動計測 | ✅ 実装済み（評価ランナー） |

**CLI**: `python agent_support_example.py --vertical gov "住民票の取り方は？"`（プロファイルを選択）。**実装済み**。

**実装状況**: `VerticalProfile` 導入と gov/saas/ec の 3 プロファイルは実装済み（PR #106）。設計時の実装順（自治体 → SaaS → EC）どおり 3 業界を同時に組み込み済み。残タスクは `collections` の実検索限定・`prompt_addendum` のプロンプト注入・評価スクリプト（KPI 自動計測）。

---

## 7. 実行例（コマンド）

業界別アプリの実行例を示す。`--vertical` フラグは**実装済み**（PR #106）であり、次の 2 段構えで示す。

- **7.1**: 共通コマンド（GRACE-Support v3・プロファイル未適用）で、業界の代表シナリオを試す
- **7.2**: `--vertical` でプロファイルを切り替えて実行する（推奨）

共通の前提: `.env` に `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`、Qdrant 起動済み＋対象コレクション登録済み。uv 管理環境では `python …` を `uv run python …` に読み替える。

### 7.1 現時点（v3 共通コマンドで業界シナリオを試す）

共通 CLI は `agent_support_example.py`（引数: `query` / `-v` / `--no-web` / `--no-action` / `--dry-run`）。`--vertical` を付けない場合は業界チューニング（エスカレ語・しきい値・アクション対応）が適用されないため、共通挙動の確認用。

**自治体（正確性・出典最優先）**
```bash
python agent_support_example.py "住民票の写しの取り方は？"
python agent_support_example.py -v "国民健康保険の加入手続きは？"   # 支持率の内訳を表示
```

**SaaS（速く・正確・再現手順）**
```bash
python agent_support_example.py "API のレート制限は？"
python agent_support_example.py -v "サービスが落ちています"        # 障害系 → escalate 想定
```

**EC（行動＝返品/キャンセルは HITL）**
```bash
python agent_support_example.py "返品したい"                       # アクション(create_ticket)・CONFIRM＋ドライラン
python agent_support_example.py --no-dry-run "解約したい"          # 擬似実行（実API連携は将来）
python agent_support_example.py --no-web "配送状況を知りたい"      # 内部ナレッジのみ
```

### 7.2 業界プロファイル（VerticalProfile・実装済み）

`--vertical {gov|saas|ec}` でプロファイル（エスカレ語・アクション対応・本人確認・閾値、および表示メタの対象コレクション・方針）を一括切替する。**実装済み**（PR #106）。

**自治体**
```bash
python agent_support_example.py --vertical gov "住民票の写しの取り方は？"
```

**SaaS**
```bash
python agent_support_example.py --vertical saas -v "Webhook の設定方法は？"
```

**EC**
```bash
python agent_support_example.py --vertical ec "返品したい"              # 本人確認 → CONFIRM → ドライラン
python agent_support_example.py --vertical ec --no-dry-run "返品したい"  # 擬似実行
```

> ✅ `--vertical` は実装済み。`escalate_keywords`/しきい値/`action_map`/`require_identity` が有効。`collections`（実検索限定）と `prompt_addendum`（プロンプト注入）は現状**表示のみ**で、フル配線は将来対応（§6 参照）。

---

## 8. 残タスク（次工程候補）

`VerticalProfile`（`--vertical`）は実装済み（PR #106）。その後の進捗は次のとおり。

| # | 残タスク | 内容 | 状態 |
|---|---------|------|------|
| 1 | `collections` の実検索限定 | プロファイルの対象コレクションで RAG 検索範囲を実際にスコープ制限する（現状は表示メタのみ） | ⏳ 未着手（`allowed_collections` 小改修案 = `docs/vertical_spec_review.md` §3.2。実コレクション名の割り当てが前提） |
| 2 | `prompt_addendum` のプロンプト注入 | reasoning ステップのプロンプトへ業界方針（断定回避・出典必須・本人確認等）を実際に追記する | ⏳ 未着手（`ReasoningTool` の `context` 引数／`config.llm.prompt_addendum` 案 = 同 §3.1） |
| 3 | KPI 評価スクリプト | 分岐一致率・誤エスカレ率・**強制エスカレ誤発火率（0 目標）**・出典付与率・**根拠なし回答率（0 目標）**・アクション適合率・本人確認遵守率を自動計測 | ✅ **実装済み**（`eval/vertical/run.py`・`eval/vertical/metrics.py`・`cases/{gov,saas,ec}.jsonl` 5 カテゴリ） |
| 4 | 二段判定（キーワード誤爆抑止） | エスカレ語・アクション語の部分一致を候補検出に格下げし、一致時のみ軽量 LLM（`claude-haiku-4-5-20251001`）で意図分類（question/request/incident）。question は強制エスカレ・起票を抑止 | ✅ **実装済み**（`_should_force_escalate` / `_decide_action`・単体テスト `tests/test_agent_support_vertical.py`） |

> #3 の in-scope 精度計測には**業界別 RAG コレクションの整備**が引き続き必要（自治体/SaaS/EC）。
> データ選定の考え方・無料データ候補は [`docs/vertical_test_data.md`](../../docs/vertical_test_data.md) を参照。

---

## 9. 変更履歴

| バージョン | 変更内容 |
|-----------|---------|
| 0.1 | 初版作成（設計フェーズ）。業界プロファイルの共通枠、GRACE-Support への適用図、自治体/SaaS/EC の対象コレクション・想定質問・エスカレ基準・アクション・KPI・注意点、VerticalProfile 実装案と差し込みポイントを定義 |
| 0.2 | §2 適用図を縦並び（`flowchart TB`）に変更。§7「実行例（コマンド）」を追加（7.1 現時点の共通コマンド／7.2 `--vertical` 実装後の想定）。変更履歴を §8 に繰り下げ |
| 0.3 | `VerticalProfile` と `--vertical {gov|saas|ec}` の実装完了（PR #106）に合わせて更新。§6 の適用ポイントに実装状況（escalate_keywords/しきい値/action_map/require_identity=実装済み、collections/prompt_addendum=表示のみ）を追記、§7.2 を「実装済み」へ、ヘッダに実装状況注記を追加 |
| 0.4 | §8「残タスク（次工程候補）」を追加（collections の実検索限定・prompt_addendum のプロンプト注入・KPI 評価スクリプト）。変更履歴を §9 に繰り下げ |
| 0.5 | §7 冒頭・§7.1 に残っていた「`--vertical` 未実装」の旧文言を実装済み前提に修正。ヘッダに仕様レビュー（`docs/vertical_spec_review.md`）への参照を追加 |
| 0.6 | **二段判定（誤爆抑止）**と **KPI 評価ランナー**の実装を反映。§6 適用ポイント表を更新（escalate_keywords/action_map は「キーワード候補検出 → 意図分類」へ、sample_queries/kpi は `eval/vertical/` に外部化）。§8 を進捗表に改め、#3 KPI 評価・#4 二段判定を実装済みに |

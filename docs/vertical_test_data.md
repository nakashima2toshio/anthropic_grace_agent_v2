# 業界特化 テストデータ準備ガイド ＋ 成果物一覧

**Version 1.2** | 最終更新: 2026-07-02

本書は GRACE-Support 業界特化（自治体 / SaaS / EC）の**テストデータ（RAG コレクション＋テスト質問）の考え方・無料データ候補**をまとめ、あわせて本取り組みで作成した**仕様書・ドキュメント・プログラムの一覧**を先頭に掲げる。

---

## 0. 成果物一覧（仕様書・ドキュメント・プログラム）

### プログラム（リポジトリ直下）

| パス | 種別 | 内容 | 状態 |
|---|---|---|---|
| [`agent_example.py`](../agent_example.py) | サンプル | 最小実行サンプル（planner→executor の 5 段階） | 実装済み |
| [`agent_example_core8.py`](../agent_example_core8.py) | サンプル | コア 8 モジュールを明示的に使う教材版 | 実装済み |
| [`agent_support_example.py`](../agent_support_example.py) | アプリ | GRACE-Support（v1 内部RAG＋出典／v2 Webフォールバック＋相互検証／v3 アクション＋HITL／業界特化 `--vertical`） | 実装済み |

### ドキュメント（`grace/doc/`）

| パス | 種別 | 内容 | 状態 |
|---|---|---|---|
| [`grace/doc/grace_core.md`](../grace/doc/grace_core.md) | 設計 | コア 8 モジュール横断アーキテクチャ | v1.1 |
| [`grace/doc/grace_core_flow.md`](../grace/doc/grace_core_flow.md) | 設計 | 5 段階設計・8 モジュール・プロンプト/API 発行部・`agent_example.py` 解説 | v1.1 |
| [`grace/doc/agent_example_core8.md`](../grace/doc/agent_example_core8.md) | 設計 | `agent_example_core8.py` 設計書 | v1.0 |
| [`grace/doc/agent_support_example.md`](../grace/doc/agent_support_example.md) | 設計 | GRACE-Support 本体設計書（v1〜v3） | v1.0 |
| [`grace/doc/agent_support_verticals.md`](../grace/doc/agent_support_verticals.md) | 設計 | 業界特化（自治体/SaaS/EC）設計・残タスク | v0.4 |

### ドキュメント（`docs/`）

| パス | 種別 | 内容 | 状態 |
|---|---|---|---|
| [`docs/migration_and_update.md`](./migration_and_update.md) | 計画 | 需要分析・GRACE-Support 採用方針・全体ロードマップ | v1.0 |
| `docs/vertical_test_data.md` | ガイド | 本書（テストデータ準備＋成果物一覧） | v1.1 |
| [`docs/vertical_spec_review.md`](./vertical_spec_review.md) | レビュー | 業界特化の仕様レビュー・改善提案（不整合の検証／残タスク再見積もり／KPI 評価設計／ロードマップ） | v1.0 |

---

## 1. まず「2 種類のデータ」を分けて考える

| 種類 | 役割 | 形式 | 用意の仕方 |
|---|---|---|---|
| **① 知識コーパス（RAG 対象）** | 回答の根拠。Qdrant に登録するコレクション | Q&A ペア or 文書（チャンク化可能） | 公開データを既存パイプラインに載せる |
| **② テスト質問セット（ユーザ入力）** | 各分岐を検証する入力 | 短い日本語クエリのリスト | **合成でよい**（データセット不要・自作） |

→ 「コレクション」と「テスト入力」は別物。**コレクションは公開データ、テスト入力は自作**が基本。

## 2. コレクション（知識コーパス）選定の 5 条件

1. **日本語**（本システムは日本語 RAG／Gemini embedding 3072 次元）
2. **既存パイプラインに載る形式**：CSV/テキスト → `chunking` → `qa_generation`（`{"qa_pairs":[...]}`）→ `qa_qdrant` 登録（コレクション名 `*_anthropic`）
3. **オープンライセンス**（CC/MIT/Apache、HuggingFace 可）
4. **ドメイン適合**：gov=行政・制度／saas=技術ドキュメント・API／ec=商品・返品・注文
5. **カバレッジに“穴”を作る**：全部を入れず一部だけ登録 → 「わからない（escalate）」分岐を検証できる

> 完璧な業界 FAQ が無くても、**近縁の公開コーパス＋既存 `qa_generation`（Q/A 自動生成）**で「疑似 FAQ コレクション」を作れる。これが現実的な最短路。

## 3. 業界別・無料データ候補（HuggingFace / オープン）

> ⚠️ データ名は知識時点（2026-01）の候補。**現在の公開状況・ライセンスは要確認**（本書 §6 の TODO(b) で検証・確定する）。

### 自治体（gov）
- **第一候補**: 各自治体の **FAQ オープンデータ**（横浜市・東京都等が CSV 公開・CC）＝そのまま Q&A 化しやすい
- **法令・制度**: **e-Gov 法令データ**（法令 API・公共データ）で条例・制度テキスト
- **代替（すぐ使える）**: 既存の **`wikipedia_ja`** の行政・制度記事（既に Qdrant にある想定）
- HF 候補: 日本語 QA（`JAQKET` / `JSQuAD`＝JGLUE）を「事実 QA」の器として代用

### SaaS
- **第一候補**: OSS 製品の**公式ドキュメント（Markdown）**をチャンク化（Apache/MIT）＝製品 FAQ の代替に最適
- **代替**: Stack Exchange / StackOverflow 系（英語中心）で「技術 QA」の器
- HF 候補: `stackexchange` 系、または OSS docs を自前取得

### EC
- **第一候補**: `amazon_reviews_multi`（日本語サブセット）等の商品説明・レビュー（※配布終了の可能性あり＝要確認）
- **返品・配送 FAQ**: 公開 EC の**利用規約／返品ポリシー**、または**合成**（返品規定は各社固有なので合成が妥当）
- **代替**: 楽天技術研究所の楽天データ（申請制・無料）

## 4. すぐ使えるテスト質問セット（②・合成・無料）

各業界で **5 カテゴリ**を用意すると全分岐＋誤爆を検証できる。
**機械可読な期待ラベル付きテストケースは [`eval/vertical/cases/*.jsonl`](../eval/vertical/cases/) に収録済み**で、
KPI 評価ランナー（`uv run python -m eval.vertical.run --vertical gov`）がそのまま読み込む。

| カテゴリ | 検証する分岐 |
|---|---|
| in-scope | 出典つき回答（answer）できるか |
| out-of-scope | 「わからない」→ Web/escalate に倒れるか |
| action | `action_map` が発火するか（返品/解約/申請 等） |
| escalate-keyword | `escalate_keywords` で強制エスカレするか（障害/決済/法的 等） |
| **keyword-trap** | **誤爆検査**: エスカレ語・アクション語を含む FAQ 質問（意図=question）が、強制エスカレ・起票**されない**か（二段判定の効果測定） |

### 自治体（gov）
```
in-scope     : 「住民票の写しの取り方は？」「粗大ごみの出し方は？」
out-of-scope : 「隣の県の手当は？」「来年の税制改正の予測は？」
action       : 「保育園の申請様式がほしい」               # 申請 → send_reply
escalate     : 「固定資産税の減免は個別に判断してほしい」   # 減免/個別 → escalate
keyword-trap : 「住民税の減免制度の概要を教えて」          # 『減免』を含む FAQ 質問 → answer のまま
```

### SaaS
```
in-scope     : 「API のレート制限は？」「Webhook の設定方法は？」
out-of-scope : 「御社の来期の売上見込みは？」
action       : 「500 エラーが出る不具合を報告したい」       # 不具合 → create_ticket
escalate     : 「サービスが落ちています」「課金が二重です」   # 障害/課金 → escalate
keyword-trap : 「課金プランの違いを教えて」                # 『課金』を含む FAQ 質問 → answer のまま
```

### EC
```
in-scope     : 「返品規定を教えて」「送料はいくら？」
out-of-scope : 「この商品の入荷予定日は？」
action       : 「返品したい」「注文をキャンセルしたい」       # 返品/キャンセル → create_ticket（本人確認→CONFIRM）
escalate     : 「決済が失敗した」「届いた商品が破損していた」   # 決済/破損 → escalate
keyword-trap : 「返金ポリシーを教えて」「解約手続きの流れを教えて」  # FAQ 質問 → エスカレ・起票しない
```

> keyword-trap の期待挙動は `agent_support_example.py` の**二段判定**（キーワード候補検出 →
> 軽量 LLM 意図分類 question/request/incident）が担保する。question（FAQ 質問）のみ
> 強制エスカレ・アクション起票を抑止し、request/incident・分類失敗時は安全側（従来どおり）に倒す。

## 5. 進め方（最小構築）

1. **既存コレクションで即開始**：`config.qdrant.search_priority` の既定（`wikipedia_ja` / `livedoor` / `cc_news` / `japanese_text`）を gov 代替として `--vertical gov` の動作確認。
2. **各業界 1 コレクション追加**：公開データ（自治体 FAQ CSV／OSS docs／EC 規約）を `qa_generation` で疑似 FAQ 化 → `*_anthropic` として登録。
3. **KPI 評価ランナーで 5 分岐を自動計測**（残タスク #3・実装済み）:
   ```bash
   uv run python -m eval.vertical.run --vertical gov --report logs/vertical_gov.json
   ```
   分岐一致率・誤エスカレ率・強制エスカレ誤発火率・出典付与率・根拠なし回答率・
   アクション適合率・本人確認遵守率を出力する（定義: `eval/vertical/metrics.py`）。
   in-scope の decision 一致率はコレクションのカバレッジに依存するため、
   専用コレクション登録後に再計測してベースラインとする。

---

## 6. TODO と進め方

| ID | タスク | 内容 | 状態 |
|---|---|---|---|
| (a) | データ準備ガイドを doc 化（テスト質問セット収録） | 本書 `docs/vertical_test_data.md` | ✅ 完了（本書） |
| (c) | まず自治体だけ最小の動作確認 | 既存 `wikipedia_ja` ＋ §4 の gov 合成質問で `--vertical gov` を検証 | 🚧 着手中（§7） |
| (b) | 具体データセットの実在・ライセンスを WebSearch で検証・確定 | §3 の候補を確定し、取得手順を追記 | ⏳ 未着手 |

> 進行順は **(a)→(c)→(b)**。まず (c)（自治体・既存コレクションでの最小確認）から着手する。

---

## 7. (c) 自治体・最小動作確認キット

**目的**: 追加データ登録なしで、既存コレクション（`wikipedia_ja` 等）を使って `--vertical gov` の各分岐（answer / escalate / action / escalate-keyword）を確認する。

**前提**: `.env` に `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`、Qdrant 起動済み＋`wikipedia_ja` 等の既定コレクション登録済み。uv 管理環境では `python …` を `uv run python …` に読み替える。

**確認コマンド（§4 の gov テスト質問を投入）**:
```bash
# in-scope（出典つき回答を期待。wikipedia_ja に該当があれば answer）
python agent_support_example.py --vertical gov -v "選挙権は何歳から？"

# out-of-scope（根拠不足 → Web フォールバック → なお不足なら escalate）
python agent_support_example.py --vertical gov "来年の税制改正の予測は？"

# action（申請 → send_reply。CONFIRM＋ドライラン）
python agent_support_example.py --vertical gov "保育園の申請様式がほしい"

# escalate-keyword（"減免"/"個別" で強制エスカレ。Web もスキップ）
python agent_support_example.py --vertical gov "固定資産税の減免を個別に判断してほしい"
```

> 注: `wikipedia_ja` は自治体 FAQ ではなく百科事典のため、in-scope は「制度・一般知識」寄りの質問（例:「選挙権は何歳から？」）が当たりやすい。自治体固有の手続き FAQ は §3 の自治体オープンデータを登録した専用コレクション（TODO(b) で確定）に置き換えると精度が上がる。

**確認観点（合否の目安）**:
| テスト | 期待する挙動 |
|---|---|
| in-scope | `decision=answer`・【出典】が付く |
| out-of-scope | Web フォールバック起動、なお不足なら `decision=escalate` |
| action | `⑥ Action` で `send_reply`・CONFIRM 通過・`[DRY-RUN]` ログ |
| escalate-keyword | `[profile] エスカレ語を検知` → `decision=escalate`（Web スキップ） |

> 本コンテナには実行時依存（anthropic/qdrant 等）・Qdrant サービスが無いため、**ライブ実行はユーザ環境で**行う。本節はその最小手順・観点を提供する。

---

## 8. 変更履歴

| バージョン | 変更内容 |
|-----------|---------|
| 1.0 | 初版作成。先頭に成果物一覧（プログラム・ドキュメント）、テストデータの考え方（2 種類のデータ・選定 5 条件）、業界別無料データ候補、すぐ使えるテスト質問セット（gov/saas/ec × 4 カテゴリ）、TODO(a/c/b)、(c) 自治体・最小動作確認キットを整備 |
| 1.1 | 成果物一覧に仕様レビュー資料（`docs/vertical_spec_review.md`）を追加。同レビュー §7 で本書への追補（実コレクション命名規約・「穴」の設計手順・keyword-trap 第 5 カテゴリ・TODO(b) の進め方）を提案 |
| 1.2 | §4 に第 5 カテゴリ **keyword-trap**（誤爆検査）と各業界の trap 質問例を追加。期待ラベル付きテストケース（`eval/vertical/cases/*.jsonl`）と KPI 評価ランナー（`eval/vertical/run.py`）の実装に合わせて §5 手順 3 を更新 |

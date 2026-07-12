# 業界特化 テストデータ準備ガイド ＋ 成果物一覧

**Version 2.2** | 最終更新: 2026-07-10

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
| [`grace/doc/agent_support_example.md`](../grace/doc/agent_support_example.md) | 設計 | GRACE-Support 本体設計書（v1〜v3 ＋ 業界特化・IPO 詳細） | v1.2 |
| [`grace/doc/agent_support_verticals.md`](../grace/doc/agent_support_verticals.md) | 設計 | 業界特化（自治体/SaaS/EC）**定義・7 つの機構・成熟度**＋設計・進捗 | v1.4 |

### ドキュメント（`docs/`）

| パス | 種別 | 内容 | 状態 |
|---|---|---|---|
| [`docs/migration_and_update.md`](./migration_and_update.md) | 計画 | 需要分析・GRACE-Support 採用方針・全体ロードマップ | v1.0 |
| `docs/vertical_test_data.md` | ガイド | 本書（テストデータ準備＋成果物一覧） | v2.2 |
| [`docs/vertical_spec_review.md`](./vertical_spec_review.md) | レビュー | 業界特化の仕様レビュー・改善提案（不整合の検証／残タスク再見積もり／KPI 評価設計／ロードマップ） | v1.2 |
| [`docs/vertical_gov.md`](./vertical_gov.md) | 業界別説明 | 自治体（gov）プロファイルの特化部分（7 機構の割り当て・二段判定・スコープ・prompt_addendum・TODO(b)・KPI） | v1.2 |
| [`docs/vertical_saas.md`](./vertical_saas.md) | 業界別説明 | SaaS プロファイルの特化部分（同上・課金/障害 trap・OSS docs 投入） | v1.2 |
| [`docs/vertical_ec.md`](./vertical_ec.md) | 業界別説明 | EC プロファイルの特化部分（同上・本人確認フロー・合成/自社データ投入） | v1.2 |
| [`docs/vertical_comparison.md`](./vertical_comparison.md) | 業界比較 | 3 業界の横並び対比（性格・7 機構・6 軸・二段判定・スコープ・データ戦略・KPI の 8 観点）＋①〜⑦フロー図・コード読解マップ（§9） | v1.1 |
| [`docs/vertical_docs_todo.md`](./vertical_docs_todo.md) | TODO | 業界特化ドキュメント再チェック結果と改善 TODO（P0〜P2） | v1.1 |

> 📌 「状態」列の版数はリンク先ヘッダーの `**Version X.X**` が正。本表の版数はチェック時点
> （2026-07-10）のスナップショットであり、更新時はリンク先の版上げと同時にこの表も同期すること。

### 評価・テスト（`eval/` ・ `tests/`）

| パス | 種別 | 内容 | 状態 |
|---|---|---|---|
| [`eval/vertical/run.py`](../eval/vertical/run.py) | 評価ランナー | 期待ラベル付き質問を `run_support_agent()` に投入し KPI（分岐一致率・誤エスカレ率・出典付与率 等）を自動計測 | 実装済み |
| [`eval/vertical/metrics.py`](../eval/vertical/metrics.py) | 指標定義 | KPI の算出ロジック | 実装済み |
| [`eval/vertical/register_test_collections.py`](../eval/vertical/register_test_collections.py) | 登録スクリプト | 合成 Q&A を `*_anthropic` 6 コレクションに一括登録 | 実装済み |
| [`eval/vertical/fetch_real_knowledge.py`](../eval/vertical/fetch_real_knowledge.py) | 取得スクリプト | 実運用ナレッジの取得・整形（gov: e-Gov 法令 API / saas: OSS docs → text CSV） | 実装済み |
| [`eval/vertical/cases/*.jsonl`](../eval/vertical/cases/) | テストケース | 期待ラベル付き質問（**gov 7 / saas 8 / ec 9 件**・5 カテゴリ。各ファイル 1 行目は `#` コメント行のため行数≠ケース数） | 実装済み |
| [`eval/vertical/data/*.csv`](../eval/vertical/data/) | 合成データ | 業界別 合成 FAQ（gov_faq/gov_laws/saas_api/saas_docs/ec_faq/ec_policy） | 実装済み |
| `tests/grace/test_vertical_scope.py` / `tests/test_agent_support_vertical.py` / `tests/eval/test_vertical_metrics.py` | 単体テスト | 検索スコープ・回答ゲート/二段判定・KPI 指標を**API 不要**で検証 | 実装済み |

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

> ✅ **TODO(b) 検証済み（2026-07-02・WebSearch）**。検証結果を各候補に注記した。
> 結論: 「自治体 FAQ の標準 CSV 配布」は**確認できず**、現実的な最短路は
> **(1) e-Gov 法令 API（gov_laws）＋ (2) 公式 FAQ ページ等からの `qa_generation` 疑似 FAQ 合成（gov_faq）**。
> EC の `amazon_reviews_multi` は**配布終了が確定**したため合成を第一候補に繰り上げ。

### 自治体（gov）
- **法令・制度（検証済み・推奨）**: **e-Gov 法令 API v2**（<https://laws.e-gov.go.jp/apitop/>）。
  法令全文を XML で取得可。**政府標準利用規約（第 2.0 版）**＝出典明示で商用含む二次利用可 → `gov_laws_anthropic` の元データに最適
- **FAQ（検証結果）**: 横浜市オープンデータポータル（<https://data.city.yokohama.lg.jp/>）は**原則 CC BY 4.0** だが、
  「コールセンター FAQ」等の**専用 Q&A データセットは確認できなかった**。東京都カタログ・自治体標準オープンデータセット
  （デジタル庁）も同様に FAQ 形式の標準データは無し → **公式 FAQ ページ・手続き案内を元に `qa_generation` で疑似 FAQ を合成**
  （出典 URL を payload に保持）するのが現実解 → `gov_faq_anthropic`
- **代替（すぐ使える）**: 既存の **`wikipedia_ja`** の行政・制度記事（gov プロファイルの検索スコープに暫定で含めてある）
- HF 候補（検証済み）: `JSQuAD` / `JAQKET`（JGLUE）は **CC BY-SA 4.0**（帰属表示＋継承）。「事実 QA」の器として利用可

### SaaS
- **第一候補**: OSS 製品の**公式ドキュメント（Markdown）**をチャンク化（Apache/MIT）＝製品 FAQ の代替に最適 → `saas_docs_anthropic` / `saas_api_anthropic`
- **代替**: Stack Exchange / StackOverflow 系（英語中心・CC BY-SA）で「技術 QA」の器
- HF 候補: `stackexchange` 系、または OSS docs を自前取得

### EC
- ~~`amazon_reviews_multi`（日本語サブセット）~~ → **配布終了を確認**（HF 上で defunct 扱い・データ提供者の判断によりアクセス不可）
- **第一候補（繰り上げ）**: **合成** — 公開 EC の利用規約・返品ポリシーの構成を参考に、返品・交換・配送・注文 FAQ を
  `qa_generation` で作成（返品規定は各社固有なので合成が最も実態に合う）→ `ec_policy_anthropic` / `ec_faq_anthropic`
- **代替**: 楽天技術研究所の楽天データ（申請制・無料）

### 検証ソース（2026-07-02）
- 横浜市オープンデータポータル（CC BY 4.0 原則）: <https://data.city.yokohama.lg.jp/>
- e-Gov 法令 API / 利用規約: <https://laws.e-gov.go.jp/apitop/> / <https://laws.e-gov.go.jp/terms/>
- JGLUE（CC BY-SA 4.0）: <https://github.com/yahoojapan/JGLUE>
- amazon_reviews_multi（defunct）: <https://huggingface.co/datasets/defunct-datasets/amazon_reviews_multi>

## 4. すぐ使えるテスト質問セット（②・合成・無料）

各業界で **5 カテゴリ**を用意すると全分岐＋誤検知を検証できる。
**機械可読な期待ラベル付きテストケースは [`eval/vertical/cases/*.jsonl`](../eval/vertical/cases/) に収録済み**で、
KPI 評価ランナー（`uv run python -m eval.vertical.run --vertical gov`）がそのまま読み込む。

| カテゴリ | 検証する分岐 |
|---|---|
| in-scope | 出典つき回答（answer）できるか |
| out-of-scope | 「わからない」→ Web/escalate に倒れるか |
| action | `action_map` が発火するか（返品/解約/申請 等） |
| escalate-keyword | `escalate_keywords` で強制エスカレするか（障害/決済/法的 等） |
| **keyword-trap** | **誤検知検査**: エスカレ語・アクション語を含む FAQ 質問（意図=question）が、強制エスカレ・起票**されない**か（二段判定の効果測定） |

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

**実コレクション名（確定・プロファイルに設定済み）**:

| 業界 | コレクション名 | 元データ |
|---|---|---|
| gov | `gov_faq_anthropic` / `gov_laws_anthropic`（暫定代替: `wikipedia_ja`） | 公式 FAQ 合成 / e-Gov 法令 API |
| saas | `saas_docs_anthropic` / `saas_api_anthropic` | OSS 公式ドキュメント |
| ec | `ec_policy_anthropic` / `ec_faq_anthropic` | 規約・FAQ 合成 |

検索スコープは `--vertical` 指定時に `config.qdrant.allowed_collections` へ自動配線される
（**未登録のコレクションは自動的に無視**され、1 つも登録が無ければ制限なしで従来どおり動作）。

1. **既存コレクションで即開始**：gov プロファイルは暫定代替 `wikipedia_ja` を検索スコープに含むため、
   登録作業なしで `--vertical gov` がスコープ付きで動く。
2. **合成テストデータを 1 コマンドで登録（最短路・推奨）**：
   ```bash
   # 全業界の専用コレクション（*_anthropic 6 個）を合成 Q&A で一括登録
   uv run python -m eval.vertical.register_test_collections --recreate

   # 業界単位（ec / saas / gov）
   uv run python -m eval.vertical.register_test_collections --vertical ec --recreate
   ```
   データは `eval/vertical/data/*.csv`（合成 FAQ・各 10 件）。§4 の in-scope / keyword-trap
   質問に社内根拠を与える一方、out-of-scope 質問（入荷予定日・売上見込み・税制改正予測）は
   **意図的にカバーしない**（「穴」＝escalate 分岐の検証を維持。整合は
   `tests/eval/test_register_test_collections.py` が担保）。
3. **実データでコレクション追加（本番相当）**：

   **3-1. 実データの取得・整形を 1 コマンド化**（`eval/vertical/fetch_real_knowledge.py`・LLM/Qdrant 不要）:
   ```bash
   # gov: e-Gov 法令 API から法令全文（既定: 行政手続法・行政不服審査法・住民基本台帳法）
   #      を条単位の text CSV へ（政府標準利用規約 2.0・出典 URL を source 列に保持）
   uv run python -m eval.vertical.fetch_real_knowledge egov --output OUTPUT/gov_laws_real.csv

   # saas: OSS 公式ドキュメント（既定: FastAPI 日本語版・MIT・タグ固定 URL）を
   #       見出しセクション単位の text CSV へ。--url で任意の raw Markdown に差し替え可
   uv run python -m eval.vertical.fetch_real_knowledge oss-docs --output OUTPUT/saas_docs_real.csv
   ```
   > ec は返品規定・利用規約が各社固有のため公開実データが無い（§3）。合成 CSV
   > （`eval/vertical/data/ec_*.csv`）または自社の規約・FAQ を同じ `text` カラム CSV
   > 形式で用意し、下の 3-2 と同一手順で登録する。

   **3-2. 登録**（チャンク化 → Q/A 生成＋登録。Q&A ペア CSV は直接登録も可）:
   ```bash
   # Q&A ペア CSV を直接登録（合成 FAQ・自治体 FAQ など）
   uv run python qa_qdrant/register_to_qdrant.py \
     --input-file qa_output/gov_faq.csv --collection gov_faq_anthropic --recreate

   # 文書 CSV（e-Gov 法令・OSS docs 等）→ チャンク化 → Q/A 生成＋登録
   uv run python -m chunking.csv_text_to_chunks_text_csv \
     --input-file OUTPUT/gov_laws_real.csv --output output_chunked
   uv run python qa_qdrant/make_qa_register_qdrant.py \
     --input-file output_chunked/gov_laws_real_chunks.csv --collection gov_laws_anthropic --recreate
   ```
4. **KPI 評価ランナーで 5 分岐を自動計測**（残タスク #3・実装済み）:
   ```bash
   uv run python -m eval.vertical.run --vertical gov --report logs/vertical_gov.json
   ```
   分岐一致率・誤エスカレ率・強制エスカレ誤検知率・出典付与率・根拠なし回答率・
   アクション適合率・本人確認遵守率を出力する（定義: `eval/vertical/metrics.py`）。
   in-scope の decision 一致率はコレクションのカバレッジに依存するため、
   専用コレクション登録後に再計測してベースラインとする。

   **`SupportResult` フィールド → KPI 指標の対応**（`run.py` が `CaseResult` に抽出し
   `metrics.py::compute_metrics()` が集計する）:

   | `SupportResult` フィールド | 流れる KPI 指標 | 備考 |
   |---|---|---|
   | `decision` | decision_accuracy / false_escalate_rate / escalate_recall | 期待ラベル（expected_decision）と照合。分母はカテゴリで層別 |
   | `forced_escalate` | forced_escalate_misfire_rate | 分母は in-scope＋keyword-trap（誤検知 0 目標） |
   | `citations`（件数） | citation_rate | answer のうち出典 1 件以上の割合 |
   | `groundedness` ＋ `groundedness_decided` | ungrounded_answer_rate / groundedness_neutral_rate | decided>0 かつ支持率<confirm_th が「根拠なし」、decided=0 は「判定不能」として分離 |
   | `action.action_type` | action_accuracy | expected_action と照合（None 同士の一致を含む） |
   | `identity_checked` | identity_check_rate | 分母は `expect_identity_check: true` のケースのみ |
   | （実行時間・`run.py` が計測） | mean_latency_ms | — |
   | `intent` | —（レポートに記録のみ） | 二段判定の分岐確認用 |
   | `no_info_detected` / `web_reused` | —（KPI 集計には未使用） | `--show-agent-output` でゲート発火・⑤最適化の確認に使う |

---

## 6. TODO と進め方

| ID | タスク | 内容 | 状態 |
|---|---|---|---|
| (a) | データ準備ガイドを doc 化（テスト質問セット収録） | 本書 `docs/vertical_test_data.md` | ✅ 完了（本書） |
| (c) | まず自治体だけ最小の動作確認 | 既存 `wikipedia_ja` ＋ §4 の gov 合成質問で `--vertical gov` を検証（KPI 計測は `eval/vertical/run.py`） | 🚧 着手中（§7・ライブ実行はユーザ環境） |
| (b) | 具体データセットの実在・ライセンスを WebSearch で検証・確定 | §3 に検証結果を反映（e-Gov=政府標準利用規約2.0 / 横浜市=CC BY 4.0・FAQ専用CSVは未確認 / JGLUE=CC BY-SA 4.0 / amazon_reviews_multi=配布終了） | ✅ 完了（§3・2026-07-02） |
| (d) | 検証コストの削減（API 代） | 反復検証の多くは「ほぼ同一ループ」。record/replay キャッシュ（LLM/Embedding/Web）＋ SourceAgreement のバッチ Embedding で再実行を実質 0 円化 | ⏳ 候補（未着手） |

> 📌 **実装タスクは完了済み**。業界特化のコア配線・二段判定・情報なしゲート・Web 重複排除・KPI 評価ランナーは
> [`agent_support_verticals.md` §8](../grace/doc/agent_support_verticals.md) で **6/6 ✅**。本書の TODO は「データ準備・ライブ計測・コスト」に限定される。
>
> **残るライブ作業（ユーザ環境）**:
> 1. 専用コレクション登録: `uv run python -m eval.vertical.register_test_collections --recreate`（§5 手順 2）
> 2. KPI ベースライン計測: `uv run python -m eval.vertical.run --vertical gov`（in-scope 精度は登録後に確定）
>
> ※ (c) の「コード」は完了済み。残るのは上記の**実測のみ**。反復実測が高コストなら (d) を先に入れると安くなる。

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
| 1.2 | §4 に第 5 カテゴリ **keyword-trap**（誤検知検査）と各業界の trap 質問例を追加。期待ラベル付きテストケース（`eval/vertical/cases/*.jsonl`）と KPI 評価ランナー（`eval/vertical/run.py`）の実装に合わせて §5 手順 3 を更新 |
| 1.3 | **TODO(b) 完了**: §3 に WebSearch 検証結果を反映（e-Gov 法令 API=政府標準利用規約 2.0・商用可 / 横浜市ポータル=CC BY 4.0 だが FAQ 専用 CSV は未確認 / JGLUE 系=CC BY-SA 4.0 / amazon_reviews_multi=配布終了確定→EC は合成を第一候補に）。§5 に**実コレクション名の確定表**（`gov_faq_anthropic` 等）と登録コマンド（`register_to_qdrant.py` / `make_qa_register_qdrant.py`）を追加 |
| 1.4 | **専用コレクションの合成データ登録を 1 コマンド化**: `eval/vertical/register_test_collections.py` と合成 Q&A（`eval/vertical/data/*.csv`・6 コレクション×各 10 件）を追加（§5 手順 2）。out-of-scope の「穴」を保つ設計をテスト（`tests/eval/test_register_test_collections.py`）で担保。ec.jsonl の keyword-trap に「未登録時は ④' 検知で escalate に倒れ得る（安全側）」ノートを追記 |
| 1.5 | **進捗最新化**: §0 成果物一覧に「評価・テスト（`eval/vertical/*`・`tests/*`）」を追加。§6 TODO を現況に同期（実装は `agent_support_verticals.md` §8 で 6/6 ✅ 完了／残は登録・KPI 実測のみ）＋ 検証コスト削減 (d)（record/replay キャッシュ）を候補として追記 |
| 1.6 | **KPI ベースライン実測＋誤エスカレ修正**: 3 業界の初回計測を反映（decision_accuracy = gov 0.857 / saas 1.000 / ec 0.889、citation_rate=1.00・ungrounded=0.00 は全業界）。ec の唯一の失敗「返金ポリシーを教えて」= **false escalate** を修正。原因は、出典付きの良質な内部RAG回答でも `GroundednessVerifier` が全 neutral（decided=0）だと `support_rate=0.0` になり `_answer_gate` が escalate に倒し、⑤ Web 二次生成で無関係な一般Web結果から「情報なし」回答に化けて ④' で誤エスカレする連鎖。**④-救済**（`_should_rescue_unaffirmed`）を追加し、支持0・矛盾なし・出典あり・**実質回答**の内部回答は未確認注記付きで answer を維持（範囲外の「情報なし」回答は除外し従来どおり escalate ＝ saas「売上見込み」は影響なし）。無駄な Web 二次生成も省け latency/コストも低減。テスト `tests/test_agent_support_vertical.py::TestRescueUnaffirmed` で固定。gov out-of-scope「税制改正の予測」の取りこぼし（予測・未確定系の intent）は別課題として残置 |
| 1.7 | **④-救済の判定基準を是正（回帰修正）**: v1.6 で追加した ④-救済が再計測で false escalate を減らせず、むしろ悪化（saas 1.000→0.875・ec 0.889→0.778／新規の in-scope 誤エスカレ = saas「API のレート制限」・ec「送料」）。原因は救済条件が `supported == 0`（全 neutral）に限定されていたこと。`GroundednessVerifier`（Haiku）は出力ぶれで **一部だけ肯定**（例 `supported=1 / contradicted=2` → `support_rate=0.33 < confirm_th`）も返し、この場合も「肯定の裏付けが弱いだけで矛盾なし」の良質回答が escalate→⑤ Web 二次生成→④' 誤エスカレの連鎖に落ちる。救済判定を**支持数の多寡ではなく「矛盾の有無」**に変更（`_should_rescue_unaffirmed` から `supported` 引数を削除。矛盾なし・出典あり・実質回答なら未確認注記付きで answer 維持）。矛盾検出時・範囲外「情報なし」回答（saas「売上見込み」/ ec「入荷予定日」）は従来どおり escalate。`TestRescueUnaffirmed` に低支持（`supported>0` かつ低 support_rate）ケースを追加して固定。**注意**: 失敗の主因である ③ groundedness は Haiku 依存で非決定的なため、`eval/vertical/run.py --show-agent-output` で失敗ケースのゲート発火を確認しつつ再計測して検証すること |
| 1.8 | **実運用ナレッジ取得を 1 コマンド化（次工程候補③）**: `eval/vertical/fetch_real_knowledge.py` を追加。gov は e-Gov 法令 API（v1 XML・政府標準利用規約 2.0）から法令全文を条単位の text CSV へ、saas は OSS 公式ドキュメント（既定 FastAPI 日本語版・MIT・タグ固定 URL）を見出しセクション単位の text CSV へ整形（長文は文境界で分割・出典 URL を source 列に保持）。ec は公開実データが無いため合成 or 自社 CSV を同一手順で登録（§5 手順 3 を 3-1 取得 / 3-2 登録に再構成）。パース・分割・CSV 出力は `tests/eval/test_fetch_real_knowledge.py` で固定（ネットワーク不要）。ライブ取得・登録・KPI 再計測はユーザー環境で実施 |
| 1.9 | **業界別説明ドキュメントを追加**: `docs/vertical_gov.md` / `vertical_saas.md` / `vertical_ec.md`（各業界の特化部分＝7 機構の割り当て・二段判定・collections 実検索限定・prompt_addendum 注入・実コレクション命名＋TODO(b)・KPI 評価ハーネス）。§0 ドキュメント一覧に追記 |
| 2.0 | **業界比較ドキュメントを追加**: `docs/vertical_comparison.md`（3 業界の横並び対比＝性格・7 機構・6 軸・二段判定の衝突語彙・検索スコープ設計・prompt_addendum・データ戦略・KPI の 8 観点＋全体対比図）。§0 ドキュメント一覧に追記 |
| 2.1 | **P0 是正（docs/vertical_docs_todo.md）**: §0 の KPI ケース数を実数（gov 7 / saas 8 / ec 9。jsonl 1 行目はコメント行のため行数≠ケース数）へ修正、成果物一覧の版数をリンク先ヘッダーに同期（agent_support_verticals v1.4 / agent_support_example v1.2 / vertical_gov・saas・ec v1.1 等）＋版数同期の運用注記を追加、変更履歴を昇順に並べ替え |
| 2.2 | **P1 改善（docs/vertical_docs_todo.md P1-3）**: §5 手順 4 に「SupportResult フィールド → KPI 指標」対応表を追加（intent は記録のみ・no_info_detected / web_reused は KPI 集計未使用、の区別を明記）。§0 の版数スナップショットを P1 反映後（gov/saas/ec v1.2・comparison v1.1・todo v1.1）に同期 |

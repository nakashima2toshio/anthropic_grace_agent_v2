# 業界特化ドキュメント 再チェック結果と改善 TODO

**Version 1.1** | 最終更新: 2026-07-10

> **進捗**: P0（3 件）は ✅ 完了（PR #160）。P1（4 件）は ✅ 完了（本更新と同じ PR）。
> 残りは **P2 のライブ計測のみ**（ユーザー環境で実施）。

`agent_support_example.py`（業界特化 GRACE-Support）の**理解を目的として**、下記 5 ドキュメントを実コード・実データと突合して再チェックした結果と、改善 TODO をまとめる。

- [`docs/vertical_gov.md`](./vertical_gov.md)（v1.1）
- [`docs/vertical_saas.md`](./vertical_saas.md)（v1.1）
- [`docs/vertical_ec.md`](./vertical_ec.md)（v1.1）
- [`docs/vertical_test_data.md`](./vertical_test_data.md)（v2.0）
- [`docs/vertical_comparison.md`](./vertical_comparison.md)（v1.0）

**突合対象（実コード・実データ）**: `agent_support_example.py` / `support_actions.py` /
`eval/vertical/cases/*.jsonl` / `eval/vertical/data/*.csv` / `eval/vertical/metrics.py` /
`grace/config.py` / `grace/tools.py` / `grace/doc/agent_support_verticals.md`（v1.4） /
`grace/doc/agent_support_example.md`（v1.2）。チェック実施日: 2026-07-10。

---

## 0. チェック結果サマリ

| 観点 | 結果 |
|---|---|
| プロファイル定義の引用コード（PROFILES / しきい値 / エスカレ語 / action_map） | ✅ 実コードと一致 |
| しきい値既定 0.7 / 0.4（`grace/config.py` ConfidenceThresholds） | ✅ 一致 |
| 意図分類モデル `claude-haiku-4-5-20251001`（INTENT_MODEL） | ✅ 一致 |
| `grace/tools.py::_apply_allowed_collections` / `_build_prompt` の行番号アンカー（525-528） | ✅ 現時点で正確 |
| KPI 10 指標名（`eval/vertical/metrics.py`） | ✅ 一致 |
| 合成データ「各 10 件」（`eval/vertical/data/*.csv` = ヘッダー＋10 行） | ✅ 一致 |
| Mermaid 黒背景規約（CLAUDE.md §7） | ✅ 全図適用済み |
| KPI ケース数・成果物一覧の版数・変更履歴の並び | ✅ **P0 の 3 件を是正済み**（PR #160） |
| 「プログラム理解」観点の構成 | ✅ **P1 の 4 件を適用済み**（comparison §9 新設ほか） |

---

## P0: 事実誤りの是正（すぐ直す・実害あり）— ✅ 完了（PR #160・vertical_test_data.md v2.1）

### P0-1. `vertical_test_data.md` §0 のテストケース件数が誤り

- **記載**: 「期待ラベル付き質問（gov 8 / saas 9 / ec 10 件・5 カテゴリ）」（§0 評価・テスト表）
- **実際**: **gov 7 / saas 8 / ec 9 件**。各 `eval/vertical/cases/*.jsonl` の 1 行目は
  `# コメント行`（JSONL 外のヘッダー）であり、`wc -l` の行数（8/9/10）をそのまま
  ケース数として記載してしまったのが原因。
- **根拠**: jsonl をパースした実ケース数は 7/8/9。業界別ドキュメント §7 の件数表
  （gov 7＝2+1+1+1+2 / saas 8＝2+1+1+2+2 / ec 9＝2+1+2+2+2）および
  `vertical_comparison.md` §8（7/8/9）**は正しい**。
- **対処**: §0 の件数を「gov 7 / saas 8 / ec 9 件」へ是正。あわせて
  「jsonl 1 行目はコメント行（行数≠ケース数）」の注記を §4 か §0 に一言添える。

### P0-2. `vertical_test_data.md` §0 成果物一覧の版数が古い

| ドキュメント | §0 の記載 | 実際 |
|---|---|---|
| `grace/doc/agent_support_verticals.md` | v0.8 | **v1.4**（2026-07-03） |
| `grace/doc/agent_support_example.md` | v1.0 | **v1.2**（2026-07-08） |
| `docs/vertical_gov.md` / `vertical_saas.md` / `vertical_ec.md` | v1.0 | **v1.1**（2026-07-04） |
| `docs/vertical_test_data.md`（本体） | v1.7 | **v2.0**（ヘッダーと不一致） |

- そのほか（grace_core v1.1 / grace_core_flow v1.1 / agent_example_core8 v1.0 /
  migration_and_update v1.0 / vertical_spec_review v1.2 / vertical_comparison v1.0）は一致 ✅。
- **対処**: 版数を実ファイルに同期。恒久策として、§0 の「状態」列は版数の手書きをやめ
  「実装済み／設計」等のステータスのみにする（版数はリンク先ヘッダーが正）ことも検討（P1-4 と同根）。

### P0-3. `vertical_test_data.md` §8 変更履歴の並び順が乱れている

- **現状**: 1.0 → … → 1.6 → **2.0 → 1.9 → 1.8 → 1.7** の順（1.6 の下に 2.0 が挿入され、
  以降が逆順）。版の追記位置を誤ったまま積み重なったもの。
- **対処**: 昇順（1.0 → 2.0）か降順（2.0 → 1.0）のどちらかに統一して並べ替える。
  他ドキュメント（昇順）に合わせるなら昇順を推奨。

---

## P1: 「プログラム理解」観点の改善（提案・中優先）— ✅ 完了（2026-07-10 適用）

> 適用先: P1-1/P1-2 = `vertical_comparison.md` §9 新設（①〜⑦フロー図＋コード読解マップ・v1.1）、
> P1-3 = `vertical_test_data.md` §5 手順 4（SupportResult→KPI 対応表・v2.2）、
> P1-4 = 判定ルール表を comparison §4 に集約し gov/saas/ec §4 は参照化＋行番号アンカーを関数名参照へ（各 v1.2）。

### P1-1. ①〜⑦パイプライン全体図に「3 つのゲート」を反映

- **現状**: 業界別ドキュメント §1 の図・`vertical_comparison.md` §9 の共通エンジン図は
  「② rag_search＋reasoning → ④ ゲート → (④'/⑤) → ⑥ Action」の粗い流れで、
  `run_support_agent()` の実フローにある **④-救済（`_should_rescue_unaffirmed`）** と
  **⑤ の Web 再利用最適化（`web_reused`・重複推論の省略）** が図に現れない。
  ④' は comparison にのみ登場し、業界別 3 本の図には無い。
- **提案**: `vertical_comparison.md` §9（または新 §）に、実コードの番号（①Plan →
  ②Execute → ③Groundedness → ④ゲート＋強制エスカレ＋④-救済 → ⑤Web フォールバック
  （再利用時は再検証のみ）→ ④'情報なし検知 → ⑥本人確認→CONFIRM→Action → ⑦応答）を
  そのまま使ったフロー図を 1 枚追加し、業界別 3 本の §1 からはそれを参照する。
  ④→⑤→④' の**適用順序**（④' は ⑤ の後に効く）が読み取れることが要点。

### P1-2. 「コード読解マップ」（機構 → 関数 → コード内アンカー）の追加

- **現状**: 7 つの機構がプロファイルのどのフィールドかは表になっているが、
  「そのフィールドがプログラムの**どの関数で**効くか」の対応が節をまたいで散在する。
- **提案**: 各業界ドキュメント（または comparison）に次の対応表を 1 つ追加する:
  `collections → run_support_agent()`（allowed_collections 配線）→
  `grace/tools.py::_apply_allowed_collections` ／ `escalate_keywords →
  _should_force_escalate()` ／ `action_map → _decide_action()` ／
  `require_identity → _perform_action()`＋`support_actions.py` ／
  `notify_th`/`confirm_th → _answer_gate()` ／ `prompt_addendum →
  config.llm.prompt_addendum → ReasoningTool._build_prompt()`。
  読者が `agent_support_example.py` を関数単位で辿れるようにする。

### P1-3. SupportResult の KPI フィールド → 10 指標の対応表

- **現状**: `SupportResult` の計測用フィールド（`forced_escalate` / `identity_checked` /
  `no_info_detected` / `web_reused` / `groundedness_decided` / `intent`）が
  どの KPI 指標（`eval/vertical/metrics.py` の 10 指標）に流れるかが、
  ドキュメント側から読み取れない（設計書 `agent_support_example.md` §7 に一部あり）。
- **提案**: `vertical_test_data.md` §5-4（KPI 評価ランナー）または各業界 §7 に
  「SupportResult フィールド → 指標」対応表を追加（例: `identity_checked →
  identity_check_rate`、`forced_escalate → forced_escalate_misfire_rate`、
  `groundedness_decided=0 → groundedness_neutral_rate`、`citations → citation_rate` 等）。

### P1-4. 二段判定・共通仕様の重複記載に同期ルールを明記

- **現状**: 二段判定の「判定ルール表」（第 1 段×第 2 段×結果）が gov/saas/ec/comparison の
  **4 箇所に同一内容**で存在する。各文書が単体で読める利点はあるが、仕様変更時に
  4 箇所同期が必要で、P0-2 のような版ずれ・記述 drift の温床になる。
- **提案**（いずれか）:
  1. 共通表は `vertical_comparison.md` §4 を正とし、業界別 3 本は「業界固有の実例表」
     だけ残して参照リンク化する（推奨）
  2. 重複を残す場合、各表の直下に「この表は 4 文書共通。変更時は
     gov/saas/ec/comparison を同時更新」と注記する
- 行番号アンカー（`grace/tools.py:525-528`）も drift しやすいため、
  「`grace/tools.py::_build_prompt()`（業務方針注入口）」のような関数名参照へ緩めることを推奨。

---

## P2: ライブ計測・運用（コード変更なし・ユーザー環境で実施）— ⏳ 未実施

### P2-0. 実施手順（ローカル・ランブック）

**前提（1 回だけ）**:

1. `.env` に `ANTHROPIC_API_KEY`（LLM）と `GOOGLE_API_KEY`（Embedding）を設定
2. Qdrant 起動: `docker-compose -f docker-compose/docker-compose.yml up -d`
   （確認: `curl http://localhost:6333/health`）
3. 依存同期: `uv sync`
4. 専用コレクション登録（6 個×各 10 件・Embedding 課金あり）:
   ```bash
   uv run python -m eval.vertical.register_test_collections --recreate
   ```
   期待: `gov_faq_anthropic` 〜 `ec_faq_anthropic` の 6 コレクションの登録ログ。
   存在確認: `uv run python -m qa_qdrant.command.list_collections`

**計測（P2-1 を含む 3 業種）**:

```bash
# スモーク（2 ケースだけ流して疎通確認）
uv run python -m eval.vertical.run --vertical gov --limit 2

# 本計測（1 業種 5〜7 分・逐次実行）
uv run python -m eval.vertical.run --vertical gov  --report logs/vertical_gov.json
uv run python -m eval.vertical.run --vertical saas --report logs/vertical_saas.json
uv run python -m eval.vertical.run --vertical ec   --report logs/vertical_ec.json
```

**期待する結果（前回ベースライン: 2026-07-03・agent_support_verticals.md §9.1）**:

| 業種 | decision_accuracy | 主眼 |
|---|---|---|
| gov | 1.000（7/7）維持 | false_escalate=0・ungrounded=0 の維持 |
| saas | **8/8 到達（前回 7/8）** | 唯一の不一致「500 エラー報告」が #12（web_search リトライ＋fallback_backend）で解消したことの確認 — **P2-1 の主目的** |
| ec | 1.000（9/9）維持 | identity_check_rate=1.000・keyword-trap 誤検知 0 の維持 |

共通: citation_rate=1.00 / ungrounded_answer_rate=0.00 / forced_escalate_misfire_rate=0 /
mean_latency ≈ 38〜44 秒/ケース。

**失敗時の切り分け**:

- 失敗ケースは `--show-agent-output` で再実行し、どのゲート（④/④-救済/④'/強制エスカレ）で
  倒れたかをログで確認する
- ③ groundedness（Haiku）は**非決定的**なため、1 回の失敗で回帰と断定しない（同ケースを再実行）
- web_search 起因（検索 0 件→情報なし化）なら #12 の設定（リトライ・fallback_backend）を確認
- API キー・Qdrant 未起動系のエラーは実行冒頭で分かる（`ANTHROPIC_API_KEY 未設定` / 接続エラー）

**結果の反映（3 箇所同期）**: `vertical_saas.md` §7・`vertical_comparison.md` §8・
`agent_support_verticals.md` §9.1 に計測 ID（例: vertical_saas5）と数値を追記。
反復計測が高コストな場合は先に P2-2 の (d)（record/replay キャッシュ）を導入する。

### P2-1. saas 再計測（#12 対策後の 8/8 確認）— 未実施のまま

- `vertical_saas.md` §7・`vertical_comparison.md` §8 に「#12（web_search リトライ設定化＋
  fallback_backend）で対策済み → **再計測で 8/8 到達を確認すること**」とあり、
  2026-07-10 時点で再計測記録が無い。
- **実行**: `uv run python -m eval.vertical.run --vertical saas --report logs/vertical_saas.json`
  → 結果を `vertical_saas.md` §7・`vertical_comparison.md` §8・
  `agent_support_verticals.md` §9.1 に反映（3 箇所同期）。

### P2-2. 既存 TODO の引き継ぎ（`vertical_test_data.md` §6）

- **(c) 自治体・最小動作確認**: 🚧 着手中のまま（コードは完了・残るはライブ実測のみ）。
- **(d) 検証コスト削減（record/replay キャッシュ）**: ⏳ 候補・未着手。
  反復再計測（P2-1 含む）が高コストなら先に入れると安くなる、という位置づけは維持。

---

## 対応順の目安

1. ~~**P0-1〜P0-3**（`vertical_test_data.md` の 3 是正）~~ — ✅ 完了（PR #160）
2. ~~**P1-1 → P1-2 → P1-3**（理解性の改善）~~ — ✅ 完了（comparison §9 新設・test_data §5 対応表）
3. ~~**P1-4**（重複の参照化）~~ — ✅ 完了（判定ルール表を comparison §4 に集約・3 本を参照化）
4. **P2-1 / P2-2**（ライブ計測）— ⏳ ユーザー環境で P2-0 のランブックに従って実施し、結果を各ドキュメントへ反映

## 変更履歴

| バージョン | 変更内容 |
|-----------|---------|
| 1.0 | 初版。業界特化ドキュメント 5 本を実コード・実データと突合し、P0（件数誤記・版ずれ・変更履歴の並び）／P1（ゲート反映のフロー図・コード読解マップ・KPI 対応表・重複の同期ルール）／P2（saas 再計測・既存 TODO 引き継ぎ）を整理 |
| 1.1 | **P0/P1 完了を反映＋P2 ランブック追加**: P0 は PR #160、P1 は comparison v1.1（§9 フロー図＋コード読解マップ・§4 判定ルール集約）／gov・saas・ec v1.2（参照化・関数名アンカー）／test_data v2.2（SupportResult→KPI 対応表）で適用。P2-0 として実施手順（前提・計測コマンド・期待結果・失敗時の切り分け・結果反映先）を追記 |

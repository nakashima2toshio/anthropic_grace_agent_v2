# gemini_grace_agent — LLMプロバイダー3社比較 移行計画書

**対象プロジェクト**: gemini_grace_agent
**目的**: Gemini / OpenAI / Anthropic 3社のAPI比較（特にPlanner結果の品質評価）
**作成日**: 2026-03-17

---

## 1. データから読み取れる重要な発見

### 発見1: Structured Output使用箇所は5ファイル、うちGRACEコアは2ファイル

Planner比較の核心である Structured Output を使っているのは `planner.py` と `confidence.py`（grace/）、および `step1〜3.py`（chunking/）の計5ファイルです。今回の比較のスコープは grace/ に絞れば、実質2ファイルのStructured Output差し替えで済みます。

### 発見2: `helper_api.py` に既にプロバイダー切り替え機構がある

`UnifiedLLMClient` が gemini/openai の切り替え対応を持っています。ただし、これは `generate_content` と `count_tokens` のみで、grace/ フォルダのモジュール群はこのラッパーを**使っていない**（`google.genai` 新SDKを直接呼んでいる）。ここにギャップがあります。

### 発見3: API種別ごとに移植難度が大きく異なる

- `generate_content`（15ファイル）は3社ともほぼ同等のAPIがあるため移植は容易。
- `embed_content`（4ファイル）は3社でモデル名・次元数・APIインターフェースが全く異なる。
- `Function Calling`（2ファイル）は今回のPlanner比較では不要。

### API種別の出現回数

| API種別 | 出現回数 |
|---|---|
| generate_content | 15 |
| embed_content | 4 |
| count_tokens | 3 |
| async | 3 |
| structured_output | 5 |
| chat_session | 2 |
| function_calling | 2 |
| config_only | 3 |

### SDK分布

| SDK種類 | ファイル数 |
|---|---|
| google.genai（新SDK） | 15 |
| google.generativeai（旧SDK） | 3 |
| helper経由 | 3 |
| 設定のみ | 3 |

---

## 2. 各APIの構造化出力の仕組み比較

### Gemini API

- **方式**: `response_mime_type="application/json"` + `response_schema` にPydanticモデルを直接渡す
- **GRACEでの現行実装**: `planner.py` がこの方式で `ExecutionPlan` を生成
- **2026年1月のアップデート**: JSON Schemaサポートが全Geminiモデルに拡張、PydanticやZodがそのまま使える

### OpenAI API

- **方式**: `response_format` に `json_schema` を指定、またはfunction calling で `strict: true`
- **保証**: Structured Outputsでスキーマ準拠が保証される
- **制約**: `additionalProperties: false` が必須、すべてのフィールドを `required` にする必要あり

### Anthropic API

- **方式**: `output_format` パラメータでJSON Schemaを渡す、またはPydanticモデルを `client.messages.parse()` で直接使用
- **技術**: constrained decodingにより、スキーマに合致しないトークン生成が不可能
- **状態**: 2025年11月公開ベータ

---

## 3. 3社の長所・短所（Planner用途の観点）

### Gemini API

**長所**:
- GRACEの現行実装がそのまま動く
- `response_schema` にPydanticモデルを直接渡せるので、`ExecutionPlan` の変換が不要
- Flashモデルのコストが安く、レスポンスも速い
- Google Search Groundingとの組み合わせが可能

**短所**:
- SDKのスキーマバリデーションが実APIより厳しく、`additionalProperties` の扱いで問題が報告されている
- プロパティの出力順序がデフォルトでアルファベット順になるため、明示的な `propertyOrdering` 指定が必要な場合がある

### OpenAI API

**長所**:
- Structured Outputsの実績が最も長く、エコシステムが成熟している
- `strict: true` でスキーマ100%準拠が保証される
- GPT-4oの推論能力が高く、複雑なクエリの計画分解で質の高い結果が期待できる
- 再帰的スキーマもサポート

**短所**:
- 全フィールドを `required` にする制約があり、GRACEの `ExecutionPlan` にある `Optional` フィールド（`query`, `collection`, `fallback` 等）をスキーマ変換時に `"type": ["string", "null"]` に書き換える必要がある
- 並列function callingとStructured Outputsが互換性がない
- 初回リクエスト時のスキーマ処理で若干のレイテンシが増加する

### Anthropic API

**長所**:
- Pydanticモデルを `client.messages.parse()` で直接利用でき、型安全なオブジェクトが返る
- `strict: true` をtool定義に設定すると、入力バリデーションが保証される
- 推論能力が高く、ニュアンスのある計画策定が期待できる

**短所**:
- Structured Outputsは比較的新しい機能（2025年11月公開ベータ）
- Extended thinkingモードとの互換性に制約がある
- GRACEの現行コードはGemini SDK（`google-genai`）に密結合しているため、Anthropic SDKへの書き換えが最も工数がかかる
- Embedding APIを自社提供していない（Voyagerなど外部モデルが必要）

---

## 4. 実装計画

### 推奨アーキテクチャ：Provider Adapter パターン

GRACEの `planner.py` を直接3社分書き換えるのではなく、**抽象化レイヤーを1つ挟む**。

```python
# grace/llm_adapter.py (新規作成)
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Type, Optional

class LLMProviderAdapter(ABC):
    """grace/ モジュール用 LLMプロバイダー抽象化"""

    @abstractmethod
    def generate_content(self, prompt: str, system: str = "",
                         temperature: float = 0.7) -> str:
        """テキスト生成 (executor, tools で使用)"""
        ...

    @abstractmethod
    def generate_structured(self, prompt: str, schema: Type[BaseModel],
                           system: str = "", temperature: float = 0.3) -> BaseModel:
        """Structured Output (planner, confidence で使用)"""
        ...

    @abstractmethod
    def embed_content(self, text: str) -> list[float]:
        """テキスト埋め込み (confidence で使用)"""
        ...
```

**`helper/UnifiedLLMClient` を拡張しない理由**: 既存のUnifiedLLMClientは `generate_content` と `count_tokens` しか持たず、Structured Output とEmbed のインターフェースがない。また、grace/ のモジュール群は `GraceConfig` から設定を取得する独自のライフサイクルを持つため、grace/ 専用のAdapterを設けるほうが依存関係がクリーン。

### Config への追加

```python
# grace/config.py への追加
class LLMConfig(BaseModel):
    provider: Literal["gemini", "openai", "anthropic"] = "gemini"
    model: str = "gemini-2.5-flash"

# grace/__init__.py での Adapter 生成
def create_adapter(config: GraceConfig) -> LLMProviderAdapter:
    match config.llm.provider:
        case "gemini":    return GeminiAdapter(config)
        case "openai":    return OpenAIAdapter(config)
        case "anthropic": return AnthropicAdapter(config)
```

---

## 5. Phase 別作業詳細

### Phase 0: LLM Provider Adapter 基盤（3日）

grace/ の4ファイル（planner, executor, tools, confidence）はすべて `google.genai` 新SDKの `client.models.generate_content` を**直接呼んでいる**。`helper/helper_api.py` に `UnifiedLLMClient` という既存の抽象化レイヤーがあるが、grace/ モジュールはこれを使っていない。

この乖離を解消するために、grace/ 専用の `LLMProviderAdapter` を新規作成する。

### Phase 1: 3社の Adapter 実装（1週間）

**GeminiAdapter** — 既存コードの移植。grace/ の4ファイルから `client.models.generate_content` の呼び出しパターンを抽出し、Adapterに統合。`response_schema=ExecutionPlan` のパターン（planner.py）と `client.models.embed_content`（confidence.py）をそのまま委譲。工数は最小。

**OpenAIAdapter** — 3つの技術的変換が必要:

1. **Structured Output の変換**: GRACEの `ExecutionPlan` はPydanticモデルで `Optional[str]` フィールドを多数持つ（`query`, `collection`, `fallback`, `timeout_seconds`）。OpenAI の Structured Outputs は全フィールド `required` + `additionalProperties: false` が必須なので、`Optional[str]` を `"type": ["string", "null"]` に変換するユーティリティが必要。

```python
# OpenAI用のスキーマ変換例
def pydantic_to_openai_schema(model: Type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    # Optional フィールドを ["type", "null"] 形式に変換
    # required に全フィールドを追加
    # additionalProperties: false を追加
    return transform(schema)
```

2. **Embedding モデルの差異**: Geminiは `gemini-embedding-001`（3072次元）だが、OpenAIは `text-embedding-3-small`（1536次元）または `text-embedding-3-large`（3072次元）。confidence.py のコサイン類似度計算は次元数に依存しないので動作するが、Qdrant側のコレクション定義と次元数が一致している必要がある点に注意。Planner比較では許容可。

3. **APIコールの構造差異**: Geminiは `client.models.generate_content(model=..., contents=...)` だが、OpenAIは `client.chat.completions.create(model=..., messages=[...])` で、メッセージ形式が異なる。

**AnthropicAdapter** — 2つの技術的変換が必要:

1. `client.messages.parse()` を使えばPydanticモデルを直接渡せる。GRACEの `ExecutionPlan` をそのまま `response_model` として渡せるため、Structured Output の変換は最も楽。

2. **Embedding API がない**: Anthropicは自社のEmbedding APIを提供していないため、confidence.py のEmbed部分は代替手段が必要。「Embeddingだけは Gemini/OpenAI のままにする」が現実的。

### Phase 2: grace/ モジュール差し替え（1週間）

| ファイル | 現行API | 改修内容 | 難度 |
|---|---|---|---|
| `planner.py` | generate_content + Structured Output | `generate_structured()` に差し替え。`response_schema=ExecutionPlan` のパターンをAdapter経由に | 中 |
| `executor.py` | generate_content のみ | `generate_content()` に差し替え。最も単純 | 低 |
| `tools.py` | generate_content のみ | `generate_content()` に差し替え。RAGSearchTool内のLLM呼び出しを変更 | 低 |
| `confidence.py` | generate_content + embed_content + Structured Output | 3種のAPI全てを差し替え。**最も改修範囲が広い** | 高 |

`confidence.py` が最も工数が大きいのは、LLMSelfEvaluator（Structured Output で信頼度スコアを取得）と QueryCoverageCalculator（Embedding でクエリ網羅度を計算）の2つの機能が同居しているため。

### Phase 3: 評価フレームワーク構築（1週間）

**テストケース設計**（20問）:

| カテゴリ | 問数 | 例 | 評価の狙い |
|---|---|---|---|
| 単純事実検索 | 4 | 「Pythonのデコレータとは何か」 | 1-2ステップの計画で十分。過剰計画を生まないか |
| マルチステップ推論 | 4 | 「GRACEとLangGraphの設計比較」 | 依存関係のあるステップを正しく組めるか |
| 日本語固有 | 4 | 「MeCabの形態素解析のエラー原因調査」 | 日本語クエリからの検索クエリ生成品質 |
| 曖昧・広範 | 4 | 「AIエージェントについてまとめて」 | 適切なスコープ分解ができるか |
| エッジケース | 4 | 空入力、超長文、矛盾する指示 | フォールバック計画の品質とスキーマ準拠率 |

**評価データモデル**:

```python
class PlanEvaluation(BaseModel):
    # 構造化出力の信頼性
    schema_compliance: bool      # ExecutionPlanとしてパースできたか
    parse_retry_count: int       # 何回リトライしたか (0が理想)

    # 計画品質 (LLM-as-Judge: 別のLLMが採点)
    step_logical_coherence: float    # 0-1: ステップの論理的一貫性
    query_relevance: float           # 0-1: 各ステップの検索クエリの適切さ
    step_count_appropriateness: float # 0-1: ステップ数の妥当性
    fallback_quality: float          # 0-1: フォールバック戦略の質
    dependency_correctness: bool     # depends_on が正しいか

    # 実行性能
    latency_ms: int             # 計画生成のレイテンシ
    input_tokens: int           # 入力トークン数
    output_tokens: int          # 出力トークン数
    estimated_cost_usd: float   # 推定コスト
```

### Phase 4: 比較実行 + レポート（3日）

3社 × 20問 = 60回の実行結果を Streamlit ダッシュボードで可視化する。UIは既存の `grace_chat_page.py` のパターンを踏襲し、サイドバーでプロバイダーとテストケースを選択、メインエリアで `ExecutionPlan` の並列比較を表示する設計。

---

## 6. 改修ファイル一覧（影響範囲）

一覧表の24ファイルのうち、**今回の比較で改修が必要なのは6ファイルのみ**。

| 改修対象 | 改修内容 | 他の18ファイルへの影響 |
|---|---|---|
| `grace/llm_adapter.py` | **新規作成** | なし |
| `grace/config.py` | `provider` フィールド追加 | なし |
| `grace/planner.py` | Adapter経由に変更 | なし |
| `grace/executor.py` | Adapter経由に変更 | なし |
| `grace/tools.py` | Adapter経由に変更 | なし |
| `grace/confidence.py` | Adapter経由に変更 | なし |

helper/、chunking/、services/、qa_generation/、ui/pages/ の各フォルダのファイルは**一切変更不要**。grace/ フォルダ内にAdapterパターンを閉じ込めることで、既存機能への影響をゼロにできる。

---

## 7. スケジュール

| Phase | 期間 | 作業内容 |
|---|---|---|
| Phase 0 | Day 1〜3 | LLM Provider Adapter 基盤作成 |
| Phase 1 | Day 4〜10 | 3社 Adapter 実装（Gemini / OpenAI / Anthropic） |
| Phase 2 | Day 11〜17 | grace/ モジュール差し替え + 評価フレームワーク構築 |
| Phase 4 | Day 18〜24 | 比較実行 + レポート生成 |

**合計**: 約24日（3.5週間）。Phase 2 と Phase 3 は並行作業可能なため、集中すれば3週間で完了可能。

---

## 8. コスト試算

60回の比較実行（3社×20問）での概算コスト:

| プロバイダー | モデル | 入力単価/1M tok | 出力単価/1M tok | 20問の推定コスト |
|---|---|---|---|---|
| Gemini | gemini-3-flash | $0.10 | $0.40 | ~$0.05 |
| OpenAI | gpt-4o | $2.50 | $10.00 | ~$1.50 |
| Anthropic | claude-sonnet-4-6 | $3.00 | $15.00 | ~$2.00 |

**合計: 約$3.55（500円程度）**

---

## 9. 総合評価

この比較計画は「やるべき」である。理由は3つ:

1. LLMプロバイダーの選択がAgent全体の品質に直結するため、定量的な比較データは今後の開発判断の基盤になる。
2. 抽象化レイヤーを構築する過程で、GRACEのLLM依存部分がきれいに分離され、コードの保守性が大幅に向上する。
3. 3社のStructured Outputsの実装差異を体験すること自体が、Agent開発者としての重要な技術知識になる。

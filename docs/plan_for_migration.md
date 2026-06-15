# GRACE Agent — LLMプロバイダー移行計画書

**対象プロジェクト**: gemini_grace_agent → openai_grace_agent / anthropic_grace_agent
**目的**: Gemini APIベースのGRACEエージェントを、OpenAI API版・Anthropic API版としてそれぞれ独立プロジェクトに移行する
**作成日**: 2026-04-03
**前提**: anthropic_grace_agent のEmbeddingは Gemini API を継続利用する

---

## 1. 移行プロジェクト全体像

### 1.1 スコープ定義

gemini_grace_agent の GRACE コアモジュール（grace/ フォルダ）を対象に、2つの独立プロジェクトを作成する。

| 項目 | openai_grace_agent | anthropic_grace_agent |
|---|---|---|
| テキスト生成 | OpenAI `chat.completions.create` | Anthropic `messages.create` |
| Structured Output | OpenAI `response_format` (json_schema) | Anthropic `messages.parse()` |
| Embedding | OpenAI `text-embedding-3-small` | **Gemini API** `gemini-embedding-001` |
| SDK | `openai` | `anthropic` + `google-genai`（Embed用） |

### 1.2 移行対象ファイル（共通）

grace/ フォルダ内の4ファイル＋設定・アダプター = 計6ファイルが改修対象。
helper/、chunking/、services/、qa_generation/、ui/pages/ は変更不要。

| ファイル | 利用API | 改修内容 | 難度 |
|---|---|---|---|
| `grace/llm_adapter.py` | — | **新規作成**: プロバイダー抽象化レイヤー | — |
| `grace/config.py` | — | `provider` フィールド追加 | 低 |
| `grace/planner.py` | generate_content + Structured Output | `generate_structured()` 経由に差し替え | 中 |
| `grace/executor.py` | generate_content のみ | `generate_content()` 経由に差し替え | 低 |
| `grace/tools.py` | generate_content のみ | `generate_content()` 経由に差し替え（RAGSearchTool内） | 低 |
| `grace/confidence.py` | generate_content + embed_content + Structured Output | 3種のAPI全差し替え。最大の改修範囲 | 高 |

---

## 2. 技術的課題と解決方針

### 2.1 openai_grace_agent 固有の課題

#### 課題A: Structured Output のスキーマ変換

GRACEの `ExecutionPlan` は Pydantic モデルで `Optional[str]` フィールドを多数持つ（`query`, `collection`, `fallback`, `timeout_seconds`）。OpenAI の Structured Outputs は**全フィールド `required`** + **`additionalProperties: false`** が必須のため、変換ユーティリティが必要。

```python
# 解決策: スキーマ変換ユーティリティ
def pydantic_to_openai_schema(model: Type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    for field_name, field_info in schema.get("properties", {}).items():
        if "anyOf" in field_info:  # Optional フィールドの検出
            types = [t["type"] for t in field_info["anyOf"] if "type" in t]
            field_info["type"] = types  # ["string", "null"] 形式に変換
            del field_info["anyOf"]
    schema["required"] = list(schema.get("properties", {}).keys())
    schema["additionalProperties"] = False
    return schema
```

#### 課題B: メッセージ形式の差異

Gemini は `contents=` に文字列を渡すが、OpenAI は `messages=[{"role": "user", "content": ...}]` 形式。system prompt の渡し方も異なる。

```python
# Gemini
client.models.generate_content(model=model, contents=prompt,
    config={"system_instruction": system})

# OpenAI
client.chat.completions.create(model=model, messages=[
    {"role": "system", "content": system},
    {"role": "user", "content": prompt}
])
```

#### 課題C: Embedding モデルの次元数

Gemini `gemini-embedding-001` は3072次元、OpenAI `text-embedding-3-small` は1536次元。Qdrant側のコレクション定義と一致させる必要がある。`text-embedding-3-large`（3072次元）を使えば次元数は一致するが、コストが上がる。

**推奨**: `text-embedding-3-small`（1536次元）を採用し、Qdrant コレクションを別名で新規作成する。コサイン類似度の計算ロジック自体は次元数非依存なので変更不要。

### 2.2 anthropic_grace_agent 固有の課題

#### 課題D: Embedding API の不在

Anthropic は自社の Embedding API を提供していない。本計画では **Gemini API の `gemini-embedding-001` をそのまま利用する**方針とする。

```python
# AnthropicAdapter — Embedding だけ Gemini SDK を使う
class AnthropicAdapter(LLMProviderAdapter):
    def __init__(self, config):
        self.anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.gemini_client = genai.Client(api_key=config.gemini_api_key)  # Embed専用

    def embed_content(self, text: str) -> list[float]:
        result = self.gemini_client.models.embed_content(
            model="gemini-embedding-001", contents=text)
        return result.embeddings[0].values
```

これにより、Qdrant 側のコレクション定義（3072次元）はそのまま流用可能。

#### 課題E: Structured Output の実装

Anthropic の `client.messages.parse()` は Pydantic モデルを `response_model` として直接渡せるため、GRACEの `ExecutionPlan` をほぼそのまま利用できる。OpenAI よりも変換が少なく、実装工数は最小。

```python
# Anthropic — Pydantic モデルをそのまま渡せる
response = self.anthropic_client.messages.parse(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}],
    response_model=ExecutionPlan
)
plan = response.parsed  # ExecutionPlan 型で返る
```

#### 課題F: メッセージ形式

Anthropic は `system` パラメータが `messages` の外にあるトップレベルパラメータ。

```python
# Anthropic
client.messages.create(
    model=model,
    system=system,  # トップレベル
    messages=[{"role": "user", "content": prompt}],
    max_tokens=4096
)
```

---

## 3. Provider Adapter 設計

### 3.1 抽象基底クラス

```python
# grace/llm_adapter.py
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Type

class LLMProviderAdapter(ABC):
    """GRACE モジュール用 LLM プロバイダー抽象化"""

    @abstractmethod
    def generate_content(self, prompt: str, system: str = "",
                         temperature: float = 0.7) -> str:
        """テキスト生成（executor, tools で使用）"""
        ...

    @abstractmethod
    def generate_structured(self, prompt: str, schema: Type[BaseModel],
                           system: str = "",
                           temperature: float = 0.3) -> BaseModel:
        """Structured Output（planner, confidence で使用）"""
        ...

    @abstractmethod
    def embed_content(self, text: str) -> list[float]:
        """テキスト埋め込み（confidence で使用）"""
        ...
```

### 3.2 各プロバイダーの Adapter 実装概要

#### OpenAIAdapter

```python
class OpenAIAdapter(LLMProviderAdapter):
    def __init__(self, config):
        self.client = openai.OpenAI(api_key=config.openai_api_key)
        self.model = config.openai_model  # "gpt-4o"
        self.embed_model = config.openai_embed_model  # "text-embedding-3-small"

    def generate_content(self, prompt, system="", temperature=0.7):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature)
        return response.choices[0].message.content

    def generate_structured(self, prompt, schema, system="", temperature=0.3):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": pydantic_to_openai_schema(schema)
                }
            })
        return schema.model_validate_json(response.choices[0].message.content)

    def embed_content(self, text):
        response = self.client.embeddings.create(
            model=self.embed_model, input=text)
        return response.data[0].embedding
```

#### AnthropicAdapter

```python
class AnthropicAdapter(LLMProviderAdapter):
    def __init__(self, config):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.gemini_client = genai.Client(api_key=config.gemini_api_key)
        self.model = config.anthropic_model  # "claude-sonnet-4-6"

    def generate_content(self, prompt, system="", temperature=0.7):
        response = self.client.messages.create(
            model=self.model, max_tokens=4096,
            system=system if system else "",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature)
        return response.content[0].text

    def generate_structured(self, prompt, schema, system="", temperature=0.3):
        response = self.client.messages.parse(
            model=self.model, max_tokens=4096,
            system=system if system else "",
            messages=[{"role": "user", "content": prompt}],
            response_model=schema, temperature=temperature)
        return response.parsed

    def embed_content(self, text):
        # Embedding は Gemini API を利用
        result = self.gemini_client.models.embed_content(
            model="gemini-embedding-001", contents=text)
        return result.embeddings[0].values
```

---

## 4. 移行スケジュール

### 4.1 推奨案: 並行開発（計4週間）

2つのプロジェクトは Adapter パターンにより独立しているため、Phase 1 完了後は並行開発が可能。

```
Week 1          Week 2          Week 3          Week 4
|--- Phase 1 ---|--- Phase 2 ---|--- Phase 3 ---|--- Phase 4 ---|
 共通基盤構築     OpenAI移行       Anthropic移行    統合テスト
                                                  + ドキュメント
```

### Phase 1: 共通基盤構築（Week 1 / Day 1–5）

| Day | 作業内容 | 成果物 |
|-----|---------|--------|
| 1 | プロジェクトリポジトリ作成（openai_grace_agent, anthropic_grace_agent） | 2リポジトリ |
| 1 | gemini_grace_agent からコードベースをコピー | ベースコード |
| 2–3 | `grace/llm_adapter.py` 抽象基底クラス作成 | LLMProviderAdapter |
| 3 | `grace/config.py` に `provider` 設定追加 | LLMConfig |
| 4–5 | grace/ モジュール（planner, executor, tools, confidence）を Adapter 経由に書き換え | 4ファイル改修 |

**Phase 1 完了条件**: GeminiAdapter を接続した状態で既存テストが全パスすること（＝リグレッションなし）。

### Phase 2: OpenAI 移行（Week 2 / Day 6–12）

| Day | 作業内容 | 難度 | 備考 |
|-----|---------|------|------|
| 6 | `openai` SDK インストール・API Key 設定 | 低 | `.env` に `OPENAI_API_KEY` 追加 |
| 6–7 | `OpenAIAdapter.generate_content()` 実装 | 低 | メッセージ形式変換のみ |
| 7–8 | `pydantic_to_openai_schema()` ユーティリティ作成 | 中 | Optional→null union 変換 |
| 8–9 | `OpenAIAdapter.generate_structured()` 実装 | 中 | ExecutionPlan でスキーマ準拠テスト |
| 9–10 | `OpenAIAdapter.embed_content()` 実装 | 低 | Qdrant コレクション次元数注意 |
| 10–11 | Qdrant コレクション設定（1536次元 or 3072次元） | 低 | 既存データとの共存方針決定 |
| 12 | 統合テスト（GRACE フロー全体） | — | Plan→Execute→Confidence 一気通貫 |

**Phase 2 完了条件**: openai_grace_agent で GRACE フロー（Plan→Execute→Confidence→Intervention→Replan）が正常動作すること。

### Phase 3: Anthropic 移行（Week 3 / Day 13–19）

| Day | 作業内容 | 難度 | 備考 |
|-----|---------|------|------|
| 13 | `anthropic` SDK インストール・API Key 設定 | 低 | `.env` に `ANTHROPIC_API_KEY` 追加 |
| 13–14 | `AnthropicAdapter.generate_content()` 実装 | 低 | system パラメータの位置差異に注意 |
| 14–15 | `AnthropicAdapter.generate_structured()` 実装 | 低 | `messages.parse()` で Pydantic 直渡し |
| 15–16 | `AnthropicAdapter.embed_content()` 実装（Gemini API） | 低 | `google-genai` SDK の依存追加 |
| 16–17 | Qdrant コレクション設定確認（3072次元＝Gemini互換） | 低 | 既存コレクション流用可能 |
| 18–19 | 統合テスト（GRACE フロー全体） | — | Plan→Execute→Confidence 一気通貫 |

**Phase 3 完了条件**: anthropic_grace_agent で GRACE フロー全体が正常動作すること。

### Phase 4: 統合テスト・ドキュメント（Week 4 / Day 20–24）

| Day | 作業内容 |
|-----|---------|
| 20–21 | 3社比較テスト実行（20問 × 3社 = 60回） |
| 22 | 品質評価レポート生成（Streamlit ダッシュボード） |
| 23 | 移行ドキュメント整備（README, MIGRATION.md） |
| 24 | systemd ユニット設定・GCP デプロイ確認 |

### 4.2 代替案: 逐次開発（計5週間）

リスクを抑えたい場合は、OpenAI 移行を完全に完了してから Anthropic 移行に着手する。

```
Week 1        Week 2        Week 3        Week 4        Week 5
|-- Phase 1 --|-- Phase 2 --|-- テスト  --|-- Phase 3 --|-- Phase 4 --|
 共通基盤       OpenAI移行     OpenAI検証    Anthropic移行  統合+ドキュメント
```

**推奨は 4.1 の並行開発案**。理由: Adapter パターンにより各プロバイダーの実装は完全に独立しており、片方の問題がもう片方に波及しない。

---

## 5. 依存パッケージ

### openai_grace_agent

```txt
# requirements.txt への追加
openai>=1.50.0
# google-genai は削除可能（Embedding も OpenAI に移行するため）
```

### anthropic_grace_agent

```txt
# requirements.txt への追加
anthropic>=0.40.0
google-genai>=1.0.0   # Embedding 用に残す
```

---

## 6. コスト試算（20問テスト実行時）

| プロバイダー | モデル | 入力単価/1M tok | 出力単価/1M tok | 20問の推定コスト |
|---|---|---|---|---|
| Gemini | gemini-3-flash | $0.10 | $0.40 | ~$0.05 |
| OpenAI | gpt-4o | $2.50 | $10.00 | ~$1.50 |
| Anthropic | claude-sonnet-4-6 | $3.00 | $15.00 | ~$2.00 |

合計: 約 $3.55（500円程度）。Embedding コスト（Gemini/OpenAI）は微小のため省略。

---

## 7. リスクと対策

| リスク | 影響度 | 発生確率 | 対策 |
|---|---|---|---|
| OpenAI スキーマ変換で ExecutionPlan の複雑な型（nested Optional, List）が正しく変換されない | 高 | 中 | 変換ユーティリティに単体テストを先行実装。Pydantic v2 の `model_json_schema()` 出力を逐一検証 |
| Anthropic `messages.parse()` がベータ版のため挙動が不安定 | 中 | 低 | フォールバックとして `messages.create()` + JSON パース手動実装を用意 |
| Qdrant 次元数不一致（OpenAI Embedding 1536次元 vs 既存 3072次元） | 高 | 確実 | OpenAI 用に別名コレクション作成。既存データの再インデックスが必要 |
| GCP サーバー上で複数プロジェクトの systemd 管理が煩雑化 | 低 | 中 | ポート分離（例: Gemini=8501, OpenAI=8502, Anthropic=8503） |
| API Rate Limit に到達（特に比較テスト60回実行時） | 中 | 低 | リトライ + exponential backoff を Adapter に組み込み |

---

## 8. 推奨開発順序

**OpenAI → Anthropic の順で開発することを推奨**する。理由:

1. **OpenAI のスキーマ変換が最大の技術的ハードル**。これを先に解決しておけば、Anthropic 移行時に「Pydantic 直渡しで動く」ことの恩恵を実感できる。
2. **OpenAI の Structured Outputs エコシステムが最も成熟**しており、問題発生時の情報が豊富。デバッグが容易。
3. **Anthropic の Embedding 不在は Gemini 流用で即解決**するため、Anthropic 移行は技術的障壁が少ない。

---

## 9. 成果物一覧

移行完了時に以下の成果物が揃う。

| 成果物 | 説明 |
|---|---|
| `openai_grace_agent/` リポジトリ | OpenAI API ベースの GRACE エージェント |
| `anthropic_grace_agent/` リポジトリ | Anthropic API（+ Gemini Embedding）ベースの GRACE エージェント |
| `grace/llm_adapter.py` | 各リポジトリのプロバイダー Adapter 実装 |
| 比較テスト結果（60実行） | 3社 × 20問の品質・コスト・レイテンシ比較データ |
| Streamlit ダッシュボード | ExecutionPlan 並列比較 UI |
| MIGRATION.md | 移行手順・注意点のドキュメント |

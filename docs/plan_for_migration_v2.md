# GRACE Agent — LLMプロバイダー移行計画書 v2

**対象プロジェクト**: gemini_grace_agent → openai_grace_agent / anthropic_grace_agent
**目的**: Gemini APIベースのGRACEエージェントを、OpenAI API版・Anthropic API版としてそれぞれ独立プロジェクトに移行する
**初版作成日**: 2026-04-03
**v2 更新日**: 2026-05-09
**前提**: anthropic_grace_agent のEmbeddingは Gemini API を継続利用する

---

## 📋 v2 での主要更新点（v1 からの差分）

| 章 | 変更内容 | 理由 |
|:---|:---|:---|
| 0章（新設） | **Gemini API 最新情報まとめ** | 2026-05 時点の最新モデル・SDK・APIパターンを一元整理 |
| 2.1節 | **GeminiAdapter の実装パターン更新** | 新SDK `google-genai==1.52.0` への移行完了を反映 |
| 6章 | **コスト試算更新** | 2026年5月時点の最新料金に修正。`gemini-2.5-flash` を基準モデルに変更 |
| 7章 | **リスク表に廃止モデル警告を追加** | `gemini-2.0-flash` が **2026-06-01廃止**（残り23日） |
| 全体 | モデル名・SDKバージョン・APIパターンを現行コードベースと一致させる | `config.py` / `planner.py` / 移行手順書 v2.1 の実コード調査結果を反映 |

---

## 🚨 緊急対応事項（2026-05-09 現在）

> **`gemini-2.0-flash` は 2026年6月1日をもってサービス停止。残り23日。**
>
> - 対象コード: `config.py` `AVAILABLE_MODELS` リスト内の `"gemini-2.0-flash"` エントリ
> - 移行先推奨: `gemini-2.5-flash`（同等性能・低コスト）または `gemini-2.5-flash`（最新・高性能）
> - `grace/config.py` の `LLMConfig.model` デフォルト値は既に `"gemini-2.5-flash"` のため影響なし
> - `config.yml` に `model: gemini-2.0-flash` の記載が残っていれば **即時変更が必要**

---

## 0. Gemini API 最新情報（2026-05 時点）

### 0.1 SDK 現状

| 項目 | 内容 |
|---|---|
| 現行SDK | `google-genai==1.52.0`（新統合SDK） |
| 旧SDK | `google-generativeai`（廃止。`gemini_grace_agent` では既に削除済み） |
| インポート | `from google import genai` / `from google.genai import types` |
| クライアント生成 | `genai.Client()` または `genai.Client(api_key="...")` |

**参照**: [Google GenAI SDK Documentation](https://googleapis.github.io/python-genai/) / [PyPI google-genai](https://pypi.org/project/google-genai/)

### 0.2 利用可能モデル一覧（2026-05 時点）

| モデルID | 区分 | コンテキスト | 最大出力 | 備考 |
|---|---|---|---|---|
| `gemini-2.5-flash` | **デフォルト推奨** | 1M tokens | 8,192 | 高速・高性能・Agentic向け |
| `gemini-3-pro-preview` | 最高性能 | 1M tokens | 64,000 | 思考モード対応 |
| `gemini-2.5-flash` | 安定版高速 | 1M tokens | 64,000 | 推論・コード・長文対応 |
| `gemini-2.5-flash-lite` | 最低コスト | 1M tokens | — | バッチ処理向け |
| `gemini-2.5-pro-preview` | 高性能安定版 | 1M tokens | 64,000 | — |
| ~~`gemini-2.0-flash`~~ | **⚠️ 廃止予定** | — | — | **2026-06-01 シャットダウン** |
| ~~`gemini-1.5-pro`~~ | レガシー | — | — | 使用不可 |

**参照**: [Gemini API Models](https://ai.google.dev/gemini-api/docs/models) / [Release notes](https://ai.google.dev/gemini-api/docs/changelog)

### 0.3 Embedding モデル

| モデルID | 次元数 | 用途 | 料金 |
|---|---|---|---|
| `gemini-embedding-001` | 3072 (MRL: 768/1536/3072) | テキスト埋め込み | 無料枠あり |

- `gemini_grace_agent` の Qdrant コレクションは **3072次元** で構築済み
- anthropic_grace_agent でもこのモデルを継続利用するため、Qdrantコレクションはそのまま流用可能

### 0.4 新SDK API パターン（現行コードから確認済み）

#### テキスト生成（generate_content）

```python
from google import genai
from google.genai import types

client = genai.Client()  # GOOGLE_API_KEY 環境変数から自動取得

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,                        # 文字列またはリスト
    config=types.GenerateContentConfig(
        system_instruction=system_prompt,   # システムプロンプト（Gemini固有）
        temperature=0.7,
        max_output_tokens=4096,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
)
text = response.text  # 簡易アクセス
# または
text = response.candidates[0].content.parts[0].text  # 防御的アクセス
```

#### Structured Output（JSON mode + Pydantic）

```python
# Pydantic モデルを response_schema に直接渡せる（新SDK固有機能）
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ExecutionPlan,      # Pydantic クラスをそのまま渡す
        temperature=0.3,
        max_output_tokens=8192,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
)
plan = ExecutionPlan.model_validate_json(response.text)
```

#### Chat セッション（マルチターン）

```python
chat = client.chats.create(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[tool_definition],
    )
)

# メッセージ送信（キーワード引数推奨）
response = chat.send_message(message=user_input)

# Function Calling レスポンス返送
function_response_part = types.Part.from_function_response(
    name=str(tool_name),
    response={"result": tool_result},
)
response = chat.send_message(message=function_response_part)
```

#### レスポンスアクセス（防御的パターン）

```python
# 新SDK では response.parts ではなく candidates 経由でアクセス
if response.candidates and len(response.candidates) > 0:
    candidate = response.candidates[0]
    if candidate.content and candidate.content.parts:
        for part in candidate.content.parts:
            if hasattr(part, 'text') and part.text:
                text = part.text
            if hasattr(part, 'function_call') and part.function_call:
                fn_name = part.function_call.name
                fn_args = dict(part.function_call.args) if hasattr(part.function_call, 'args') else {}
```

#### Embedding

```python
result = client.models.embed_content(
    model="gemini-embedding-001",
    contents=text,                          # 文字列
)
embedding = result.embeddings[0].values    # list[float]、3072次元
```

### 0.5 旧SDK → 新SDK 主要パターン対照表

| 操作 | 旧SDK (`google.generativeai`) | 新SDK (`google.genai`) |
|---|---|---|
| クライアント初期化 | `genai.configure(api_key=...)` + `GenerativeModel(model)` | `genai.Client(api_key=...)` |
| テキスト生成 | `model.generate_content(prompt, generation_config=GenerationConfig(...))` | `client.models.generate_content(model=..., contents=..., config=GenerateContentConfig(...))` |
| Structured Output | 手動JSONパース | `response_schema=PydanticClass` で直接取得 |
| チャット作成 | `model.start_chat()` → `ChatSession` | `client.chats.create(model=..., config=...)` |
| チャット送信 | `chat.send_message(msg)` | `chat.send_message(message=msg)` |
| レスポンスアクセス | `response.parts` | `response.candidates[0].content.parts` |
| Function Response | `genai.protos.Part(function_response={...})` | `types.Part.from_function_response(name=..., response=...)` |
| AFC 無効化 | デフォルト無効 | `AutomaticFunctionCallingConfig(disable=True)` |
| Embedding | `genai.embed_content(model=..., content=...)` | `client.models.embed_content(model=..., contents=...)` |

---

## 1. 移行プロジェクト全体像

### 1.1 スコープ定義

gemini_grace_agent の GRACE コアモジュール（grace/ フォルダ）を対象に、2つの独立プロジェクトを作成する。

| 項目 | openai_grace_agent | anthropic_grace_agent |
|---|---|---|
| テキスト生成 | OpenAI `chat.completions.create` | Anthropic `messages.create` |
| Structured Output | OpenAI `response_format` (json_schema) | Anthropic `messages.parse()` |
| Embedding | OpenAI `text-embedding-3-small` | **Gemini API** `gemini-embedding-001` |
| SDK | `openai>=2.0.0` | `anthropic>=0.40.0` + `google-genai>=1.52.0`（Embed用） |

### 1.2 移行対象ファイル（共通）

grace/ フォルダ内の主要ファイル＋設定・アダプター = 計7ファイルが改修対象。
helper/、chunking/、services/、qa_generation/、ui/pages/ は変更不要。

| ファイル | 利用API | 改修内容 | 難度 |
|---|---|---|---|
| `grace/llm_adapter.py` | — | **新規作成**: プロバイダー抽象化レイヤー | — |
| `grace/config.py` | — | `provider` フィールド追加（`LLMConfig.provider` は既に存在） | 低 |
| `grace/planner.py` | generate_content + Structured Output | `generate_structured()` 経由に差し替え | 中 |
| `grace/executor.py` | generate_content のみ | `generate_content()` 経由に差し替え | 低 |
| `grace/tools.py` | generate_content のみ | `generate_content()` 経由に差し替え（RAGSearchTool内） | 低 |
| `grace/confidence.py` | generate_content + embed_content + Structured Output | 3種のAPI全差し替え。最大の改修範囲 | 高 |
| `grace/replan.py` | generate_content | `generate_content()` 経由に差し替え | 低 |

### 1.3 現行 grace/ モジュールの Gemini API 利用箇所（実コード確認済み）

```python
# grace/planner.py（実コードから抽出）
from google import genai
from google.genai import types

client = genai.Client()

# Structured Output（response_schema にPydanticクラス直渡し）
response = self.client.models.generate_content(
    model=self.model_name,
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ExecutionPlan,
        temperature=self.config.llm.temperature,
        max_output_tokens=8192,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
    )
)
plan = ExecutionPlan.model_validate_json(response.text)
```

---

## 2. 技術的課題と解決方針

### 2.1 openai_grace_agent 固有の課題

#### 課題A: Structured Output のスキーマ変換

GRACEの `ExecutionPlan` は Pydantic モデルで `Optional[str]` フィールドを多数持つ（`query`, `collection`, `fallback`, `timeout_seconds`）。OpenAI の Structured Outputs は**全フィールド `required`** + **`additionalProperties: false`** が必須のため、変換ユーティリティが必要。

なお Gemini 新SDK では `response_schema=ExecutionPlan`（Pydantic クラスをそのまま渡す）だけで済んでいたが、OpenAI では手動変換が必要となる点が最大の工数差。

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

Gemini は `contents=` に文字列を渡し、system prompt は `GenerateContentConfig.system_instruction` で渡す。OpenAI は `messages=[{"role": "user", "content": ...}]` 形式で、system prompt も messages 配列に含める。

```python
# Gemini 新SDK（現行）
client.models.generate_content(
    model=model,
    contents=prompt,
    config=types.GenerateContentConfig(system_instruction=system)
)

# OpenAI
client.chat.completions.create(model=model, messages=[
    {"role": "system", "content": system},
    {"role": "user", "content": prompt}
])
```

#### 課題C: Embedding モデルの次元数

Gemini `gemini-embedding-001` は3072次元、OpenAI `text-embedding-3-small` は1536次元。Qdrant側のコレクション定義と一致させる必要がある。

**推奨**: `text-embedding-3-small`（1536次元）を採用し、Qdrant コレクションを別名で新規作成する。コサイン類似度の計算ロジック自体は次元数非依存なので変更不要。

| OpenAI Embedding モデル | 次元数 | 料金 | 推奨度 |
|---|---|---|---|
| `text-embedding-3-small` | 1536 | 低 | ✅ 推奨（コスト最適） |
| `text-embedding-3-large` | 3072 | 高 | △（Gemini互換次元だがコスト高） |

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
        return result.embeddings[0].values  # 3072次元
```

これにより、Qdrant 側のコレクション定義（3072次元）はそのまま流用可能。

#### 課題E: Structured Output の実装

Anthropic の `client.messages.parse()` は Pydantic モデルを `response_model` として直接渡せるため、GRACEの `ExecutionPlan` をほぼそのまま利用できる。Gemini の `response_schema=ExecutionPlan` と同様に変換不要。

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
    system=system,  # トップレベル（Gemini の system_instruction と類似した構造）
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
        """テキスト生成（executor, tools, replan で使用）"""
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

### 3.2 各プロバイダーの Adapter 実装

#### GeminiAdapter（現行 grace/ のパターンを直接踏襲）

```python
from google import genai
from google.genai import types

class GeminiAdapter(LLMProviderAdapter):
    def __init__(self, config):
        self.client = genai.Client()  # GOOGLE_API_KEY 環境変数から自動取得
        self.model = config.llm.model          # "gemini-2.5-flash"
        self.embed_model = config.embedding.model  # "gemini-embedding-001"

    def generate_content(self, prompt, system="", temperature=0.7):
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system if system else None,
                temperature=temperature,
                max_output_tokens=4096,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
        )
        return response.text

    def generate_structured(self, prompt, schema, system="", temperature=0.3):
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system if system else None,
                response_mime_type="application/json",
                response_schema=schema,          # Pydantic クラスを直接渡す
                temperature=temperature,
                max_output_tokens=8192,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
        )
        return schema.model_validate_json(response.text)

    def embed_content(self, text):
        result = self.client.models.embed_content(
            model=self.embed_model,
            contents=text,
        )
        return result.embeddings[0].values      # list[float]、3072次元
```

#### OpenAIAdapter

```python
import openai
from .utils import pydantic_to_openai_schema

class OpenAIAdapter(LLMProviderAdapter):
    def __init__(self, config):
        self.client = openai.OpenAI(api_key=config.openai_api_key)
        self.model = config.openai_model          # "gpt-4o"
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
        return response.data[0].embedding       # list[float]、1536次元
```

#### AnthropicAdapter

```python
import anthropic
from google import genai

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
        # Embedding は Gemini API を継続利用（3072次元）
        result = self.gemini_client.models.embed_content(
            model="gemini-embedding-001", contents=text)
        return result.embeddings[0].values
```

### 3.3 プロバイダー選択の比較（Structured Output）

| 機能 | Gemini | OpenAI | Anthropic |
|---|---|---|---|
| Pydantic 直渡し | ✅ `response_schema=Model` | ❌ スキーマ変換必要 | ✅ `response_model=Model` |
| Optional フィールド | ✅ そのまま動作 | ⚠️ null union 変換必要 | ✅ そのまま動作 |
| 実装難度 | 低 | 高（変換ユーティリティ必要） | 低 |

---

## 4. 移行スケジュール

### 4.1 推奨案: 並行開発（計4週間）

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
| 2–3 | `grace/llm_adapter.py` 抽象基底クラス + GeminiAdapter 作成 | LLMProviderAdapter, GeminiAdapter |
| 3 | `grace/config.py` の `provider` 設定確認（既に `LLMConfig.provider` フィールドあり） | 確認のみ |
| 4–5 | grace/ モジュール（planner, executor, tools, confidence, replan）を Adapter 経由に書き換え | 5ファイル改修 |

**Phase 1 完了条件**: GeminiAdapter を接続した状態で既存テストが全パスすること。

### Phase 2: OpenAI 移行（Week 2 / Day 6–12）

| Day | 作業内容 | 難度 |
|-----|---------|------|
| 6 | `openai` SDK 確認（既に `requirements.txt` に `openai==2.8.1` あり）・API Key 設定 | 低 |
| 6–7 | `OpenAIAdapter.generate_content()` 実装 | 低 |
| 7–8 | `pydantic_to_openai_schema()` ユーティリティ作成 | 中 |
| 8–9 | `OpenAIAdapter.generate_structured()` 実装・ExecutionPlan でスキーマ準拠テスト | 中 |
| 9–10 | `OpenAIAdapter.embed_content()` 実装・Qdrant コレクション新規作成（1536次元） | 低 |
| 11–12 | 統合テスト（GRACE フロー全体 Plan→Execute→Confidence） | — |

**Phase 2 完了条件**: openai_grace_agent で GRACE フロー（Plan→Execute→Confidence→Intervention→Replan）が正常動作すること。

### Phase 3: Anthropic 移行（Week 3 / Day 13–19）

| Day | 作業内容 | 難度 |
|-----|---------|------|
| 13 | `anthropic` SDK インストール・API Key 設定 | 低 |
| 13–14 | `AnthropicAdapter.generate_content()` 実装 | 低 |
| 14–15 | `AnthropicAdapter.generate_structured()` 実装（`messages.parse()` + Pydantic直渡し） | 低 |
| 15–16 | `AnthropicAdapter.embed_content()` 実装（Gemini `gemini-embedding-001` 流用） | 低 |
| 16 | Qdrant コレクション設定確認（3072次元 = Gemini と同一、流用可能） | 低 |
| 17–19 | 統合テスト（GRACE フロー全体） | — |

**Phase 3 完了条件**: anthropic_grace_agent で GRACE フロー全体が正常動作すること。

### Phase 4: 統合テスト・ドキュメント（Week 4 / Day 20–24）

| Day | 作業内容 |
|-----|---------|
| 20–21 | 3社比較テスト実行（20問 × 3社 = 60回） |
| 22 | 品質評価レポート生成（Streamlit ダッシュボード） |
| 23 | 移行ドキュメント整備（README, MIGRATION.md） |
| 24 | systemd ユニット設定・GCP デプロイ確認 |

---

## 5. 依存パッケージ

### gemini_grace_agent（現行）

```txt
google-genai==1.52.0       # 新統合SDK（旧 google-generativeai は削除済み）
openai==2.8.1              # 既存（比較テスト用途あり）
```

### openai_grace_agent

```txt
# requirements.txt
openai>=2.0.0
# google-genai は削除可能（Embedding も OpenAI に移行するため）
```

### anthropic_grace_agent

```txt
# requirements.txt
anthropic>=0.40.0
google-genai>=1.52.0   # Embedding 用に残す（gemini-embedding-001）
```

---

## 6. コスト試算（2026-05 時点料金・20問テスト実行時）

| プロバイダー | モデル | 入力単価/1M tok | 出力単価/1M tok | 20問の推定コスト |
|---|---|---|---|---|
| Gemini | `gemini-2.5-flash` | $0.50 | $3.00 | ~$0.05 |
| Gemini | `gemini-2.5-flash`（代替） | $0.30 | $2.50 | ~$0.04 |
| Gemini | `gemini-2.5-flash-lite`（最安） | $0.10 | $0.40 | ~$0.01 |
| OpenAI | `gpt-4o` | $2.50 | $10.00 | ~$1.50 |
| Anthropic | `claude-sonnet-4-6` | $3.00 | $15.00 | ~$2.00 |

**3社合計**: 約 $3.55（500円程度）。Embedding コストは微小のため省略。

> **注意**: Gemini の long context（200K トークン超）は全トークンが長文レートで課金される。
> Batch API 利用時は50%コスト削減可能。

---

## 7. リスクと対策

| リスク | 影響度 | 発生確率 | 対策 |
|---|---|---|---|
| **`gemini-2.0-flash` 廃止（2026-06-01）** | **高** | **確実** | **即時対応必要。`config.yml` を `gemini-2.5-flash` または `gemini-2.5-flash` に更新** |
| OpenAI スキーマ変換で ExecutionPlan の複雑な型（nested Optional, List）が正しく変換されない | 高 | 中 | 変換ユーティリティに単体テストを先行実装。Pydantic v2 の `model_json_schema()` 出力を逐一検証 |
| Anthropic `messages.parse()` がベータ版のため挙動が不安定 | 中 | 低 | フォールバックとして `messages.create()` + JSON パース手動実装を用意 |
| Qdrant 次元数不一致（OpenAI Embedding 1536次元 vs 既存 3072次元） | 高 | 確実 | OpenAI 用に別名コレクション作成。既存データの再インデックスが必要 |
| GCP サーバー上で複数プロジェクトの systemd 管理が煩雑化 | 低 | 中 | ポート分離（例: Gemini=8501, OpenAI=8502, Anthropic=8503） |
| API Rate Limit に到達（特に比較テスト60回実行時） | 中 | 低 | リトライ + exponential backoff を Adapter に組み込み（grace/config.py の `ErrorConfig` 設定を流用） |
| Gemini 新SDK の AFC（Automatic Function Calling）が予期せず有効化され空レスポンス発生 | 中 | 低 | `AutomaticFunctionCallingConfig(disable=True)` を全 generate_content 呼び出しに明示（現行 planner.py で実証済み） |

---

## 8. 推奨開発順序

**OpenAI → Anthropic の順で開発することを推奨**する。理由:

1. **OpenAI のスキーマ変換が最大の技術的ハードル**。Gemini/Anthropic では `response_schema`/`response_model` に Pydantic を直接渡せるが、OpenAI は手動変換が必要。先に解決すれば Anthropic 移行時の容易さを実感できる。
2. **OpenAI の Structured Outputs エコシステムが最も成熟**しており、問題発生時の情報が豊富。
3. **Anthropic の Embedding 不在は Gemini 流用で即解決**するため、Anthropic 移行は技術的障壁が少ない。

---

## 9. 成果物一覧

| 成果物 | 説明 |
|---|---|
| `openai_grace_agent/` リポジトリ | OpenAI API ベースの GRACE エージェント |
| `anthropic_grace_agent/` リポジトリ | Anthropic API（+ Gemini Embedding）ベースの GRACE エージェント |
| `grace/llm_adapter.py` | 各リポジトリのプロバイダー Adapter 実装（GeminiAdapter / OpenAIAdapter / AnthropicAdapter） |
| 比較テスト結果（60実行） | 3社 × 20問の品質・コスト・レイテンシ比較データ |
| Streamlit ダッシュボード | ExecutionPlan 並列比較 UI |
| MIGRATION.md | 移行手順・注意点のドキュメント |

---

## 改訂履歴

| 版 | 日付 | 変更内容 |
|---|---|---|
| v1 | 2026-04-03 | 初版作成 |
| v2 | 2026-05-09 | 0章（Gemini API最新情報）新設。新SDK `google-genai==1.52.0` パターンを全面反映。モデル名・料金を2026-05時点に更新。`gemini-2.0-flash` 廃止警告を緊急対応事項として追加。GeminiAdapter を現行コードベース（planner.py / migration v2.1）準拠の実装に更新。replan.py を移行対象ファイルに追加。 |

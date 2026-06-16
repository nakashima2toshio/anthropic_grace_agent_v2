# gemini_grace_agent — 旧SDK → 新SDK 移行計画書

**対象プロジェクト**: gemini_grace_agent
**目的**: 旧SDK (`google.generativeai`) を新SDK (`google.genai`) に統一
**作成日**: 2026-03-19
**前提**: 本移行はLLMプロバイダー3社比較（migration.md）の前段作業として実施する

---

## 目次

1. [移行対象の概要](#1-移行対象の概要)
2. [旧SDK → 新SDK 主要API対応表](#2-旧sdk--新sdk-主要api対応表)
3. [改修対象ファイル詳細](#3-改修対象ファイル詳細)
4. [改修順序と工数見積もり](#4-改修順序と工数見積もり)
5. [改修後に削除できるもの](#5-改修後に削除できるもの)

---

## 1. 移行対象の概要

全23ファイル中、旧SDK (`google.generativeai`) を使用しているのは **4ファイル**。
うち1ファイルは完全旧SDK、2ファイルは新旧両対応（フォールバック）、1ファイルは内部フォールバックコードを含む。

| ファイル | フォルダー | 分類 | 旧SDK API（改修対象） | 難度 |
|---------|-----------|------|---------------------|------|
| `agent_main.py` | (root) | 完全旧SDK | `GenerativeModel`, `ChatSession`, `start_chat`, `send_message`, Function Calling | **高** |
| `smart_qa_generator.py` | qa_generation/ | 新旧両対応 | `genai.configure`, `GenerativeModel`, `model.generate_content` | 中 |
| `pipeline.py` | qa_generation/ | 新旧両対応 | `genai.configure`, `GenerativeModel`, `model.generate_content` | 低 |
| `helper_llm.py` | helper/ | FB残存 | `except` ブロック内に旧SDKフォールバックコードが残存 | 低 |

残りの19ファイルは既に新SDK (`google.genai`) を使用しており、改修不要。

---

## 2. 旧SDK → 新SDK 主要API対応表

### 2.1 初期化

| 旧SDK (`google.generativeai`) | 新SDK (`google.genai`) |
|------|------|
| `import google.generativeai as genai` | `from google import genai` |
| `genai.configure(api_key=KEY)` | `client = genai.Client(api_key=KEY)` |

### 2.2 テキスト生成

| 旧SDK | 新SDK |
|------|------|
| `model = GenerativeModel("gemini-...")` | （モデルインスタンス不要） |
| `model.generate_content(prompt)` | `client.models.generate_content(model="gemini-...", contents=prompt)` |

### 2.3 Structured Output

| 旧SDK | 新SDK |
|------|------|
| `model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})` | `client.models.generate_content(model=..., contents=prompt, config={"response_mime_type": "application/json", "response_schema": PydanticModel})` |

### 2.4 Chat Session + Function Calling

| 旧SDK | 新SDK |
|------|------|
| `chat = model.start_chat()` | `chat = client.chats.create(model="gemini-...", config={"tools": [...]})` |
| `response = chat.send_message(prompt, tools=[...])` | `response = chat.send_message(prompt)` |
| `genai.protos.Content(parts=[...])` | `types.Part.from_function_response(...)` |
| `genai.protos.FunctionResponse(name=..., response=...)` | `automatic_function_calling` または手動FC |

### 2.5 トークンカウント

| 旧SDK | 新SDK |
|------|------|
| `model.count_tokens(prompt)` | `client.models.count_tokens(model="gemini-...", contents=prompt)` |

### 2.6 Embedding

| 旧SDK | 新SDK |
|------|------|
| `genai.embed_content(model="embedding-...", content=text)` | `client.models.embed_content(model="gemini-embedding-001", contents=text)` |

---

## 3. 改修対象ファイル詳細

### 3.1 `agent_main.py`（難度：高）

**現状**: 旧SDKの Chat Session + Function Calling の組み合わせを使用。461行の最大ファイル。

**現行コード（旧SDK）**:

```python
import google.generativeai as genai
from google.generativeai import ChatSession, GenerativeModel

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = GenerativeModel(
    model_name=AgentConfig.MODEL_NAME,
    system_instruction=SYSTEM_INSTRUCTION,
    tools=[search_rag_knowledge_base, list_rag_collections]
)
chat = model.start_chat()
response = chat.send_message(user_input)

# Function Callingのレスポンス処理（手動ループ）
for part in response.parts:
    if hasattr(part, 'function_call'):
        func_name = part.function_call.name
        func_args = dict(part.function_call.args)
        result = execute_tool(func_name, func_args)
        response = chat.send_message(
            genai.protos.Content(parts=[genai.protos.Part(
                function_response=genai.protos.FunctionResponse(
                    name=func_name, response={"result": result}
                )
            )])
        )
```

**改修案（新SDK）**:

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

tools = [search_rag_knowledge_base, list_rag_collections]

chat = client.chats.create(
    model=AgentConfig.MODEL_NAME,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=False
        )
    )
)
response = chat.send_message(user_input)
```

**改修戦略の選択**:

| 戦略 | 内容 | メリット | デメリット |
|------|------|---------|-----------|
| **A: automatic_function_calling** | SDK内部で自動的にツール呼び出し→結果返送 | コード量大幅削減 | ReActの中間プロセス表示が失われる |
| **B: 手動FC維持（推奨）** | `genai.protos.*` を `google.genai.types.*` に書き換え | ReAct思考プロセスの可視化を維持 | 改修箇所が多い |

**推奨: 戦略B**。`agent_main.py` はCLI版のReActエージェントであり、思考プロセスの可視化がこのファイルの存在意義。`agent_service.py`（services/）の新SDK実装をリファレンスにすれば、改修のリスクを最小化できる。

---

### 3.2 `smart_qa_generator.py`（難度：中）

**現状**: 新旧両対応のtry/except分岐を持つ。

**現行コード（新旧フォールバック）**:

```python
try:
    from google import genai
    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(
        model=model_name, contents=prompt
    )
except ImportError:
    import google.generativeai as genai
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
```

**改修案（新SDK一本化）**:

```python
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def generate_qa(prompt: str, model_name: str) -> str:
    response = client.models.generate_content(
        model=model_name,
        contents=prompt
    )
    return response.text
```

旧SDK分岐を完全削除し、新SDK一本化。`generate_content` のみの使用なので変換は素直。

---

### 3.3 `pipeline.py`（難度：低）

**現状**: `smart_qa_generator.py` と同じパターンの新旧両対応。

**改修案**: `smart_qa_generator.py` と同様に旧SDK分岐を削除し新SDK一本化。このファイルは `smart_qa_generator.py` を呼び出すパイプライン制御なので、内部で直接APIを叩く箇所は少なく、`smart_qa_generator.py` の改修が完了すれば連動して解決する部分が大きい。

---

### 3.4 `helper_llm.py`（難度：低）

**現状**: 新SDKが主だが、旧SDKフォールバックコードが残存。

**現行コード（フォールバック残存）**:

```python
try:
    from google import genai
    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(model=..., contents=...)
except Exception:
    import google.generativeai as old_genai
    old_genai.configure(api_key=API_KEY)
    model = old_genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
```

**改修案（フォールバック削除）**:

```python
from google import genai

class GeminiLLMClient:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def generate(self, prompt: str, model: str, **kwargs) -> str:
        response = self.client.models.generate_content(
            model=model, contents=prompt, config=kwargs
        )
        return response.text

    def count_tokens(self, prompt: str, model: str) -> int:
        result = self.client.models.count_tokens(
            model=model, contents=prompt
        )
        return result.total_tokens
```

`except` ブロック内の旧SDK呼び出しを完全削除。新SDKが安定稼働しているため、フォールバック分岐を維持する理由はない。

---

## 4. 改修順序と工数見積もり

影響範囲が小さいものから着手し、各ステップでテスト確認してから次へ進む。

| Step | ファイル | 改修内容 | 工数 | テスト方法 |
|------|---------|---------|------|-----------|
| **1** | `helper_llm.py` | フォールバック削除 | 0.5日 | 既存Streamlit UIの正常動作確認（helper_api → grace/* → ui/pages/* → services/* のチェーン） |
| **2** | `pipeline.py` | 旧SDK分岐削除 | 0.5日 | QA生成パイプラインのimport確認 |
| **3** | `smart_qa_generator.py` | 旧SDK分岐削除 + 新SDK一本化 | 1日 | QA生成パイプラインのE2Eテスト（入力テキスト→QAペア出力） |
| **4** | `agent_main.py` | Chat + FC 全面書き換え + ReActテスト | 2〜3日 | CLIでのReAct+Reflectionループ動作確認、FC結果返送の検証 |

**合計工数: 4〜5日**

### 改修順序の設計思想

**Step 1 → `helper_llm.py` を最初に改修する理由**: このファイルは `helper_api.py` → `ui/pages/*` → `services/*` のチェーン上流にあるが、改修内容は「exceptブロックの削除」だけで、正常系の動作パスには影響しない。改修後に既存のStreamlit UIが正常動作することを確認すれば、新SDKが安定していることの証明になる。

**Step 2〜3 → `qa_generation/` の2ファイルをセットで改修する理由**: `pipeline.py` が `smart_qa_generator.py` を呼び出す親子関係にあるため、片方だけ改修すると不整合が起きる。`pipeline.py`（import周りだけ）を先に改修してから `smart_qa_generator.py` の旧SDK分岐を削除し、QA生成パイプラインのE2Eテスト（テキスト入力→QAペア出力）で動作確認する。

**Step 4 → `agent_main.py` を最後にする理由**: 461行の最大ファイルで、Chat Session + Function Calling + ReActループという3要素が絡む。特に `genai.protos.Content` / `genai.protos.FunctionResponse` を手動構築してFunction Callingの結果を返送している箇所は、新SDKでは `types.Part.from_function_response()` か `automatic_function_calling` への置き換えが必要で、ReActの思考プロセス可視化に影響する。

### `agent_main.py` 改修時の最大リスク

`agent_main.py` のFunction Callingループで、`genai.protos.Content` / `genai.protos.Part` / `genai.protos.FunctionResponse` を手動構築している箇所が最大の改修ポイント。新SDKでは以下の2戦略がある:

- **automatic_function_calling 有効化**: ツール呼び出しが自動化されるが、ReActの中間プロセス表示が失われる
- **手動FC維持（推奨）**: `agent_service.py`（services/）が既に新SDKで手動FC制御を実装しているので、そのパターンを移植する

---

## 5. 改修後に削除できるもの

旧SDK一本化が完了すると、以下の不要コード・依存を削除できる。

| 削除対象 | 内容 | 推定削減行数 |
|---------|------|------------|
| `requirements.txt` | `google-generativeai` パッケージ依存の削除（`google-genai` のみ残す） | 1行 |
| 各ファイルの `try/except ImportError` | フォールバック分岐の削除 | 各20〜40行 × 3ファイル |
| `agent_main.py` の `genai.protos.*` | 旧SDK特有のprotobuf構築コード | 約30行 |
| `celery_config.py` | 旧SDK前提のモデル設定を新SDK前提に統一 | 微小 |

**推定合計削減: 約100〜150行の不要コード削除**

---

## 付録: 移行前後のSDK分布

### 移行前

| SDK種類 | ファイル数 |
|---|---|
| google.genai（新SDK） | 15 |
| google.generativeai（旧SDK）含む | 4 |
| helper経由 | 3 |
| 設定のみ | 3 |

### 移行後（目標）

| SDK種類 | ファイル数 |
|---|---|
| google.genai（新SDK） | 19 |
| google.generativeai（旧SDK）含む | **0** |
| helper経由 | 3 |
| 設定のみ | 3 |

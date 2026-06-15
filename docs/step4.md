
# Step 4: `agent_main.py` — Chat + FC 全面書き換え

## 4.1 改修内容の概要

`agent_main.py` は CLI 版 ReAct + Reflection エージェント（461行）で、旧SDKの以下3要素を全面的に書き換える:

1. **Chat Session**: `genai.GenerativeModel` + `model.start_chat()` → `client.chats.create()`
2. **Function Calling**: `genai.protos.Part(function_response=...)` → `types.Part.from_function_response()`
3. **API 初期化**: `genai.configure(api_key=...)` → `genai.Client(api_key=...)`

**改修する理由**: 最大のファイルで3要素が絡む高難度改修のため、Step 1〜3 で新SDK安定動作を確認した後に着手する。

**改修戦略: 手動FC維持（戦略B）を推奨**。`automatic_function_calling` を有効にするとコード量は減るが、ReAct の思考プロセス可視化（このファイルの存在意義）が失われる。`services/agent_service.py` の新SDK実装をリファレンスにする。

## 4.2 対象ファイル

`agent_main.py`（ルートディレクトリ）

### 関連ファイル（改修不要だが参照）

| ファイル | 役割 |
|:---|:---|
| `agent_tools.py` | ツール関数定義（`search_rag_knowledge_base`, `list_rag_collections`）。改修不要。 |
| `services/agent_service.py` | 新SDK版の ReActAgent 実装。**リファレンスとして参照**。 |

## 4.3 対象箇所と改修コード

### 対象箇所 (1): インポート文

**改修前:**

```python
import google.generativeai as genai
from google.generativeai import ChatSession, GenerativeModel
```

**改修後:**

```python
from google import genai
from google.genai import types
```

---

### 対象箇所 (2): `_setup_session` メソッド（API初期化 + Chat Session 作成）

**改修前:**

```python
def _setup_session(self) -> ChatSession:
    """Geminiエージェントのセットアップ"""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("API Key missing: GEMINI_API_KEY or GOOGLE_API_KEY not set.")

    genai.configure(api_key=api_key)

    # 動的にコレクション一覧を取得
    available_collections = get_available_collections_dynamic()
    collections_str = ", ".join(available_collections)

    system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(
        available_collections=collections_str
    )

    tools_list = [search_rag_knowledge_base, list_rag_collections]

    model = genai.GenerativeModel(
        model_name=self.model_name,
        tools=tools_list,
        system_instruction=system_instruction
    )

    chat = model.start_chat(enable_automatic_function_calling=False)
    return chat
```

**改修後:**

```python
def _setup_session(self):
    """Geminiエージェントのセットアップ（新SDK版）"""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("API Key missing: GEMINI_API_KEY or GOOGLE_API_KEY not set.")

    self.client = genai.Client(api_key=api_key)

    # 動的にコレクション一覧を取得
    available_collections = get_available_collections_dynamic()
    collections_str = ", ".join(available_collections)

    system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(
        available_collections=collections_str
    )

    tools_list = [search_rag_knowledge_base, list_rag_collections]

    chat = self.client.chats.create(
        model=self.model_name,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools_list,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True  # 手動FC維持（ReAct思考プロセスの可視化のため）
            ),
        ),
    )
    return chat
```

**変更ポイント:**

| 項目 | 旧SDK | 新SDK |
|:---|:---|:---|
| 初期化 | `genai.configure(api_key=...)` | `genai.Client(api_key=...)` |
| モデル | `genai.GenerativeModel(model_name=..., tools=..., system_instruction=...)` | 不要（`chats.create` に統合） |
| Chat 作成 | `model.start_chat(enable_automatic_function_calling=False)` | `client.chats.create(model=..., config=GenerateContentConfig(...))` |
| AFC 制御 | `enable_automatic_function_calling=False` | `automatic_function_calling=AutomaticFunctionCallingConfig(disable=True)` |

---

### 対象箇所 (3): Function Calling レスポンス返送（`_execute_react_loop` 内）

**これが最大の改修ポイント。** `genai.protos.Part(function_response=...)` を新SDK の `types.Part.from_function_response()` に置き換える。

**改修前:**

```python
# 次のターンへ（ツール結果をモデルに返送）
current_response = self.chat_session.send_message(
    [genai.protos.Part(
        function_response={
            "name"    : tool_name,
            "response": {'result': tool_result}
        }
    )]
)
```

**改修後:**

```python
# 次のターンへ（ツール結果をモデルに返送）
function_response_part = types.Part.from_function_response(
    name=tool_name,
    response={"result": tool_result},
)
current_response = self.chat_session.send_message(function_response_part)
```

**変更ポイント:**

| 項目 | 旧SDK | 新SDK |
|:---|:---|:---|
| FunctionResponse構築 | `genai.protos.Part(function_response={"name": ..., "response": ...})` | `types.Part.from_function_response(name=..., response=...)` |
| 送信方法 | `chat.send_message([Part])` (リストで渡す) | `chat.send_message(Part)` (直接渡す) |

---

### 対象箇所 (4): レスポンスの parts アクセス

**改修前:**

```python
for part in current_response.parts:
    if part.text:
        text = part.text.strip()
    if part.function_call:
        fn = part.function_call
        tool_name = fn.name
        tool_args = dict(fn.args)
```

**改修後:**

```python
for part in current_response.candidates[0].content.parts:
    if part.text:
        text = part.text.strip()
    if part.function_call:
        fn = part.function_call
        tool_name = fn.name
        tool_args = dict(fn.args)
```

> **注意**: 新SDK の `chats.create` が返す `send_message` レスポンスの構造は、旧SDKと異なる場合がある。`services/agent_service.py` の既存実装を参照し、`response.parts` か `response.candidates[0].content.parts` かを確認すること。Chat Session 経由であれば `.text` / `.parts` でアクセスできる可能性が高い（要実機確認）。

---

### 対象箇所 (5): 型ヒント（ChatSession の削除）

**改修前:**

```python
from google.generativeai import ChatSession, GenerativeModel

class UpgradedCLIAgent:
    def __init__(self, model_name: str = None):
        self.chat_session = self._setup_session()

    def _setup_session(self) -> ChatSession:
```

**改修後:**

```python
from google import genai
from google.genai import types

class UpgradedCLIAgent:
    def __init__(self, model_name: str = None):
        self.chat_session = self._setup_session()

    def _setup_session(self):  # 型ヒントは省略（新SDKのChat型を確認後に追加可）
```

## 4.4 改修後に削除できるもの

| 削除対象 | 内容 | 推定行数 |
|:---|:---|:---|
| `import google.generativeai as genai` | 旧SDKインポート | 1行 |
| `from google.generativeai import ChatSession, GenerativeModel` | 旧SDK型インポート | 1行 |
| `genai.configure(api_key=...)` | 旧SDK初期化 | 1行 |
| `genai.GenerativeModel(...)` | 旧SDKモデルインスタンス生成 | 5行 |
| `model.start_chat(enable_automatic_function_calling=False)` | 旧SDK Chat 作成 | 1行 |
| `genai.protos.Part(function_response=...)` | 旧SDK protobuf 構築 | 約8行 |

**推定削減: 約20〜30行**（新SDKコードとの差し替え分を含めるとネットでは微減）

## 4.5 改修後の動作確認テスト

### テスト環境の前提

- Step 1〜3 が全て完了し、テスト済みであること
- `GEMINI_API_KEY` または `GOOGLE_API_KEY` が設定済み
- Qdrant サーバーが稼働中
- `agent_tools.py` の `search_rag_knowledge_base` が正常動作すること

### テスト 1: 起動テスト

```bash
python agent_main.py
```

**期待結果:**

- エラーなく起動する
- `🤖 Upgraded CLI Agent (ReAct + Reflection)` バナーが表示される
- `✅ ReAct + Reflection 2段階処理` 等の機能一覧が表示される

### テスト 2: 一般質問（ツール不使用）

```
💬 You: こんにちは
```

**期待結果:**

- ツール呼び出しが発生しない（`🛠️ Tool Call` が表示されない）
- `🤖 Agent:` で挨拶が返される
- Reflection フェーズが実行される

### テスト 3: RAG 検索（Function Calling の動作確認）★最重要

```
💬 You: 金色夜叉の著者は誰ですか？
```

**期待結果（処理順序の確認）:**

1. `💭 Thought:` — 思考プロセスが表示される
2. `🛠️ Tool Call: search_rag_knowledge_base({"query": "..."})` — FC が発動する
3. `📝 Tool Result:` — ツール結果が表示される（`genai.protos` エラーが出ないこと）
4. `💭 Thought:` — 結果に基づく思考が表示される
5. `🔄 Reflection Phase` — Reflection フェーズに入る
6. `🤖 Agent:` — 最終回答が返される

### テスト 4: 連続ターン（Chat Session の状態維持）

```
💬 You: 東京タワーについて教えて
💬 You: その高さは何メートルですか？
```

**期待結果:**

- 2回目の質問で「その」が「東京タワー」を指すことを理解する
- Chat Session のコンテキストが維持されている

### テスト 5: リセットテスト

```
💬 You: reset
```

**期待結果:**

- `🔄 Resetting agent...` が表示される
- `✅ Agent reset complete!` が表示される
- 新しいセッションが作成される

### テスト 6: エラーハンドリング

```
💬 You: 存在しないコレクションから検索して
```

**期待結果:**

- `RAGToolError` がキャッチされ、ユーザーにエラーメッセージが表示される
- エージェントがクラッシュしない

---

# 全体完了後の最終確認

## requirements.txt の更新

```diff
- google-generativeai>=0.7.0
+ # google-generativeai は不要（google-genai に統一済み）
  google-genai>=1.0.0
```

## 全体 grep 確認

```bash
# プロジェクト全体で旧SDKの参照が残っていないことを確認
grep -rn "google.generativeai" --include="*.py" .
grep -rn "genai.configure" --include="*.py" .
grep -rn "genai.protos" --include="*.py" .
grep -rn "GenerativeModel" --include="*.py" .
```

**期待結果**: 全てのコマンドで 0 件がヒットすること。

## 推定合計削減

| Step | ファイル | 推定削減行数 |
|:---|:---|:---|
| Step 1 | `helper_llm.py` | 5〜8行 |
| Step 2 | `pipeline.py` | 20〜40行 |
| Step 3 | `smart_qa_generator.py` | 約27行（実コード確認済み） |
| Step 4 | `agent_main.py` | 20〜30行 |
| **合計** | — | **約65〜120行の不要コード削除** |

---

## 補足: 未提供ファイルの一覧

以下のファイルは本手順書作成時に未提供であった。実際の改修時にはファイル内容を確認し、対象箇所のコード（改修前/改修後）を更新すること。

| Step | ファイル | 現状 |
|:---|:---|:---|
| Step 2 | `qa_generation/pipeline.py` | 未提供（改修方針のみ記述） |
| Step 3 | `qa_generation/smart_qa_generator.py` | 未提供（改修方針のみ記述） |
| (参照) | `services/agent_service.py` | 未提供（Step 4 のリファレンス） |

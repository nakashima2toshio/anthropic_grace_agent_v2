# gemini_grace_agent — 旧SDK → 新SDK 移行手順書

**対象プロジェクト**: gemini_grace_agent
**目的**: 旧SDK (`google.generativeai`) を新SDK (`google.genai`) に統一
**作成日**: 2026-03-22
**参照**: `agent_rag_new_api_migration.md`（移行計画書）

---

## 改修順序サマリ

| Step | 対象ファイル | 改修内容 | 難度 | 工数 |
|:---|:---|:---|:---|:---|
| Step 1 | `helper/helper_llm.py` | フォールバック削除 | 低 | 0.5日 |
| Step 2 | `qa_generation/pipeline.py` | 旧SDK分岐削除 | 低 | 0.5日 |
| Step 3 | `qa_generation/smart_qa_generator.py` | 旧SDK分岐削除 + 新SDK一本化 | 中 | 1日 |
| Step 4 | `agent_main.py` | Chat + FC 全面書き換え + ReActテスト | 高 | 2〜3日 |

---

# Step 1: `helper_llm.py` — フォールバック削除

## 1.1 改修内容の概要

`helper_llm.py` は LLM クライアントの抽象化レイヤーで、OpenAI API と Gemini API の統一インターフェースを提供する。メインの `GeminiClient` クラスは既に新SDK (`google.genai`) を使用しているが、**`except` ブロック内に旧SDK (`google.generativeai`) へのフォールバックコードが残存**している。

このフォールバックを削除し、新SDKのみで動作するクリーンな状態にする。

**改修する理由**: Step 1 を最初に行うことで、新SDKが本番環境で安定動作していることの証明になる。改修内容は「except ブロックの削除」のみで正常系のコードパスに影響しないため、リスクが最も低い。

## 1.2 対象ファイル

`helper/helper_llm.py`

## 1.3 対象箇所と改修コード

### 対象箇所 (1): SDK インポート部分

旧SDKの ImportError フォールバックを削除し、新SDKの直接インポートに変更する。

**改修前:**

```python
# SDK imports
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
```

**改修後:**

```python
# SDK imports
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from google import genai
from google.genai import types
```

**変更理由**: `google-genai` パッケージは本番環境に必ずインストールされている前提のため、`ImportError` ガードは不要。`None` 代入による遅延エラーより、import 時の即座のエラーの方がデバッグしやすい。

---

### 対象箇所 (2): `GeminiClient.__init__` のガード条件

**改修前:**

```python
class GeminiClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, default_model: str = "gemini-2.0-flash"):
        if not genai:
            raise ImportError("google-genai package is not installed. Install with: pip install google-genai")
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is not set")
        self.client = genai.Client(api_key=self.api_key)
        self.default_model = default_model
```

**改修後:**

```python
class GeminiClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, default_model: str = "gemini-2.0-flash"):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is not set")
        self.client = genai.Client(api_key=self.api_key)
        self.default_model = default_model
```

**変更理由**: import がトップレベルで直接行われるため、`if not genai:` ガードは到達不能コードとなる。削除してクリーンにする。

## 1.4 改修後に削除できるもの

| 削除対象 | 内容 |
|:---|:---|
| `try/except ImportError` (genai) | `google.genai` のインポートガード |
| `genai = None` / `types = None` | フォールバック用の None 代入 |
| `if not genai:` ガード | `GeminiClient.__init__` 内の到達不能コード |

**推定削減: 約5〜8行**

## 1.5 改修後の動作確認テスト

### テスト環境の前提

- Python 3.11+
- `google-genai` パッケージがインストール済み
- `GOOGLE_API_KEY` 環境変数が設定済み
- Qdrant サーバーが稼働中

### テスト 1: インポートテスト

```bash
python -c "from helper.helper_llm import GeminiClient, OpenAIClient, create_llm_client; print('OK')"
```

**期待結果**: `OK` が出力される。ImportError が発生しないこと。

### テスト 2: GeminiClient 単体テスト

```python
# test_helper_llm_step1.py
import os
from helper.helper_llm import GeminiClient

def test_generate_content():
    """テキスト生成の基本動作確認"""
    client = GeminiClient()
    result = client.generate_content("1+1は何ですか？一言で答えてください。")
    assert result is not None
    assert len(result) > 0
    print(f"✅ generate_content: {result}")

def test_count_tokens():
    """トークンカウントの動作確認"""
    client = GeminiClient()
    count = client.count_tokens("これはテスト文です。")
    assert count > 0
    print(f"✅ count_tokens: {count}")

def test_generate_structured():
    """構造化出力の動作確認"""
    from pydantic import BaseModel

    class SimpleAnswer(BaseModel):
        answer: str
        confidence: float

    client = GeminiClient()
    result = client.generate_structured(
        prompt="日本の首都はどこですか？",
        response_schema=SimpleAnswer
    )
    assert isinstance(result, SimpleAnswer)
    print(f"✅ generate_structured: {result}")

if __name__ == "__main__":
    test_generate_content()
    test_count_tokens()
    test_generate_structured()
    print("\n✅ All Step 1 tests passed!")
```

**実行コマンド:**

```bash
python test_helper_llm_step1.py
```

### テスト 3: Streamlit UI E2E 確認

`helper_llm.py` は `helper_api.py` → `grace/*` → `ui/pages/*` → `services/*` のチェーン上流にあるため、既存 UI の正常動作を確認する。

```bash
streamlit run agent_rag.py --server.port 8501
```

**確認項目:**

1. サイドバーのメニューが全て表示されること
2. 「Qdrant検索」ページで検索が実行できること
3. 「自律型Agent(Plan+Executor)」ページでチャットが動作すること
4. エラーログに `google.generativeai` 関連のエラーが出ないこと

---

# Step 2: `pipeline.py` — 旧SDK分岐削除

## 2.1 改修内容の概要

`qa_generation/pipeline.py` は QA 生成パイプラインの制御を行うファイルで、`smart_qa_generator.py` を呼び出す親モジュール。新旧両対応の `try/except` 分岐を持っており、旧SDK分岐を削除して新SDK一本化する。

**改修する理由**: `pipeline.py` は `smart_qa_generator.py` の親なので、先に改修しておくことで Step 3 との不整合を防ぐ。改修内容は import 周りだけで最小限。

## 2.2 対象ファイル

`qa_generation/pipeline.py`

> **注意**: 本ファイルは現時点で未提供のため、以下は移行計画書 `agent_rag_new_api_migration.md` の記述に基づく改修方針である。実際のコードを確認のうえ、詳細を更新すること。

## 2.3 対象箇所と改修コード

### 対象箇所: 新旧SDK両対応の try/except 分岐

**改修前（想定）:**

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

**改修後:**

```python
from google import genai

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# generate_content の呼び出しは smart_qa_generator.py に委譲
```

**変更理由**: `pipeline.py` は `smart_qa_generator.py` を呼ぶ上位モジュールなので、API 直接呼び出し箇所は少ない。旧SDK分岐を削除するだけで完了する見込み。

## 2.4 改修後に削除できるもの

| 削除対象 | 内容 |
|:---|:---|
| `except ImportError` ブロック | 旧SDK (`google.generativeai`) へのフォールバック全体 |
| `import google.generativeai as genai` | 旧SDKのインポート文 |
| `genai.configure(api_key=...)` | 旧SDK の初期化コード |
| `genai.GenerativeModel(...)` | 旧SDK のモデルインスタンス生成 |

**推定削減: 約20〜40行**

## 2.5 改修後の動作確認テスト

### テスト 1: インポートテスト

```bash
python -c "from qa_generation.pipeline import *; print('OK')"
```

### テスト 2: パイプライン結合テスト

```bash
# pipeline.py が smart_qa_generator.py を正しく呼び出せるか確認
python -c "
from qa_generation.pipeline import Pipeline  # クラス名は実装に合わせて調整
print('Pipeline import OK')
"
```

**期待結果**: ImportError が発生せず、旧SDK の `google.generativeai` が一切参照されないこと。

### テスト 3: QA 生成パイプライン E2E（Step 3 と合わせて実施）

Step 3 完了後に、テキスト入力 → QA ペア出力の E2E テストを実施する（Step 3 のテスト項目を参照）。

---

# Step 3: `smart_qa_generator.py` — 旧SDK分岐削除 + 新SDK一本化

## 3.1 改修内容の概要

`qa_generation/smart_qa_generator.py` は QA ペア生成の中核ファイルで、LLM を使ってテキストチャンクから Question/Answer ペアを生成する。新旧両対応の `try/except` 分岐を持っており、旧SDK分岐を完全削除して新SDK一本化する。

**改修する理由**: `pipeline.py`（Step 2）の子モジュールであり、セットで改修することで不整合を防ぐ。`generate_content` のみの使用なので変換は素直。

## 3.2 対象ファイル

`qa_generation/smart_qa_generator.py`

> **更新**: 実際のコードを確認済み（2026-03-30）。以下は実コードに基づく改修内容。

## 3.3 対象箇所と改修コード

旧SDK分岐は **3か所** に存在する。

---

### 対象箇所 (1): インポート部分（行 24〜37）

**改修前:**

```python
try:
    # 新しいパッケージを優先
    from google import genai

    USING_NEW_API = True
except ImportError:
    # フォールバック: 古いパッケージ
    import google.generativeai as genai

    USING_NEW_API = False
    import warnings

    warnings.filterwarnings('ignore', category=FutureWarning, module='google.generativeai')
```

**改修後:**

```python
from google import genai
```

**変更理由**: `google-genai` は本番環境に必ずインストールされている前提。`USING_NEW_API` フラグが不要になるため、後続の分岐も全て削除できる。

---

### 対象箇所 (2): `__init__` メソッドの分岐（行 57〜70）

**改修前:**

```python
if USING_NEW_API:
    # 新しいAPIの初期化
    if api_key:
        client = genai.Client(api_key=api_key)
        self.client = client
    else:
        self.client = genai.Client()
    logger.info("✅ 新しいgoogle.genai APIを使用")
else:
    # 古いAPIの初期化
    if api_key:
        genai.configure(api_key=api_key)
    self.model_instance = genai.GenerativeModel(model)
    logger.info("⚠️ 古いgoogle.generativeai APIを使用（非推奨）")
```

**改修後:**

```python
if api_key:
    self.client = genai.Client(api_key=api_key)
else:
    self.client = genai.Client()
logger.info("✅ 新しいgoogle.genai APIを使用")
```

**変更理由**: `else` ブロック（`genai.configure`, `genai.GenerativeModel`, 非推奨ログ）を削除。`if USING_NEW_API:` のネストも不要になる。

---

### 対象箇所 (3): `_generate_content` メソッドの分岐（行 81〜99）

**改修前:**

```python
if USING_NEW_API:
    # 新しいAPI
    response = self.client.models.generate_content(
        model=self.model,
        contents=prompt,
        # config={
        #     'temperature': temperature,
        # }
    )
    return response.text
else:
    # 古いAPI
    response = self.model_instance.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=temperature,
        )
    )
    return response.text
```

**改修後:**

```python
response = self.client.models.generate_content(
    model=self.model,
    contents=prompt,
)
return response.text
```

**変更理由**: `if/else` 分岐構造ごと削除し、新SDK呼び出しのみを残す。`temperature` 引数はメソッドシグネチャに残るが使用されない状態となる（必要なら `types.GenerateContentConfig(temperature=temperature)` を有効化するか引数ごと削除する）。

## 3.4 改修後に削除できるもの

| 削除対象 | 内容 | 推定行数 |
|:---|:---|:---|
| `try/except ImportError` ブロック | `google.generativeai` へのフォールバック、`USING_NEW_API` フラグ、`warnings` インポート | 約9行 |
| `__init__` の `else` ブロック | `genai.configure`, `genai.GenerativeModel`, 非推奨ログ | 約8行 |
| `_generate_content` の `if/else` 分岐 | 旧SDK呼び出しブロック全体 | 約10行 |

**推定削減: 約27行**

## 3.5 改修後の動作確認テスト

### テスト 1: インポートテスト

```bash
python -c "from qa_generation.smart_qa_generator import *; print('OK')"
```

### テスト 2: QA 生成パイプライン E2E テスト

ファイルの `__main__` ブロックに組み込みのデモを実行する（テスト用チャンク 4件が定義済み）。

**テスト手順:**

```bash
cd /path/to/gemini_grace_agent
GOOGLE_API_KEY=your_key python qa_generation/smart_qa_generator.py
```

**組み込みテストケース（ファイル末尾の `__main__` ブロックに定義済み）:**

| ケース | 内容 | 期待Q/A数 |
|:---|:---|:---|
| 1 | 短いチャンク「この製品は赤色です。」 | 1個 |
| 2 | 中程度チャンク（色・サイズ・価格） | 2〜3個 |
| 3 | AES-256暗号化の技術情報 | 4〜5個 |
| 4 | メタ情報「詳細は付録Aを参照」 | 0個 |

**期待結果:**

- 各チャンクの分析結果（Q/A数・重要度・複雑さ・トピック）が表示される
- 統計情報（総チャンク数・総Q/A数・平均）が最後に表示される
- エラーログに `google.generativeai` 関連のエラーが出ない
- `✅ デモ完了` が表示される

### テスト 3: pipeline.py 経由の結合テスト

```bash
# パイプライン全体のE2Eテスト
# テキスト入力 → チャンク分割 → QAペア生成 → 出力
python -m qa_generation.pipeline \
    --input-file test_data/sample.txt \
    --output-file test_data/qa_output.json
```

**確認項目:**

1. `test_data/qa_output.json` が生成されること
2. JSON 構造が正しいこと（question / answer フィールドが存在）
3. ログに `旧SDK` や `google.generativeai` のトレースが一切出ないこと

---

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

# gemini_grace_agent — 旧SDK → 新SDK 移行手順書 **v2**

**対象プロジェクト**: gemini_grace_agent
**目的**: 旧SDK (`google.generativeai`) を新SDK (`google.genai`) に統一
**作成日**: 2026-04-17
**前版**: `agent_rag_old_api_to_new_api_migration.md` (2026-03-22)
**参照**: `agent_rag_new_api_migration.md`（移行計画書）

---

## 📋 v2 での主要更新点（v1 からの差分）

| 章 | 変更内容 | 理由 |
|:---|:---|:---|
| Step 2 | **改修不要(検証のみ)に変更** | 実コード調査の結果、`pipeline.py` は既に `helper_llm.py` 抽象化レイヤー経由で実装されており、旧SDK直接参照ゼロを確認 |
| Step 3 | **実コードベースの確定版に更新** + temperature 有効化の改善提案を追加 | 実コードを精査し、計画書記載の3箇所の改修内容を確定 |
| Step 4 | **実コード精査で改修範囲を縮小**: インポート・`_setup_session` は既に新SDK移行済み。**未改修は3箇所のみ**(parts アクセス・FunctionResponse返送・Reflection parts アクセス) | `agent_main.py` 現状精査(2026-04-18)で部分的に完了済みと判明 |
| Step 1 | 任意クリーンアップ手順を追記 | コメントアウトされた旧コードの削除推奨 |
| 全体 | `requirements.txt` の更新手順を明記 | 全Step完了後の最終クリーンアップ |

### 🔴 v2 update (2026-04-18): Step 4 大幅改訂

Step 4 を **実コード精査ベース** で全面書き換え:
- **新SDK移行済み箇所の明示化**: インポート(L22-23)、`_setup_session`(L207-233) は既に完了
- **未改修3箇所を明確化**: ReAct parts(L289-303) / FunctionResponse返送(L328-335) / Reflection parts(L351-352)
- **Reflection フェーズの改修を追加**: v2初版では抜けていた `_execute_reflection_phase` の parts アクセス改修を独立した対象箇所として追加
- **改修工数を「2〜3日」→「1〜1.5日」に下方修正**: 既完了部分の反映による

---

## 改修順序サマリ（更新版）

| Step | 対象ファイル | 改修内容 | 難度 | 工数 | 状態 |
|:---|:---|:---|:---|:---|:---|
| Step 1 | `helper/helper_llm.py` | フォールバック削除 + 任意クリーンアップ | 低 | 0.5日 | ✅ 完了 |
| Step 2 | `qa_generation/pipeline.py` | **改修不要(検証のみ)** | なし | 0日 | ⏸ 検証 |
| Step 3 | `qa_generation/smart_qa_generator.py` | 旧SDK分岐削除 + 新SDK一本化 + temperature 有効化 | 中 | 1日 | ⏳ 未着手 |
| Step 4 | `agent_main.py` | **未改修3箇所のみ**(parts アクセス・FunctionResponse返送・Reflection) | 中 | 1〜1.5日 | ⏳ 未着手 |
| 最終 | `requirements.txt` | `google-generativeai` 削除 | 低 | 0.1日 | ⏳ 未着手 |

---

# Step 1: `helper_llm.py` — フォールバック削除 ✅ 完了済み

## 1.1 完了確認

`helper_llm.py` の現状（2026-04-17 時点）:

```python
# 現状: 新SDKが直接インポートされている (32-37行)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from google import genai          # ← 新SDK直接インポート ✅
from google.genai import types
```

- ✅ `try/except ImportError` ガード(genai側)は削除済み
- ✅ `genai = None` / `types = None` フォールバックは削除済み
- ✅ `GeminiClient.__init__` 内の `if not genai:` ガードは削除済み

## 1.2 任意クリーンアップ（推奨）

`helper_llm.py` の 15-25行に、**コメントアウトされた旧コード**が残存している。動作には影響しないが、可読性向上のため削除を推奨。

**削除対象:**

```python
# SDK imports
# try:
#     from openai import OpenAI
# except ImportError:
#     OpenAI = None
#
# try:
#     from google import genai
#     from google.genai import types
# except ImportError:
#     genai = None
#     types = None
```

`GeminiClient.__init__` 内のコメントも同様に削除推奨:

```python
# New API改修 2026 03-24
# if not genai:
#     raise ImportError("google-genai package is not installed. Install with: pip install google-genai")
```

**所要時間**: 5分

---

# Step 2: `pipeline.py` — 改修不要 ⏸ 検証のみ

## 2.1 v2 における重要発見

**v1 計画書の前提:** `pipeline.py` に旧SDKフォールバック分岐があり、削除が必要(20〜40行削減を想定)。

**v2 実コード調査結果:** **旧SDKへの直接参照は1件もない**。pipeline.py は完全に抽象化レイヤー経由で実装されている。

## 2.2 実コードの確認

`qa_generation/pipeline.py` の関連 import (40-44行):

```python
from config import DATASET_CONFIGS
from helper.helper_llm import LLMClient                    # ← 抽象化経由 ✅
from qa_generation.smart_qa_generator import SmartQAGenerator
from qa_generation.evaluation import analyze_coverage
from celery_tasks import submit_unified_qa_generation, collect_results, check_celery_workers
```

LLM 呼び出し箇所はすべて `SmartQAGenerator` クラス（Step 3 対象）または `LLMClient`（Step 1 完了済み）経由。直接 `genai.*` を呼ぶコードは存在しない。

## 2.3 Step 2 の代替アクション（検証のみ）

### 検証 1: 旧SDK参照の不在確認

```bash
grep -n "google.generativeai" qa_generation/pipeline.py
grep -n "genai\." qa_generation/pipeline.py
```

**期待結果:** 両方とも 0 件。

### 検証 2: import テスト

```bash
python -c "from qa_generation.pipeline import QAPipeline; print('OK')"
```

**期待結果:** `OK` が出力される。

### 検証 3: 簡易結合テスト（Step 3 完了後に実施）

Step 3 完了後、`pipeline.py` 経由で SmartQAGenerator が新SDK で動作することを確認:

```python
from qa_generation.pipeline import QAPipeline

# 動作確認のみ（最小データセット）
pipeline = QAPipeline(
    input_file="test_data/small_chunks.csv",
    model="gemini-2.0-flash",
    output_dir="qa_output/test"
)
result = pipeline.run(use_celery=False, use_smart_generation=True)
print(f"Generated: {result['qa_count']} Q/A pairs")
```

## 2.4 v1 計画書との差分

| 項目 | v1 想定 | v2 実態 |
|:---|:---|:---|
| 改修箇所 | try/except ImportError 分岐削除 | **改修不要(0箇所)** |
| 削減行数 | 20〜40行 | **0行** |
| 工数 | 0.5日 | **0日(検証のみ約10分)** |
| アクション | コード変更 | **import テストのみ** |

---

# Step 3: `smart_qa_generator.py` — 旧SDK分岐削除 + 新SDK一本化（実コードベース確定版）

## 3.1 改修内容の概要

`qa_generation/smart_qa_generator.py` は QA ペア生成の中核ファイル。**実コード確認の結果、計画書通り 3 箇所** に旧SDK分岐が存在する。

**v1 からの追加改善提案:**
- v1 では `temperature` 引数がメソッドシグネチャに残るが使用されない状態を許容していたが、v2 では **`types.GenerateContentConfig(temperature=temperature)` で有効化することを強く推奨** する。理由は呼び出し元（172行・308行）で意図的に `0.1`（分析時）/ `0.3`（生成時）と使い分けているため。

## 3.2 対象ファイル

`qa_generation/smart_qa_generator.py`

## 3.3 対象箇所と改修コード（実コード確認済み）

旧SDK分岐は **3か所** に存在する。

---

### 対象箇所 (1): インポート部分（行 24〜36）

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
from google.genai import types  # ← 改善提案: temperature 有効化のため追加
```

**変更理由**:
- `google-genai` は本番環境に必ずインストールされている前提
- `USING_NEW_API` フラグが不要になるため、後続の分岐も全て削除できる
- `types` のインポートは対象箇所(3) で `GenerateContentConfig` に使用

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
logger.info("google.genai APIを使用")
```

**変更理由**: `else` ブロック（`genai.configure`, `genai.GenerativeModel`, 非推奨ログ）を削除。`if USING_NEW_API:` のネストも不要になる。ログメッセージも「✅ 新しい」「⚠️ 古い」の対比が不要となるためシンプル化。

---

### 対象箇所 (3): `_generate_content` メソッドの分岐（行 72〜99）

**改修前:**

```python
def _generate_content(self, prompt: str, temperature: float = 0.1) -> str:
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

**改修後（推奨: temperature を実際に有効化）:**

```python
def _generate_content(self, prompt: str, temperature: float = 0.1) -> str:
    response = self.client.models.generate_content(
        model=self.model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    return response.text
```

**変更理由**:
- `if/else` 分岐構造ごと削除し、新SDK呼び出しのみを残す
- **★ v2 改善提案**: `temperature` 引数は呼び出し元で意図的に使い分けられている（`analyze_chunk` で `0.1`、`generate_qa_pairs` で `0.3`）。新SDKでも `types.GenerateContentConfig(temperature=temperature)` を渡して有効化することで、旧SDKと同等の動作品質を維持する。

#### temperature 使用箇所の確認

```python
# 172行目: analyze_chunk 内
text = self._generate_content(prompt, temperature=0.1)  # ← 分析は低温度（再現性重視）

# 308行目: generate_qa_pairs 内
text = self._generate_content(prompt, temperature=0.3)  # ← 生成は中温度（多様性確保）
```

これらは**意図的な設計**であり、新SDK でも維持すべき。

## 3.4 改修後に削除できるもの

| 削除対象 | 内容 | 推定行数 |
|:---|:---|:---|
| `try/except ImportError` ブロック | `google.generativeai` フォールバック、`USING_NEW_API` フラグ、`warnings` インポート | 約9行 |
| `__init__` の `else` ブロック | `genai.configure`, `genai.GenerativeModel`, 非推奨ログ | 約8行 |
| `_generate_content` の `if/else` 分岐 | 旧SDK呼び出しブロック全体 | 約10行 |

**推定削減: 約27行**

## 3.5 改修後の動作確認テスト

### テスト環境の前提

- Python 3.11+
- `google-genai` パッケージがインストール済み
- `GOOGLE_API_KEY` 環境変数が設定済み
- Step 1 が完了済み

### テスト 1: インポートテスト

```bash
python -c "from qa_generation.smart_qa_generator import SmartQAGenerator; print('OK')"
```

**期待結果**: `OK` が出力される。`USING_NEW_API` 等のフラグへの参照エラーが発生しないこと。

### テスト 2: 旧SDK参照の不在確認

```bash
grep -n "google.generativeai\|USING_NEW_API\|model_instance\|genai.configure\|GenerativeModel" \
    qa_generation/smart_qa_generator.py
```

**期待結果**: すべて 0 件。

### テスト 3: 単体動作確認（組み込みデモ実行）

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
- ログに `古い google.generativeai API を使用` が**出ない**こと
- ログに `google.genai APIを使用` が表示されること
- `✅ デモ完了` が表示される

### テスト 4: temperature 動作確認（v2 追加）

`temperature` が実際にAPIに渡されているかを確認するため、同一プロンプトで複数回実行し、低温度（0.1）では結果が安定し、中温度（0.3）では適度なばらつきが出ることを目視で確認。

```python
from qa_generation.smart_qa_generator import SmartQAGenerator

gen = SmartQAGenerator()
chunk = "AES-256は対称鍵暗号方式の一種で、256ビットの鍵長を持ちます。"

# 低温度: 同じ結果が安定して返る
for _ in range(3):
    print(gen.analyze_chunk(chunk)['qa_count'])  # ほぼ同じ値が3回出る想定
```

### テスト 5: pipeline.py 経由の結合テスト

Step 2 の検証(2.3)で記述した結合テストを実施。`pipeline.py` 経由で `SmartQAGenerator` が新SDK で動作することを確認。

---

# Step 4: `agent_main.py` — 未改修3箇所の書き換え（実コード精査ベースの確定版）

## 4.1 実コード精査結果 — Step 4 対象の再定義 ★★★ 重要 ★★★

### 現状精査（2026-04-18 実施）

`agent_main.py`（462行）に対して以下の grep を実施した結果:

```bash
$ grep -n "google\.\|genai\.\|types\.\|\.parts\|\.candidates\|send_message\|chats\.create\|hasattr" agent_main.py
23:from google.genai import types                                        ← ✅ 新SDK
213:        self.client = genai.Client(api_key=api_key)                   ← ✅ 新SDK
226:        chat = self.client.chats.create(                              ← ✅ 新SDK
228:            config=types.GenerateContentConfig(                       ← ✅ 新SDK
279:        current_response = self.chat_session.send_message(...)        ← ⚠️ 位置引数
289:            for part in current_response.parts:                       ← ⏳ 未改修(旧SDK)
328:                    current_response = self.chat_session.send_message(
329:                        [genai.protos.Part(                            ← ⏳ 未改修(旧SDK最重要)
348:            reflection_response = self.chat_session.send_message(...)  ← ⚠️ 位置引数
351:            if reflection_response.parts:                              ← ⏳ 未改修(旧SDK)
352:                for part in reflection_response.parts:                 ← ⏳ 未改修(旧SDK)
```

### 🎯 判明した事実

**`agent_main.py` の新SDK移行は既に部分的に完了している**。これは Step 1 の helper_llm.py 改修時に並行して進められた可能性が高い。

| セクション | 状態 | 備考 |
|:---|:---|:---|
| インポート文(L22-23) | ✅ **完了** | `from google import genai` / `from google.genai import types` |
| `_setup_session`(L207-233) | ✅ **完了** | `genai.Client()` + `chats.create()` + `GenerateContentConfig` |
| ReActループ parts アクセス(L289-303) | ⏳ **未改修** | 旧パターン `response.parts` + ガード無し |
| FunctionResponse 返送(L328-335) | ⏳ **未改修** | **最重要**: `genai.protos.Part(function_response=...)` |
| Reflection parts アクセス(L351-352) | ⏳ **未改修** | 旧パターン `response.parts` |
| `send_message` 引数形式(L279, L348) | ⚠️ **改善推奨** | 位置引数 → キーワード引数 `message=` |
| 型ヒント(L207) | ✅ **完了** | `def _setup_session(self):` 型ヒント無しで既に正しい |

### 実改修対象は「3箇所 + 位置引数2箇所」のみ

v1 計画書の「全面書き換え」「2〜3日」は現状と合わない。**実際の改修は限定的**であり、工数は **1〜1.5日** に下方修正する。

## 4.2 改修内容の概要（改訂版）

`agent_main.py` の残存する旧SDKパターンを書き換える。焦点は以下の3点:

1. **parts アクセスパターン**: `response.parts` → `response.candidates[0].content.parts` + `hasattr` ガード（2箇所: ReAct / Reflection）
2. **FunctionResponse 返送**: `genai.protos.Part(function_response=...)` → `types.Part.from_function_response(...)`（1箇所、Step 4 の最大焦点）
3. **`send_message` 引数形式**: 位置引数 → キーワード引数 `message=`（2箇所、改善推奨）

**改修戦略: 手動FC維持（戦略B）**。`automatic_function_calling` はデフォルトで無効なので明示指定不要（`agent_service.py` で実証済み）。

## 4.3 対象ファイル

### メインターゲット

`agent_main.py`（ルートディレクトリ）

### 関連ファイル（改修不要）

| ファイル | 役割 | 改修 |
|:---|:---|:---|
| `agent_tools.py` | ツール関数定義（`search_rag_knowledge_base`, `list_rag_collections`） | ❌ 不要 |
| `services/agent_service.py` | 新SDK版の ReActAgent 実装 | ❌ 不要（**リファレンスとして全面参照**） |
| `config.py`（`AgentConfig`, `PathConfig`） | 設定クラス | ❌ 不要（動作影響なし） |

### 既に完了済みの箇所（改修しない）

以下は既に新SDKに移行済みのため**触らないこと**:

- **L22-23**: インポート文（`from google import genai` + `from google.genai import types`）
- **L207-233**: `_setup_session` メソッド全体
  - `self.client = genai.Client(api_key=api_key)`（L213）
  - `chat = self.client.chats.create(model=..., config=types.GenerateContentConfig(...))`（L226-232）
- **L191**: `def __init__` の構造（`model_name`, `session_id`, `chat_session` の初期化順）

## 4.4 改修箇所一覧と改修コード（実コードベース）

### 改修箇所 (1): ReActループ内の parts アクセス（L289-303）★

**改修前(現在のコード):**

```python
for part in current_response.parts:                         # L289: 旧SDK
    if part.text:                                           # L290: ガード無し
        text = part.text.strip()
        if "Thought:" in text or "考え:" in text:
            print_colored(f"💭 {text}", "blue")
            logger.info(f"Thought: {text}")
            current_turn_text = text
        else:
            current_turn_text = text

    if part.function_call:                                  # L299: ガード無し
        function_call_found = True
        fn = part.function_call
        tool_name = fn.name
        tool_args = dict(fn.args)                           # L303: ガード無し
```

**改修後（`agent_service.py` L285-305 パターン）:**

```python
# レスポンスの処理（新SDK: candidates[0].content.parts + hasattr ガード）
if current_response.candidates and len(current_response.candidates) > 0:
    candidate = current_response.candidates[0]

    if candidate.content and candidate.content.parts:
        for part in candidate.content.parts:
            # テキスト部分の処理
            if hasattr(part, 'text') and part.text:
                text = part.text.strip()
                if "Thought:" in text or "考え:" in text:
                    print_colored(f"💭 {text}", "blue")
                    logger.info(f"Thought: {text}")
                    current_turn_text = text
                else:
                    current_turn_text = text

            # 関数呼び出しの処理
            if hasattr(part, 'function_call') and part.function_call:
                function_call_found = True
                fn = part.function_call
                tool_name = fn.name
                tool_args = dict(fn.args) if hasattr(fn, 'args') else {}
```

**変更点:**

| 項目 | 旧 | 新 |
|:---|:---|:---|
| トップレベルガード | なし | `if current_response.candidates and len(...) > 0` |
| content ガード | なし | `if candidate.content and candidate.content.parts` |
| parts アクセス | `current_response.parts` | `candidate.content.parts` |
| text ガード | `if part.text` | `if hasattr(part, 'text') and part.text` |
| function_call ガード | `if part.function_call` | `if hasattr(part, 'function_call') and part.function_call` |
| args ガード | `dict(fn.args)` | `dict(fn.args) if hasattr(fn, 'args') else {}` |

---

### 改修箇所 (2): FunctionResponse 返送（L327-335）★★★ 最重要

**改修前(現在のコード):**

```python
# 次のターンへ
current_response = self.chat_session.send_message(
    [genai.protos.Part(                                     # ★ 旧SDK protobuf
        function_response={
            "name"    : tool_name,
            "response": {'result': tool_result}
        }
    )]
)
```

**改修後（`agent_service.py` L352-363 パターン）:**

```python
# 次のターンへ（ツール結果をモデルに返送 / 新SDK形式）
# tool_name を明示的に str() でキャスト（型エラー回避）
function_response_part = types.Part.from_function_response(
    name=str(tool_name),
    response={'result': tool_result},
)

# Partオブジェクトを直接渡す（キーワード引数 message= 推奨）
current_response = self.chat_session.send_message(
    message=function_response_part
)
```

**変更点:**

| 項目 | 旧 | 新 |
|:---|:---|:---|
| Part構築 | `genai.protos.Part(function_response={"name": ..., "response": ...})` | `types.Part.from_function_response(name=..., response=...)` |
| 名前の型 | 自動推論 | **`str(tool_name)` 明示キャスト**（型エラー回避） |
| リスト vs Part | `[Part]` リスト | Part 単体 |
| 引数形式 | 位置引数 | **キーワード引数 `message=`** |

> **ここが Step 4 の最大の改修ポイント**。`genai.protos` は旧SDK専用のシンボルで、新SDK には存在しないため、このままでは AttributeError でクラッシュする。

---

### 改修箇所 (3): Reflection フェーズの parts アクセス（L351-354）

**改修前(現在のコード):**

```python
reflection_response = self.chat_session.send_message(reflection_msg)

reflection_text = ""
if reflection_response.parts:                               # L351: 旧SDK
    for part in reflection_response.parts:                  # L352: 旧SDK
        if part.text:                                       # L353: ガード無し
            reflection_text += part.text
```

**改修後（`agent_service.py` L377-389 パターン）:**

```python
reflection_response = self.chat_session.send_message(message=reflection_msg)

reflection_text = ""

# レスポンスからテキストを抽出（新SDK形式）
if reflection_response.candidates and len(reflection_response.candidates) > 0:
    candidate = reflection_response.candidates[0]
    if candidate.content and candidate.content.parts:
        for part in candidate.content.parts:
            if hasattr(part, 'text') and part.text:
                reflection_text += part.text
            elif hasattr(part, 'function_call') and part.function_call:
                # Reflection段階では function_call は発生しないはずだが防御的に警告
                logger.warning("Reflection phase generated a function call, ignoring.")
```

**変更点:**

| 項目 | 旧 | 新 |
|:---|:---|:---|
| send_message 引数 | `send_message(reflection_msg)` | `send_message(message=reflection_msg)` |
| parts アクセス | `reflection_response.parts` | `reflection_response.candidates[0].content.parts` |
| text ガード | `if part.text` | `if hasattr(part, 'text') and part.text` |
| function_call 防御 | なし | **追加: Reflection 段階での予期しない FC に対する警告ログ**（推奨） |

> **追加提案**: Reflection 段階で function_call が返ることは通常ないが、モデルの挙動次第では発生しうる。`agent_service.py` ではこれを warning として記録しているため、同パターンを採用推奨。

---

### 改修箇所 (4): `send_message` の引数形式統一（L279）

**改修前(現在のコード):**

```python
current_response = self.chat_session.send_message(augmented_input)    # L279: 位置引数
```

**改修後:**

```python
current_response = self.chat_session.send_message(message=augmented_input)
```

**変更理由**: `agent_service.py` 全体で `send_message(message=...)` の**キーワード引数パターンに統一**されている。新SDK の将来のメソッドシグネチャ変更に対して、キーワード引数の方がロバスト。

---

## 4.5 改修後に削除・変更される行数

| 改修箇所 | 変更量 | 備考 |
|:---|:---|:---|
| (1) ReActループ parts アクセス | +5行 | ガード追加でネストが深くなる |
| (2) FunctionResponse 返送 | -4行 | 旧SDK protobuf(8行) → 新SDK関数(4行) |
| (3) Reflection parts アクセス | +6行 | ガード追加 + function_call 防御警告 |
| (4) `send_message` 位置→キーワード引数 | 0行 | 変更のみ |

**推定純増**: +7行程度（ガード強化のため、本質的には変化なし）

> v1 計画書の「20〜30行削減」は、インポート等の既完了部分を含んでいたための過大見積もり。実改修部分だけでは削減量はわずか。

## 4.6 改修の実施手順

以下の順序で改修することを推奨。各ステップでテストしながら進める:

### Step 4-A: `send_message` 引数形式統一（リスク最小）

1. L279: `send_message(augmented_input)` → `send_message(message=augmented_input)`
2. L348: `send_message(reflection_msg)` → `send_message(message=reflection_msg)`
3. テスト: 起動テスト（4.7 テスト1）

### Step 4-B: Reflection parts アクセス改修（比較的独立）

1. L351-354 を改修箇所(3)のコードに置き換え
2. テスト: 一般質問テスト（4.7 テスト2） — Reflection が通常動作することを確認

### Step 4-C: ReActループ parts アクセス改修（本体）

1. L289-303 を改修箇所(1)のコードに置き換え
2. インデントに注意（`if current_response.candidates ...` のネストが追加される）
3. テスト: 起動 + 一般質問（4.7 テスト1, 2）

### Step 4-D: FunctionResponse 返送改修（最重要）★

1. L327-335 を改修箇所(2)のコードに置き換え
2. テスト: **RAG検索テスト（4.7 テスト3）** — ここで FC が動作すれば、Step 4 の核心は完了

## 4.7 改修後の動作確認テスト

### テスト環境の前提

- Step 1〜3 が全て完了し、テスト済みであること
- `GEMINI_API_KEY` または `GOOGLE_API_KEY` が設定済み
- Qdrant サーバーが稼働中（コレクション `wikipedia_ja` 等が存在）
- `agent_tools.py` の `search_rag_knowledge_base` が正常動作すること

### テスト 1: 起動テスト

```bash
python agent_main.py
```

**期待結果:**

- エラーなく起動する
- `🤖 Upgraded CLI Agent (ReAct + Reflection)` バナーが表示される
- `✅ ReAct + Reflection 2段階処理` 等の機能一覧が表示される
- ログに `AttributeError` や `ImportError` が出ない

### テスト 2: 一般質問（ツール不使用）

```
💬 You: こんにちは
```

**期待結果:**

- ツール呼び出しが発生しない（`🛠️ Tool Call` が表示されない）
- `💭 Thought:` が表示される（ReActループのtext処理が正常動作）
- `🤖 Agent:` で挨拶が返される（Reflection正常動作）

### テスト 3: RAG 検索（Function Calling の動作確認）★ 最重要

```
💬 You: 金色夜叉の著者は誰ですか？
```

**期待結果（処理順序の確認）:**

1. `💭 Thought:` — 思考プロセスが表示される（改修箇所1が動作）
2. `🛠️ Tool Call: search_rag_knowledge_base({"query": "金色夜叉 著者"})` — FC が発動する（改修箇所1が動作）
3. `📝 Tool Result:` — ツール結果が表示される
4. **★ここが最重要★** `genai.protos` に関する AttributeError が出ない（改修箇所2が動作）
5. `💭 Thought:` — 結果に基づく思考が表示される（2巡目のループ）
6. `🔄 Reflection Phase` — Reflection フェーズに入る（改修箇所3が動作）
7. `🤖 Agent:` — 最終回答「尾崎紅葉」が返される

### テスト 4: 連続ターン（Chat Session の状態維持）

```
💬 You: 東京タワーについて教えて
💬 You: その高さは何メートルですか？
```

**期待結果:**

- 2回目の質問で「その」が「東京タワー」を指すことを理解する
- Chat Session のコンテキストが新SDK でも維持されている
- 両ターンで Reflection が正常に実行される

### テスト 5: リセットテスト

```
💬 You: reset
```

**期待結果:**

- `🔄 Resetting agent...` が表示される
- `✅ Agent reset complete!` が表示される
- 新しい `UpgradedCLIAgent` インスタンスが生成される（`_setup_session` が再実行される）

### テスト 6: エラーハンドリング

```
💬 You: 全く意味不明な質問xyzpdq
```

**期待結果:**

- RAG検索で結果が見つからない場合、`[[NO_RAG_RESULT` のような応答がモデルに返される
- エージェントがクラッシュせず、「情報が見つかりませんでした」と応答する

### テスト 7: 旧SDK参照の不在確認

```bash
grep -n "google\.generativeai\|GenerativeModel\|ChatSession\|genai\.configure\|genai\.protos" \
    agent_main.py
```

**期待結果**: すべて 0 件。

### テスト 8: hasattr ガードの動作確認（v2 追加）

新SDK ではレスポンスのパート構造が変化する可能性があるため、防御的ガードが機能することを確認:

```python
# 簡易スクリプトで確認（任意）
from unittest.mock import MagicMock

# function_call のみを持ち text を持たないパート
part = MagicMock(spec=['function_call'])  # text 属性を持たない

# hasattr ガードが正しく働くことを確認
assert not hasattr(part, 'text')
assert hasattr(part, 'function_call')
```

**期待結果**: `AttributeError` が発生しない。本番コードではこのガードが無いとクラッシュする可能性がある。

## 4.8 トラブルシューティング

改修後に起こりうる主要エラーと対処:

| エラー | 原因 | 対処 |
|:---|:---|:---|
| `AttributeError: module 'google.genai' has no attribute 'protos'` | 改修箇所(2)が未適用 | L328-335 を `types.Part.from_function_response(...)` に書き換え |
| `AttributeError: 'GenerateContentResponse' object has no attribute 'parts'` | 改修箇所(1)または(3)が未適用 | `response.candidates[0].content.parts` パターンに書き換え |
| `TypeError: send_message() got unexpected keyword argument 'message'` | 新SDK のバージョンが古い | `pip install -U google-genai` で最新版へ |
| `ValidationError: name must be str` | `tool_name` が `str` でない | `name=str(tool_name)` にキャスト |
| Reflection 段階でエージェントが無限ループ | Reflection で function_call が返されて処理できていない | 改修箇所(3)の `function_call` 警告ログ対応を追加 |

## 4.9 計画書 v1 との比較（Step 4 のみ）

| 項目 | v1 想定 | v2 実態（2026-04-18 精査） |
|:---|:---|:---|
| インポート文の改修 | 必要（`import google.generativeai as genai` を削除） | **既に完了** |
| `_setup_session` の改修 | 必要（`genai.GenerativeModel` → `chats.create`） | **既に完了** |
| 型ヒント(`ChatSession`)の削除 | 必要 | **既に完了**（型ヒント無し状態） |
| AFC 設定 | `AutomaticFunctionCallingConfig(disable=True)` 明示 | **不要**（デフォルトで手動FC） |
| parts アクセス改修 | 必要 | **必要**（ReAct + Reflection の2箇所） |
| FunctionResponse 返送改修 | 必要 | **必要**（最重要） |
| `send_message` 引数形式 | 言及なし | **推奨**（位置 → キーワード） |
| Reflection フェーズの改修 | **v1 では言及なし** | **追加必要**（v2 で明示） |
| 改修行数 | 20〜30行削減 | +7行程度（ガード強化のため） |
| 改修工数 | 2〜3日 | **1〜1.5日** |
| 難度 | 高 | **中** |


---


# 全体完了後の最終確認

## requirements.txt の更新

現状:

```text
google-genai==1.52.0
google-generativeai==0.8.6        ← ★ 削除対象
```

更新後:

```text
google-genai==1.52.0
# google-generativeai は不要（google-genai に統一済み 2026-04-XX）
```

### 関連 google-* パッケージの確認

`requirements.txt` には以下の Google 系パッケージも含まれているが、これらは別目的のため**削除しないこと**:

| パッケージ | 用途 | 削除可否 |
|:---|:---|:---|
| `google-genai==1.52.0` | 新SDK本体 | ❌ 必須 |
| `google-generativeai==0.8.6` | 旧SDK | ✅ 削除可 |
| `google-ai-generativelanguage==0.6.15` | 旧SDKの依存パッケージ | ⚠️ pip uninstall で連動削除されるか要確認 |
| `google-api-core==2.28.1` | Google APIs共通 | ❌ 他サービスでも使用 |
| `google-api-python-client==2.187.0` | Google APIs Python | ❌ 他サービスでも使用 |
| `google-auth==2.43.0` | 認証 | ❌ 他サービスでも使用 |
| `google-auth-httplib2==0.2.1` | 認証 | ❌ 他サービスでも使用 |

### 削除手順

```bash
# 1. アンインストール
pip uninstall google-generativeai

# 2. 連動して不要になった依存パッケージの確認
pip check
pip list | grep google

# 3. requirements.txt 再生成（オプション）
pip freeze > requirements.txt.new
diff requirements.txt requirements.txt.new
# 差分を確認のうえ requirements.txt を更新
```

## 全体 grep 確認

```bash
# プロジェクト全体で旧SDKの参照が残っていないことを確認
grep -rn "google.generativeai" --include="*.py" .
grep -rn "genai.configure" --include="*.py" .
grep -rn "genai.protos" --include="*.py" .
grep -rn "GenerativeModel" --include="*.py" .
grep -rn "USING_NEW_API" --include="*.py" .
```

**期待結果**: 全てのコマンドで 0 件がヒットすること。

## 推定合計削減（v2 更新版）

| Step | ファイル | v1 推定 | v2 確定/再推定 |
|:---|:---|:---|:---|
| Step 1 | `helper_llm.py` | 5〜8行 | 5〜8行 + 任意クリーンアップ約11行 |
| Step 2 | `pipeline.py` | 20〜40行 | **0行（改修不要）** ★ 修正 |
| Step 3 | `smart_qa_generator.py` | 約27行 | 約27行（実コード確認済み） |
| Step 4 | `agent_main.py` | 20〜30行 | 20〜30行 |
| **合計** | — | **約65〜120行** | **約52〜76行** |

> **v1 との差分**: Step 2 の改修不要化により、削減行数の見積もりは下方修正。ただし**実作業工数も `0.5日` 削減**される。

---

# 全体スケジュール（v2 更新版）

| 時期 | Step | 工数 | 累計工数 | 備考 |
|:---|:---|:---|:---|:---|
| 2026-04-XX (済) | Step 1 | 0.5日 | 0.5日 | フォールバック削除完了 |
| 2026-04-XX | Step 1 任意クリーンアップ | 0.05日 | 0.55日 | コメントアウト旧コード削除 |
| 2026-04-XX | Step 2 検証 | 0.05日 | 0.6日 | grep + import テストのみ |
| 2026-04-XX | Step 3 | 1日 | 1.6日 | smart_qa_generator.py |
| 2026-04-XX | Step 4 | 2〜3日 | 3.6〜4.6日 | agent_main.py |
| 2026-04-XX | requirements.txt | 0.1日 | 3.7〜4.7日 | 最終クリーンアップ |

**v1 比較**: v1 では合計4〜5日想定 → v2 では **3.7〜4.7日**。Step 2 の不要化で約0.5日の短縮。

---

# 補足: v2 で確定した未確定事項一覧

| v1 での記述 | v2 での確定内容 | 確定根拠 |
|:---|:---|:---|
| 「`pipeline.py` は現時点で未提供」 | **改修不要(検証のみ)** | 実コード提供（2026-04-17） |
| 「`smart_qa_generator.py` は現時点で未提供」 | 計画書通り3箇所改修。temperature 有効化を改善提案 | 実コード提供（2026-04-17） |
| 「`response.parts` か `response.candidates[0].content.parts` か要実機確認」 | **`response.candidates[0].content.parts` + `hasattr` ガード** | `agent_service.py` L285-305 |
| 「AFC は `disable=True` を明示」 | **指定不要（デフォルトで手動FC）** | `agent_service.py` L203-211 |
| 「`chat.send_message(part)` 位置引数」 | **`chat.send_message(message=part)` キーワード引数推奨** | `agent_service.py` L361-363 |
| 「`name=tool_name`」 | **`name=str(tool_name)` 明示キャスト推奨** | `agent_service.py` L355 |
| **「agent_main.py は 2〜3日で全面書き換え」** | **インポート・`_setup_session` は既に完了済み。実改修は3箇所のみで1〜1.5日** | `agent_main.py` 現状精査 (2026-04-18) |
| **「agent_main.py の Reflection 改修」** | **v1 では言及なし → v2 で独立した改修箇所として追加** | `agent_main.py` L351-354 精査 (2026-04-18) |

---

# 改訂履歴

| 版 | 日付 | 変更内容 |
|:---|:---|:---|
| v1 | 2026-03-22 | 初版作成（pipeline.py / smart_qa_generator.py / agent_service.py 未提供） |
| v2 | 2026-04-17 | 実コード調査結果を反映。Step 2 を改修不要化、Step 3/4 を実コードベースの確定版に更新 |
| **v2.1** | **2026-04-18** | **Step 4 を `agent_main.py` の現状精査に基づき全面改訂。インポート・`_setup_session` は既に完了済みと判明し、実改修を3箇所(parts アクセス×2・FunctionResponse返送×1)に特定。Reflection フェーズの改修を独立した対象箇所として追加。工数を 2〜3日 → 1〜1.5日 に下方修正。** |

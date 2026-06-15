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

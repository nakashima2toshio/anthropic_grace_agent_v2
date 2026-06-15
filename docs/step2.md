
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

# pip → uv 移行手順

**環境**: Mac / zsh / Anthropic Claude API（LLM）＋ Gemini Embedding API（Embedding）  
**プロジェクト**: `anthropic_grace_agent`  
**バージョン**: 1.1  
**作成日**: 2026-05-26  
**最終更新**: 2026-06-16

---

## なぜ uv か

| 項目 | pip | uv |
|---|---|---|
| インストール速度 | 普通 | **10〜100倍高速** |
| lock ファイル | なし（requirements.txt のみ） | `uv.lock`（再現性が高い） |
| 仮想環境管理 | `venv` 別途必要 | `uv venv` で統合管理 |
| Python バージョン管理 | 別途 pyenv 等が必要 | `uv python install` で管理可能 |

---

## Step 1: uv のインストール

```zsh
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

# インストール確認
uv --version
```

---

## Step 2: プロジェクトへ移動・初期化

```zsh
cd /Users/nakashima_toshio/PycharmProjects/anthropic_grace_agent

# pyproject.toml を生成
uv init --no-workspace
```

---

## Step 3: Python バージョンを固定

```zsh
# 現在のバージョン確認
python --version

# Python 3.13 を使う（本プロジェクト必須）
uv python pin 3.13
```

---

## Step 4: requirements.txt から移行

本プロジェクトは **Anthropic Claude API**（LLM）と **Gemini Embedding API**（Embedding）を使用します。  
`anthropic` と `google-generativeai` が必要で、`openai` パッケージは不要です。

```zsh
# openai を除いた requirements を生成
grep -vE "^openai" requirements.txt > requirements_anthropic.txt

# 確認（openai が含まれていないこと）
grep -E "^openai" requirements_anthropic.txt
# → 何も表示されなければOK

# 確認（anthropic / google-generativeai が含まれていること）
grep -E "^anthropic|^google-generativeai" requirements_anthropic.txt
# → 両方表示されればOK

# 仮想環境を作成して一括インストール
uv venv
uv pip install -r requirements_anthropic.txt
```

---

## Step 5: lock ファイルを生成

```zsh
uv lock
uv sync
```

---

## Step 6: requirements.txt を更新

```zsh
# uv から正式な requirements.txt を再生成
uv export --format requirements-txt > requirements.txt

# openai が含まれていないか確認
grep -E "^openai" requirements.txt
# → 何も表示されなければOK

# anthropic / google-generativeai が含まれているか確認
grep -E "^anthropic|^google-generativeai" requirements.txt
# → 両方表示されればOK
```

---

## Step 7: よく使うコマンド対応表

| 操作 | pip（変更前） | uv（変更後） |
|---|---|---|
| パッケージ追加 | `pip install google-generativeai` | `uv add google-generativeai` |
| パッケージ削除 | `pip uninstall google-generativeai` | `uv remove google-generativeai` |
| 一括インストール | `pip install -r requirements.txt` | `uv sync` |
| アップデート | `pip install --upgrade google-generativeai` | `uv add google-generativeai --upgrade` |
| 仮想環境作成 | `python -m venv .venv` | `uv venv` |
| スクリプト実行 | `python script.py` | `uv run python script.py` |
| Streamlit 起動 | `streamlit run app.py` | `uv run streamlit run app.py` |

---

## Step 8: `.env` の設定確認

本プロジェクトで必要な API キーを確認します。

```zsh
# .env の API キー確認
cat .env | grep -E "API_KEY"
```

`.env` に以下が設定されていること:

```dotenv
# LLM（必須）: Anthropic Claude API
ANTHROPIC_API_KEY=your-anthropic-api-key-here

# Embedding（必須）: Google Gemini API
GOOGLE_API_KEY=your-google-api-key-here
GEMINI_API_KEY=your-google-api-key-here

# Rerank（オプション）: Cohere
# COHERE_API_KEY=your-cohere-api-key-here
```

> LLM 用の `ANTHROPIC_API_KEY` と、Embedding 用の `GOOGLE_API_KEY`（または `GEMINI_API_KEY`）が必須です。  
> `OPENAI_API_KEY` は本プロジェクトでは不要です。`.env` に存在していても動作には影響しませんが、整理することを推奨します。

不要なキーを削除する場合:

```zsh
# .env から OPENAI_API_KEY を削除
sed -i '' '/OPENAI_API_KEY/d' .env

# 確認（ANTHROPIC_API_KEY / GOOGLE_API_KEY / GEMINI_API_KEY が残っていればOK）
cat .env | grep -E "API_KEY"
```

---

## Step 9: Systemd サービスの修正（GCP サーバー）

```zsh
# GCP サーバーに SSH 接続
ssh -i ~/.ssh/gcp_key_v2 nakashima@34.84.198.115
```

```bash
# サーバー側（bash）で uv をインストール
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# サービスファイルを修正
sudo vim /etc/systemd/system/streamlit-app.service
```

```ini
# 変更前
ExecStart=/path/.venv/bin/streamlit run agent_rag.py

# 変更後
ExecStart=/usr/local/bin/uv run streamlit run agent_rag.py --server.port 8501
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart streamlit-app
sudo systemctl status streamlit-app
```

---

## Step 10: `.gitignore` に追加

```zsh
cat >> .gitignore << 'EOF'
.venv/
__pycache__/
EOF
```

> `uv.lock` はチーム開発では**コミット推奨**です。

---

## Step 11: PyCharm のインタープリタ更新

```
Settings → Project → Python Interpreter
→ Add Interpreter → Existing
→ /Users/nakashima_toshio/PycharmProjects/anthropic_grace_agent/.venv/bin/python を選択
```

---

## 移行後のプロジェクト構成

```
anthropic_grace_agent/
├── pyproject.toml     ← uv の設定ファイル（新規）
├── uv.lock            ← lock ファイル（新規・コミット推奨）
├── requirements.txt   ← anthropic + google-generativeai（openai 除外済み）
├── .python-version    ← Python バージョン固定（新規）
├── .env               ← ANTHROPIC_API_KEY + GOOGLE_API_KEY + GEMINI_API_KEY
└── .venv/             ← 仮想環境（.gitignore に追加）
```

---

## まとめ：移行コマンド一覧

```zsh
# ① uv インストール
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.zshrc

# ② プロジェクトへ移動
cd /Users/nakashima_toshio/PycharmProjects/anthropic_grace_agent

# ③ openai を除いた requirements を作成
grep -vE "^openai" requirements.txt > requirements_anthropic.txt

# ④ 仮想環境作成 + インストール
uv venv && uv pip install -r requirements_anthropic.txt

# ⑤ lock ファイル生成
uv lock

# ⑥ .env の確認
cat .env | grep -E "ANTHROPIC_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY"

# ⑦ 動作確認
uv run streamlit run agent_rag.py --server.port 8501
```

---

*本ドキュメントは `anthropic_grace_agent` の pip → uv 移行手順書として使用する。*

---

*最終更新: 2026-06-16*

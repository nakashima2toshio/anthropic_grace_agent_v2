#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
uv run streamlit run agent_rag.py --server.port 8501
Agent RAG Q&A生成・Qdrant管理 Streamlit アプリケーション
sudo systemctl restart streamlit-app

実行コマンド：
# -----------
# ./start_celery.sh restart -w 4 --flower
# uv run streamlit run agent_rag.py --server.port 8501

詳細な仕様、実行方法、アーキテクチャについては、プロジェクトルートの `README.md` を参照してください。

[リモートサーバー管理 (GCP)]:
ssh -i ~/.ssh/gcp_key_v2 nakashima@34.84.198.115

# 設定ファイルの変更を反映
sudo systemctl daemon-reload

# サーバー起動時に自動で立ち上がるように設定
sudo systemctl enable streamlit-app

# 今すぐ起動する
sudo systemctl start streamlit-app

# 停止する
sudo systemctl stop streamlit-app

# 再起動する
sudo systemctl restart streamlit-app

# 状態確認
sudo systemctl status streamlit-app

# ログ確認
journalctl -u streamlit-app -f
"""

import streamlit as st

# UIページをインポート
from ui.pages import (
    show_grace_chat_page,
    show_qdrant_search_page,
    show_system_explanation_page,
)
from ui.pages.agent_chat_page import show_agent_chat_page
from ui.pages.log_viewer_page import show_log_viewer_page

# --- 関連ドキュメント定義 ---
RAG_DATA_DOCS = [
    {
        "path"       : "readme_usage_tools.md",
        "description": "[tools]：ツールの使い方（RAGデータ作成はCLIの下記コマンドを利用します）",
    },
    {
        "path": "chunking/doc/csv_text_to_chunks_text_csv.md",
        "description": "[チャンク分割]：LLMベース - 3段階セマンティックチャンキング - パイプラインの仕様書",
    },
    {
        "path": "qa_qdrant/doc/make_qa_register_qdrant.md",
        "description": "[Q/A生成＋Qdrant登録]： 統合CLIツールの仕様書",
    },
]


def _load_local_markdown(file_path: str) -> str:
    """プロジェクト内のMarkdownファイルを読み込む"""
    from pathlib import Path
    p = Path(file_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return f"⚠️ ファイルが見つかりません: `{file_path}`"


# --- 新規ページ（仮実装） ---
def show_rag_data_creation_page():
    """RAGデータ作成ページ"""
    st.header("📄 RAGデータ作成")
    st.divider()

    # --- 関連ドキュメント参照テーブル ---
    st.subheader("📚 RAGデータ作成・登録のドキュメント")
    st.markdown(
        "| ドキュメント | 説明 |\n"
        "|:------------|:-----|\n"
        + "\n".join(
            f"| `{doc['path']}` | {doc['description']} |"
            for doc in RAG_DATA_DOCS
        )
    )

    # Expanderでドキュメント内容を表示
    for doc in RAG_DATA_DOCS:
        with st.expander(f"📖 {doc['path']}"):
            content = _load_local_markdown(doc["path"])
            st.markdown(content)

    st.divider()

    st.markdown(
        """
        ### RAGデータ作成の流れ：
        #### （チャンク分割 -> Q/Aペア作成 -> ベクターDB:Qdrantへ登録）
        - (1) チャンク分割：「Text or CVS」：文字列を「意味のある単位」に分割する。
        - (2) Q/Aペア作成：チャンクから、Question/Answerペアを作成
        - (3) Q/AペアをEmbedding(ベクトル化）し、Qdrantへ登録する。
        """
    )

    st.divider()

    # --- 使い方（CLIクイックスタート） ---
    st.markdown(
        """
        ### 🛠️ 使い方（CLIクイックスタート）

        RAGデータ作成は、以下のCLIツールを順に実行します。
        テキストデータ → チャンク → Q/Aペア → Qdrant登録 という一連のパイプラインが完成します。
        詳細は上記の `readme_usage_tools.md` を参照してください。

        #### 0. 事前準備（Docker / Celery 起動）

        ```bash
        # Qdrant + Redis を起動
        docker compose -f docker-compose/docker-compose.yml up -d

        # Q/A生成で Celery 並列処理を使う場合（推奨: concurrency=8 + Flower）
        ./start_celery.sh restart -c 8 --flower
        ```

        `.env` に LLM 用 `ANTHROPIC_API_KEY` と Embedding 用 `GEMINI_API_KEY` / `GOOGLE_API_KEY` を設定しておきます。

        #### ① チャンク作成（CSV / テキスト → チャンクCSV）

        ```bash
        uv run python -m chunking.csv_text_to_chunks_text_csv \\
          --input-file OUTPUT/cc_news_1per.csv \\
          --output output_chunked \\
          --model claude-haiku-4-5-20251001 \\
          --workers 2
        ```

        → 固定ファイル名 `{入力名}_chunks.csv`（メタデータ付き）が生成されます。

        #### ② Q/Aペア作成 ＋ Qdrant登録（チャンクCSV → Qdrant）

        ```bash
        uv run python qa_qdrant/make_qa_register_qdrant.py \\
          --input-file output_chunked/cc_news_1per_chunks.csv \\
          --collection cc_news_1per \\
          --model claude-sonnet-4-6 \\
          --concurrency 8 \\
          --use-celery \\
          --recreate
        ```

        → チャンクごとに LLM が Q/A を自動生成し、Embedding（`gemini-embedding-001`, 3072次元）して Qdrant に登録します。

        #### ③ Agent検索（Web UI で確認）

        ```bash
        streamlit run agent_rag.py --server.port 8501
        ```

        > 補足：`question` / `answer` 列を持つ CSV はQ/A生成をスキップして直接登録されます。
        > Celery を使わない同期実行は `--use-celery` を外してください。
        """
    )


def show_qdrant_crud_page():
    """QdrantのCRUDページ"""
    st.header("🗄️ QdrantのCRUD")
    st.divider()
    st.markdown(
        """
        ### Qdrant CRUD操作について

        このページでは、Qdrantベクトルデータベースに対するCRUD操作を行います。

        **主な機能：**
        - **Create**: コレクション作成、ポイント追加
        - **Read**: コレクション一覧、ポイント検索・取得
        - **Update**: ポイントのペイロード更新
        - **Delete**: ポイント削除、コレクション削除

        """
    )

    st.divider()

    # --- 使い方（CLI / REST） ---
    st.markdown(
        """
        ### 🛠️ 使い方

        #### 0. 事前準備（Qdrant 起動・疎通確認）

        ```bash
        # Qdrant + Redis を起動
        docker compose -f docker-compose/docker-compose.yml up -d

        # Qdrant ヘルスチェック
        curl http://localhost:6333/health
        ```

        #### ① Create / Update：CSVからコレクションへ登録

        Q/Aペア CSV（`question` / `answer`）や汎用 CSV を Qdrant に登録します。
        `--recreate` を付けると既存コレクションを削除して作り直します（付けなければ追記＝Upsert）。

        ```bash
        uv run python qa_qdrant/register_to_qdrant.py \\
          --input-file qa_output/pipeline/qa_pairs_cc_news_1per.csv \\
          --collection cc_news_1per \\
          --recreate \\
          --batch-size 100
        ```

        → Embedding は Gemini `gemini-embedding-001`（3072次元）に固定。
        ベクトル化対象カラムは自動検出（`question`+`answer` → `Combined_Text` → `text`）され、`--text-col` で明示指定もできます。

        #### ② Read：コレクション一覧・件数・検索（REST API）

        ```bash
        # コレクション一覧
        curl http://localhost:6333/collections

        # 特定コレクションの情報（件数・次元など）
        curl http://localhost:6333/collections/cc_news_1per

        # ポイントをスクロール取得（先頭10件）
        curl -X POST http://localhost:6333/collections/cc_news_1per/points/scroll \\
          -H 'Content-Type: application/json' \\
          -d '{"limit": 10, "with_payload": true}'
        ```

        > ベクトル検索の体験は、左メニューの「🔎 Qdrant検索」ページからも実行できます。

        #### ③ Delete：ポイント / コレクション削除

        ```bash
        # コレクションごと削除
        curl -X DELETE http://localhost:6333/collections/cc_news_1per

        # 条件に一致するポイントのみ削除（payload フィルタ例）
        curl -X POST http://localhost:6333/collections/cc_news_1per/points/delete \\
          -H 'Content-Type: application/json' \\
          -d '{"filter": {"must": [{"key": "domain", "match": {"value": "cc_news_1per"}}]}}'
        ```

        > 詳細は `readme_usage_tools.md`（補助ツール: Qdrant登録のみ）も参照してください。
        """
    )


def main():
    """メインアプリケーション - 画面選択"""

    # ページ設定
    st.set_page_config(page_title="Agent RAG (Anthropic)", page_icon="🤖", layout="wide")

    # サイドバー：画面選択
    with st.sidebar:
        st.title("Agent RAG (Anthropic)")
        st.divider()

        # メニュー見出し
        st.markdown("**メニュー**")

        # 画面選択
        page = st.radio(
            "機能選択",
            options=[
                "explanation_diagram",
                "explanation_document",
                "qdrant_search",
                "agent_chat",
                "grace_chat",
                "log_viewer",
                "rag_data_creation",
                "qdrant_crud",
            ],
            format_func=lambda x: {
                "explanation_diagram": "📖 システム説明（図表）",
                "explanation_document": "📖 システム説明（ドキュメント）",
                "qdrant_search": "🔎 Qdrant検索",
                "agent_chat": "自立型Agent(ReAct+Reflection)",
                "grace_chat": "自律型Agent(最新：動的Agent)",
                "log_viewer": "📊 未回答ログ",
                "rag_data_creation": "📄 RAGデータ作成",
                "qdrant_crud": "🗄️ QdrantのCRUD",
            }[x],
            label_visibility="collapsed",
        )
        st.markdown("全ソースは： [GitHub: nakashima2toshio/anthropic_grace_agent_v2](https://github.com/nakashima2toshio/anthropic_grace_agent_v2)")
        st.divider()

    # 選択された画面を表示
    page_mapping = {
        "explanation_diagram": lambda: show_system_explanation_page(section="diagram"),
        "explanation_document": lambda: show_system_explanation_page(section="document"),
        "agent_chat": show_agent_chat_page,
        "grace_chat": show_grace_chat_page,
        "log_viewer": show_log_viewer_page,
        "rag_data_creation": show_rag_data_creation_page,
        "qdrant_crud": show_qdrant_crud_page,
        "qdrant_search": show_qdrant_search_page,
    }
    page_mapping[page]()


if __name__ == "__main__":
    main()

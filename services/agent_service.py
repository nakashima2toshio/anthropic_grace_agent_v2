# agent_services.py
import os
import uuid
from typing import Any, Dict, Generator, List, Optional

from google import genai  # 新しいSDK
from google.genai import types  # 新しいSDK

# Configuration and Tools
from qdrant_client import (
    QdrantClient,  # noqa: F401  (レガシーテストの patch ターゲット)
)

from agent_tools import (
    RAGToolError,
    list_rag_collections,
    search_rag_knowledge_base,
    search_rag_knowledge_base_cached,
)
from qdrant_client_wrapper import get_qdrant_client

# 設定サービスからロガーと設定を取得
from services.config_service import get_config, logger
from services.log_service import log_unanswered_question

# キーワード抽出（オプション）
try:
    from regex_mecab import KeywordExtractor

    KEYWORD_EXTRACTION_AVAILABLE = True
except ImportError:
    KEYWORD_EXTRACTION_AVAILABLE = False
    KeywordExtractor = None

# キャッシュと並列検索をインポート

# -----------------------------------------------------------------------------
# Constants & Configuration
# -----------------------------------------------------------------------------

SYSTEM_INSTRUCTION_TEMPLATE = """
あなたは、社内ドキュメント検索システムと連携した「ハイブリッド・ナレッジ・エージェント」です。
あなたの役割は、ユーザーの質問に対して、一般的な知識と、提供されたツール（社内ナレッジ検索）を適切に使い分けて回答することです。

## ReAct プロセスと出力フォーマット (厳守)

あなたは **Thought (思考)**、**Action (ツール実行)**、**Observation (結果観察)** のサイクルを回して回答に到達する必要があります。

### 1. ツールを使用する場合（検索が必要な場合）
必ず以下の形式で思考を出力してから、ツールを呼び出してください。
**Thought: [なぜ検索が必要か、どんなクエリで検索するか]**
(この後にツール呼び出しが行われます)
**重要: 
- 検索クエリを作成する際は、提供された「重要キーワード」を必ず含めてください。
- `collection_name` パラメータは絶対に指定しないでください。システムが自動的に全コレクションから最適なものを選択します。**

### 2. 最終回答を行う場合（検索が完了した、または検索不要な場合）
必ず以下の形式で出力してください。
**Thought: [得られた情報に基づいてどう回答するか、または検索結果がなかった場合の判断]**
**Answer: [ユーザーへの最終的な回答]**

**重要:**
- 検索クエリは、質問文から「いつ」「誰」「何」などの具体的な要素を抽出して作成してください。抽象的な質問（例：「教えて」）をそのまま検索クエリにせず、具体的なキーワードに変換してください。
- 検索結果のスコアが低くても（例: 0.5程度）、内容が質問に関連していれば、その情報を積極的に使用して回答を作成してください。「情報が見つかりませんでした」と即断せず、得られた断片的な情報からでも回答を試みてください。
- 回答は必ず `Answer:` (または `**Answer:**`) で始めてください。

---

## 行動指針 (Router Guidelines)

1.  **専門知識の検索**:
    *   以下のいずれかに該当する場合は、**必ず `search_rag_knowledge_base` ツールを使用してください。**
        *   プロジェクト固有の仕様、設定、エラー、社内規定、Wikipediaの知識に関する質問。
        *   特定の情報源（例: "Wikipediaによると"、"ライブドアニュースで"）が指定されている質問。
        *   **内容が不明瞭であっても、社内ナレッジに関連する可能性があると判断される質問（例：特定のコード名、システム名、ランダムに見える文字列など）。**
        *   **ただし、一般的なプログラミング言語の文法や使い方に関する質問にはツールを使用しないでください。**
    *   **現在利用可能なコレクションは以下の通りです:**
        {available_collections}

2.  **スマート検索システム（自動コレクション選択）**:
    *   **重要: `search_rag_knowledge_base` ツールを呼び出す際、`collection_name` パラメータは絶対に指定しないでください。**
    *   システムが自動的に以下の戦略で最適なコレクションを選択します：
        *   **キャッシュ優先**: 前回成功したコレクションを優先的に検索
        *   **並列検索**: キャッシュミス時は全コレクションを同時並列検索
        *   **スコアベース選択**: 最もスコアが高い結果を自動的に返す
    *   あなたは `query` パラメータのみを指定してください。例: `search_rag_knowledge_base(query="カリン・フォン・アロルディンゲン")`
    *   
    *   **参考: 利用可能なコレクション（自動選択されます）**
        *   `cc_news`: 英語のニュース記事
        *   `wikipedia_ja`: 日本語の百科事典
        *   `livedoor`: 日本語のニュース・ブログ
        *   `japanese_text`: 日本語のWebテキスト
        *   `qa_pairs_custom_upload`, `custom_upload`: ユーザーアップロードの専門Q&A

3.  **一般的な会話**:
    *   挨拶、雑談、単純な計算など、専門知識が不要な場合は、ツールを使わずに `Answer:` で直接回答してください。

4.  **正直さと不足情報の処理 (Critical)**:
    *   ツール検索の結果、情報が得られなかった場合は、**絶対に**あなたの事前学習知識で捏造してはいけません。
    *   「提供された社内ナレッジには関連情報がありませんでした」と正直に伝えてください。

5.  **回答のスタイル**:
    *   丁寧な日本語（です・ます調）で回答してください。
    *   検索結果に基づく回答の場合、「社内ナレッジによると...」や「ソース [ファイル名] によると...」と出典を明示してください。
"""

REFLECTION_INSTRUCTION = """
## Reflection (自己評価と修正)

あなたは上記で作成した「回答案」を、以下の基準で客観的に評価し、必要であれば修正してください。

**チェックリスト:**
1.  **正確性:** 検索結果(もしあれば)に基づいているか？ 提供された情報源に含まれない情報を捏造していないか？
2.  **回答の適切性:** ユーザーの質問に直接的かつ明確に答えているか？
3.  **スタイル:** 親しみやすく、丁寧な日本語（です・ます調）か？ 箇条書きなどを活用して読みやすいか？

**指示:**
*   修正が不要な場合でも、必ず **Final Answer** を出力してください。
*   修正が必要な場合は、修正後の回答を **Final Answer** として出力してください。
*   思考プロセスは `Thought:` で始めてください。

**出力フォーマット:**
Thought: [評価と修正の思考プロセス]
Final Answer: [最終的な回答]
"""

TOOLS_MAP: Dict[str, Any] = {
    'search_rag_knowledge_base': search_rag_knowledge_base,
    'list_rag_collections'     : list_rag_collections
}


# -----------------------------------------------------------------------------
# ReActAgent Class
# -----------------------------------------------------------------------------

class ReActAgent:
    # ★変更: use_hybrid_search パラメータを追加（デフォルトは True）
    def __init__(
        self,
        selected_collections: List[str],
        model_name: str = None,
        session_id: Optional[str] = None,
        use_hybrid_search: bool = True  # ★追加: ハイブリッド検索フラグ
    ):
        self.selected_collections = selected_collections
        # モデル名はconfig_serviceから取得（デフォルト）
        resolved_model = model_name or get_config("models.default", "gemini-2.5-flash")
        # 安全デカップル: このレガシー ReActAgent は Gemini ネイティブの
        # function-calling（chats.create(tools=...) / function_call）に依存しているため、
        # Gemini 以外（例: GRACE 本体既定の claude-sonnet-4-6）が渡されると
        # Gemini エンドポイントに Claude モデル名を投げて失敗する。
        # その場合は Gemini 既定モデルへ自動回避し、警告を出す。
        legacy_default = get_config("models.legacy_default", "gemini-2.5-flash")
        if not str(resolved_model).lower().startswith("gemini"):
            logger.warning(
                f"ReActAgent(legacy) は Gemini ネイティブ function-calling 専用のため、"
                f"非 Gemini モデル '{resolved_model}' を Gemini 既定 '{legacy_default}' へ回避します。"
            )
            resolved_model = legacy_default
        self.model_name = resolved_model
        self.session_id = session_id or str(uuid.uuid4())
        self.use_hybrid_search = use_hybrid_search  # ★追加: インスタンス変数として保持

        # クライアントとチャットの初期化
        self.client = self._setup_client()
        self.chat = self._create_chat()

        self.thought_log: List[str] = []

        # キーワード抽出器の初期化
        if KEYWORD_EXTRACTION_AVAILABLE:
            try:
                self.keyword_extractor = KeywordExtractor(prefer_mecab=True)
                logger.info(f"KeywordExtractor initialized successfully. Session: {self.session_id}")
            except Exception as e:
                logger.error(f"Failed to initialize KeywordExtractor: {e}")
                self.keyword_extractor = None
        else:
            self.keyword_extractor = None

        # ★追加: ハイブリッド検索の状態をログ出力
        logger.info(
            f"ReActAgent initialized with session_id: {self.session_id}, "
            f"model: {self.model_name}, use_hybrid_search: {self.use_hybrid_search}"
        )

    def _setup_client(self) -> genai.Client:
        """
        新しいGoogle GenAI SDKクライアントのセットアップ
        config_service.pyから設定を取得
        """
        # config_serviceから取得（環境変数も自動処理される）
        api_key = get_config("api.google_api_key")

        # フォールバック：環境変数から直接取得
        if not api_key:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        if not api_key:
            error_msg = get_config("error_messages.api_key_missing", "APIキーが設定されていません")
            logger.error(f"{error_msg}: GEMINI_API_KEY or GOOGLE_API_KEY")
            raise ValueError(f"{error_msg}: GEMINI_API_KEY or GOOGLE_API_KEY not set.")

        logger.debug(f"Initializing GenAI client with API key: {api_key[:10]}...")
        return genai.Client(api_key=api_key)

    def _create_chat(self):
        """チャットセッションの作成"""
        collections_str = ", ".join(self.selected_collections) if self.selected_collections else "(コレクションが見つかりません)"
        system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(available_collections=collections_str)

        # ツールリスト
        tools_list = [search_rag_knowledge_base, list_rag_collections]

        # 新しいSDKでのチャット作成（最新仕様: types.GenerateContentConfig使用）
        logger.debug(f"Creating chat session with model: {self.model_name}")
        chat = self.client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=tools_list
            )
        )
        return chat

    def execute_turn(self, user_input: str) -> Generator[Dict[str, Any], None, None]:
        """
        ReAct → Reflection の順にエージェントのターンを実行し、
        進捗状況をイベントとしてyieldするジェネレータ。
        """
        self.thought_log = []
        logger.info(f"Starting agent turn. Session: {self.session_id}, Input: {user_input[:100]}...")

        # --- Phase 1: ReAct Loop ---
        # ★変更: ハイブリッド検索の状態を表示に追加
        hybrid_status = "有効 (Sparse + Dense)" if self.use_hybrid_search else "無効 (Dense のみ)"
        yield {"type": "log", "content": f"""🤖 **ReAct Phase Start**
📖 **説明**: エージェントが「思考→行動→観察」のサイクルで問題を解決します。
   質問を分析し、必要に応じてツール（検索など）を使用して情報を収集します。
⚡ **ハイブリッド検索**: {hybrid_status}"""}
        draft_answer: Optional[str] = None
        for event in self._execute_react_loop(user_input):
            yield event
            if event["type"] == "final_text":
                draft_answer = event["content"]

        # --- Phase 2: Reflection ---
        if draft_answer:
            yield {"type": "log", "content": """🔄 **Reflection Phase (推敲)**
📖 **説明**: エージェントが作成した回答案を客観的に評価・修正します。
   正確性、適切性、スタイルをチェックして最終回答を作成します。"""}
            final_answer_after_reflection = yield from self._execute_reflection_phase(draft_answer)
            draft_answer = final_answer_after_reflection

        final_answer = self._format_final_answer(draft_answer)
        logger.info(f"Agent turn completed. Final answer length: {len(final_answer)}")
        yield {"type": "final_answer", "content": final_answer}

    def _execute_react_loop(self, user_input: str) -> Generator[Dict[str, Any], None, None]:
        """ReActループを実行し、各ステップのイベントをyieldする"""
        # 重要単語抽出とプロンプト拡張
        augmented_input = user_input
        if self.keyword_extractor:
            try:
                keywords = self.keyword_extractor.extract(user_input, top_n=5)
                if keywords:
                    keywords_str = ", ".join(keywords)
                    # Phase 4 STEP 10 改善: プロンプトを具体化
                    augmented_input = (
                        f"{user_input}\n\n"
                        f"【重要: 検索クエリ作成の指示】\n"
                        f"以下の抽出された重要キーワードを、検索クエリに含めてください。\n"
                        f"特に固有名詞・専門用語は原文のまま含めること。\n"
                        f"重要キーワード: {keywords_str}"
                    )
                    logger.info(f"Augmented input with keywords: {keywords_str}")
                    yield {"type": "log", "content": f"""🔑 **Extracted Keywords:** {keywords_str}
📖 **説明**: 質問から重要なキーワードを自動抽出しました。
   これらのキーワードを使って、より正確な検索を行います。"""}
            except Exception as e:
                logger.warning(f"Keyword extraction failed during turn: {e}")

        # メッセージ送信
        current_response = self.chat.send_message(message=augmented_input)

        max_turns = get_config("agent.max_turns", 10)
        turn_count = 0
        final_text_from_react = ""

        while turn_count < max_turns:
            turn_count += 1
            logger.debug(f"ReAct turn {turn_count}/{max_turns}")
            function_call_found = False
            current_turn_text_from_model = ""

            # レスポンスの処理
            if current_response.candidates and len(current_response.candidates) > 0:
                candidate = current_response.candidates[0]

                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        # テキスト部分の処理
                        if hasattr(part, 'text') and part.text:
                            text = part.text.strip()
                            if "Thought:" in text or "考え:" in text:
                                self.thought_log.append(f"🧠 **Thought:**\n{text}")
                                yield {"type": "log", "content": f"🧠 **Thought:**\n{text}"}
                                current_turn_text_from_model = text
                            else:
                                current_turn_text_from_model = text

                        # 関数呼び出しの処理
                        if hasattr(part, 'function_call') and part.function_call:
                            function_call_found = True
                            fn = part.function_call
                            tool_name = fn.name
                            tool_args = dict(fn.args) if hasattr(fn, 'args') else {}

                            logger.info(f"Agent Tool Call: {tool_name}({tool_args})")
                            self.thought_log.append(f"🛠️ **Tool Call:** `{tool_name}`\nArgs: `{tool_args}`")
                            yield {"type": "tool_call", "name": tool_name, "args": tool_args}

                            tool_result = ""
                            try:
                                if tool_name in TOOLS_MAP:
                                    # search_rag_knowledge_base の場合はキャッシュ版を使用
                                    if tool_name == 'search_rag_knowledge_base':
                                        # ★変更: use_hybrid_search パラメータを渡す
                                        tool_result = search_rag_knowledge_base_cached(
                                            query=tool_args.get('query', ''),
                                            session_id=self.session_id,
                                            collection_name=tool_args.get('collection_name'),
                                            use_hybrid_search=self.use_hybrid_search  # ★追加
                                        )
                                    else:
                                        tool_result = TOOLS_MAP[tool_name](**tool_args)
                                else:
                                    tool_result = f"Error: Tool '{tool_name}' not found."
                            except RAGToolError as e:
                                tool_result = f"エラーが発生しました: {str(e)}"
                                logger.error(f"RAG Tool Error during '{tool_name}': {e}")
                            except Exception as e:
                                tool_result = f"予期せぬエラー: {str(e)}"
                                logger.error(f"Unexpected error during tool '{tool_name}': {e}", exc_info=True)

                            log_tool_result = str(tool_result)[:500] + "..." if len(str(tool_result)) > 500 else str(
                                tool_result)
                            self.thought_log.append(f"📝 **Tool Result:**\n{log_tool_result}")
                            yield {"type": "tool_result", "content": log_tool_result}
                            logger.info(f"Tool Result: {log_tool_result}")

                            if isinstance(tool_result, str) and tool_result.startswith("[[NO_RAG_RESULT"):
                                reason = "NO_RESULT"
                                if "LOW_SCORE" in tool_result:
                                    reason = "LOW_SCORE"
                                collection_arg = tool_args.get('collection_name', 'unknown')
                                log_unanswered_question(
                                    query=user_input,
                                    collections=[collection_arg],
                                    reason=reason,
                                    agent_response="(Search Failed)"
                                )

                            # ツール結果を送信（新しいSDK形式）
                            # tool_nameを明示的にstrにキャスト（型エラー回避）
                            function_response_part = types.Part.from_function_response(
                                name=str(tool_name),
                                response={'result': tool_result}
                            )

                            # 最新SDK: Partオブジェクトを直接渡す
                            # (Content型はsend_messageで受け付けないため、Partを使用)
                            current_response = self.chat.send_message(
                                message=function_response_part
                            )
                            break

            if not function_call_found:
                final_text_from_react = current_turn_text_from_model
                break

        yield {"type": "final_text", "content": final_text_from_react}

    def _execute_reflection_phase(self, draft_answer: str) -> Generator[Dict[str, Any], None, str]:
        """Reflectionフェーズを実行し、修正後の回答を返す"""
        final_response_text = draft_answer
        try:
            reflection_msg = f"{REFLECTION_INSTRUCTION}\n\n**あなたの回答案:**\n{draft_answer}"
            reflection_response = self.chat.send_message(message=reflection_msg)

            reflection_text = ""

            # レスポンスからテキストを抽出
            if reflection_response.candidates and len(reflection_response.candidates) > 0:
                candidate = reflection_response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            reflection_text += part.text
                        elif hasattr(part, 'function_call') and part.function_call:
                            logger.warning("Reflection phase generated a function call, ignoring.")

            if not reflection_text:
                logger.warning("Reflection phase did not generate text.")
                return draft_answer

            reflection_thought = ""
            reflection_answer = ""

            if "Final Answer:" in reflection_text:
                parts = reflection_text.split("Final Answer:", 1)
                reflection_thought = parts[0].strip()
                reflection_answer = parts[1].strip()
            else:
                reflection_thought = "Format mismatch in reflection."
                reflection_answer = reflection_text

            if reflection_thought:
                clean_thought = reflection_thought.replace("Thought:", "").strip()
                self.thought_log.append(f"🤔 **Reflection Thought:**\n{clean_thought}")
                logger.info(f"Reflection Thought: {clean_thought}")
                yield {"type": "log", "content": f"""🤔 **Reflection Thought:**
📖 **説明**: エージェントの自己評価の思考プロセスです。
   回答の品質を確認し、必要に応じて修正を行います。

{clean_thought}"""}

            if reflection_answer:
                final_response_text = reflection_answer
                logger.info(f"Reflection Answer: {reflection_answer[:100]}...")

        except Exception as e:
            logger.error(f"Error during reflection phase: {e}")
            self.thought_log.append(f"⚠️ **Reflection Error:** {str(e)}")
            yield {"type": "log", "content": f"⚠️ **Reflection Error:** {str(e)}"}
            final_response_text = draft_answer

        return final_response_text

    def _format_final_answer(self, raw_answer: str) -> str:
        """最終回答の整形"""
        if "Answer:" in raw_answer:
            parts = raw_answer.split("Answer:", 1)
            return parts[1].strip()
        elif raw_answer.startswith("Thought:"):
            return raw_answer.replace("Thought:", "").strip()
        elif raw_answer.startswith("考え:"):
            return raw_answer.replace("考え:", "").strip()
        return raw_answer


# Helper function
def get_available_collections_from_qdrant_helper() -> List[str]:
    """Qdrantから利用可能なコレクション名を取得"""
    try:
        # シングルトン QdrantClient を使用（Phase 2 STEP 4 改善）
        client = get_qdrant_client()
        collections = client.get_collections()
        return [c.name for c in collections.collections]
    except Exception as e:
        logger.error(f"Failed to fetch collections: {e}")
        return []

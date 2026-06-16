# tests/services/test_agent_service.py
from unittest.mock import MagicMock, patch

import pytest

from services.agent_service import ReActAgent


# ---------------------------------------------------------------------------
# 新しい google-genai SDK 用のレスポンスビルダー
#
# 新SDKでは chat.send_message(...) の戻り値は
#   response.candidates[0].content.parts -> [Part, ...]
# という構造を持つ。各 Part は .text または .function_call を持つ。
# ---------------------------------------------------------------------------
def make_part(text=None, function_call=None):
    part = MagicMock()
    part.text = text
    part.function_call = function_call
    return part


def make_response(parts):
    response = MagicMock()
    candidate = MagicMock()
    candidate.content.parts = parts
    response.candidates = [candidate]
    return response


def make_function_call(name, args):
    fc = MagicMock()
    fc.name = name
    fc.args = args
    return fc


@pytest.fixture
def mock_genai():
    """services.agent_service.genai 全体をモック。

    新SDK: genai.Client(api_key=...) -> client、
           client.chats.create(...) -> chat。
    """
    with patch("services.agent_service.genai") as mock:
        yield mock


@pytest.fixture
def mock_agent_tools():
    with patch("services.agent_service.search_rag_knowledge_base") as mock_search, \
         patch("services.agent_service.list_rag_collections") as mock_list:
        yield mock_search, mock_list


class TestReActAgent:

    def test_init(self, mock_genai):
        """ReActAgent の初期化（新SDK: genai.Client）"""
        # config_service が .env の実 google_api_key を返すと env パッチが無効化され、
        # 実APIキーが genai.Client へ渡って assert が落ちる（環境依存）。
        # get_config をモックして api.google_api_key を None にし、env フォールバックを
        # 確定的に通す。
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test_key'}, clear=True), \
             patch("services.agent_service.get_config") as mock_get_config:
            mock_get_config.side_effect = (
                lambda key, default=None: None if key == "api.google_api_key" else default
            )
            agent = ReActAgent(selected_collections=["coll1"], model_name="gemini-pro")

            assert agent.selected_collections == ["coll1"]
            assert agent.model_name == "gemini-pro"
            assert agent.thought_log == []

            # 新SDK: genai.Client(api_key=...) が呼ばれる
            mock_genai.Client.assert_called_with(api_key='test_key')
            # チャットセッションが作成される
            mock_genai.Client.return_value.chats.create.assert_called()
            # agent.chat が client.chats.create の戻り値
            assert agent.chat is mock_genai.Client.return_value.chats.create.return_value

    def test_init_missing_key(self, mock_genai):
        """APIキー未設定時に ValueError"""
        with patch.dict('os.environ', {}, clear=True):
            # config_service が google_api_key を返さないようにする
            with patch("services.agent_service.get_config") as mock_get_config:
                # api.google_api_key は None、その他はデフォルトを返す
                def _side_effect(key, default=None):
                    if key == "api.google_api_key":
                        return None
                    return default
                mock_get_config.side_effect = _side_effect
                with pytest.raises(ValueError, match="not set"):
                    ReActAgent(selected_collections=[], model_name="gemini-pro")

    def test_execute_turn_simple_answer(self, mock_genai):
        """モデルが直接回答を返すケース"""
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test_key'}):
            agent = ReActAgent(selected_collections=[], model_name="gemini-pro")

            # ReAct ループ: テキストのみ（function_call なし）
            react_response = make_response([
                make_part(text="Thought: I know the answer.\nAnswer: The answer is 42.")
            ])
            # Reflection: Final Answer を含むテキスト
            reflection_response = make_response([
                make_part(text="Reflection complete.\nFinal Answer: The answer is 42.")
            ])

            agent.chat.send_message.side_effect = [react_response, reflection_response]

            events = list(agent.execute_turn("What is the meaning of life?"))

            event_types = [e["type"] for e in events]
            assert "log" in event_types
            assert "final_text" in event_types
            assert "final_answer" in event_types

            final_event = events[-1]
            assert final_event["type"] == "final_answer"
            assert final_event["content"] == "The answer is 42."

    def test_execute_turn_with_tool_call(self, mock_genai, mock_agent_tools):
        """ツール呼び出しを伴う execute_turn"""
        mock_search, mock_list = mock_agent_tools

        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test_key'}), \
             patch.dict('services.agent_service.TOOLS_MAP', {
                 'search_rag_knowledge_base': mock_search,
                 'list_rag_collections': mock_list
             }):

            agent = ReActAgent(selected_collections=["coll1"], model_name="gemini-pro")

            # 1. 最初の応答: Thought テキスト + Tool Call
            response1 = make_response([
                make_part(text="Thought: I need to search."),
                make_part(function_call=make_function_call(
                    "search_rag_knowledge_base",
                    {"query": "test query", "collection_name": "coll1"},
                )),
            ])

            # 2. ツール結果を受けた応答
            response2 = make_response([
                make_part(text="Thought: I found it.\nAnswer: The result is X.")
            ])

            # 3. Reflection 応答
            reflection = make_response([
                make_part(text="Final Answer: The result is X.")
            ])

            agent.chat.send_message.side_effect = [response1, response2, reflection]

            # search_rag_knowledge_base は cached ラッパー経由で呼ばれるため、
            # そちらをモックして戻り値を制御する
            with patch("services.agent_service.search_rag_knowledge_base_cached",
                       return_value="Search Result Content") as mock_search_cached:
                events = list(agent.execute_turn("Search for test."))

            # cached 検索が想定引数で呼ばれたか
            mock_search_cached.assert_called_once()
            _, kwargs = mock_search_cached.call_args
            assert kwargs["query"] == "test query"
            assert kwargs["collection_name"] == "coll1"

            types = [e["type"] for e in events]
            assert "tool_call" in types
            assert "tool_result" in types
            assert "final_answer" in types

            assert "Thought: I need to search." in agent.thought_log[0]

    def test_format_final_answer(self, mock_genai):
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test_key'}):
            agent = ReActAgent(selected_collections=[], model_name="gemini-pro")

            assert agent._format_final_answer("Answer: Yes") == "Yes"
            assert agent._format_final_answer("Thought: Hmmm\nAnswer: Yes") == "Yes"
            assert agent._format_final_answer("Thought: Just a thought") == "Just a thought"
            assert agent._format_final_answer("考え: 日本語で") == "日本語で"
            assert agent._format_final_answer("Raw text") == "Raw text"

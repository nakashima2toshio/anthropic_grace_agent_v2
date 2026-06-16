"""
GRACE Tools - ツール定義

エージェントが使用するツール（RAG検索、推論、ask_user等）を定義
"""

import ast
import logging
import os
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from google.genai import types
from qdrant_client import QdrantClient

# Import wrappers for robust execution
from regex_mecab import KeywordExtractor

from .config import GraceConfig, get_config
from .llm_compat import create_chat_client

logger = logging.getLogger(__name__)


# =============================================================================
# ツール結果データクラス
# =============================================================================

@dataclass
class ToolResult:
    """ツール実行結果"""
    success: bool
    output: Any
    confidence_factors: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


# =============================================================================
# ツール基底クラス
# =============================================================================

class BaseTool(ABC):
    """ツール基底クラス"""

    name: str = "base_tool"
    description: str = "Base tool"

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """ツールを実行"""
        pass


# =============================================================================
# RAG検索ツール
# =============================================================================

class RAGSearchTool(BaseTool):
    """RAG検索ツール（Qdrant）"""

    name = "rag_search"
    description = "ベクトルDBから関連情報を検索"

    def __init__(
        self,
        config: Optional[GraceConfig] = None,
        qdrant_url: Optional[str] = None
    ):
        self.config = config or get_config()
        self.qdrant_url = qdrant_url or self.config.qdrant.url
        self._client: Optional[QdrantClient] = None
        
        # KeywordExtractorの初期化
        try:
            self.keyword_extractor = KeywordExtractor(prefer_mecab=True)
            logger.info("RAGSearchTool: KeywordExtractor initialized")
        except Exception as e:
            logger.warning(f"RAGSearchTool: Failed to initialize KeywordExtractor: {e}")
            self.keyword_extractor = None

    @property
    def client(self) -> QdrantClient:
        """Qdrantクライアントを取得（遅延初期化）"""
        if self._client is None:
            self._client = QdrantClient(url=self.qdrant_url)
        return self._client

    def execute(
        self,
        query: str,
        collection: Optional[str] = None,
        limit: Optional[int] = None,
        score_threshold: Optional[float] = None,
        **kwargs
    ) -> ToolResult:
        """
        RAG検索を実行（Legacy Proven Logic委譲版 + 独自キーワードフィルタリング + 自動コレクションフォールバック）

        Args:
            query: 検索クエリ
            collection: 検索対象コレクション（指定がない場合や、指定したコレクションで結果がない場合は自動的に他を試行）
            limit: 取得件数上限
            score_threshold: スコア閾値

        Returns:
            ToolResult: 検索結果
        """
        import time

        from agent_tools import search_rag_knowledge_base_structured
        
        start_time = time.time()
        
        # --- 重要単語抽出 (Regex Logic) ---
        required_keywords = []  # ★ 空で初期化しておく
        # kanji_katakana_pattern = r'^[\u4e00-\u9fff\u30a0-\u30ffー]+$'
        # kanji_katakana_extract_pattern = r'[\u4e00-\u9fff\u30a0-\u30ffー]{2,}'
        #
        # tokens = query.split()
        # required_keywords = [t for t in tokens if re.match(kanji_katakana_pattern, t)]
        # extracted = re.findall(kanji_katakana_extract_pattern, query)
        # required_keywords.extend(extracted)
        # required_keywords = list(set(required_keywords))
        
        if required_keywords:
            logger.info(f"RAGSearchTool: Required keywords for filtering: {required_keywords}")

        # --- 検索対象コレクションの決定（優先順位リスト） ---
        # 指定があればそれを最初に、なければデフォルト順
        search_candidates = []
        if collection:
            search_candidates.append(collection)
        
        # フォールバック用のコレクションを追加（重複排除・動的取得）
        # Qdrantから全コレクションを取得し、優先順位リストに従ってソート
        dynamic_collections = self._get_all_collections_dynamic()
        for c in dynamic_collections:
            if c not in search_candidates:
                search_candidates.append(c)
        
        logger.info(f"RAGSearchTool: Search candidates: {search_candidates}")

        final_results = []
        used_collection = None
        
        # --- コレクションを順次検索 ---
        for target_collection in search_candidates:
            logger.info(f"RAG search (Native): query='{query[:50]}...', collection={target_collection}")
            print(f"🔍 Searching collection: {target_collection}") # コンソールにも出力
            
            try:
                # 検索実行
                results = search_rag_knowledge_base_structured(query, target_collection)
                
                # エラーまたはメッセージのみの場合はスキップ
                if isinstance(results, str):
                    logger.debug(f"Search in {target_collection} returned message: {results}")
                    continue
                
                if not isinstance(results, list) or not results:
                    continue

                # --- 独自キーワードフィルタリング ---
                # if required_keywords:
                #     initial_count = len(results)
                #     filtered_results = []
                #     for res in results:
                #         payload = res.get("payload", {})
                #         content = (str(payload.get("question", "")) + " " +
                #                    str(payload.get("answer", "")) + " " +
                #                    str(payload.get("content", "")))
                #
                #         if any(kw in content for kw in required_keywords):
                #             filtered_results.append(res)
                #
                #     results = filtered_results
                #     logger.info(f"RAGSearchTool: Filtered results {initial_count} -> {len(results)} (Collection: {target_collection})")

                # 結果があれば採用してループ終了
                if results:
                    final_results = results
                    used_collection = target_collection
                    logger.info(f"Found {len(results)} valid results in {target_collection}")
                    break
            
            except Exception as e:
                logger.warning(f"Search failed for collection {target_collection}: {e}")
                continue

        # --- Dynamic Thresholding (動的な絞り込み) ---
        # 1位のスコアが非常に高い場合、2位以下のノイズを除去する
        if final_results:
            top_score = final_results[0].get("score", 0.0)
            # 閾値: Top 1が0.98以上の場合、他を切り捨てる
            if top_score >= 0.98 and len(final_results) > 1:
                logger.info(f"Dynamic Thresholding: Top score is {top_score:.4f}. Keeping only the top result (dropped {len(final_results)-1} others).")
                final_results = [final_results[0]]

        execution_time = int((time.time() - start_time) * 1000)

        # 結果なしの場合
        if not final_results:
            msg = "No relevant results found in any collection."
            return ToolResult(
                success=False,
                output=[],
                error=msg,
                confidence_factors={
                    "result_count": 0,
                    "avg_score": 0.0,
                    "message": msg
                },
                execution_time_ms=execution_time
            )

        # 成功時
        scores = [r.get("score", 0.0) for r in final_results]
        confidence_factors = self._calculate_confidence_factors(scores)
        
        # どのコレクションで見つかったかを記録
        confidence_factors["used_collection"] = used_collection

        # --- [IPO LOG] PROCESS OUTPUT (RAG SEARCH) ---
        import json
        results_display = json.dumps(final_results, indent=2, ensure_ascii=False)
        log_output = f"\n{'='*20} [RAG SEARCH IPO: OUTPUT] {'='*20}\nCollection: {used_collection}\n{results_display}\n{'='*60}"
        logger.info(log_output)
        print(log_output)

        return ToolResult(
            success=True,
            output=final_results,
            confidence_factors=confidence_factors,
            execution_time_ms=execution_time
        )

    def _get_all_collections_dynamic(self) -> List[str]:
        """Qdrantから全コレクション一覧を動的に取得し、優先順位付けして返す"""
        try:
            # Qdrantからコレクション一覧を取得
            collections_response = self.client.get_collections()
            all_collections = [c.name for c in collections_response.collections]
            
            # 設定ファイルの優先順位を取得
            priority_list = self.config.qdrant.search_priority
            
            # 優先順位リストにあるものを先に、それ以外を後に配置
            sorted_collections = []
            
            # 1. 優先順位リストにあるものを追加（存在チェック付き）
            for c in priority_list:
                if c in all_collections:
                    sorted_collections.append(c)
            
            # 2. 残りのコレクションを追加
            for c in all_collections:
                if c not in sorted_collections:
                    sorted_collections.append(c)
            
            logger.info(f"RAGSearchTool: Dynamic collections list: {sorted_collections}")
            return sorted_collections
            
        except Exception as e:
            logger.error(f"Failed to get collections dynamically: {e}", exc_info=True) # エラーログ強化
            print(f"❌ Failed to get collections dynamically: {e}") # コンソールにも出力
            # 失敗時は設定ファイルの値をそのまま返す
            return self.config.qdrant.search_priority

    def _calculate_confidence_factors(self, scores: List[float]) -> Dict[str, Any]:
        """Confidence計算用の統計情報を算出"""
        if not scores:
            return {
                "result_count": 0,
                "avg_score": 0.0,
                "score_variance": 1.0,
                "max_score": 0.0,
                "min_score": 0.0
            }

        avg_score = sum(scores) / len(scores)

        # 分散計算
        if len(scores) > 1:
            variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)
        else:
            variance = 0.0

        return {
            "result_count": len(scores),
            "avg_score": avg_score,
            "score_variance": variance,
            "max_score": max(scores),
            "min_score": min(scores)
        }


# =============================================================================
# 推論ツール
# =============================================================================

class ReasoningTool(BaseTool):
    """LLM推論ツール"""

    name = "reasoning"
    description = "収集した情報を分析・統合して回答を生成"

    def __init__(
        self,
        config: Optional[GraceConfig] = None,
        model_name: Optional[str] = None
    ):
        self.config = config or get_config()
        self.model_name = model_name or self.config.llm.model
        self.client = create_chat_client(self.config)

    def execute(
        self,
        query: str,
        context: Optional[str] = None,
        sources: Optional[List[Dict]] = None,
        **kwargs
    ) -> ToolResult:
        """
        LLM推論を実行

        Args:
            query: 元のクエリ
            context: 追加コンテキスト
            sources: 参照ソース（RAG検索結果など）

        Returns:
            ToolResult: 生成された回答
        """
        import time
        start_time = time.time()

        logger.info(f"Reasoning: query='{query[:50]}...'")

        try:
            # プロンプト構築
            prompt = self._build_prompt(query, context, sources)

            # --- [IPO LOG] PROCESS INPUT (GRACE REASONING) ---
            logger.info(f"\n{'='*20} [GRACE REASONING IPO: INPUT] {'='*20}\n{prompt}\n{'='*60}")

            # LLM呼び出し
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.config.llm.temperature,
                    max_output_tokens=self.config.llm.max_tokens,
                )
            )

            answer = response.text

            # --- [IPO LOG] PROCESS OUTPUT (GRACE REASONING) ---
            logger.info(f"\n{'='*20} [GRACE REASONING IPO: OUTPUT] {'='*20}\n{answer}\n{'='*60}")

            execution_time = int((time.time() - start_time) * 1000)

            # トークン使用量（利用可能な場合）
            token_usage = {}
            if hasattr(response, 'usage_metadata'):
                token_usage = {
                    "input_tokens": getattr(response.usage_metadata, 'prompt_token_count', 0),
                    "output_tokens": getattr(response.usage_metadata, 'candidates_token_count', 0),
                }

            logger.info(f"Reasoning completed: {len(answer)} chars")

            return ToolResult(
                success=True,
                output=answer,
                confidence_factors={
                    "has_sources": bool(sources),
                    "source_count": len(sources) if sources else 0,
                    "answer_length": len(answer),
                    "token_usage": token_usage
                },
                execution_time_ms=execution_time
            )

        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )

    def _build_prompt(
        self,
        query: str,
        context: Optional[str],
        sources: Optional[List[Dict]]
    ) -> str:
        """
        推論用プロンプトを構築（高度化版）
        Legacy Agentの知見を活かした指示セットを使用。
        """
        prompt_parts = []

        # システム指示
        prompt_parts.append(
            "あなたは社内ドキュメント検索システムと連携した「ハイブリッド・ナレッジ・エージェント」です。\n"
            "提供された【参照情報】を元に、ユーザーの質問に対して正確で誠実な回答を生成してください。\n"
        )

        # ソース情報（RAG結果）
        if sources:
            prompt_parts.append("\n### 【参照情報】")
            for i, source in enumerate(sources, 1):
                payload = source.get("payload", {})
                score = source.get("score", 0)
                col = source.get("collection", "unknown")

                question = payload.get("question", "")
                answer = payload.get("answer", "")
                content = payload.get("content", "")
                src_file = payload.get("source", "unknown")

                prompt_parts.append(f"\n--- 情報源 {i} (信頼度: {score:.2f}, コレクション: {col}) ---")
                if question:
                    prompt_parts.append(f"Q: {question}")
                if answer:
                    prompt_parts.append(f"A: {answer}")
                if content and not (question or answer):
                    prompt_parts.append(content[:1000])
                prompt_parts.append(f"出典: {src_file}")

        # 追加コンテキスト（他ステップの結果など）
        if context:
            prompt_parts.append(f"\n### 【補足コンテキスト】\n{context}")

        # ユーザーの質問
        prompt_parts.append(f"\n### 【ユーザーの質問】\n{query}")

        # 回答のルール
        prompt_parts.append(
            "\n### 【回答の構成ルール（最重要）】\n"
            "1. **正確性と誠実さ**: 参照情報にある事実のみを述べてください。情報がない場合は「提供された情報源には見当たりませんでした」と正直に回答してください。\n"
            "2. **判明した事実を優先**: 質問に対する直接的な回答が見つかった場合は、それを最初に簡潔に述べてください。\n"
            "3. **出典の明示**: 回答の根拠となった情報がある場合、「社内ナレッジ（出典ファイル名）によると...」の形式で出典を明示してください。\n"
            "4. **丁寧な日本語**: です・ます調で、読みやすく構造化（箇条書き等）して回答してください。\n"
            "5. **捏造禁止**: あなた自身の事前知識で情報を補完したり、勝手な推測で回答を作成したりしないでください。\n"
            "\n上記のルールに従い、プロフェッショナルな回答を生成してください。"
        )

        return "\n".join(prompt_parts)


# =============================================================================
# Ask User ツール（HITL用）
# =============================================================================

class AskUserTool(BaseTool):
    """ユーザーに質問するツール（HITL）"""

    name = "ask_user"
    description = "ユーザーに追加情報や確認を求める"

    # Gemini Function Calling用の定義
    FUNCTION_DECLARATION = {
        "name": "ask_user_for_clarification",
        "description": """
ユーザーに追加情報を求めるツール。
以下の場合にのみ使用:
- 質問の意図が曖昧で、複数の解釈が可能
- 必要な情報が検索で見つからない
- 矛盾する情報があり、どちらを優先すべきか不明
""",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "ユーザーへの質問文（明確かつ簡潔に）"
                },
                "reason": {
                    "type": "string",
                    "description": "なぜこの質問が必要か（ユーザーに表示）"
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "選択肢がある場合のリスト（任意）"
                },
                "urgency": {
                    "type": "string",
                    "enum": ["blocking", "optional"],
                    "description": "blocking: 回答がないと進めない, optional: 推測で進めることも可能"
                }
            },
            "required": ["question", "reason", "urgency"]
        }
    }

    def execute(
        self,
        question: str,
        reason: str,
        urgency: str = "blocking",
        options: Optional[List[str]] = None,
        **kwargs
    ) -> ToolResult:
        """
        ユーザーに質問（実際のUIとの連携はExecutorで行う）

        Args:
            question: ユーザーへの質問
            reason: 質問の理由
            urgency: 緊急度（blocking/optional）
            options: 選択肢リスト

        Returns:
            ToolResult: 質問情報（回答はExecutorで処理）
        """
        logger.info(f"Ask user: {question} (urgency={urgency})")

        return ToolResult(
            success=True,
            output={
                "question": question,
                "reason": reason,
                "urgency": urgency,
                "options": options,
                "awaiting_response": True
            },
            confidence_factors={
                "requires_user_input": True,
                "urgency": urgency
            }
        )


# =============================================================================
# Web検索ツール
# =============================================================================

class WebSearchTool(BaseTool):
    """Web検索ツール（SerpAPI / DuckDuckGo / Google CSE 切り替え対応）"""

    name = "web_search"
    description = "Web検索で最新情報を取得"

    def __init__(self, config: Optional[GraceConfig] = None):
        self.config = config or get_config()
        self.backend = self.config.web_search.backend
        self.num_results = self.config.web_search.num_results
        self.language = self.config.web_search.language
        self.timeout = self.config.web_search.timeout
        logger.info(f"WebSearchTool initialized: backend={self.backend}")

    def execute(
        self,
        query: str,
        num_results: Optional[int] = None,
        language: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """
        Web検索を実行

        Args:
            query: 検索クエリ
            num_results: 取得件数（デフォルト: configの値）
            language: 検索言語（デフォルト: configの値）

        Returns:
            ToolResult: rag_search互換形式の検索結果
        """
        import time
        start_time = time.time()

        num = num_results or self.num_results
        lang = language or self.language

        logger.info(f"WebSearch: query='{query[:50]}...', backend={self.backend}, num={num}")

        try:
            if self.backend == "duckduckgo":
                raw_results = self._search_ddg(query, num, lang)
            elif self.backend == "google_cse":
                raw_results = self._search_google(query, num, lang)
            elif self.backend == "serpapi":
                raw_results = self._search_serpapi(query, num, lang)
            else:
                raise ValueError(f"Unknown web search backend: {self.backend}")

            # rag_search互換フォーマットに変換
            formatted = self._parse_to_rag_format(raw_results, num)
            execution_time = int((time.time() - start_time) * 1000)

            if not formatted:
                msg = f"Web検索結果が見つかりませんでした: '{query}'"
                logger.warning(msg)
                return ToolResult(
                    success=False,
                    output=[],
                    error=msg,
                    confidence_factors={"result_count": 0, "search_engine": self.backend},
                    execution_time_ms=execution_time
                )

            scores = [r["score"] for r in formatted]
            confidence_factors = self._calculate_confidence_factors(scores)

            # --- [IPO LOG] PROCESS OUTPUT (WEB SEARCH) ---
            import json
            results_display = json.dumps(formatted, indent=2, ensure_ascii=False)
            log_output = (
                f"\n{'='*20} [WEB SEARCH IPO: OUTPUT] {'='*20}"
                f"\nBackend: {self.backend}"
                f"\nQuery: {query}"
                f"\n{results_display}"
                f"\n{'='*60}"
            )
            logger.info(log_output)
            print(log_output)

            return ToolResult(
                success=True,
                output=formatted,
                confidence_factors=confidence_factors,
                execution_time_ms=execution_time
            )

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            error_msg = f"Web検索エラー ({self.backend}): {e}"
            logger.error(error_msg, exc_info=True)
            return ToolResult(
                success=False,
                output=None,
                error=error_msg,
                execution_time_ms=execution_time
            )

    def _search_ddg(self, query: str, num_results: int, language: str) -> list:
        """DuckDuckGo検索バックエンド"""
        from duckduckgo_search import DDGS

        region = "jp-jp" if language == "ja" else "wt-wt"
        logger.info(f"DDG search: query='{query}', region={region}, max_results={num_results}")

        with DDGS() as ddgs:
            results = list(ddgs.text(query, region=region, max_results=num_results))

        logger.info(f"DDG search returned {len(results)} results")
        return results

    def _search_google(self, query: str, num_results: int, language: str) -> list:
        """Google CSE検索バックエンド"""
        import os

        import requests

        api_key = (
            os.environ.get("GOOGLE_CSE_API_KEY", "")
            or self.config.web_search.google_cse_api_key
        )
        engine_id = (
            os.environ.get("GOOGLE_CSE_ENGINE_ID", "")
            or self.config.web_search.google_cse_engine_id
        )

        if not api_key or not engine_id:
            raise ValueError(
                "Google CSEの設定が不足しています。"
                "GOOGLE_CSE_API_KEY と GOOGLE_CSE_ENGINE_ID を設定してください"
            )

        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": engine_id,
                "q": query,
                "lr": f"lang_{language}",
                "num": num_results,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    def _search_serpapi(self, query: str, num_results: int, language: str) -> list:
        """SerpAPI検索バックエンド（リトライ1回付き）"""
        import os
        import time as _time

        import requests

        api_key = (
            os.environ.get("SERPAPI_KEY", "")
            or self.config.web_search.serpapi_api_key
        )

        if not api_key:
            raise ValueError(
                "SerpAPIの設定が不足しています。"
                "SERPAPI_KEY 環境変数を設定してください"
            )

        logger.info(f"SerpAPI search: query='{query}', num={num_results}, lang={language}")

        params = {
            "api_key": api_key,
            "q": query,
            "hl": language,
            "gl": "jp" if language == "ja" else "us",
            "num": num_results,
        }

        # リトライ1回付き（タイムアウト対策）
        max_retries = 2
        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    "https://serpapi.com/search.json",
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()

                results = data.get("organic_results", [])
                logger.info(f"SerpAPI search returned {len(results)} results")
                return results

            except requests.exceptions.ReadTimeout:
                if attempt < max_retries - 1:
                    wait = 2 * (attempt + 1)
                    logger.warning(f"SerpAPI timeout (attempt {attempt + 1}/{max_retries}), retrying in {wait}s...")
                    _time.sleep(wait)
                else:
                    raise

    def _parse_to_rag_format(self, raw_results: list, num_results: int) -> list:
        """検索結果を rag_search 互換フォーマットに変換"""
        formatted = []
        for i, item in enumerate(raw_results):
            # 検索順位ベースの正規化スコア: 1位=1.0, 最下位=0.5
            score = round(1.0 - (i / max(num_results, 1)) * 0.5, 2)

            if self.backend == "duckduckgo":
                entry = {
                    "score": score,
                    "payload": {
                        "question": "",
                        "answer": item.get("body", ""),
                        "content": "",
                        "source": item.get("href", ""),
                        "title": item.get("title", ""),
                    },
                    "collection": "web_search",
                }
            else:  # serpapi / google_cse (both use title/link/snippet)
                entry = {
                    "score": score,
                    "payload": {
                        "question": "",
                        "answer": item.get("snippet", ""),
                        "content": "",
                        "source": item.get("link", ""),
                        "title": item.get("title", ""),
                    },
                    "collection": "web_search",
                }

            formatted.append(entry)
        return formatted

    def _calculate_confidence_factors(self, scores: list) -> dict:
        """検索結果の Confidence 統計情報を算出"""
        if not scores:
            return {
                "result_count": 0,
                "avg_score": 0.0,
                "top_score": 0.0,
                "score_spread": 0.0,
                "search_engine": self.backend,
            }

        return {
            "result_count": len(scores),
            "avg_score": round(sum(scores) / len(scores), 2),
            "top_score": max(scores),
            "score_spread": round(max(scores) - min(scores), 2),
            "search_engine": self.backend,
        }


# =============================================================================
# ツールレジストリ
# =============================================================================

class CodeExecuteTool(BaseTool):
    """サンドボックス Python 実行ツール（P2）。

    best-effort サンドボックス:
      - 別プロセスで実行（`python -I -S`: isolated mode + site 無効）
      - resource 制限（CPU 時間 / アドレス空間 / 生成ファイルサイズ）※POSIX
      - 環境変数を最小化、stdin を遮断、一時ディレクトリで実行
      - 実時間タイムアウトで強制終了
      - AST レベルで危険モジュールの import を拒否（多層防御）

    注意: これは利便性のための隔離であり、決定的な攻撃者に対する
    セキュリティ境界ではない。信頼できないコードにはコンテナ/gVisor 等の
    外部境界を併用すること。既定では `tools.enabled` に含めず opt-in。
    """

    name = "code_execute"
    description = "Python コードをサンドボックスで実行し標準出力を返す"

    def __init__(self, config: Optional[GraceConfig] = None):
        self.config = config or get_config()
        self.cfg = self.config.code_execute

    def _static_check(self, code: str) -> tuple[bool, Optional[str]]:
        """AST で構文検証＋禁止 import / 危険属性アクセスを拒否する。"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

        denied = set(self.cfg.denied_imports)
        dangerous_attrs = {"system", "popen", "exec", "execv", "execve",
                           "spawn", "spawnv", "fork", "remove", "rmdir", "unlink"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in denied:
                        return False, f"禁止された import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                if top in denied:
                    return False, f"禁止された import: from {node.module}"
            elif isinstance(node, ast.Attribute):
                # os.system / os.popen / os.exec* 等の危険呼び出しを拒否
                if node.attr in dangerous_attrs:
                    return False, f"禁止された属性アクセス: .{node.attr}"
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in {"eval", "exec", "compile", "__import__"}:
                    return False, f"禁止された関数呼び出し: {fn.id}()"
        return True, None

    @staticmethod
    def _apply_limits(cpu_seconds: int, mem_bytes: int):
        """子プロセスで resource 制限を適用する（POSIX のみ）。"""
        import resource
        # CPU 時間（秒）
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        # アドレス空間（メモリ）
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        # 生成ファイルサイズ上限（1MB）
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))

    def execute(self, code: Optional[str] = None, query: Optional[str] = None,
                **kwargs) -> ToolResult:
        start = time.time()
        source = code or query
        if not source or not isinstance(source, str) or not source.strip():
            return ToolResult(success=False, output=None,
                              error="実行する Python コードが指定されていません")

        ok, reason = self._static_check(source)
        if not ok:
            logger.warning(f"CodeExecuteTool: rejected by static check: {reason}")
            return ToolResult(success=False, output=None, error=reason,
                              confidence_factors={"rejected": True})

        cpu = max(1, int(self.cfg.timeout_seconds))
        mem_bytes = max(64, int(self.cfg.max_memory_mb)) * 1024 * 1024
        env = {"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8",
               "LC_ALL": "C.UTF-8", "HOME": "/tmp"}
        preexec = None
        if os.name == "posix":
            preexec = lambda: CodeExecuteTool._apply_limits(cpu, mem_bytes)  # noqa: E731

        try:
            with tempfile.TemporaryDirectory() as td:
                script = os.path.join(td, "snippet.py")
                with open(script, "w", encoding="utf-8") as f:
                    f.write(source)
                proc = subprocess.run(
                    [sys.executable, "-I", "-S", script],
                    cwd=td,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=cpu + 1,
                    preexec_fn=preexec,
                )
            stdout = (proc.stdout or "")[: self.cfg.max_output_chars]
            stderr = (proc.stderr or "")[: self.cfg.max_output_chars]
            elapsed = int((time.time() - start) * 1000)
            success = proc.returncode == 0
            output = stdout if success else (stdout + ("\n[stderr]\n" + stderr if stderr else ""))
            return ToolResult(
                success=success,
                output=output if output else "(出力なし)",
                error=None if success else (stderr or f"exit code {proc.returncode}"),
                execution_time_ms=elapsed,
                confidence_factors={
                    "returncode": proc.returncode,
                    "stdout_len": len(stdout),
                    "timed_out": False,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, output=None,
                error=f"実行がタイムアウトしました（{cpu}s）",
                confidence_factors={"timed_out": True},
            )
        except Exception as e:
            logger.error(f"CodeExecuteTool failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class ToolRegistry:
    """ツールレジストリ"""

    def __init__(self, config: Optional[GraceConfig] = None):
        self.config = config or get_config()
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """デフォルトツールを登録"""
        enabled_tools = self.config.tools.enabled

        if "rag_search" in enabled_tools:
            self.register(RAGSearchTool(config=self.config))

        if "web_search" in enabled_tools:
            self.register(WebSearchTool(config=self.config))

        if "reasoning" in enabled_tools:
            self.register(ReasoningTool(config=self.config))

        if "ask_user" in enabled_tools:
            self.register(AskUserTool())

        # code_execute は opt-in（既定の enabled には含めない）
        if "code_execute" in enabled_tools:
            self.register(CodeExecuteTool(config=self.config))

        logger.info(f"ToolRegistry initialized with: {list(self._tools.keys())}")

    def register(self, tool: BaseTool):
        """ツールを登録"""
        self._tools[tool.name] = tool
        logger.debug(f"Tool registered: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """ツールを取得"""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """登録済みツール名のリスト"""
        return list(self._tools.keys())

    def execute(self, name: str, **kwargs) -> ToolResult:
        """ツールを実行"""
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output=None,
                error=f"Unknown tool: {name}"
            )
        return tool.execute(**kwargs)


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_tool_registry(config: Optional[GraceConfig] = None) -> ToolRegistry:
    """ToolRegistryインスタンスを作成"""
    return ToolRegistry(config=config)


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    # Data classes
    "ToolResult",

    # Base class
    "BaseTool",

    # Tools
    "RAGSearchTool",
    "WebSearchTool",
    "ReasoningTool",
    "AskUserTool",
    "CodeExecuteTool",

    # Registry
    "ToolRegistry",
    "create_tool_registry",
]
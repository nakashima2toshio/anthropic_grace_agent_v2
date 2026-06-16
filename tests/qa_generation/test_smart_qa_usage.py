"""B-1: SmartQAGenerator のトークン使用量配線（process_chunk の 'usage'）。

実 LLM API 不要。統一 LLM クライアント（create_llm_client）をモックし、
generate_structured が返す解析済み SmartQAResult が process_chunk の戻り値に
正しく載ること、および失敗時に usage がゼロになることを検証する。

注: Anthropic への移行に伴い、構造化出力は解析済み Pydantic インスタンスを
直接返すため、レスポンスからのトークン使用量取得は行わない（usage は 0）。
"""
from unittest.mock import MagicMock, patch

import qa_generation.smart_qa_generator as m
from qa_generation.smart_qa_generator import SmartQAResult


def _make_generator():
    with patch.object(m, "create_llm_client") as mock_factory:
        mock_factory.return_value = MagicMock()
        return m.SmartQAGenerator(api_key="x")


def _fake_result(qa_count=1):
    return SmartQAResult(
        qa_count=qa_count,
        qa_pairs=[{"question": "Q", "answer": "A", "topic": "t"}] * qa_count,
    )


def test_process_chunk_includes_usage():
    gen = _make_generator()
    gen.client.generate_structured.return_value = _fake_result(1)

    out = gen.process_chunk("text")

    assert out["success"] is True
    assert out["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert len(out["qa_pairs"]) == 1


def test_failure_returns_zero_usage():
    gen = _make_generator()
    gen.client.generate_structured.side_effect = RuntimeError("boom")

    out = gen.process_chunk("text")

    assert out["success"] is False
    assert out["usage"] == {"input_tokens": 0, "output_tokens": 0}


def test_empty_result_defaults_zero():
    """qa_count=0 のレスポンスでも安全に処理する。"""
    gen = _make_generator()
    gen.client.generate_structured.return_value = SmartQAResult(qa_count=0, qa_pairs=[])

    out = gen.process_chunk("text")

    assert out["success"] is True
    assert out["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert out["qa_pairs"] == []

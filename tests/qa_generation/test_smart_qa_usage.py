"""B-1: SmartQAGenerator のトークン使用量配線（usage_metadata → process_chunk）。

実 Gemini API 不要。genai.Client をモックし、レスポンスの usage_metadata から
input/output トークンが process_chunk の戻り値 'usage' に載ることを検証する。
"""
from unittest.mock import MagicMock, patch

import qa_generation.smart_qa_generator as m
from qa_generation.smart_qa_generator import SmartQAResult


def _make_generator():
    with patch.object(m.genai, "Client"):
        return m.SmartQAGenerator(api_key="x")


def _fake_response(qa_count=1, in_tok=123, out_tok=45):
    resp = MagicMock()
    resp.text = SmartQAResult(
        qa_count=qa_count,
        qa_pairs=[{"question": "Q", "answer": "A", "topic": "t"}] * qa_count,
    ).model_dump_json()
    resp.usage_metadata.prompt_token_count = in_tok
    resp.usage_metadata.candidates_token_count = out_tok
    return resp


def test_process_chunk_includes_real_usage():
    gen = _make_generator()
    gen.client.models.generate_content.return_value = _fake_response(1, 123, 45)

    out = gen.process_chunk("text")

    assert out["success"] is True
    assert out["usage"] == {"input_tokens": 123, "output_tokens": 45}


def test_failure_returns_zero_usage():
    gen = _make_generator()
    gen.client.models.generate_content.side_effect = RuntimeError("boom")

    out = gen.process_chunk("text")

    assert out["success"] is False
    assert out["usage"] == {"input_tokens": 0, "output_tokens": 0}


def test_missing_usage_metadata_defaults_zero():
    """usage_metadata が無いレスポンスでも 0 で安全に処理する。"""
    gen = _make_generator()
    resp = MagicMock()
    resp.text = SmartQAResult(qa_count=0, qa_pairs=[]).model_dump_json()
    resp.usage_metadata = None
    gen.client.models.generate_content.return_value = resp

    out = gen.process_chunk("text")

    assert out["success"] is True
    assert out["usage"] == {"input_tokens": 0, "output_tokens": 0}

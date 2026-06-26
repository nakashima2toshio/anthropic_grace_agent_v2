#!/usr/bin/env zsh
# ==============================================================
# run_benchmark.sh - anthropic_grace_agent_v2 ベンチマーク実行
# ==============================================================
# 使用法:
#   chmod +x run_benchmark.sh
#   ./run_benchmark.sh
#
# 前提条件:
#   - Qdrant が起動済み (localhost:6333)
#   - cc_news_2per_anthropic コレクションが作成・ embedding 済み
#   - .env または環境変数に ANTHROPIC_API_KEY が設定済み（LLM: Plan/Execute/
#     Confidence/Replan/ReAct）
#   - 既定の Embedding は Gemini（gemini-embedding-001 / 3072次元）のため、
#     RAG 検索のクエリ埋め込みに GOOGLE_API_KEY も必要
# ==============================================================

set -euo pipefail

COLLECTION="cc_news_2per_anthropic"
PROJECT="anthropic_grace_agent_v2"
MODEL="claude-sonnet-4-6"
PROVIDER="anthropic"

# API キーの簡易チェック（未設定でも実行は試みるが警告する）
: "${ANTHROPIC_API_KEY:=}"
if [[ -z "${ANTHROPIC_API_KEY}" ]]; then
  echo "⚠️  ANTHROPIC_API_KEY が未設定です（.env もしくは環境変数を確認してください）"
fi

echo "================================================================"
echo "  GRACE Benchmark Runner"
echo "  Project   : ${PROJECT}"
echo "  Provider  : ${PROVIDER}"
echo "  Model     : ${MODEL}"
echo "  Collection: ${COLLECTION}"
echo "  Start     : $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"

uv run python - << PYEOF
from grace.benchmark import BenchmarkRunner

# model_name / provider を明示指定し、Anthropic 専用で実行する
runner = BenchmarkRunner(
    model_name="${MODEL}",
    provider="${PROVIDER}",
    qdrant_collection="${COLLECTION}",
)
sessions = runner.run_query_set(runs_per_query=3)
count = len(sessions)

# 経路一致率（route_correct）を集計して表示
scored = [s for s in sessions if s.route_correct is not None]
if scored:
    correct = sum(1 for s in scored if s.route_correct)
    rate = correct / len(scored) * 100
    print(f"\n経路一致率(route_correct): {correct}/{len(scored)} = {rate:.1f}%")
print(f"完了: {count} セッション -> logs/benchmark_results.csv")
PYEOF

echo "================================================================"
echo "  End: $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"

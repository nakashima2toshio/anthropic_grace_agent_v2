"""ベンチマーク実行スクリプト"""
from grace.benchmark import BenchmarkRunner

if __name__ == "__main__":
    runner = BenchmarkRunner()
    sessions = runner.run_query_set(runs_per_query=3)
    print(f"\n完了: {len(sessions)} セッション -> logs/benchmark_results.csv")

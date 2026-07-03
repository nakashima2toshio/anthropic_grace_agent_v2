# eval/vertical/fetch_real_knowledge.py
"""実運用ナレッジの取得・整形（業界特化 次工程候補③）。

公開データから業界コレクションの「実データ」を取得し、既存パイプライン
（`chunking` → `qa_generation` → Qdrant 登録）に載る text CSV へ整形する。
LLM・Qdrant・APIキーは不要（HTTP 取得のみ）。登録はユーザー環境で行う。

出典・ライセンス（docs/vertical_test_data.md §3 の検証結果）:
- gov : e-Gov 法令 API（政府標準利用規約 2.0・出典明示で二次利用可）
- saas: OSS 公式ドキュメント（Markdown・Apache/MIT 等。既定は FastAPI 日本語版 MIT）
- ec  : 返品規定・利用規約は各社固有のため公開実データなし（合成 or 自社データを
        同じ CSV 形式で用意して同一手順で登録する）

使い方::

    # 自治体: e-Gov 法令 API から法令全文を取得し、条単位の text CSV を出力
    uv run python -m eval.vertical.fetch_real_knowledge egov \
        --output OUTPUT/gov_laws_real.csv

    # SaaS: OSS 公式ドキュメント（Markdown）を取得し、見出しセクション単位で出力
    uv run python -m eval.vertical.fetch_real_knowledge oss-docs \
        --output OUTPUT/saas_docs_real.csv

    # 登録（ユーザー環境・Qdrant 起動済み）:
    uv run python -m chunking.csv_text_to_chunks_text_csv \
        --input-file OUTPUT/gov_laws_real.csv --output output_chunked
    uv run python qa_qdrant/make_qa_register_qdrant.py \
        --input-file output_chunked/gov_laws_real_chunks.csv \
        --collection gov_laws_anthropic --recreate
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import quote

EGOV_API_BASE = "https://laws.e-gov.go.jp/api/1"

# 既定の取得対象法令（gov プロファイルのテスト質問と親和する行政手続き系）。
# 法令番号は e-Gov の正式表記。--law で上書き・追加できる。
DEFAULT_LAWS = [
    "平成五年法律第八十八号",        # 行政手続法
    "平成二十六年法律第六十八号",    # 行政不服審査法
    "昭和四十二年法律第八十一号",    # 住民基本台帳法
]

# 既定の OSS ドキュメント（FastAPI 日本語版・MIT）。タグ固定で再現性を確保。
# --url で任意の raw Markdown URL に差し替え可能。
DEFAULT_DOC_URLS = [
    "https://raw.githubusercontent.com/fastapi/fastapi/0.115.6/docs/ja/docs/index.md",
    "https://raw.githubusercontent.com/fastapi/fastapi/0.115.6/docs/ja/docs/tutorial/first-steps.md",
    "https://raw.githubusercontent.com/fastapi/fastapi/0.115.6/docs/ja/docs/tutorial/security/index.md",
    "https://raw.githubusercontent.com/fastapi/fastapi/0.115.6/docs/ja/docs/deployment/concepts.md",
]

DEFAULT_MAX_CHARS = 2000  # 1 行（1 条・1 セクション）の最大文字数（超過分は分割）


@dataclass
class KnowledgeRow:
    """text CSV の 1 行（text カラムは chunking / 登録スクリプトが自動検出する）。"""

    text: str
    title: str
    source: str


# =============================================================================
# gov: e-Gov 法令 API（XML）→ 条単位の text 行
# =============================================================================

def parse_law_xml(xml_text: str, source_url: str = "") -> List[KnowledgeRow]:
    """e-Gov 法令 API の XML から条単位の KnowledgeRow を抽出する。

    スキーマ差異に強いよう、<Article> 要素の itertext() を結合する汎用抽出とし、
    条見出し（ArticleTitle/ArticleCaption）を title に含める。
    """
    root = ET.fromstring(xml_text)
    law_title_el = root.find(".//LawTitle")
    law_title = "".join(law_title_el.itertext()).strip() if law_title_el is not None else "法令"

    rows: List[KnowledgeRow] = []
    for article in root.iter("Article"):
        title_el = article.find("ArticleTitle")
        caption_el = article.find("ArticleCaption")
        article_no = "".join(title_el.itertext()).strip() if title_el is not None else ""
        caption = "".join(caption_el.itertext()).strip() if caption_el is not None else ""

        # 条全文（見出し要素を除く本文）を汎用抽出
        parts = []
        for child in article:
            if child.tag in ("ArticleTitle", "ArticleCaption"):
                continue
            text = " ".join(t.strip() for t in child.itertext() if t.strip())
            if text:
                parts.append(text)
        body = " ".join(parts).strip()
        if not body:
            continue

        caption_part = f"（{caption.strip('（）')}）" if caption else ""
        heading = f"{law_title} {article_no}{caption_part}".strip()
        rows.append(KnowledgeRow(
            text=f"{heading}: {body}",
            title=heading,
            source=source_url,
        ))
    return rows


def fetch_egov_law(law_num: str, timeout: int = 30) -> str:
    """e-Gov 法令 API v1 から法令全文 XML を取得する。"""
    import requests

    url = f"{EGOV_API_BASE}/lawdata/{quote(law_num)}"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


# =============================================================================
# saas: OSS ドキュメント（Markdown）→ 見出しセクション単位の text 行
# =============================================================================

_MD_HEADING = re.compile(r"^(#{1,4})\s+(.+)$")


def parse_markdown_sections(md_text: str, source_url: str = "") -> List[KnowledgeRow]:
    """Markdown を見出し（#〜####）単位のセクションに分割して KnowledgeRow 化する。

    コードフェンス内の見出し風の行は無視する。先頭見出しまでの前文は
    ドキュメント名（URL 末尾）を見出しとして扱う。
    """
    doc_name = source_url.rsplit("/", 1)[-1].removesuffix(".md") if source_url else "document"

    sections: List[tuple[str, List[str]]] = [(doc_name, [])]
    in_fence = False
    for line in md_text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _MD_HEADING.match(line)
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)

    rows: List[KnowledgeRow] = []
    for heading, lines in sections:
        body = _normalize_markdown_body("\n".join(lines))
        if not body:
            continue
        rows.append(KnowledgeRow(
            text=f"{heading}: {body}",
            title=heading,
            source=source_url,
        ))
    return rows


def _normalize_markdown_body(body: str) -> str:
    """Markdown 記法の骨組みを落として平文へ寄せる（RAG 素材向け）。"""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)          # 画像
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # リンク → ラベル
    text = re.sub(r"[*_`>#|]", "", text)                      # 記号・引用・表罫線
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_url(url: str, timeout: int = 30) -> str:
    """raw Markdown 等のテキストを取得する。"""
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


# =============================================================================
# 共通: 行の分割・CSV 出力
# =============================================================================

def split_long_rows(rows: Iterable[KnowledgeRow],
                    max_chars: int = DEFAULT_MAX_CHARS) -> List[KnowledgeRow]:
    """max_chars を超える text を文境界（。）優先で分割する。"""
    out: List[KnowledgeRow] = []
    for row in rows:
        if len(row.text) <= max_chars:
            out.append(row)
            continue
        buf = ""
        part = 1
        for sentence in re.split(r"(?<=。)", row.text):
            if buf and len(buf) + len(sentence) > max_chars:
                out.append(KnowledgeRow(
                    text=buf, title=f"{row.title}（{part}）", source=row.source))
                buf, part = "", part + 1
            buf += sentence
        if buf:
            out.append(KnowledgeRow(
                text=buf, title=f"{row.title}（{part}）" if part > 1 else row.title,
                source=row.source))
    return out


def write_csv(rows: List[KnowledgeRow], output: Path) -> None:
    """text / title / source の 3 カラム CSV を出力する。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "title", "source"])
        for row in rows:
            writer.writerow([row.text, row.title, row.source])


# =============================================================================
# CLI
# =============================================================================

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="実運用ナレッジの取得・整形（gov: e-Gov 法令 / saas: OSS docs）"
    )
    sub = parser.add_subparsers(dest="source", required=True)

    p_egov = sub.add_parser("egov", help="e-Gov 法令 API から法令全文を取得（gov_laws 向け）")
    p_egov.add_argument("--law", action="append", default=None,
                        help=f"法令番号（複数指定可。既定: {len(DEFAULT_LAWS)} 法令）")
    p_egov.add_argument("--output", type=Path, default=Path("OUTPUT/gov_laws_real.csv"))
    p_egov.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    p_egov.add_argument("--timeout", type=int, default=30)

    p_docs = sub.add_parser("oss-docs", help="OSS 公式ドキュメント（raw Markdown）を取得（saas_docs 向け）")
    p_docs.add_argument("--url", action="append", default=None,
                        help=f"raw Markdown の URL（複数指定可。既定: FastAPI ja {len(DEFAULT_DOC_URLS)} ページ）")
    p_docs.add_argument("--output", type=Path, default=Path("OUTPUT/saas_docs_real.csv"))
    p_docs.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    p_docs.add_argument("--timeout", type=int, default=30)

    args = parser.parse_args(argv)
    rows: List[KnowledgeRow] = []

    if args.source == "egov":
        laws = args.law or DEFAULT_LAWS
        for law_num in laws:
            print(f"[egov] 取得中: {law_num} ...")
            try:
                xml_text = fetch_egov_law(law_num, timeout=args.timeout)
            except Exception as e:
                print(f"  ⚠ 取得失敗（スキップ）: {e}", file=sys.stderr)
                continue
            law_rows = parse_law_xml(
                xml_text, source_url=f"{EGOV_API_BASE}/lawdata/{quote(law_num)}")
            print(f"  → {len(law_rows)} 条を抽出")
            rows.extend(law_rows)
    else:  # oss-docs
        urls = args.url or DEFAULT_DOC_URLS
        for url in urls:
            print(f"[oss-docs] 取得中: {url} ...")
            try:
                md_text = fetch_url(url, timeout=args.timeout)
            except Exception as e:
                print(f"  ⚠ 取得失敗（スキップ）: {e}", file=sys.stderr)
                continue
            doc_rows = parse_markdown_sections(md_text, source_url=url)
            print(f"  → {len(doc_rows)} セクションを抽出")
            rows.extend(doc_rows)

    if not rows:
        print("有効なデータを取得できませんでした（ネットワーク・URL を確認してください）",
              file=sys.stderr)
        sys.exit(1)

    rows = split_long_rows(rows, max_chars=args.max_chars)
    write_csv(rows, args.output)
    print(f"\n✅ {len(rows)} 行を出力しました: {args.output}")
    print("次の手順（登録・ユーザー環境）:")
    print(f"  uv run python -m chunking.csv_text_to_chunks_text_csv "
          f"--input-file {args.output} --output output_chunked")
    stem = args.output.stem
    collection = "gov_laws_anthropic" if args.source == "egov" else "saas_docs_anthropic"
    print(f"  uv run python qa_qdrant/make_qa_register_qdrant.py "
          f"--input-file output_chunked/{stem}_chunks.csv "
          f"--collection {collection} --recreate")


if __name__ == "__main__":
    main()

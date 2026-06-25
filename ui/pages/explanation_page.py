#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
explanation_page.py - システム説明ページ
========================================
README.md の内容を表示（Mermaid図対応）
"""

import base64
import mimetypes
import re
from pathlib import Path

import streamlit as st

try:
    import streamlit_mermaid as stmd

    MERMAID_AVAILABLE = True
except ImportError:
    MERMAID_AVAILABLE = False


def get_image_base64(image_path_str):
    """
    Reads an image from the local path and returns a base64 data URL.
    Resolves paths relative to the project root.
    """
    # Calculate project root based on the location of this file (ui/pages/explanation_page.py)
    # root is ../../../ relative to this file
    project_root = Path(__file__).resolve().parent.parent.parent
    
    target_path = Path(image_path_str)
    
    # List of possible paths to check
    candidates = [
        project_root / target_path,
        project_root / "doc" / target_path.name,
        project_root / "assets" / target_path.name,
        project_root / "doc" / "assets" / target_path.name
    ]

    found_path = None
    for p in candidates:
        if p.exists() and p.is_file():
            found_path = p
            break

    if found_path:
        try:
            with open(found_path, "rb") as img_file:
                b64_data = base64.b64encode(img_file.read()).decode()
                mime_type, _ = mimetypes.guess_type(found_path)
                if not mime_type:
                    mime_type = "image/png"
                return f"data:{mime_type};base64,{b64_data}"
        except Exception:
            # print(f"Error reading image {found_path}: {e}")
            return None
    return None


def render_markdown_with_mermaid(content: str):
    """
    Mermaid コードブロックを含む Markdown を表示する。
    画像パスのBase64化、リンクのクエリパラメータ化を行う。
    """
    
    # 1. Image Replacement: Convert local images to Base64
    # Pattern: ![alt](path)
    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)
        # Skip external links and already base64 encoded images
        if image_path.startswith("http") or image_path.startswith("data:"):
            return match.group(0)
        
        b64_src = get_image_base64(image_path)
        if b64_src:
            return f"![{alt_text}]({b64_src})"
        return match.group(0)

    content = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_image, content)

    # 2. Link Replacement: Convert [text](file.md) to ?doc=file.md
    # This allows navigation within the Streamlit app
    def replace_link(match):
        text = match.group(1)
        link_path = match.group(2)
        if link_path.endswith(".md") and not link_path.startswith("http"):
            return f"[{text}](?doc={link_path})"
        return match.group(0)

    content = re.sub(r'\[(.*?)\]\((.*?\.md)\)', replace_link, content)


    # Mermaid コードブロックを検出するパターン
    mermaid_pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

    # コンテンツを分割
    last_end = 0
    for match in mermaid_pattern.finditer(content):
        # Mermaid の前のマークダウン部分を表示
        before_text = content[last_end : match.start()]
        if before_text.strip():
            st.markdown(before_text, unsafe_allow_html=True)

        # Mermaid 図を表示
        # ※ README 側の各 mermaid ブロックが規約スタイル(末尾の classDef default)を
        #   持つため、ここで classDef を注入すると二重定義となりパースエラーで
        #   空表示になる。注入はせず、コードをそのまま streamlit-mermaid に渡す。
        mermaid_code = match.group(1).strip()

        if MERMAID_AVAILABLE:
            try:
                stmd.st_mermaid(mermaid_code)
            except Exception as e:
                st.code(mermaid_code, language="mermaid")
                st.warning(f"Mermaid 図のレンダリングに失敗: {e}")
        else:
            st.code(mermaid_code, language="mermaid")
            st.info("Mermaid 図を表示するには: pip install streamlit-mermaid")

        last_end = match.end()

    # 残りのマークダウン部分を表示
    remaining_text = content[last_end:]
    if remaining_text.strip():
        st.markdown(remaining_text, unsafe_allow_html=True)


def split_readme_section(content: str, section: str) -> str:
    """README.md を「図表」と「ドキュメント」の2セクションに分割する。

    分割点は「## 目次」見出し。
    - "diagram":  先頭〜目次直前（…Version 表記・最終更新まで）
    - "document": 目次〜末尾
    - その他:     分割せず全体を返す
    見出しが見つからない場合は全体を返す（後方互換）。
    """
    match = re.search(r'(?m)^##\s*目次\s*$', content)
    if not match:
        return content
    if section == "diagram":
        return content[: match.start()].rstrip() + "\n"
    if section == "document":
        return content[match.start():]
    return content


def show_system_explanation_page(section: str = "all"):
    """システム説明ページ - README.md または指定されたドキュメントを表示

    Args:
        section: README.md の表示範囲を指定する。
            "diagram"  … システム説明（図表）: 先頭〜目次直前
            "document" … システム説明（ドキュメント）: 目次〜末尾
            "all"      … 全体（既定・後方互換）
    """

    # Check for query parameter 'doc'
    query_params = st.query_params
    target_doc = query_params.get("doc", "README.md")

    # Title logic
    if target_doc == "README.md":
        section_titles = {
            "diagram": "📖 システム説明（図表）",
            "document": "📖 システム説明（ドキュメント）",
            "all": "📖 システム説明",
        }
        st.title(section_titles.get(section, "📖 システム説明"))
        st.caption("プロジェクト README.md")
    else:
        st.title(f"📖 {target_doc}")
        if st.button("← README.md に戻る"):
            st.query_params.clear()
            st.rerun()

    st.markdown("---")

    # Resolve file path
    project_root = Path(__file__).resolve().parent.parent.parent
    
    # Handle simple relative paths
    file_path = project_root / target_doc
    
    # If not found directly, try finding it in doc/ folder if it looks like a doc
    if not file_path.exists() and not str(target_doc).startswith("doc/"):
         alt_path = project_root / "doc" / target_doc
         if alt_path.exists():
             file_path = alt_path

    if file_path.exists() and file_path.suffix == ".md":
        readme_content = file_path.read_text(encoding="utf-8")
        # README.md のみ section 指定で分割表示（他ドキュメントは全体表示）
        if target_doc == "README.md" and section in ("diagram", "document"):
            readme_content = split_readme_section(readme_content, section)
        render_markdown_with_mermaid(readme_content)
    else:
        st.error(f"ドキュメントが見つかりません: {target_doc}")
        if target_doc != "README.md":
             if st.button("トップに戻る"):
                st.query_params.clear()
                st.rerun()
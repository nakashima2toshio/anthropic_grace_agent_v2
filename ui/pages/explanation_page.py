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
import streamlit.components.v1 as components

# Mermaid 図の表示枠の高さ(px)。図ごとに実寸が大きく異なる（数百〜数千px）ため、
# 固定枠＋pan/zoom で枠内に全体を収める。
_MERMAID_BOX_HEIGHT = 560


def render_mermaid(code: str) -> None:
    """Mermaid 図を CDN の mermaid.js v11 で描画する（st.components.v1.html）。

    外部 Python パッケージ streamlit-mermaid は mermaid v10.2.4 で更新が止まり、
    新しい構文（例: `class ... default`）が構文エラーになる。そこで CDN から
    最新の mermaid を読み込んで描画する。図ごとにレンダリング実寸が大きく異なり
    （数百〜数千px）、固定高さでは必ず切れるため、svg-pan-zoom で固定枠内を
    パン/ズーム可能にし、どの大きさの図も枠内で全体を閲覧できるようにする。
    """
    html = (
        '<div id="mbox" style="height:' + str(_MERMAID_BOX_HEIGHT) + 'px;'
        'background:#000;border:1px solid #333;border-radius:6px;overflow:hidden;">\n'
        '<div class="mermaid" style="height:100%;">\n'
        + code
        + "\n</div>\n</div>\n"
        '<script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>\n'
        '<script type="module">\n'
        "  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';\n"
        "  mermaid.initialize({ startOnLoad: false, securityLevel: 'loose', theme: 'base' });\n"
        "  const box = document.getElementById('mbox');\n"
        "  try {\n"
        "    await mermaid.run({ querySelector: '#mbox .mermaid' });\n"
        "    const svg = box.querySelector('svg');\n"
        "    if (svg && window.svgPanZoom) {\n"
        "      svg.setAttribute('width', '100%');\n"
        "      svg.setAttribute('height', '100%');\n"
        "      svg.style.maxWidth = 'none';\n"
        "      window.svgPanZoom(svg, { controlIconsEnabled: true, fit: true, center: true,\n"
        "        mouseWheelZoomEnabled: false, minZoom: 0.2, maxZoom: 12 });\n"
        "    }\n"
        "  } catch (err) {\n"
        '    box.innerHTML = \'<pre style="color:#fff;white-space:pre-wrap;padding:8px;">\'\n'
        "      + String(err && err.message ? err.message : err) + '</pre>';\n"
        "  }\n"
        "</script>\n"
    )
    components.html(html, height=_MERMAID_BOX_HEIGHT + 16)


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

        try:
            render_mermaid(mermaid_code)
        except Exception as e:
            st.code(mermaid_code, language="mermaid")
            st.warning(f"Mermaid 図のレンダリングに失敗: {e}")

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
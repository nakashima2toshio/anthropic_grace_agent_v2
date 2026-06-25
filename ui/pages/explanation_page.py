#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
explanation_page.py - システム説明ページ
========================================
README.md の内容を表示（Mermaid図対応）
"""

import base64
import html as html_lib
import mimetypes
import re
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Mermaid.js（CDN）。ノード背景=黒・文字=白の黒テーマで描画する。
_MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"

# 黒背景・白文字テーマ（プロジェクト規約: ノード fill:#000 / color:#fff、
# サブグラフ fill:#1a1a1a）。README 側の classDef があればそちらが優先される。
_MERMAID_INIT = """{
  startOnLoad: false,
  securityLevel: 'loose',
  theme: 'base',
  themeVariables: {
    background: '#000000',
    primaryColor: '#000000',
    primaryTextColor: '#ffffff',
    primaryBorderColor: '#ffffff',
    secondaryColor: '#1a1a1a',
    tertiaryColor: '#1a1a1a',
    mainBkg: '#000000',
    secondBkg: '#1a1a1a',
    lineColor: '#ffffff',
    textColor: '#ffffff',
    nodeTextColor: '#ffffff',
    clusterBkg: '#1a1a1a',
    clusterBorder: '#ffffff',
    edgeLabelBackground: '#1a1a1a',
    actorBkg: '#000000',
    actorBorder: '#ffffff',
    actorTextColor: '#ffffff',
    actorLineColor: '#ffffff',
    signalColor: '#ffffff',
    signalTextColor: '#ffffff',
    labelBoxBkgColor: '#1a1a1a',
    labelBoxBorderColor: '#ffffff',
    labelTextColor: '#ffffff',
    loopTextColor: '#ffffff',
    noteBkgColor: '#1a1a1a',
    noteBorderColor: '#ffffff',
    noteTextColor: '#ffffff',
    activationBkgColor: '#1a1a1a',
    activationBorderColor: '#ffffff',
    sequenceNumberColor: '#000000',
    fontFamily: 'sans-serif',
    fontSize: '15px'
  },
  flowchart: { htmlLabels: true, useMaxWidth: true },
  sequence: { useMaxWidth: true }
}"""


def _estimate_mermaid_height(code: str) -> int:
    """Mermaid コードから描画iframeの概算高さ(px)を見積もる。"""
    lines = [ln for ln in code.splitlines() if ln.strip()]
    head = code.lstrip()[:40]
    if head.startswith("sequenceDiagram"):
        msgs = sum(1 for ln in lines if "->>" in ln or "-->>" in ln or "->" in ln)
        return max(320, min(1200, 180 + msgs * 46))
    edges = sum(1 for ln in lines if "-->" in ln or "->>" in ln or "---" in ln or "-.->" in ln)
    subgraphs = sum(1 for ln in lines if ln.strip().startswith("subgraph"))
    is_lr = bool(re.match(r"(flowchart|graph)\s+(LR|RL)", head))
    per_edge = 26 if is_lr else 40
    base = 240 + edges * per_edge + subgraphs * 70
    return max(320, min(1700, base))


def _render_mermaid(code: str) -> None:
    """Mermaid コードを mermaid.js で図として描画する（黒背景・白文字）。

    開閉部品（expander）は使わず常に表示する。ブラウザが <br/> 等を
    実DOM化しないよう HTML エスケープし、textContent として mermaid に渡す。
    """
    # init ディレクティブ（%%{...}%%）は色テーマ指定のみのため除去し、
    # 全図に統一の黒テーマ(_MERMAID_INIT)を適用する（noteBkg 等の誤指定対策）。
    code = re.sub(r"%%\{.*?\}%%\s*", "", code, flags=re.DOTALL).strip()
    height = _estimate_mermaid_height(code)
    escaped = html_lib.escape(code)
    html = (
        '<div id="mmwrap" style="background:#000000;padding:6px 4px;">'
        f'<pre class="mermaid" style="background:#000000;color:#ffffff;'
        f'margin:0;border:none;white-space:pre;text-align:center;">{escaped}</pre>'
        "</div>"
        f'<script src="{_MERMAID_CDN}"></script>'
        "<script>"
        f"mermaid.initialize({_MERMAID_INIT});"
        # 描画後に SVG の実寸を測り、iframe 本体だけでなく Streamlit が
        # 確保する専用ラッパー(stIFrame)も同じ高さに合わせる。これにより
        # 「枠が大きすぎて黒い空白が残る」「枠からはみ出して次図に重なる」を解消。
        # ページ全体の共有ブロックには触れない（高さを壊さない）。
        "function _fit(){"
        "  var s=document.querySelector('.mermaid svg');"
        "  if(!s){return;}"
        "  var h=Math.ceil(s.getBoundingClientRect().height)+8;"
        "  if(h<40){return;}"
        "  document.documentElement.style.height=h+'px';"
        "  document.body.style.margin='0';document.body.style.height=h+'px';"
        "  try{"
        "    var f=window.frameElement;"
        "    if(f){"
        "      f.style.height=h+'px';f.setAttribute('height',h);"
        "      var p=f.parentElement;"
        "      if(p&&p.getAttribute&&p.getAttribute('data-testid')==='stIFrame'){"
        "        p.style.height=h+'px';"
        "      }"
        "    }"
        "  }catch(e){}"
        "}"
        "mermaid.run({querySelector:'.mermaid'}).then(function(){"
        "  _fit();setTimeout(_fit,120);setTimeout(_fit,400);"
        "  try{var o=new ResizeObserver(_fit);"
        "      o.observe(document.querySelector('.mermaid svg'));}catch(e){}"
        "}).catch(function(e){var pr=document.createElement('pre');"
        "  pr.style.color='#f88';pr.textContent=String(e);"
        "  document.body.appendChild(pr);});"
        "</script>"
    )
    components.html(html, height=height, scrolling=True)


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

        # Mermaid 図を描画する
        mermaid_code = match.group(1).strip()

        # 開閉部品（expander）を使わず、常に表示される図として描画する。
        # ※ 以前は mermaid コード先頭へ classDef を注入していたが、README の
        #   各 mermaid ブロック末尾の `classDef default ...`（規約スタイル）と
        #   二重定義になり、パースエラーで空表示になっていた。注入は行わない。
        _render_mermaid(mermaid_code)

        last_end = match.end()

    # 残りのマークダウン部分を表示
    remaining_text = content[last_end:]
    if remaining_text.strip():
        st.markdown(remaining_text, unsafe_allow_html=True)


def show_system_explanation_page():
    """システム説明ページ - README.md または指定されたドキュメントを表示"""
    
    # Check for query parameter 'doc'
    query_params = st.query_params
    target_doc = query_params.get("doc", "README.md")
    
    # Title logic
    if target_doc == "README.md":
        st.title("📖 システム説明")
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
        render_markdown_with_mermaid(readme_content)
    else:
        st.error(f"ドキュメントが見つかりません: {target_doc}")
        if target_doc != "README.md":
             if st.button("トップに戻る"):
                st.query_params.clear()
                st.rerun()
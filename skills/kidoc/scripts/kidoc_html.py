#!/usr/bin/env python3
"""HTML generation from kidoc markdown scaffolds.

Converts markdown to a self-contained HTML file with embedded CSS.
SVG images are inlined directly (no rasterization needed). This is the
lightest output format — zero dependencies beyond Python stdlib.

Usage (called by kidoc_generate.py, or directly):
    python3 kidoc_html.py --input reports/HDD.md --output reports/output/HDD.html
                          --config '{"project": {"name": "..."}}'
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kidoc_md_parser import parse_markdown


# ======================================================================
# CSS
# ======================================================================

CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 'Helvetica Neue', Arial, sans-serif;
    max-width: 900px;
    margin: 40px auto;
    padding: 0 20px;
    color: #1a1a1a;
    line-height: 1.6;
    font-size: 14px;
}
h1 { font-size: 24px; border-bottom: 2px solid #2060c0; padding-bottom: 8px; }
h2 { font-size: 20px; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px; margin-top: 32px; }
h3 { font-size: 16px; margin-top: 24px; }
h4, h5, h6 { font-size: 14px; margin-top: 16px; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
    font-size: 13px;
}
th, td {
    border: 1px solid #d0d0d0;
    padding: 6px 10px;
    text-align: left;
}
th { background: #e8e8f0; font-weight: 600; }
tr:nth-child(even) { background: #fafafa; }
img, svg { max-width: 100%; height: auto; margin: 16px 0; display: block; }
code {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    background: #f5f5f5;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 13px;
    color: #c04000;
}
pre {
    background: #f5f5f5;
    padding: 12px 16px;
    border-radius: 4px;
    overflow-x: auto;
    border: 1px solid #e0e0e0;
}
pre code { background: none; padding: 0; color: #303030; }
blockquote {
    border-left: 3px solid #2060c0;
    margin: 16px 0;
    padding: 8px 16px;
    color: #606060;
    font-style: italic;
}
.caption { text-align: center; font-size: 12px; color: #606060; font-style: italic; }
.header { color: #808080; font-size: 11px; margin-bottom: 24px; }
.footer { color: #808080; font-size: 11px; margin-top: 40px; border-top: 1px solid #e0e0e0; padding-top: 8px; }
hr { border: none; border-top: 1px solid #e0e0e0; margin: 24px 0; }
ul, ol { padding-left: 24px; }
.toc { background: #f8f8fc; border: 1px solid #e0e0e8; border-radius: 6px;
       padding: 12px 20px; margin: 16px 0 24px; }
.toc h3 { margin: 0 0 8px; font-size: 14px; color: #404060; }
.toc ul { list-style: none; padding: 0; margin: 0; }
.toc li { padding: 2px 0; }
.toc a { color: #2060c0; text-decoration: none; font-size: 13px; }
.toc a:hover { text-decoration: underline; }
@media print {
    .toc { break-after: page; }
    h2 { break-before: page; }
    table { break-inside: avoid; }
    .header, .footer { position: fixed; }
    .header { top: 0; }
    .footer { bottom: 0; }
}
"""


# ======================================================================
# Element to HTML conversion
# ======================================================================

def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _runs_to_html(runs: list[dict]) -> str:
    """Convert inline runs to HTML."""
    parts = []
    for r in runs:
        text = _escape(r['text'])
        if r.get('code'):
            parts.append(f'<code>{text}</code>')
        elif r.get('bold') and r.get('italic'):
            parts.append(f'<strong><em>{text}</em></strong>')
        elif r.get('bold'):
            parts.append(f'<strong>{text}</strong>')
        elif r.get('italic'):
            parts.append(f'<em>{text}</em>')
        elif r.get('link'):
            parts.append(f'<a href="{_escape(r["link"])}">{text}</a>')
        else:
            parts.append(text)
    return ''.join(parts)


def _element_to_html(elem: dict, base_dir: str) -> str:
    """Convert a parsed markdown element to HTML."""
    etype = elem['type']

    if etype == 'heading':
        level = elem['level']
        anchor = elem.get('_anchor', '')
        anchor_attr = f' id="{anchor}"' if anchor else ''
        return f'<h{level}{anchor_attr}>{_escape(elem["text"])}</h{level}>'

    elif etype == 'paragraph':
        return f'<p>{_runs_to_html(elem["runs"])}</p>'

    elif etype == 'image':
        return _build_image_html(elem, base_dir)

    elif etype == 'table':
        return _build_table_html(elem)

    elif etype == 'code_block':
        lang = f' class="language-{elem["language"]}"' if elem.get('language') else ''
        return f'<pre><code{lang}>{_escape(elem["code"])}</code></pre>'

    elif etype == 'hr':
        return '<hr>'

    elif etype == 'bullet_list':
        items = ''.join(f'<li>{_runs_to_html(runs)}</li>' for runs in elem['items'])
        return f'<ul>{items}</ul>'

    elif etype == 'numbered_list':
        items = ''.join(f'<li>{_runs_to_html(runs)}</li>' for runs in elem['items'])
        return f'<ol>{items}</ol>'

    elif etype == 'blockquote':
        return f'<blockquote><p>{_runs_to_html(elem["runs"])}</p></blockquote>'

    return ''


def _build_image_html(elem: dict, base_dir: str) -> str:
    """Build image HTML — SVGs inlined, rasters base64-encoded."""
    path = elem['path']
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)

    if not os.path.isfile(path):
        return f'<p class="caption"><em>[Image not found: {_escape(elem["path"])}]</em></p>'

    alt = _escape(elem.get('alt', ''))
    html = ''

    if path.lower().endswith('.svg'):
        # Inline SVG directly — vector quality, no rasterization
        with open(path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        # Strip XML declaration if present
        if svg_content.startswith('<?xml'):
            svg_content = svg_content[svg_content.index('?>') + 2:].strip()
        html = f'<div>{svg_content}</div>'
    else:
        # Base64-encode raster images
        ext = os.path.splitext(path)[1].lower()
        mime = {'png': 'image/png', 'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg', 'gif': 'image/gif'}.get(ext.lstrip('.'), 'image/png')
        with open(path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        html = f'<img src="data:{mime};base64,{b64}" alt="{alt}">'

    if alt:
        html += f'\n<p class="caption">{alt}</p>'

    return html


def _build_table_html(elem: dict) -> str:
    """Build HTML table."""
    headers = elem['headers']
    rows = elem['rows']
    alignments = elem.get('alignments', ['left'] * len(headers))

    html = '<table>\n<thead><tr>'
    for i, h in enumerate(headers):
        align = f' style="text-align:{alignments[i]}"' if i < len(alignments) else ''
        html += f'<th{align}>{_escape(h)}</th>'
    html += '</tr></thead>\n<tbody>'

    for row in rows:
        html += '<tr>'
        for i in range(len(headers)):
            cell = row[i] if i < len(row) else ''
            align = f' style="text-align:{alignments[i]}"' if i < len(alignments) else ''
            html += f'<td{align}>{_escape(cell)}</td>'
        html += '</tr>'

    html += '</tbody>\n</table>'
    return html


# ======================================================================
# Main generation
# ======================================================================

def generate_html(markdown_path: str, output_path: str, config: dict) -> str:
    """Convert markdown to self-contained HTML.  Returns the output path."""
    with open(markdown_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    elements = parse_markdown(md_text)
    base_dir = os.path.dirname(os.path.abspath(markdown_path))

    project = config.get('project', {})
    branding = config.get('reports', {}).get('branding', {})
    classification = config.get('reports', {}).get('classification', '')

    # Build HTML
    body_parts = []

    # Header
    header_left = branding.get('header_left', project.get('company', ''))
    header_right = branding.get('header_right', '')
    for key, val in project.items():
        header_left = header_left.replace('{' + key + '}', str(val))
        header_right = header_right.replace('{' + key + '}', str(val))
    if header_left or header_right:
        body_parts.append(
            f'<div class="header">{_escape(header_left)}'
            f'<span style="float:right">{_escape(header_right)}</span></div>')

    # Build table of contents from headings
    toc_entries = []
    heading_id = 0
    for elem in elements:
        if elem['type'] == 'heading' and elem['level'] in (1, 2, 3):
            heading_id += 1
            anchor = f'section-{heading_id}'
            toc_entries.append((elem['level'], elem['text'], anchor))
            elem['_anchor'] = anchor  # stash for rendering

    if len(toc_entries) > 2:
        toc_html = '<nav class="toc"><h3>Contents</h3><ul>'
        for level, text, anchor in toc_entries:
            indent = 'style="margin-left:16px"' if level == 3 else ''
            toc_html += f'<li {indent}><a href="#{anchor}">{_escape(text)}</a></li>'
        toc_html += '</ul></nav>'
        body_parts.append(toc_html)

    # Content
    for elem in elements:
        html = _element_to_html(elem, base_dir)
        if html:
            body_parts.append(html)

    # Footer
    if classification:
        body_parts.append(f'<div class="footer">{_escape(classification)}</div>')

    title = project.get('name', 'Engineering Document')
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
{chr(10).join(body_parts)}
</body>
</html>"""

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(page)

    return output_path


def main():
    parser = argparse.ArgumentParser(description='Generate HTML from markdown')
    parser.add_argument('--input', '-i', required=True,
                        help='Input markdown file')
    parser.add_argument('--output', '-o', required=True,
                        help='Output HTML file')
    parser.add_argument('--config', '-c', default='{}',
                        help='JSON config string or path to config file')
    args = parser.parse_args()

    if os.path.isfile(args.config):
        with open(args.config) as f:
            config = json.load(f)
    else:
        config = json.loads(args.config)

    output = generate_html(args.input, args.output, config)
    print(output, file=sys.stderr)


if __name__ == '__main__':
    main()

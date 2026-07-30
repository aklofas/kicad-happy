#!/usr/bin/env python3
"""ODT (OpenDocument Text) generation from kidoc markdown scaffolds.

Converts markdown to ODT using odfpy.  SVGs are rasterized to PNG via
svglib + rl-renderPM before embedding.  Runs inside reports/.venv/.

Usage (called by kidoc_generate.py, not directly):
    python3 kidoc_odt.py --input reports/HDD.md --output reports/output/HDD.odt
                         --config '{"project": {"name": "..."}}'
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from odf.opendocument import OpenDocumentText
from odf import text as odftext
from odf import draw as odfdraw
from odf import table as odftable
from odf.style import (Style, TextProperties, ParagraphProperties,
                        TableProperties, TableColumnProperties,
                        TableCellProperties, GraphicProperties, FontFace)
from odf.text import P, H, List, ListItem, ListLevelStyleBullet, ListStyle
from odf.table import Table, TableColumn, TableRow, TableCell

# Add kidoc scripts to path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kidoc_md_parser import parse_markdown
from kidoc_raster import svg_to_png as _svg_to_png, has_svg_render, get_dpi


# ======================================================================
# Style definitions
# ======================================================================

def _create_styles(doc):
    """Create document styles and return a style lookup dict."""
    styles = {}

    # Title
    s = Style(name='KidocTitle', family='paragraph')
    s.addElement(TextProperties(fontsize='20pt', fontweight='bold',
                                color='#202020'))
    s.addElement(ParagraphProperties(marginbottom='0.3cm'))
    doc.styles.addElement(s)
    styles['title'] = s

    # Headings
    for level, size in [(1, '16pt'), (2, '13pt'), (3, '11pt'), (4, '10pt')]:
        s = Style(name=f'KidocH{level}', family='paragraph')
        s.addElement(TextProperties(fontsize=size, fontweight='bold',
                                    color='#202040'))
        s.addElement(ParagraphProperties(margintop='0.4cm',
                                         marginbottom='0.2cm'))
        doc.styles.addElement(s)
        styles[f'h{level}'] = s

    # Body
    s = Style(name='KidocBody', family='paragraph')
    s.addElement(TextProperties(fontsize='9pt', color='#000000'))
    s.addElement(ParagraphProperties(marginbottom='0.15cm'))
    doc.styles.addElement(s)
    styles['body'] = s

    # Code
    s = Style(name='KidocCode', family='paragraph')
    s.addElement(TextProperties(fontsize='8pt', fontfamily='Courier New',
                                color='#303030'))
    s.addElement(ParagraphProperties(marginleft='0.5cm',
                                      marginbottom='0.2cm',
                                      backgroundcolor='#f5f5f5'))
    doc.styles.addElement(s)
    styles['code'] = s

    # Blockquote
    s = Style(name='KidocBlockquote', family='paragraph')
    s.addElement(TextProperties(fontsize='9pt', fontstyle='italic',
                                color='#606060'))
    s.addElement(ParagraphProperties(marginleft='1cm',
                                      marginbottom='0.2cm'))
    doc.styles.addElement(s)
    styles['blockquote'] = s

    # Caption
    s = Style(name='KidocCaption', family='paragraph')
    s.addElement(TextProperties(fontsize='8pt', fontstyle='italic',
                                color='#606060'))
    s.addElement(ParagraphProperties(textalign='center',
                                      marginbottom='0.3cm'))
    doc.styles.addElement(s)
    styles['caption'] = s

    # Bold inline
    s = Style(name='KidocBold', family='text')
    s.addElement(TextProperties(fontweight='bold'))
    doc.styles.addElement(s)
    styles['bold'] = s

    # Italic inline
    s = Style(name='KidocItalic', family='text')
    s.addElement(TextProperties(fontstyle='italic'))
    doc.styles.addElement(s)
    styles['italic'] = s

    # Code inline
    s = Style(name='KidocCodeInline', family='text')
    s.addElement(TextProperties(fontfamily='Courier New', fontsize='8pt',
                                color='#c04000'))
    doc.styles.addElement(s)
    styles['code_inline'] = s

    # Table cell
    s = Style(name='KidocTableCell', family='table-cell')
    s.addElement(TableCellProperties(padding='0.1cm',
                                      border='0.5pt solid #c0c0c0'))
    doc.automaticstyles.addElement(s)
    styles['table_cell'] = s

    # Table header cell
    s = Style(name='KidocTableHeaderCell', family='table-cell')
    s.addElement(TableCellProperties(padding='0.1cm',
                                      border='0.5pt solid #c0c0c0',
                                      backgroundcolor='#e8e8f0'))
    doc.automaticstyles.addElement(s)
    styles['table_header_cell'] = s

    # Table
    s = Style(name='KidocTable', family='table')
    s.addElement(TableProperties(width='17cm', align='margins'))
    doc.automaticstyles.addElement(s)
    styles['table'] = s

    # Frame
    s = Style(name='KidocFrame', family='graphic')
    s.addElement(GraphicProperties(horizontalpos='center',
                                    horizontalrel='paragraph'))
    doc.automaticstyles.addElement(s)
    styles['frame'] = s

    return styles


# ======================================================================
# Inline formatting
# ======================================================================

def _add_runs_to_paragraph(p, runs: list[dict], styles: dict) -> None:
    """Add formatted inline runs to an ODF paragraph."""
    for r in runs:
        text_content = r['text']
        if r.get('bold') and r.get('italic'):
            span = odftext.Span(stylename=styles['bold'], text='')
            inner = odftext.Span(stylename=styles['italic'], text=text_content)
            span.addElement(inner)
            p.addElement(span)
        elif r.get('bold'):
            span = odftext.Span(stylename=styles['bold'], text=text_content)
            p.addElement(span)
        elif r.get('italic'):
            span = odftext.Span(stylename=styles['italic'], text=text_content)
            p.addElement(span)
        elif r.get('code'):
            span = odftext.Span(stylename=styles['code_inline'], text=text_content)
            p.addElement(span)
        else:
            span = odftext.Span(text=text_content)
            p.addElement(span)


# ======================================================================
# Element conversion
# ======================================================================

def _add_element(doc, elem: dict, base_dir: str, styles: dict,
                 dpi: int, temp_files: list) -> None:
    """Add a parsed markdown element to the ODT document."""
    etype = elem['type']

    if etype == 'heading':
        level = min(elem['level'], 4)
        style_name = 'title' if level == 1 else f'h{level}'
        h = H(outlinelevel=level, stylename=styles.get(style_name, styles['body']),
              text=elem['text'])
        doc.text.addElement(h)

    elif etype == 'paragraph':
        p = P(stylename=styles['body'])
        _add_runs_to_paragraph(p, elem['runs'], styles)
        doc.text.addElement(p)

    elif etype == 'image':
        _add_image(doc, elem, base_dir, styles, dpi, temp_files)

    elif etype == 'table':
        _add_table(doc, elem, styles)

    elif etype == 'code_block':
        for line in elem['code'].split('\n'):
            p = P(stylename=styles['code'], text=line)
            doc.text.addElement(p)

    elif etype == 'hr':
        p = P(stylename=styles['body'], text='—' * 40)
        doc.text.addElement(p)

    elif etype == 'bullet_list':
        for item_runs in elem['items']:
            p = P(stylename=styles['body'], text='• ')
            _add_runs_to_paragraph(p, item_runs, styles)
            doc.text.addElement(p)

    elif etype == 'numbered_list':
        for i, item_runs in enumerate(elem['items']):
            p = P(stylename=styles['body'], text=f'{i+1}. ')
            _add_runs_to_paragraph(p, item_runs, styles)
            doc.text.addElement(p)

    elif etype == 'blockquote':
        p = P(stylename=styles['blockquote'])
        _add_runs_to_paragraph(p, elem['runs'], styles)
        doc.text.addElement(p)


def _add_image(doc, elem: dict, base_dir: str, styles: dict,
               dpi: int, temp_files: list) -> None:
    """Add an image to the ODT. SVGs are rasterized first."""
    path = elem['path']
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)

    if not os.path.isfile(path):
        p = P(stylename=styles['caption'], text=f'[Image not found: {elem["path"]}]')
        doc.text.addElement(p)
        return

    img_path = path
    if path.lower().endswith('.svg'):
        png_path = _svg_to_png(path, dpi=dpi)
        if png_path:
            img_path = png_path
            temp_files.append(png_path)
        else:
            p = P(stylename=styles['caption'],
                  text=f'[SVG rendering unavailable: {elem["path"]}]')
            doc.text.addElement(p)
            return

    try:
        # Read image to determine size
        from PIL import Image as PILImage
        with PILImage.open(img_path) as img:
            img_w, img_h = img.size
        # Scale to fit ~16cm width
        max_w_cm = 16.0
        w_cm = min(max_w_cm, img_w * 2.54 / dpi)
        h_cm = w_cm * img_h / img_w

        # Create frame + image
        p = P(stylename=styles['body'])
        frame = odfdraw.Frame(stylename=styles['frame'],
                               width=f'{w_cm:.1f}cm', height=f'{h_cm:.1f}cm')
        href = doc.addPicture(img_path)
        img_elem = odfdraw.Image(href=href)
        frame.addElement(img_elem)
        p.addElement(frame)
        doc.text.addElement(p)
    except Exception:
        p = P(stylename=styles['caption'],
              text=f'[Failed to embed image: {elem["path"]}]')
        doc.text.addElement(p)

    # Caption
    if elem.get('alt'):
        p = P(stylename=styles['caption'], text=elem['alt'])
        doc.text.addElement(p)


def _add_table(doc, elem: dict, styles: dict) -> None:
    """Add a table to the ODT."""
    headers = elem['headers']
    rows = elem['rows']
    n_cols = len(headers)

    t = Table(stylename=styles['table'])

    # Columns
    col_style = Style(name='KidocTableCol', family='table-column')
    col_style.addElement(TableColumnProperties(
        columnwidth=f'{17.0/n_cols:.1f}cm'))
    doc.automaticstyles.addElement(col_style)
    for _ in range(n_cols):
        t.addElement(TableColumn(stylename=col_style))

    # Header row
    tr = TableRow()
    for h in headers:
        tc = TableCell(stylename=styles['table_header_cell'])
        p = P(text=h)
        # Bold header text
        tc.addElement(p)
        tr.addElement(tc)
    t.addElement(tr)

    # Data rows
    for row in rows:
        tr = TableRow()
        for i in range(n_cols):
            cell_text = row[i] if i < len(row) else ''
            tc = TableCell(stylename=styles['table_cell'])
            tc.addElement(P(text=cell_text))
            tr.addElement(tc)
        t.addElement(tr)

    doc.text.addElement(t)
    # Spacer
    doc.text.addElement(P(stylename=styles['body'], text=''))


# ======================================================================
# Main generation
# ======================================================================

def generate_odt(markdown_path: str, output_path: str, config: dict) -> str:
    """Convert markdown to ODT. Returns the output path."""
    with open(markdown_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    elements = parse_markdown(md_text)
    base_dir = os.path.dirname(os.path.abspath(markdown_path))
    dpi = config.get('reports', {}).get('rendering', {}).get('schematic_dpi', 300)

    doc = OpenDocumentText()
    styles = _create_styles(doc)

    temp_files: list[str] = []

    try:
        for elem in elements:
            _add_element(doc, elem, base_dir, styles, dpi, temp_files)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)
        doc.save(output_path)
    finally:
        for tf in temp_files:
            try:
                os.unlink(tf)
            except OSError:
                pass

    return output_path


def main():
    parser = argparse.ArgumentParser(description='Generate ODT from markdown')
    parser.add_argument('--input', '-i', required=True,
                        help='Input markdown file')
    parser.add_argument('--output', '-o', required=True,
                        help='Output ODT file')
    parser.add_argument('--config', '-c', default='{}',
                        help='JSON config string or path to config file')
    args = parser.parse_args()

    if os.path.isfile(args.config):
        with open(args.config) as f:
            config = json.load(f)
    else:
        config = json.loads(args.config)

    output = generate_odt(args.input, args.output, config)
    print(output, file=sys.stderr)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Publication-quality PDF generation from kidoc markdown scaffolds.

Produces professional engineering documents with dark navy headers,
styled cover pages, table of contents, formatted tables with alternating
rows, and vector SVG diagrams.

Styling modeled after B&W generate_pdfs.py with engineering-document
terminology and kidoc markdown parser integration.

Usage (called by kidoc_generate.py, not directly):
    python3 kidoc_pdf.py --input reports/HDD.md --output reports/output/HDD.pdf
                         --config '{"project": {"name": "..."}}'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

# These imports require the venv to be active
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle,
    PageBreak, Preformatted, HRFlowable, KeepTogether, Flowable,
)
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate, Frame, NextPageTemplate

# Add kidoc scripts to path for the markdown parser and SVG embed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kidoc_md_parser import parse_markdown, parse_inline
from figures.lib.svg_embed import svg_to_flowable


# ======================================================================
# Brand colors (engineering document palette)
# ======================================================================

DARK_NAVY = HexColor("#1a1a2e")
ACCENT_BLUE = HexColor("#0f4c75")
ACCENT_TEAL = HexColor("#1b6ca8")
LIGHT_BLUE = HexColor("#e8f4fc")
DARK_TEXT = HexColor("#2c2c2c")
MEDIUM_TEXT = HexColor("#555555")
LIGHT_TEXT = HexColor("#999999")
TABLE_HEADER_BG = HexColor("#1a3a5c")
TABLE_ALT_ROW = HexColor("#f4f8fb")
RULE_COLOR = HexColor("#d0d8e0")
CALLOUT_BG = HexColor("#edf5fb")
CALLOUT_BORDER = HexColor("#1b6ca8")
WHITE = white

PAGE_SIZES = {
    'letter': letter,
    'a4': A4,
}


def _resolve_branding(config: dict) -> dict:
    """Resolve branding settings from config, with defaults."""
    branding = config.get('reports', {}).get('branding', {})
    colors = branding.get('colors', {})

    return {
        'dark_navy': HexColor(colors.get('primary', '#1a1a2e')),
        'accent_blue': HexColor(colors.get('accent', '#0f4c75')),
        'accent_teal': HexColor(colors.get('highlight', '#1b6ca8')),
        'table_header_bg': HexColor(colors.get('table_header', '#1a3a5c')),
        'table_alt_row': HexColor(colors.get('table_alt_row', '#f4f8fb')),
        'callout_bg': HexColor(colors.get('callout_bg', '#edf5fb')),
        'callout_border': HexColor(colors.get('callout_border', '#1b6ca8')),
        'company_name': branding.get('company_name',
                                      config.get('project', {}).get('company', '')),
        'logo_path': branding.get('logo', ''),
        'header_left': branding.get('header_left', '{company}'),
        'header_right': branding.get('header_right', '{number} Rev {rev}'),
    }


# ======================================================================
# Custom flowables
# ======================================================================

class CalloutBox(Flowable):
    """A colored box with left border accent for callouts/blockquotes."""

    def __init__(self, text, width, bg_color, border_color, style,
                 border_width=3):
        Flowable.__init__(self)
        self.text = text
        self.box_width = width
        self.bg_color = bg_color
        self.border_color = border_color
        self.style = style
        self.border_width = border_width
        self._para = Paragraph(text, style)
        self._para.wrap(width - 24, 10000)
        self.height = self._para.height + 16

    def wrap(self, availWidth, availHeight):
        self._para.wrap(self.box_width - 24, availHeight)
        self.height = self._para.height + 16
        self.width = self.box_width
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.bg_color)
        c.roundRect(0, 0, self.box_width, self.height, 3, fill=1, stroke=0)
        c.setFillColor(self.border_color)
        c.rect(0, 0, self.border_width, self.height, fill=1, stroke=0)
        self._para.drawOn(c, 12 + self.border_width, 8)
        c.restoreState()


# ======================================================================
# Styles
# ======================================================================

def create_styles(brand: dict | None = None):
    """Build the complete style set for engineering documents."""
    b = brand or {}
    dark_navy = b.get('dark_navy', DARK_NAVY)
    accent_blue = b.get('accent_blue', ACCENT_BLUE)
    accent_teal = b.get('accent_teal', ACCENT_TEAL)

    s = {}
    s['h1'] = ParagraphStyle(
        'H1', fontName='Helvetica-Bold', fontSize=16, leading=20,
        textColor=dark_navy, spaceBefore=20, spaceAfter=4,
    )
    s['h2'] = ParagraphStyle(
        'H2', fontName='Helvetica-Bold', fontSize=13, leading=16,
        textColor=accent_blue, spaceBefore=16, spaceAfter=6,
    )
    s['h3'] = ParagraphStyle(
        'H3', fontName='Helvetica-Bold', fontSize=11, leading=14,
        textColor=accent_teal, spaceBefore=10, spaceAfter=4,
    )
    s['body'] = ParagraphStyle(
        'Body', fontName='Helvetica', fontSize=9.5, leading=13.5,
        textColor=DARK_TEXT, spaceAfter=7, alignment=TA_JUSTIFY,
    )
    s['bullet'] = ParagraphStyle(
        'Bullet', fontName='Helvetica', fontSize=9.5, leading=13.5,
        textColor=DARK_TEXT, spaceAfter=3, leftIndent=18, bulletIndent=6,
    )
    s['numbered'] = ParagraphStyle(
        'Numbered', fontName='Helvetica', fontSize=9.5, leading=13.5,
        textColor=DARK_TEXT, spaceAfter=3, leftIndent=18, bulletIndent=6,
    )
    s['callout'] = ParagraphStyle(
        'Callout', fontName='Helvetica', fontSize=9.5, leading=13,
        textColor=DARK_TEXT,
    )
    s['code'] = ParagraphStyle(
        'Code', fontName='Courier', fontSize=7.5, leading=9.5,
        textColor=DARK_TEXT, backColor=HexColor('#f5f5f5'),
        borderWidth=0.5, borderColor=HexColor('#e0e0e0'),
        borderPadding=6, leftIndent=6, spaceAfter=8,
    )
    s['table_header'] = ParagraphStyle(
        'TH', fontName='Helvetica-Bold', fontSize=8, leading=11,
        textColor=WHITE,
    )
    s['table_cell'] = ParagraphStyle(
        'TC', fontName='Helvetica', fontSize=8, leading=11,
        textColor=DARK_TEXT,
    )
    s['table_cell_bold'] = ParagraphStyle(
        'TCB', fontName='Helvetica-Bold', fontSize=8, leading=11,
        textColor=DARK_TEXT,
    )
    s['toc'] = ParagraphStyle(
        'TOC', fontName='Helvetica', fontSize=10, leading=18,
        textColor=DARK_TEXT, leftIndent=0,
    )
    s['toc_sub'] = ParagraphStyle(
        'TOCSub', fontName='Helvetica', fontSize=9, leading=16,
        textColor=MEDIUM_TEXT, leftIndent=16,
    )
    s['meta_label'] = ParagraphStyle(
        'MetaLabel', fontName='Helvetica', fontSize=8.5, leading=12,
        textColor=LIGHT_TEXT,
    )
    s['meta_value'] = ParagraphStyle(
        'MetaValue', fontName='Helvetica-Bold', fontSize=8.5, leading=12,
        textColor=DARK_TEXT,
    )
    s['figure_caption'] = ParagraphStyle(
        'FigCaption', fontName='Helvetica-Oblique', fontSize=8, leading=11,
        textColor=MEDIUM_TEXT, spaceAfter=10, spaceBefore=2,
        alignment=TA_CENTER,
    )
    return s


# ======================================================================
# Document template with cover + main page templates
# ======================================================================

class KidocDocTemplate(BaseDocTemplate):
    """Custom document template with cover page and main page layouts."""

    def __init__(self, filename, doc_title='', doc_subtitle='',
                 company='', classification='', doc_date='',
                 brand: dict | None = None, **kwargs):
        self.doc_title = doc_title
        self.doc_subtitle = doc_subtitle
        self.company = company
        self.classification = classification
        self.doc_date = doc_date or datetime.now().strftime("%B %d, %Y")
        self.brand = brand or {}
        super().__init__(filename, **kwargs)

        page_w, page_h = kwargs.get('pagesize', letter)
        margin = kwargs.get('leftMargin', inch)
        content_w = page_w - 2 * margin

        frame = Frame(
            margin, 0.7 * inch, content_w, page_h - 1.4 * inch,
            id='normal', topPadding=6, bottomPadding=6,
        )
        self.addPageTemplates([
            PageTemplate(id='cover', frames=[frame],
                         onPage=self._draw_cover_page),
            PageTemplate(id='main', frames=[frame],
                         onPage=self._draw_page),
        ])

    def _draw_cover_page(self, canvas, doc):
        """Dark navy header band, company name, accent line."""
        canvas.saveState()
        page_w, page_h = doc.pagesize
        margin = doc.leftMargin
        dark_navy = self.brand.get('dark_navy', DARK_NAVY)
        accent_teal = self.brand.get('accent_teal', ACCENT_TEAL)

        # Top accent block
        canvas.setFillColor(dark_navy)
        canvas.rect(0, page_h - 1.2 * inch, page_w, 1.2 * inch,
                    fill=1, stroke=0)
        canvas.setStrokeColor(accent_teal)
        canvas.setLineWidth(3)
        canvas.line(0, page_h - 1.2 * inch, page_w, page_h - 1.2 * inch)

        # Company name in header block
        canvas.setFillColor(WHITE)
        canvas.setFont('Helvetica-Bold', 14)
        canvas.drawString(margin, page_h - 0.55 * inch,
                          self.company.upper() if self.company else '')
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(HexColor("#8899aa"))
        canvas.drawString(margin, page_h - 0.8 * inch, self.doc_subtitle)

        # Bottom accent bar
        canvas.setFillColor(accent_teal)
        canvas.rect(0, 0.5 * inch, page_w, 3, fill=1, stroke=0)

        # Footer
        canvas.setFillColor(LIGHT_TEXT)
        canvas.setFont('Helvetica', 7)
        if self.classification:
            canvas.drawString(margin, 0.3 * inch,
                              f"{self.classification}  |  {self.company}")
        canvas.drawRightString(page_w - margin, 0.3 * inch, self.doc_date)

        canvas.restoreState()

    def _draw_page(self, canvas, doc):
        """Compact navy header bar, footer with classification and page."""
        canvas.saveState()
        page_w, page_h = doc.pagesize
        margin = doc.leftMargin
        dark_navy = self.brand.get('dark_navy', DARK_NAVY)
        accent_teal = self.brand.get('accent_teal', ACCENT_TEAL)

        # Header bar
        canvas.setFillColor(dark_navy)
        canvas.rect(0, page_h - 0.45 * inch, page_w, 0.45 * inch,
                    fill=1, stroke=0)
        canvas.setStrokeColor(accent_teal)
        canvas.setLineWidth(2)
        canvas.line(0, page_h - 0.45 * inch, page_w, page_h - 0.45 * inch)

        canvas.setFillColor(WHITE)
        canvas.setFont('Helvetica-Bold', 7.5)
        canvas.drawString(margin, page_h - 0.3 * inch,
                          self.company.upper() if self.company else '')
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(HexColor("#8899aa"))
        canvas.drawRightString(page_w - margin, page_h - 0.3 * inch,
                               self.doc_subtitle)

        # Footer
        canvas.setStrokeColor(RULE_COLOR)
        canvas.setLineWidth(0.4)
        canvas.line(margin, 0.55 * inch, page_w - margin, 0.55 * inch)

        canvas.setFillColor(LIGHT_TEXT)
        canvas.setFont('Helvetica', 6.5)
        if self.classification:
            canvas.drawString(margin, 0.38 * inch, self.classification)
        canvas.drawCentredString(page_w / 2, 0.38 * inch, self.doc_date)
        canvas.drawRightString(page_w - margin, 0.38 * inch,
                               f"Page {doc.page}")

        canvas.restoreState()


# ======================================================================
# XML escaping and inline formatting
# ======================================================================

def _escape_xml(text: str) -> str:
    """Escape special XML characters for ReportLab Paragraph markup."""
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _runs_to_xml(runs: list[dict]) -> str:
    """Convert inline runs from kidoc_md_parser to ReportLab XML markup."""
    parts = []
    for r in runs:
        text = _escape_xml(r['text'])
        if r.get('code'):
            parts.append(
                f'<font face="Courier" size="7.5" color="#c0392b">'
                f'{text}</font>')
        elif r.get('bold') and r.get('italic'):
            parts.append(f'<b><i>{text}</i></b>')
        elif r.get('bold'):
            parts.append(f'<b>{text}</b>')
        elif r.get('italic'):
            parts.append(f'<i>{text}</i>')
        elif r.get('link'):
            href = _escape_xml(r['link'])
            parts.append(
                f'<a href="{href}" color="#1b6ca8"><u>{text}</u></a>')
        else:
            parts.append(text)
    return ''.join(parts)


def _strip_html_comments(text: str) -> str:
    """Remove HTML comments (AUTO markers, NARRATIVE markers, etc.)."""
    return re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)


# ======================================================================
# Cover page
# ======================================================================

def build_cover(title: str, subtitle: str, meta_lines: list[tuple],
                styles: dict, classification: str = '',
                brand: dict | None = None) -> list:
    """Build cover page flowables: title, accent rule, metadata table."""
    b = brand or {}
    dark_navy = b.get('dark_navy', DARK_NAVY)
    accent_teal = b.get('accent_teal', ACCENT_TEAL)

    elements = []
    elements.append(Spacer(1, 1.6 * inch))

    # Title
    elements.append(Paragraph(
        _escape_xml(title).replace('\n', '<br/>'),
        ParagraphStyle(
            'CoverTitle', fontName='Helvetica-Bold', fontSize=34,
            leading=40, textColor=dark_navy,
        ),
    ))
    elements.append(Spacer(1, 6))

    # Accent rule (35% width, 3pt teal, left-aligned)
    elements.append(HRFlowable(
        width="35%", thickness=3, color=accent_teal,
        spaceBefore=0, spaceAfter=16, hAlign='LEFT',
    ))

    # Subtitle
    elements.append(Paragraph(
        _escape_xml(subtitle),
        ParagraphStyle(
            'CoverSub', fontName='Helvetica', fontSize=14, leading=18,
            textColor=MEDIUM_TEXT,
        ),
    ))
    elements.append(Spacer(1, 1.2 * inch))

    # Metadata table with subtle bottom borders
    if meta_lines:
        meta_data = []
        for label, value in meta_lines:
            meta_data.append([
                Paragraph(_escape_xml(label), styles['meta_label']),
                Paragraph(_escape_xml(value), styles['meta_value']),
            ])
        meta_table = Table(meta_data, colWidths=[1.5 * inch, 4 * inch])
        meta_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, 0), (-1, -2), 0.3, RULE_COLOR),
        ]))
        elements.append(meta_table)

    elements.append(Spacer(1, 1 * inch))

    # Classification tag
    if classification:
        elements.append(Paragraph(
            f'<font color="#c0392b"><b>{_escape_xml(classification.upper())}</b></font>',
            ParagraphStyle('ConfTag', fontSize=9, leading=12),
        ))

    return elements


# ======================================================================
# Table of Contents
# ======================================================================

def build_toc(elements: list[dict], styles: dict,
              brand: dict | None = None) -> list:
    """Build TOC from parsed markdown elements.

    Extracts headings from the element list and renders as a styled TOC.
    Only includes level-1 and level-2 headings (## and ###).
    Skips the first heading (document title, shown on cover).
    """
    b = brand or {}
    dark_navy = b.get('dark_navy', DARK_NAVY)
    accent_teal = b.get('accent_teal', ACCENT_TEAL)

    flowables = []
    flowables.append(Paragraph("Table of Contents", ParagraphStyle(
        'TOCTitle', fontName='Helvetica-Bold', fontSize=18, leading=22,
        textColor=dark_navy, spaceAfter=12,
    )))
    flowables.append(HRFlowable(
        width="100%", thickness=1, color=accent_teal,
        spaceBefore=0, spaceAfter=12,
    ))

    # Collect headings, skip the first H1 (title)
    first_h1_seen = False
    for elem in elements:
        if elem['type'] != 'heading':
            continue
        level = elem['level']
        if level == 1 and not first_h1_seen:
            first_h1_seen = True
            continue
        if level > 3:
            continue

        text = _escape_xml(elem['text'])
        if level <= 2:
            flowables.append(Paragraph(
                f'<b>{text}</b>', styles['toc'],
            ))
        else:
            flowables.append(Paragraph(text, styles['toc_sub']))

    flowables.append(PageBreak())
    return flowables


# ======================================================================
# Table builder
# ======================================================================

def build_table(headers: list[str], rows: list[list[str]],
                styles: dict, content_w: float,
                brand: dict | None = None) -> list:
    """Build a styled table: dark header, alternating rows, rounded corners.

    First column rendered bold. Thin borders with RULE_COLOR.
    """
    if not headers:
        return []

    b = brand or {}
    table_header_bg = b.get('table_header_bg', TABLE_HEADER_BG)
    table_alt_row = b.get('table_alt_row', TABLE_ALT_ROW)
    accent_blue = b.get('accent_blue', ACCENT_BLUE)

    num_cols = len(headers)
    table_data = []

    # Header row
    header = [Paragraph(_escape_xml(h), styles['table_header'])
              for h in headers]
    table_data.append(header)

    # Data rows
    for row in rows:
        styled_row = []
        for j in range(num_cols):
            cell_text = row[j] if j < len(row) else ''
            if j == 0:
                styled_row.append(
                    Paragraph(_escape_xml(cell_text), styles['table_cell_bold']))
            else:
                styled_row.append(
                    Paragraph(_escape_xml(cell_text), styles['table_cell']))
        table_data.append(styled_row)

    col_widths = [content_w / num_cols] * num_cols
    t = Table(table_data, colWidths=col_widths, repeatRows=1)

    cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), table_header_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 7),
        ('TOPPADDING', (0, 0), (-1, 0), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.4, HexColor("#dde4ea")),
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, accent_blue),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROUNDEDCORNERS', [3, 3, 3, 3]),
    ]

    # Alternating row colors
    for ri in range(1, len(table_data)):
        if ri % 2 == 0:
            cmds.append(('BACKGROUND', (0, ri), (-1, ri), table_alt_row))

    t.setStyle(TableStyle(cmds))
    return [t, Spacer(1, 8)]


# ======================================================================
# Element-to-flowable conversion
# ======================================================================

def elements_to_flowables(elements: list[dict], styles: dict,
                          base_dir: str, content_w: float,
                          brand: dict | None = None) -> list:
    """Convert parsed markdown elements to ReportLab flowables.

    Uses kidoc_md_parser element types. The first H1 heading is skipped
    (it appears on the cover page).
    """
    b = brand or {}
    accent_blue = b.get('accent_blue', ACCENT_BLUE)
    accent_teal = b.get('accent_teal', ACCENT_TEAL)
    callout_bg = b.get('callout_bg', CALLOUT_BG)
    callout_border = b.get('callout_border', CALLOUT_BORDER)

    flowables = []
    first_h1_seen = False
    figure_counter = 0

    for elem in elements:
        etype = elem['type']

        # --- heading ---
        if etype == 'heading':
            level = elem['level']
            text = _escape_xml(elem['text'])

            if level == 1 and not first_h1_seen:
                first_h1_seen = True
                continue  # skip title, it's on the cover

            if level == 1:
                flowables.append(Paragraph(text, styles['h1']))
                flowables.append(HRFlowable(
                    width="100%", thickness=1.5, color=accent_blue,
                    spaceBefore=0, spaceAfter=6,
                ))
            elif level == 2:
                # KeepTogether: heading + rule stays with first paragraph
                heading_group = [
                    Spacer(1, 6),
                    Paragraph(text, styles['h1']),
                    HRFlowable(
                        width="100%", thickness=1, color=accent_teal,
                        spaceBefore=0, spaceAfter=4,
                    ),
                ]
                flowables.append(KeepTogether(heading_group))
            elif level == 3:
                flowables.append(Spacer(1, 4))
                flowables.append(Paragraph(text, styles['h2']))
            else:
                flowables.append(Paragraph(text, styles['h3']))

        # --- paragraph ---
        elif etype == 'paragraph':
            xml = _runs_to_xml(elem['runs'])
            if xml.strip():
                flowables.append(Paragraph(xml, styles['body']))

        # --- image ---
        elif etype == 'image':
            figure_counter += 1
            img_flowables = _build_image(
                elem, base_dir, content_w, styles, figure_counter)
            flowables.extend(img_flowables)

        # --- table ---
        elif etype == 'table':
            flowables.extend(build_table(
                elem['headers'], elem['rows'], styles, content_w,
                brand=b))

        # --- code_block ---
        elif etype == 'code_block':
            code = _escape_xml(elem['code'])
            flowables.append(Preformatted(code, styles['code']))

        # --- bullet_list ---
        elif etype == 'bullet_list':
            for item_runs in elem['items']:
                xml = _runs_to_xml(item_runs)
                flowables.append(Paragraph(
                    f'<bullet>&bull;</bullet> {xml}',
                    styles['bullet'],
                ))

        # --- numbered_list ---
        elif etype == 'numbered_list':
            for i, item_runs in enumerate(elem['items'], 1):
                xml = _runs_to_xml(item_runs)
                flowables.append(Paragraph(
                    f'<bullet>{i}.</bullet> {xml}',
                    styles['numbered'],
                ))

        # --- blockquote ---
        elif etype == 'blockquote':
            xml = _runs_to_xml(elem['runs'])
            flowables.append(Spacer(1, 4))
            flowables.append(CalloutBox(
                xml, content_w, callout_bg, callout_border,
                styles['callout'],
            ))
            flowables.append(Spacer(1, 4))

        # --- hr ---
        elif etype == 'hr':
            flowables.append(Spacer(1, 4))
            flowables.append(HRFlowable(
                width="100%", thickness=0.5, color=RULE_COLOR,
                spaceBefore=2, spaceAfter=6,
            ))

    return flowables


def _build_image(elem: dict, base_dir: str, content_w: float,
                 styles: dict, figure_num: int) -> list:
    """Build image flowable with figure caption.

    Uses svg_to_flowable for vector SVG embedding. Falls back to
    placeholder text if file not found.

    Caps image height to fit within the page content area and wraps
    figure + caption in KeepTogether to prevent splitting across pages.
    Large full-sheet schematics (width > 400pt) get a PageBreak before them.
    """
    MAX_IMAGE_HEIGHT = 500  # points — leaves room for header, footer, caption

    path = elem['path']
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)

    flowables = []

    if not os.path.isfile(path):
        flowables.append(Paragraph(
            f'<i>[Image not found: {_escape_xml(elem["path"])}]</i>',
            styles['figure_caption'],
        ))
        return flowables

    max_width = content_w
    img_flowable = None
    if path.lower().endswith('.svg'):
        img_flowable = svg_to_flowable(path, max_width)
    else:
        # Raster image
        try:
            from reportlab.platypus import Image
            img_flowable = Image(path)
            if img_flowable.drawWidth > max_width:
                scale = max_width / img_flowable.drawWidth
                img_flowable.drawWidth *= scale
                img_flowable.drawHeight *= scale
        except Exception:
            flowables.append(Paragraph(
                f'<i>[Failed to load image: {_escape_xml(elem["path"])}]</i>',
                styles['figure_caption'],
            ))
            return flowables

    if img_flowable is None:
        return flowables

    # Cap image height to fit within the page content frame
    img_h = getattr(img_flowable, 'height', 0) or getattr(img_flowable, 'drawHeight', 0)
    img_w = getattr(img_flowable, 'width', 0) or getattr(img_flowable, 'drawWidth', 0)
    if img_h > MAX_IMAGE_HEIGHT:
        ratio = MAX_IMAGE_HEIGHT / img_h
        if hasattr(img_flowable, 'height'):
            img_flowable.width = img_flowable.width * ratio
            img_flowable.height = MAX_IMAGE_HEIGHT
        if hasattr(img_flowable, 'drawHeight'):
            img_flowable.drawWidth = img_flowable.drawWidth * ratio
            img_flowable.drawHeight = MAX_IMAGE_HEIGHT
        if hasattr(img_flowable, 'renderScale'):
            img_flowable.renderScale = getattr(img_flowable, 'renderScale', 1.0) * ratio
        img_w = img_w * ratio

    # Full-sheet schematics get a page break before them
    if img_w > 400:
        flowables.append(PageBreak())

    # Build figure group: image + optional caption, kept together
    figure_elements = [img_flowable]

    # Figure caption (if alt text provided)
    alt = elem.get('alt', '').strip()
    if alt:
        figure_elements.append(Spacer(1, 4))
        figure_elements.append(Paragraph(
            f'<i>Figure {figure_num}: {_escape_xml(alt)}</i>',
            styles['figure_caption'],
        ))

    flowables.append(KeepTogether(figure_elements))
    return flowables


# ======================================================================
# Main generation
# ======================================================================

def generate_pdf(markdown_path: str, output_path: str, config: dict) -> str:
    """Convert markdown to PDF with publication-quality styling.

    Returns the output path.
    """
    with open(markdown_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # Strip HTML comments before parsing
    md_text = _strip_html_comments(md_text)

    elements = parse_markdown(md_text)
    brand = _resolve_branding(config)
    styles = create_styles(brand=brand)
    base_dir = os.path.dirname(os.path.abspath(markdown_path))

    # Extract config
    project = config.get('project', {})
    reports = config.get('reports', {})

    title = project.get('name', 'Untitled Document')
    subtitle = reports.get('subtitle', project.get('number', ''))
    company = project.get('company', '')
    classification = reports.get('classification', '')
    author = project.get('author', '')
    revision = project.get('revision', '')
    doc_date = project.get('date', datetime.now().strftime("%Y-%m-%d"))

    # If markdown starts with H1, use that as the title
    for elem in elements:
        if elem['type'] == 'heading' and elem['level'] == 1:
            title = elem['text']
            break

    # Page size
    page_size_name = reports.get('page_size', 'letter')
    page_size = PAGE_SIZES.get(page_size_name.lower(), letter)
    page_w = page_size[0]
    margin = inch
    content_w = page_w - 2 * margin

    # Build document
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.',
                exist_ok=True)

    doc = KidocDocTemplate(
        output_path,
        doc_title=title,
        doc_subtitle=subtitle or title,
        company=company,
        classification=classification,
        doc_date=doc_date,
        brand=brand,
        pagesize=page_size,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        leftMargin=margin,
        rightMargin=margin,
        title=title,
        author=author or company,
        subject=subtitle or title,
    )

    story = []

    # Cover page
    meta_lines = []
    if project.get('number'):
        meta_lines.append(("Document", project['number']))
    if revision:
        meta_lines.append(("Revision", revision))
    if author:
        meta_lines.append(("Author", author))
    if doc_date:
        meta_lines.append(("Date", doc_date))
    if classification:
        meta_lines.append(("Classification", classification))

    story.extend(build_cover(title, subtitle or title, meta_lines, styles,
                             classification, brand=brand))
    story.append(PageBreak())

    # Switch to main template after cover
    story.append(NextPageTemplate('main'))

    # TOC (only if enough sections)
    heading_count = sum(
        1 for e in elements
        if e['type'] == 'heading' and e['level'] <= 2
    )
    if heading_count >= 4:
        story.extend(build_toc(elements, styles, brand=brand))

    # Content
    story.extend(elements_to_flowables(elements, styles, base_dir, content_w,
                                       brand=brand))

    doc.build(story)
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='Generate publication-quality PDF from markdown')
    parser.add_argument('--input', '-i', required=True,
                        help='Input markdown file')
    parser.add_argument('--output', '-o', required=True,
                        help='Output PDF file')
    parser.add_argument('--config', '-c', default='{}',
                        help='JSON config string or path to config file')
    args = parser.parse_args()

    # Load config
    if os.path.isfile(args.config):
        with open(args.config) as f:
            config = json.load(f)
    else:
        config = json.loads(args.config)

    output = generate_pdf(args.input, args.output, config)
    print(output, file=sys.stderr)


if __name__ == '__main__':
    main()

"""Markdown parser for kidoc document generation.

Parses the subset of markdown used by kidoc scaffolds into a list of
typed document elements.  Used by both kidoc_pdf.py and kidoc_docx.py.

Supports: headings, paragraphs (with bold/italic/code), tables, images,
code blocks, horizontal rules, bullet lists, numbered lists, blockquotes.
HTML comments are skipped silently.

Zero external dependencies — Python stdlib only.
"""

from __future__ import annotations

import re
from typing import Any


# ======================================================================
# Element types
# ======================================================================

def heading(level: int, text: str) -> dict:
    return {'type': 'heading', 'level': level, 'text': text}

def paragraph(runs: list[dict]) -> dict:
    return {'type': 'paragraph', 'runs': runs}

def table(headers: list[str], rows: list[list[str]],
          alignments: list[str]) -> dict:
    return {'type': 'table', 'headers': headers, 'rows': rows,
            'alignments': alignments}

def image(alt: str, path: str) -> dict:
    return {'type': 'image', 'alt': alt, 'path': path}

def code_block(code: str, language: str = '') -> dict:
    return {'type': 'code_block', 'code': code, 'language': language}

def horizontal_rule() -> dict:
    return {'type': 'hr'}

def bullet_list(items: list[list[dict]]) -> dict:
    return {'type': 'bullet_list', 'items': items}

def numbered_list(items: list[list[dict]]) -> dict:
    return {'type': 'numbered_list', 'items': items}

def blockquote(runs: list[dict]) -> dict:
    return {'type': 'blockquote', 'runs': runs}


# ======================================================================
# Inline parsing (bold, italic, code, links)
# ======================================================================

_INLINE_PATTERNS = [
    # Order matters: longer/more specific patterns first
    (re.compile(r'\*\*\*(.+?)\*\*\*'), 'bold_italic'),
    (re.compile(r'\*\*(.+?)\*\*'), 'bold'),
    (re.compile(r'\*(.+?)\*'), 'italic'),
    (re.compile(r'`(.+?)`'), 'code'),
    (re.compile(r'\[(.+?)\]\((.+?)\)'), 'link'),
]


def parse_inline(text: str) -> list[dict]:
    """Parse inline formatting into a list of runs.

    Each run: {'text': str, 'bold': bool, 'italic': bool, 'code': bool, 'link': str|None}
    """
    runs: list[dict] = []
    pos = 0

    while pos < len(text):
        best_match = None
        best_start = len(text)
        best_pattern = None

        for pattern, ptype in _INLINE_PATTERNS:
            m = pattern.search(text, pos)
            if m and m.start() < best_start:
                best_match = m
                best_start = m.start()
                best_pattern = ptype

        if best_match is None:
            # No more inline formatting — rest is plain text
            remaining = text[pos:]
            if remaining:
                runs.append(_run(remaining))
            break

        # Add plain text before the match
        if best_start > pos:
            runs.append(_run(text[pos:best_start]))

        # Add the formatted run
        if best_pattern == 'bold_italic':
            runs.append(_run(best_match.group(1), bold=True, italic=True))
        elif best_pattern == 'bold':
            runs.append(_run(best_match.group(1), bold=True))
        elif best_pattern == 'italic':
            runs.append(_run(best_match.group(1), italic=True))
        elif best_pattern == 'code':
            runs.append(_run(best_match.group(1), code=True))
        elif best_pattern == 'link':
            runs.append(_run(best_match.group(1), link=best_match.group(2)))

        pos = best_match.end()

    return runs if runs else [_run(text)]


def _run(text: str, bold: bool = False, italic: bool = False,
         code: bool = False, link: str | None = None) -> dict:
    return {'text': text, 'bold': bold, 'italic': italic,
            'code': code, 'link': link}


# ======================================================================
# Block-level parsing
# ======================================================================

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$')
_IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$')
_TABLE_SEP_RE = re.compile(r'^\|[\s:|-]+\|\s*$')
_TABLE_ROW_RE = re.compile(r'^\|(.+)\|\s*$')
_CODE_FENCE_RE = re.compile(r'^```(\w*)\s*$')
_HR_RE = re.compile(r'^---+\s*$')
_BULLET_RE = re.compile(r'^[-*+]\s+(.+)$')
_NUMBERED_RE = re.compile(r'^\d+\.\s+(.+)$')
_BLOCKQUOTE_RE = re.compile(r'^>\s*(.*)$')
_COMMENT_RE = re.compile(r'^<!--.*-->$')


def parse_markdown(text: str) -> list[dict]:
    """Parse markdown text into a list of document elements."""
    lines = text.split('\n')
    elements: list[dict] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Skip HTML comments (AUTO markers, NARRATIVE markers)
        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        # Code fence
        m = _CODE_FENCE_RE.match(stripped)
        if m:
            lang = m.group(1)
            code_lines = []
            i += 1
            while i < n and not _CODE_FENCE_RE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            elements.append(code_block('\n'.join(code_lines), lang))
            continue

        # Heading
        m = _HEADING_RE.match(stripped)
        if m:
            level = len(m.group(1))
            elements.append(heading(level, m.group(2)))
            i += 1
            continue

        # Horizontal rule
        if _HR_RE.match(stripped):
            elements.append(horizontal_rule())
            i += 1
            continue

        # Image (standalone on a line)
        m = _IMAGE_RE.match(stripped)
        if m:
            elements.append(image(m.group(1), m.group(2)))
            i += 1
            continue

        # Table (starts with | and next line is separator)
        if _TABLE_ROW_RE.match(stripped) and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1].strip()):
            headers = _parse_table_row(stripped)
            alignments = _parse_table_alignments(lines[i + 1].strip())
            rows = []
            i += 2  # skip header and separator
            while i < n and _TABLE_ROW_RE.match(lines[i].strip()):
                rows.append(_parse_table_row(lines[i].strip()))
                i += 1
            elements.append(table(headers, rows, alignments))
            continue

        # Bullet list
        m = _BULLET_RE.match(stripped)
        if m:
            items = []
            while i < n and _BULLET_RE.match(lines[i].strip()):
                item_m = _BULLET_RE.match(lines[i].strip())
                items.append(parse_inline(item_m.group(1)))
                i += 1
            elements.append(bullet_list(items))
            continue

        # Numbered list
        m = _NUMBERED_RE.match(stripped)
        if m:
            items = []
            while i < n and _NUMBERED_RE.match(lines[i].strip()):
                item_m = _NUMBERED_RE.match(lines[i].strip())
                items.append(parse_inline(item_m.group(1)))
                i += 1
            elements.append(numbered_list(items))
            continue

        # Blockquote
        m = _BLOCKQUOTE_RE.match(stripped)
        if m:
            quote_lines = []
            while i < n and _BLOCKQUOTE_RE.match(lines[i].strip()):
                qm = _BLOCKQUOTE_RE.match(lines[i].strip())
                quote_lines.append(qm.group(1))
                i += 1
            elements.append(blockquote(parse_inline(' '.join(quote_lines))))
            continue

        # Default: paragraph (collect consecutive non-empty, non-special lines)
        para_lines = []
        while i < n:
            l = lines[i].strip()
            if not l:
                break
            if (_HEADING_RE.match(l) or _HR_RE.match(l) or _IMAGE_RE.match(l)
                    or _CODE_FENCE_RE.match(l) or _COMMENT_RE.match(l)
                    or (_TABLE_ROW_RE.match(l) and i + 1 < n
                        and _TABLE_SEP_RE.match(lines[i + 1].strip()))
                    or _BULLET_RE.match(l) or _NUMBERED_RE.match(l)):
                break
            para_lines.append(l)
            i += 1
        if para_lines:
            elements.append(paragraph(parse_inline(' '.join(para_lines))))

    return elements


# ======================================================================
# Table helpers
# ======================================================================

def _parse_table_row(line: str) -> list[str]:
    """Parse a markdown table row into cells."""
    # Strip leading/trailing pipes and split
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|'):
        line = line[:-1]
    return [cell.strip() for cell in line.split('|')]


def _parse_table_alignments(sep_line: str) -> list[str]:
    """Parse table separator to determine column alignments."""
    cells = _parse_table_row(sep_line)
    alignments = []
    for cell in cells:
        cell = cell.strip()
        if cell.startswith(':') and cell.endswith(':'):
            alignments.append('center')
        elif cell.endswith(':'):
            alignments.append('right')
        else:
            alignments.append('left')
    return alignments

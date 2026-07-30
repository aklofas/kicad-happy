"""Markdown table formatting and unit formatting utilities.

Zero external dependencies — Python stdlib only.
"""

from __future__ import annotations


def markdown_table(headers: list[str], rows: list[list[str]],
                   alignments: list[str] | None = None) -> str:
    """Generate a markdown table with proper column padding.

    *alignments*: list of ``'left'``, ``'center'``, or ``'right'`` per column.
    Defaults to left-aligned.
    """
    if not headers:
        return ''

    n_cols = len(headers)
    if alignments is None:
        alignments = ['left'] * n_cols

    # Compute column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row[:n_cols]):
            widths[i] = max(widths[i], len(str(cell)))

    def _pad(text: str, width: int, align: str) -> str:
        text = str(text)
        if align == 'right':
            return text.rjust(width)
        elif align == 'center':
            return text.center(width)
        return text.ljust(width)

    # Header row
    header_line = '| ' + ' | '.join(
        _pad(h, widths[i], alignments[i]) for i, h in enumerate(headers)
    ) + ' |'

    # Separator row
    sep_parts = []
    for i, a in enumerate(alignments):
        w = widths[i]
        if a == 'center':
            sep_parts.append(':' + '-' * max(w - 2, 1) + ':')
        elif a == 'right':
            sep_parts.append('-' * max(w - 1, 1) + ':')
        else:
            sep_parts.append('-' * w)
    sep_line = '| ' + ' | '.join(sep_parts) + ' |'

    # Data rows
    data_lines = []
    for row in rows:
        padded = []
        for i in range(n_cols):
            cell = str(row[i]) if i < len(row) else ''
            padded.append(_pad(cell, widths[i], alignments[i]))
        data_lines.append('| ' + ' | '.join(padded) + ' |')

    return '\n'.join([header_line, sep_line] + data_lines)


# ---------------------------------------------------------------------------
# Unit formatters
# ---------------------------------------------------------------------------

def format_voltage(v: float | None) -> str:
    """Format a voltage value: ``3.3V``, ``1.8V``, ``—`` for None."""
    if v is None:
        return '—'
    if abs(v) >= 1:
        return f"{v:.1f}V" if v != int(v) else f"{int(v)}V"
    return f"{v * 1000:.0f}mV"


def format_frequency(hz: float | None) -> str:
    """Format frequency: ``1.23kHz``, ``48.0MHz``, ``—`` for None."""
    if hz is None:
        return '—'
    if hz >= 1e9:
        return f"{hz / 1e9:.1f}GHz"
    if hz >= 1e6:
        return f"{hz / 1e6:.1f}MHz"
    if hz >= 1e3:
        return f"{hz / 1e3:.1f}kHz"
    return f"{hz:.0f}Hz"


def format_current(a: float | None) -> str:
    """Format current: ``500mA``, ``2.5A``, ``—`` for None."""
    if a is None:
        return '—'
    if abs(a) >= 1:
        return f"{a:.1f}A" if a != int(a) else f"{int(a)}A"
    if abs(a) >= 0.001:
        return f"{a * 1000:.0f}mA"
    return f"{a * 1e6:.0f}µA"


def format_capacitance(f: float | None) -> str:
    """Format capacitance: ``100nF``, ``10µF``, ``—`` for None."""
    if f is None:
        return '—'
    if f >= 1e-3:
        return f"{f * 1e3:.0f}mF"
    if f >= 1e-6:
        return f"{f * 1e6:.0f}µF"
    if f >= 1e-9:
        return f"{f * 1e9:.0f}nF"
    return f"{f * 1e12:.0f}pF"


def format_resistance(ohms: float | None) -> str:
    """Format resistance: ``10kΩ``, ``4.7Ω``, ``—`` for None."""
    if ohms is None:
        return '—'
    if ohms >= 1e6:
        return f"{ohms / 1e6:.1f}MΩ"
    if ohms >= 1e3:
        return f"{ohms / 1e3:.1f}kΩ" if ohms != int(ohms / 1e3) * 1e3 else f"{int(ohms / 1e3)}kΩ"
    return f"{ohms:.1f}Ω" if ohms != int(ohms) else f"{int(ohms)}Ω"

"""Shared colors, constants, and drawing helpers for figure generators.

All figure modules import their styling from here to keep the palette
consistent and avoid duplicating drawing primitives.

The legacy module-level color constants (``BOX_FILL``, etc.) are
preserved for backward compatibility.  New code should use the
``FigureTheme`` dataclass from ``theme.py`` instead.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple, TYPE_CHECKING

from .svg_builder import SvgBuilder

if TYPE_CHECKING:
    from .theme import FigureTheme

__all__ = [
    # Re-export SvgBuilder so figure modules can do:
    #   from .styles import SvgBuilder, BOX_FILL, _draw_box, ...
    'SvgBuilder',
    # Colors (legacy constants — prefer FigureTheme)
    'BOX_FILL', 'BOX_STROKE', 'BOX_FONT',
    'POWER_FILL', 'POWER_STROKE', 'POWER_FONT',
    'BUS_FILL', 'BUS_STROKE', 'BUS_FONT',
    'IO_FILL', 'IO_STROKE', 'IO_FONT',
    'ARROW_COLOR', 'LABEL_FONT', 'BG_COLOR',
    # Constants
    'BOX_CORNER_RADIUS', 'BOX_PADDING', 'FONT_SIZE', 'SMALL_FONT',
    'ARROW_HEAD_SIZE',
    # Legacy drawing helpers
    '_draw_box', '_draw_arrow', '_draw_bus_line', '_format_cap_summary',
    # Advanced drawing helpers (theme-aware)
    'draw_gradient_box', 'draw_shadow_box', 'draw_header_box',
    'draw_pill', 'draw_port', 'draw_curved_arrow', 'draw_right_angle_arrow',
]

# ======================================================================
# Colors and constants
# ======================================================================

BOX_FILL = "#e8e8ff"
BOX_STROKE = "#4040c0"
BOX_FONT = "#202060"

POWER_FILL = "#fff0e0"
POWER_STROKE = "#c06000"
POWER_FONT = "#804000"

BUS_FILL = "#e0ffe0"
BUS_STROKE = "#008040"
BUS_FONT = "#004020"

IO_FILL = "#ffe0e0"
IO_STROKE = "#c04040"
IO_FONT = "#802020"

ARROW_COLOR = "#606060"
LABEL_FONT = "#404040"
BG_COLOR = "#ffffff"

BOX_CORNER_RADIUS = 2.0
BOX_PADDING = 3.0
FONT_SIZE = 2.5
SMALL_FONT = 1.8
ARROW_HEAD_SIZE = 1.5


# ======================================================================
# Drawing primitives
# ======================================================================

def _draw_box(svg: SvgBuilder, x: float, y: float, w: float, h: float,
              label: str, sublabel: str = "",
              fill: str = BOX_FILL, stroke: str = BOX_STROKE,
              font_color: str = BOX_FONT) -> None:
    """Draw a labeled rounded-rectangle box."""
    svg.rect(x, y, w, h, stroke=stroke, fill=fill,
             stroke_width=0.3, rx=BOX_CORNER_RADIUS)
    svg.text(x + w / 2, y + h / 2 - (1.5 if sublabel else 0),
             label, font_size=FONT_SIZE, fill=font_color,
             anchor='middle', dominant_baseline='central', bold=True)
    if sublabel:
        svg.text(x + w / 2, y + h / 2 + 2.0,
                 sublabel, font_size=SMALL_FONT, fill=font_color,
                 anchor='middle', dominant_baseline='central')


def _draw_arrow(svg: SvgBuilder, x1: float, y1: float,
                x2: float, y2: float, label: str = "",
                color: str = ARROW_COLOR, stroke_width: float = 0.3) -> None:
    """Draw an arrow from (x1,y1) to (x2,y2) with optional label."""
    svg.line(x1, y1, x2, y2, stroke=color, stroke_width=stroke_width)
    # Arrowhead
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 0.1:
        return
    nx, ny = dx / dist, dy / dist
    px, py = -ny, nx  # perpendicular
    s = ARROW_HEAD_SIZE
    svg.polyline([
        (x2 - nx * s + px * s * 0.4, y2 - ny * s + py * s * 0.4),
        (x2, y2),
        (x2 - nx * s - px * s * 0.4, y2 - ny * s - py * s * 0.4),
    ], stroke=color, fill=color, stroke_width=stroke_width, closed=True)
    # Label at midpoint
    if label:
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        svg.text(mx, my - 1.5, label, font_size=SMALL_FONT,
                 fill=LABEL_FONT, anchor='middle')


def _draw_bus_line(svg: SvgBuilder, x1: float, y1: float,
                   x2: float, y2: float,
                   color: str = BUS_STROKE, width: float = 0.6) -> None:
    """Draw a thick bus line."""
    svg.line(x1, y1, x2, y2, stroke=color, stroke_width=width)


def _format_cap_summary(caps: list[dict]) -> str:
    """Format a capacitor list into a compact summary string."""
    if not caps:
        return ''
    # Group by value
    by_value: dict[str, list[str]] = {}
    for c in caps:
        val = c.get('value', '?')
        ref = c.get('ref', '')
        # Skip compensation/feedforward caps (tiny values)
        farads = c.get('farads', 0)
        if farads and farads < 1e-9:
            continue
        by_value.setdefault(val, []).append(ref)
    parts = []
    for val, refs in sorted(by_value.items(), key=lambda x: -len(x[1])):
        if len(refs) == 1:
            parts.append(f"{refs[0]}: {val}")
        else:
            parts.append(f"{len(refs)}\u00d7{val}")
    return ', '.join(parts)


# ======================================================================
# Advanced drawing primitives (theme-aware)
# ======================================================================

def _get_theme() -> 'FigureTheme':
    """Lazy-import and return a default FigureTheme (avoids circular import)."""
    from .theme import FigureTheme
    return FigureTheme()


def _resolve_theme(theme: Optional['FigureTheme']) -> 'FigureTheme':
    """Return *theme* if given, else default."""
    return theme if theme is not None else _get_theme()


def draw_gradient_box(svg: SvgBuilder, x: float, y: float,
                      w: float, h: float,
                      label: str, sublabel: str = "",
                      fill: str = BOX_FILL,
                      fill_bottom: Optional[str] = None,
                      stroke: str = BOX_STROKE,
                      font_color: str = BOX_FONT,
                      theme: Optional['FigureTheme'] = None) -> None:
    """Draw a box with a subtle top-to-bottom gradient fill.

    If *fill_bottom* is ``None``, auto-darkens *fill* by ~8%.
    Falls back to flat fill when ``theme.use_gradients`` is ``False``.
    """
    from .theme import darken
    theme = _resolve_theme(theme)
    rx = theme.box_corner_radius

    if theme.use_gradients:
        bottom = fill_bottom or darken(fill, 0.08)
        grad = svg.linear_gradient(fill, bottom)
        svg.rect(x, y, w, h, stroke=stroke, fill=grad,
                 stroke_width=0.3, rx=rx)
    else:
        svg.rect(x, y, w, h, stroke=stroke, fill=fill,
                 stroke_width=0.3, rx=rx)

    svg.text(x + w / 2, y + h / 2 - (1.5 if sublabel else 0),
             label, font_size=theme.font_body, fill=font_color,
             anchor='middle', dominant_baseline='central', bold=True)
    if sublabel:
        svg.text(x + w / 2, y + h / 2 + 2.0,
                 sublabel, font_size=theme.font_small, fill=font_color,
                 anchor='middle', dominant_baseline='central')


def draw_shadow_box(svg: SvgBuilder, x: float, y: float,
                    w: float, h: float,
                    label: str, sublabel: str = "",
                    fill: str = BOX_FILL, stroke: str = BOX_STROKE,
                    font_color: str = BOX_FONT,
                    theme: Optional['FigureTheme'] = None) -> None:
    """Draw a box with a drop shadow.

    The shadow is an offset gray rectangle rendered behind the main
    shape.  Disabled when ``theme.shadow_opacity == 0``.
    """
    theme = _resolve_theme(theme)
    off = theme.shadow_offset

    if theme.shadow_opacity > 0:
        svg.rect(x + off, y + off, w, h,
                 stroke='none', fill='#000000',
                 stroke_width=0, rx=theme.box_corner_radius,
                 opacity=theme.shadow_opacity)

    draw_gradient_box(svg, x, y, w, h, label, sublabel,
                      fill=fill, stroke=stroke, font_color=font_color,
                      theme=theme)


def draw_header_box(svg: SvgBuilder, x: float, y: float,
                    w: float, h: float,
                    header_text: str,
                    body_lines: Optional[List[str]] = None,
                    header_color: str = "#1a3c5c",
                    header_font_color: str = "#ffffff",
                    body_fill: str = "#f0f4f8",
                    stroke: str = "#4a6fa5",
                    body_font_color: str = "#1a3c5c",
                    header_h: float = 6.0,
                    theme: Optional['FigureTheme'] = None) -> None:
    """Draw a box with a colored header strip and white body.

    The header strip gets a gradient fill for depth.  Body lines are
    rendered left-aligned below the header.
    """
    from .theme import darken, lighten
    theme = _resolve_theme(theme)
    rx = theme.box_corner_radius
    body_lines = body_lines or []

    # Clip path approach: draw full rounded rect, then overlay
    # Outer rounded rect (stroke only)
    svg.rect(x, y, w, h, stroke=stroke, fill='none',
             stroke_width=0.3, rx=rx)

    # Header fill — gradient for depth
    if theme.use_gradients:
        hdr_grad = svg.linear_gradient(
            lighten(header_color, 0.10), darken(header_color, 0.05))
        svg.rect(x + 0.15, y + 0.15, w - 0.3, header_h,
                 stroke='none', fill=hdr_grad, rx=rx)
    else:
        svg.rect(x + 0.15, y + 0.15, w - 0.3, header_h,
                 stroke='none', fill=header_color, rx=rx)

    # Square off bottom corners of header by overlaying a small rect
    if header_h < h - rx:
        svg.rect(x + 0.15, y + header_h - rx, w - 0.3, rx,
                 stroke='none', fill=header_color if not theme.use_gradients
                 else darken(header_color, 0.05))

    # Body fill
    body_y = y + header_h
    body_h = h - header_h
    if body_h > 0:
        svg.rect(x + 0.15, body_y, w - 0.3, body_h - 0.15,
                 stroke='none', fill=body_fill)
        # Square off top corners of body
        if body_h > rx:
            svg.rect(x + 0.15, body_y, w - 0.3, min(rx, body_h),
                     stroke='none', fill=body_fill)

    # Header text
    svg.text(x + w / 2, y + header_h / 2,
             header_text, font_size=theme.font_body,
             fill=header_font_color,
             anchor='middle', dominant_baseline='central', bold=True)

    # Body lines
    line_y = body_y + 3.5
    for line in body_lines:
        if line_y > y + h - 1.5:
            break
        svg.text(x + 2.5, line_y, line,
                 font_size=theme.font_small, fill=body_font_color,
                 anchor='start', dominant_baseline='central')
        line_y += theme.font_small + 1.2


def draw_pill(svg: SvgBuilder, cx: float, cy: float,
              text: str, fill: str = "#e0e0e0",
              font_color: str = "#404040",
              font_size: Optional[float] = None,
              theme: Optional['FigureTheme'] = None
              ) -> Tuple[float, float]:
    """Draw a rounded badge/pill label.  Returns ``(width, height)``.

    Auto-sizes to text content with fully rounded ends (rx = h/2).
    """
    theme = _resolve_theme(theme)
    fs = font_size or theme.font_small
    # Approximate text width: ~0.55 × font_size × char_count
    text_w = len(text) * fs * 0.55
    pad = fs * 0.8
    w = text_w + pad * 2
    h = fs * 1.8
    rx = h / 2

    svg.rect(cx - w / 2, cy - h / 2, w, h,
             stroke='none', fill=fill, rx=rx)
    svg.text(cx, cy, text, font_size=fs, fill=font_color,
             anchor='middle', dominant_baseline='central')
    return w, h


def draw_port(svg: SvgBuilder, x: float, y: float,
              side: str, label: str = "",
              color: str = "#4040c0",
              theme: Optional['FigureTheme'] = None
              ) -> Tuple[float, float]:
    """Draw a connector-style port on a box edge.

    *side*: ``'left'``, ``'right'``, ``'top'``, ``'bottom'``.
    Returns the connection point ``(cx, cy)`` for arrow routing.
    """
    theme = _resolve_theme(theme)
    r = 1.2  # port radius
    svg.circle(x, y, r, stroke=color, fill='#ffffff', stroke_width=0.3)
    svg.circle(x, y, r * 0.4, stroke='none', fill=color)

    if label:
        fs = theme.font_small
        if side == 'left':
            svg.text(x - r - 1.0, y, label, font_size=fs, fill=color,
                     anchor='end', dominant_baseline='central')
        elif side == 'right':
            svg.text(x + r + 1.0, y, label, font_size=fs, fill=color,
                     anchor='start', dominant_baseline='central')
        elif side == 'top':
            svg.text(x, y - r - 0.8, label, font_size=fs, fill=color,
                     anchor='middle', dominant_baseline='auto')
        else:  # bottom
            svg.text(x, y + r + 1.2, label, font_size=fs, fill=color,
                     anchor='middle', dominant_baseline='hanging')
    return x, y


def draw_curved_arrow(svg: SvgBuilder, x1: float, y1: float,
                      x2: float, y2: float, label: str = "",
                      color: str = ARROW_COLOR,
                      stroke_width: float = 0.3,
                      theme: Optional['FigureTheme'] = None) -> None:
    """Draw a curved arrow using a cubic Bezier S-curve.

    Auto-calculates control points for a smooth curve that bows
    perpendicular to the start→end vector.
    """
    theme = _resolve_theme(theme)
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 0.1:
        return

    # Bow amount: ~25% of distance, perpendicular to line
    bow = dist * 0.25
    # Normal vector (perpendicular)
    nx, ny = -dy / dist, dx / dist

    # Control points
    cp1x = x1 + dx * 0.33 + nx * bow
    cp1y = y1 + dy * 0.33 + ny * bow
    cp2x = x1 + dx * 0.67 + nx * bow
    cp2y = y1 + dy * 0.67 + ny * bow

    svg.bezier([(x1, y1), (cp1x, cp1y), (cp2x, cp2y), (x2, y2)],
               stroke=color, fill='none', stroke_width=stroke_width)

    # Arrowhead at endpoint
    # Direction from last control point to end
    adx, ady = x2 - cp2x, y2 - cp2y
    adist = math.hypot(adx, ady)
    if adist > 0.01:
        anx, any_ = adx / adist, ady / adist
        px, py = -any_, anx
        s = theme.arrow_head_size
        svg.polyline([
            (x2 - anx * s + px * s * 0.4, y2 - any_ * s + py * s * 0.4),
            (x2, y2),
            (x2 - anx * s - px * s * 0.4, y2 - any_ * s - py * s * 0.4),
        ], stroke=color, fill=color, stroke_width=stroke_width, closed=True)

    if label:
        mx = (x1 + x2) / 2 + nx * bow * 0.5
        my = (y1 + y2) / 2 + ny * bow * 0.5
        svg.text(mx, my - 1.5, label, font_size=theme.font_small,
                 fill=theme.label_font, anchor='middle')


def draw_right_angle_arrow(svg: SvgBuilder, x1: float, y1: float,
                           x2: float, y2: float, label: str = "",
                           color: str = ARROW_COLOR,
                           stroke_width: float = 0.3,
                           mid_x: Optional[float] = None,
                           theme: Optional['FigureTheme'] = None) -> None:
    """Draw an orthogonal routed arrow (horizontal → vertical → horizontal).

    *mid_x*: x-coordinate of the vertical segment.
    Auto-calculated as the midpoint if *None*.
    """
    theme = _resolve_theme(theme)
    if mid_x is None:
        mid_x = (x1 + x2) / 2

    # Three-segment polyline: horizontal out, vertical, horizontal in
    svg.line(x1, y1, mid_x, y1, stroke=color, stroke_width=stroke_width)
    svg.line(mid_x, y1, mid_x, y2, stroke=color, stroke_width=stroke_width)
    svg.line(mid_x, y2, x2, y2, stroke=color, stroke_width=stroke_width)

    # Arrowhead at endpoint
    s = theme.arrow_head_size
    direction = 1 if x2 > mid_x else -1
    svg.polyline([
        (x2 - direction * s, y2 - s * 0.4),
        (x2, y2),
        (x2 - direction * s, y2 + s * 0.4),
    ], stroke=color, fill=color, stroke_width=stroke_width, closed=True)

    if label:
        svg.text(mid_x + 1.0, (y1 + y2) / 2, label,
                 font_size=theme.font_small, fill=theme.label_font,
                 anchor='start', dominant_baseline='central')

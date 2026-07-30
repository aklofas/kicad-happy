"""Extract graphical primitives from KiCad schematic lib_symbols.

Parses the symbol body shapes (rectangles, circles, arcs, polylines,
beziers, text) and pin rendering data that extract_lib_symbols() in
analyze_schematic.py currently skips.  These are needed to render
publication-quality SVG output.

Zero external dependencies — Python stdlib only (+ sexp_parser from kicad skill).
"""

from __future__ import annotations

import os
import sys
from collections import namedtuple
from typing import Any

from ._path_setup import setup_kicad_imports
setup_kicad_imports()

try:
    from sexp_parser import find_all, find_first, get_value, get_at, get_property
except ImportError:
    raise ImportError("sexp_parser.py not found — ensure the kicad skill is installed")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

StrokeStyle = namedtuple('StrokeStyle', ['width', 'type', 'color'])
FillStyle = namedtuple('FillStyle', ['fill_type', 'color'])
TextEffects = namedtuple('TextEffects', [
    'height', 'width', 'bold', 'italic',
    'h_justify', 'v_justify', 'hidden',
])

RectGraphic = namedtuple('RectGraphic', ['x1', 'y1', 'x2', 'y2', 'stroke', 'fill'])
CircleGraphic = namedtuple('CircleGraphic', ['cx', 'cy', 'radius', 'stroke', 'fill'])
ArcGraphic = namedtuple('ArcGraphic', ['sx', 'sy', 'mx', 'my', 'ex', 'ey', 'stroke', 'fill'])
PolylineGraphic = namedtuple('PolylineGraphic', ['points', 'stroke', 'fill'])
BezierGraphic = namedtuple('BezierGraphic', ['points', 'stroke', 'fill'])
TextGraphic = namedtuple('TextGraphic', ['text', 'x', 'y', 'angle', 'effects'])
PinGraphic = namedtuple('PinGraphic', [
    'number', 'name', 'elec_type', 'shape',
    'x', 'y', 'angle', 'length',
    'name_effects', 'number_effects',
])
SymbolGraphics = namedtuple('SymbolGraphics', [
    'unit_graphics',        # dict[int, list[graphic]] — unit 0 = shared
    'pin_name_offset',      # float
    'pin_names_visible',    # bool
    'pin_numbers_visible',  # bool
])


# ---------------------------------------------------------------------------
# Stroke / fill / effects parsing
# ---------------------------------------------------------------------------

_DEFAULT_STROKE = StrokeStyle(width=0, type='solid', color=None)
_DEFAULT_FILL = FillStyle(fill_type='none', color=None)
_DEFAULT_EFFECTS = TextEffects(
    height=1.27, width=1.27, bold=False, italic=False,
    h_justify='center', v_justify='center', hidden=False,
)


def parse_stroke(node: list) -> StrokeStyle:
    """Parse ``(stroke (width W) (type T) (color R G B A))``."""
    stroke_node = find_first(node, 'stroke')
    if not stroke_node:
        return _DEFAULT_STROKE
    width = _float(get_value(stroke_node, 'width'), 0)
    stype = get_value(stroke_node, 'type') or 'solid'
    color_node = find_first(stroke_node, 'color')
    color = None
    if color_node and len(color_node) >= 4:
        try:
            r, g, b = int(float(color_node[1])), int(float(color_node[2])), int(float(color_node[3]))
            a = float(color_node[4]) if len(color_node) > 4 else 1.0
            if r > 0 or g > 0 or b > 0:
                color = (r, g, b, a)
        except (ValueError, IndexError):
            pass
    return StrokeStyle(width=width, type=stype, color=color)


def parse_fill(node: list) -> FillStyle:
    """Parse ``(fill (type none|outline|background) (color R G B A))``."""
    fill_node = find_first(node, 'fill')
    if not fill_node:
        return _DEFAULT_FILL
    ftype = get_value(fill_node, 'type') or 'none'
    color_node = find_first(fill_node, 'color')
    color = None
    if color_node and len(color_node) >= 4:
        try:
            r, g, b = int(float(color_node[1])), int(float(color_node[2])), int(float(color_node[3]))
            a = float(color_node[4]) if len(color_node) > 4 else 1.0
            if r > 0 or g > 0 or b > 0:
                color = (r, g, b, a)
        except (ValueError, IndexError):
            pass
    return FillStyle(fill_type=ftype, color=color)


def parse_effects(node: list) -> TextEffects:
    """Parse ``(effects (font (size H W) (bold) (italic)) (justify ...) (hide))``."""
    effects_node = find_first(node, 'effects')
    if not effects_node:
        return _DEFAULT_EFFECTS
    font_node = find_first(effects_node, 'font')
    height, width = 1.27, 1.27
    bold = False
    italic = False
    if font_node:
        size_node = find_first(font_node, 'size')
        if size_node and len(size_node) >= 3:
            height = _float(size_node[1], 1.27)
            width = _float(size_node[2], 1.27)
        bold = any(isinstance(c, str) and c == 'bold' for c in font_node)
        italic = any(isinstance(c, str) and c == 'italic' for c in font_node)

    h_justify = 'center'
    v_justify = 'center'
    justify_node = find_first(effects_node, 'justify')
    if justify_node:
        for item in justify_node[1:]:
            if isinstance(item, str):
                if item in ('left', 'right'):
                    h_justify = item
                elif item in ('top', 'bottom'):
                    v_justify = item

    hidden = (any(isinstance(c, str) and c == 'hide' for c in effects_node)
              or any(isinstance(c, list) and c[0] == 'hide' for c in effects_node))

    return TextEffects(
        height=height, width=width, bold=bold, italic=italic,
        h_justify=h_justify, v_justify=v_justify, hidden=hidden,
    )


# ---------------------------------------------------------------------------
# Primitive parsers
# ---------------------------------------------------------------------------

def _parse_rectangle(node: list) -> RectGraphic:
    """Parse ``(rectangle (start x y) (end x y) ...)``."""
    start = find_first(node, 'start')
    end = find_first(node, 'end')
    x1 = _float(start[1], 0) if start and len(start) >= 3 else 0
    y1 = _float(start[2], 0) if start and len(start) >= 3 else 0
    x2 = _float(end[1], 0) if end and len(end) >= 3 else 0
    y2 = _float(end[2], 0) if end and len(end) >= 3 else 0
    return RectGraphic(x1, y1, x2, y2, parse_stroke(node), parse_fill(node))


def _parse_circle(node: list) -> CircleGraphic:
    """Parse ``(circle (center x y) (radius R) ...)``."""
    center = find_first(node, 'center')
    cx = _float(center[1], 0) if center and len(center) >= 3 else 0
    cy = _float(center[2], 0) if center and len(center) >= 3 else 0
    radius_node = find_first(node, 'radius')
    radius = _float(radius_node[1], 0) if radius_node and len(radius_node) >= 2 else 0
    return CircleGraphic(cx, cy, radius, parse_stroke(node), parse_fill(node))


def _parse_arc(node: list) -> ArcGraphic:
    """Parse ``(arc (start x y) (mid x y) (end x y) ...)``."""
    start = find_first(node, 'start')
    mid = find_first(node, 'mid')
    end = find_first(node, 'end')
    sx = _float(start[1], 0) if start and len(start) >= 3 else 0
    sy = _float(start[2], 0) if start and len(start) >= 3 else 0
    mx = _float(mid[1], 0) if mid and len(mid) >= 3 else 0
    my = _float(mid[2], 0) if mid and len(mid) >= 3 else 0
    ex = _float(end[1], 0) if end and len(end) >= 3 else 0
    ey = _float(end[2], 0) if end and len(end) >= 3 else 0
    return ArcGraphic(sx, sy, mx, my, ex, ey, parse_stroke(node), parse_fill(node))


def _parse_polyline(node: list) -> PolylineGraphic:
    """Parse ``(polyline (pts (xy x y) ...) ...)``."""
    pts_node = find_first(node, 'pts')
    points = []
    if pts_node:
        for child in pts_node:
            if isinstance(child, list) and len(child) >= 3 and child[0] == 'xy':
                points.append((_float(child[1], 0), _float(child[2], 0)))
    return PolylineGraphic(points, parse_stroke(node), parse_fill(node))


def _parse_bezier(node: list) -> BezierGraphic:
    """Parse ``(bezier (pts (xy x y) ...) ...)``."""
    pts_node = find_first(node, 'pts')
    points = []
    if pts_node:
        for child in pts_node:
            if isinstance(child, list) and len(child) >= 3 and child[0] == 'xy':
                points.append((_float(child[1], 0), _float(child[2], 0)))
    return BezierGraphic(points, parse_stroke(node), parse_fill(node))


def _parse_text(node: list) -> TextGraphic | None:
    """Parse ``(text "content" (at x y [angle]) (effects ...))``."""
    if len(node) < 2:
        return None
    text = node[1] if isinstance(node[1], str) else ''
    at = get_at(node)
    x, y, angle = at if at else (0, 0, 0)
    return TextGraphic(text, x, y, angle, parse_effects(node))


def _parse_pin(node: list) -> PinGraphic | None:
    """Parse a pin with full rendering data.

    ``(pin type shape (at x y angle) (length L) (name "N" (effects ...)) (number "N" (effects ...)))``
    """
    if len(node) < 3:
        return None
    elec_type = node[1] if len(node) > 1 and isinstance(node[1], str) else 'passive'
    shape = node[2] if len(node) > 2 and isinstance(node[2], str) else 'line'

    at = get_at(node)
    x, y, angle = at if at else (0, 0, 0)

    length_node = find_first(node, 'length')
    length = _float(length_node[1], 2.54) if length_node and len(length_node) >= 2 else 2.54

    name_node = find_first(node, 'name')
    name = str(name_node[1]) if name_node and len(name_node) > 1 else ''
    name_effects = parse_effects(name_node) if name_node else _DEFAULT_EFFECTS

    num_node = find_first(node, 'number')
    number = str(num_node[1]) if num_node and len(num_node) > 1 else ''
    number_effects = parse_effects(num_node) if num_node else _DEFAULT_EFFECTS

    return PinGraphic(
        number=number, name=name, elec_type=elec_type, shape=shape,
        x=x, y=y, angle=angle, length=length,
        name_effects=name_effects, number_effects=number_effects,
    )


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_symbol_graphics(root: list) -> dict[str, SymbolGraphics]:
    """Extract graphical primitives from all lib_symbols.

    *root* is the parsed S-expression root of a ``.kicad_sch`` file.

    Returns a dict keyed by symbol name (e.g. ``"Device:C"``), each
    containing per-unit graphics lists, pin visibility, and pin name offset.
    """
    lib_symbols_node = find_first(root, 'lib_symbols')
    if not lib_symbols_node:
        return {}

    result: dict[str, SymbolGraphics] = {}

    for sym in find_all(lib_symbols_node, 'symbol'):
        name = sym[1] if len(sym) > 1 and isinstance(sym[1], str) else ''
        if not name:
            continue

        # Skip sub-unit symbols (they are children of the top-level symbol)
        parts = name.split(':')[-1].rsplit('_', 2)
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            continue

        # Pin name offset and visibility
        pin_name_offset_node = find_first(sym, 'pin_name_offset')
        pin_name_offset = _float(
            pin_name_offset_node[1], 0.508
        ) if pin_name_offset_node and len(pin_name_offset_node) >= 2 else 0.508

        pin_names_node = find_first(sym, 'pin_names')
        pin_names_visible = True
        if pin_names_node:
            # (pin_names hide) or (pin_names (offset X) hide)
            if any(isinstance(c, str) and c == 'hide' for c in pin_names_node):
                pin_names_visible = False
            offset_node = find_first(pin_names_node, 'offset')
            if offset_node and len(offset_node) >= 2:
                pin_name_offset = _float(offset_node[1], pin_name_offset)

        pin_numbers_node = find_first(sym, 'pin_numbers')
        pin_numbers_visible = True
        if pin_numbers_node:
            if any(isinstance(c, str) and c == 'hide' for c in pin_numbers_node):
                pin_numbers_visible = False

        # Extract graphics from sub-symbols (unit_0 = shared, unit_N = specific)
        unit_graphics: dict[int, list] = {}

        for child in sym:
            if not isinstance(child, list) or len(child) < 2 or child[0] != 'symbol':
                continue
            sub_name = child[1] if isinstance(child[1], str) else ''
            # Parse unit number: "Name_U_V" -> unit U
            sub_parts = sub_name.rsplit('_', 2)
            if len(sub_parts) >= 3 and sub_parts[-1].isdigit() and sub_parts[-2].isdigit():
                unit_num = int(sub_parts[-2])
            else:
                unit_num = 0

            graphics = _extract_graphics_from_node(child)
            if graphics:
                unit_graphics.setdefault(unit_num, []).extend(graphics)

        result[name] = SymbolGraphics(
            unit_graphics=unit_graphics,
            pin_name_offset=pin_name_offset,
            pin_names_visible=pin_names_visible,
            pin_numbers_visible=pin_numbers_visible,
        )

    return result


def _extract_graphics_from_node(node: list) -> list:
    """Extract all graphic primitives from a symbol sub-node."""
    graphics = []
    for child in node:
        if not isinstance(child, list) or len(child) < 2:
            continue
        tag = child[0]
        if tag == 'rectangle':
            graphics.append(_parse_rectangle(child))
        elif tag == 'circle':
            graphics.append(_parse_circle(child))
        elif tag == 'arc':
            graphics.append(_parse_arc(child))
        elif tag == 'polyline':
            graphics.append(_parse_polyline(child))
        elif tag == 'bezier':
            graphics.append(_parse_bezier(child))
        elif tag == 'text':
            g = _parse_text(child)
            if g:
                graphics.append(g)
        elif tag == 'pin':
            g = _parse_pin(child)
            if g:
                graphics.append(g)
    return graphics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _float(val: Any, default: float = 0.0) -> float:
    """Safe float conversion with default."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

"""SVG-to-ReportLab embedding module.

Converts SVG files to ReportLab Drawing objects for vector PDF embedding.
Three-tier fallback strategy:

  Tier 1: svglib (best quality, handles full SVG spec)
  Tier 2: Custom converter (handles the SVG subset from kidoc's svg_builder)
  Tier 3: Pillow rasterization via svg_to_png (fallback to bitmap Image)

This module runs INSIDE reports/.venv/ where reportlab is available.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Optional

from reportlab.graphics.shapes import (
    Drawing, Group, Line, Rect, Circle, Ellipse,
    PolyLine, Polygon, String,
)
from reportlab.lib.colors import toColor, HexColor, Color
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER


# ======================================================================
# Constants
# ======================================================================

MM_TO_PT = mm  # 2.8346 pt/mm (reportlab.lib.units.mm)
SVG_NS = '{http://www.w3.org/2000/svg}'


# ======================================================================
# Public API
# ======================================================================

def svg_to_flowable(svg_path: str, max_width: float = 450) -> object:
    """Convert an SVG file to a ReportLab Flowable.

    Returns a Drawing (vector) if possible, or an Image (raster) as fallback.
    max_width is in points (72pt = 1 inch).

    Tries three approaches in order:
      1. svglib — best quality, full SVG support
      2. Custom converter — handles kidoc's SVG subset
      3. Pillow rasterization — bitmap fallback
    """
    # Tier 1: svglib
    drawing = _try_svglib(svg_path)
    if drawing is not None:
        return _scale_drawing(drawing, max_width)

    # Tier 2: custom converter
    drawing = _try_custom(svg_path)
    if drawing is not None:
        return _scale_drawing(drawing, max_width)

    # Tier 3: rasterize
    return _rasterize(svg_path, max_width)


# ======================================================================
# Tier 1: svglib
# ======================================================================

def _try_svglib(svg_path: str) -> Optional[Drawing]:
    """Try converting SVG using svglib.  Returns Drawing or None."""
    try:
        from svglib.svglib import svg2rlg
        drawing = svg2rlg(svg_path)
        if drawing is not None and drawing.width > 0 and drawing.height > 0:
            return drawing
    except Exception:
        pass
    return None


# ======================================================================
# Tier 2: custom converter for kidoc SVG subset
# ======================================================================

def _parse_gradient_defs(root: ET.Element) -> dict:
    """Parse ``<defs>`` for gradient definitions.

    Returns a dict mapping gradient ID to its first stop color (hex).
    Used as a graceful degradation when svglib is not available:
    gradients fall back to a single representative color.
    """
    gradient_colors: dict[str, str] = {}
    for defs in root.iter(SVG_NS + 'defs'):
        for grad in defs:
            tag = grad.tag.replace(SVG_NS, '')
            if tag not in ('linearGradient', 'radialGradient'):
                continue
            grad_id = grad.get('id', '')
            if not grad_id:
                continue
            # Use the first stop color as the representative color
            for stop in grad:
                stop_tag = stop.tag.replace(SVG_NS, '')
                if stop_tag == 'stop':
                    color = stop.get('stop-color', '')
                    if color:
                        gradient_colors[grad_id] = color
                        break
    return gradient_colors


# Module-level gradient lookup, populated per SVG parse
_gradient_lookup: dict[str, str] = {}


def _try_custom(svg_path: str) -> Optional[Drawing]:
    """Parse our SVG subset with xml.etree and build a ReportLab Drawing.

    Handles: line, rect, circle, ellipse, polyline, polygon, text, g.
    Coordinates are in mm (from svg_builder's viewBox), converted to points.
    Y-axis is flipped (SVG is top-down, ReportLab is bottom-up).
    Gradients degrade to their first stop color.
    """
    global _gradient_lookup
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()

        # Build gradient fallback lookup from <defs>
        _gradient_lookup = _parse_gradient_defs(root)

        # Parse dimensions from viewBox
        viewbox = root.get('viewBox', '')
        if not viewbox:
            w_str = root.get('width', '297mm')
            h_str = root.get('height', '210mm')
            vb_w = _parse_dim(w_str)
            vb_h = _parse_dim(h_str)
        else:
            parts = viewbox.split()
            vb_w = float(parts[2])
            vb_h = float(parts[3])

        # Drawing dimensions in points
        dw = vb_w * MM_TO_PT
        dh = vb_h * MM_TO_PT

        drawing = Drawing(dw, dh)

        # Process all child elements
        for child in root:
            _convert_element(child, drawing, dh, vb_w, vb_h)

        return drawing
    except Exception:
        return None


def _convert_element(elem: ET.Element, group: Group, dh: float,
                     vb_w: float, vb_h: float) -> None:
    """Recursively convert an SVG element to ReportLab shapes.

    Args:
        elem: XML element to convert
        group: ReportLab Group/Drawing to add shapes to
        dh: Drawing height in points (for Y-flip)
        vb_w: viewBox width in mm
        vb_h: viewBox height in mm
    """
    tag = elem.tag.replace(SVG_NS, '')

    # Skip <defs> — definitions (gradients etc.), not drawn elements
    if tag == 'defs':
        return

    if tag == 'g':
        g = Group()
        for child in elem:
            _convert_element(child, g, dh, vb_w, vb_h)
        group.add(g)
        return

    if tag == 'line':
        _add_line(elem, group, dh)
    elif tag == 'rect':
        _add_rect(elem, group, dh)
    elif tag == 'circle':
        _add_circle(elem, group, dh)
    elif tag == 'ellipse':
        _add_ellipse(elem, group, dh)
    elif tag == 'polyline':
        _add_polyline(elem, group, dh)
    elif tag == 'polygon':
        _add_polygon(elem, group, dh)
    elif tag == 'text':
        _add_text(elem, group, dh)

    # Recurse into unknown elements that might contain children
    if tag not in ('g', 'line', 'rect', 'circle', 'ellipse',
                   'polyline', 'polygon', 'text'):
        for child in elem:
            _convert_element(child, group, dh, vb_w, vb_h)


def _add_line(elem: ET.Element, group: Group, dh: float) -> None:
    """Convert SVG <line> to ReportLab Line."""
    x1 = _mm_to_pt(float(elem.get('x1', '0')))
    y1 = _flip_y(float(elem.get('y1', '0')), dh)
    x2 = _mm_to_pt(float(elem.get('x2', '0')))
    y2 = _flip_y(float(elem.get('y2', '0')), dh)

    stroke = _parse_color(elem.get('stroke', '#000000'))
    sw = _mm_to_pt(float(elem.get('stroke-width', '0.2')))

    line = Line(x1, y1, x2, y2)
    if stroke:
        line.strokeColor = stroke
    line.strokeWidth = sw
    group.add(line)


def _add_rect(elem: ET.Element, group: Group, dh: float) -> None:
    """Convert SVG <rect> to ReportLab Rect."""
    x = _mm_to_pt(float(elem.get('x', '0')))
    y_svg = float(elem.get('y', '0'))
    w = _mm_to_pt(float(elem.get('width', '0')))
    h = _mm_to_pt(float(elem.get('height', '0')))
    rx = _mm_to_pt(float(elem.get('rx', '0')))
    ry = _mm_to_pt(float(elem.get('ry', '0')))

    # Y-flip: ReportLab rect y is bottom-left, SVG rect y is top-left
    y = _flip_y(y_svg, dh) - h

    fill = _parse_color(elem.get('fill', 'none'))
    stroke = _parse_color(elem.get('stroke', 'none'))
    sw = _mm_to_pt(float(elem.get('stroke-width', '0.2')))

    rect = Rect(x, y, w, h, rx=rx, ry=ry)
    rect.fillColor = fill
    rect.strokeColor = stroke
    rect.strokeWidth = sw if stroke else 0
    group.add(rect)


def _add_circle(elem: ET.Element, group: Group, dh: float) -> None:
    """Convert SVG <circle> to ReportLab Circle."""
    cx = _mm_to_pt(float(elem.get('cx', '0')))
    cy = _flip_y(float(elem.get('cy', '0')), dh)
    r = _mm_to_pt(float(elem.get('r', '0')))

    fill = _parse_color(elem.get('fill', 'none'))
    stroke = _parse_color(elem.get('stroke', 'none'))
    sw = _mm_to_pt(float(elem.get('stroke-width', '0.2')))

    circle = Circle(cx, cy, r)
    circle.fillColor = fill
    circle.strokeColor = stroke
    circle.strokeWidth = sw if stroke else 0
    group.add(circle)


def _add_ellipse(elem: ET.Element, group: Group, dh: float) -> None:
    """Convert SVG <ellipse> to ReportLab Ellipse."""
    cx = _mm_to_pt(float(elem.get('cx', '0')))
    cy = _flip_y(float(elem.get('cy', '0')), dh)
    rx = _mm_to_pt(float(elem.get('rx', '0')))
    ry = _mm_to_pt(float(elem.get('ry', '0')))

    fill = _parse_color(elem.get('fill', 'none'))
    stroke = _parse_color(elem.get('stroke', 'none'))
    sw = _mm_to_pt(float(elem.get('stroke-width', '0.2')))

    ellipse = Ellipse(cx, cy, rx, ry)
    ellipse.fillColor = fill
    ellipse.strokeColor = stroke
    ellipse.strokeWidth = sw if stroke else 0
    group.add(ellipse)


def _add_polyline(elem: ET.Element, group: Group, dh: float) -> None:
    """Convert SVG <polyline> to ReportLab PolyLine."""
    points = _parse_points(elem.get('points', ''), dh)
    if len(points) < 4:  # Need at least 2 points (4 values)
        return

    stroke = _parse_color(elem.get('stroke', '#000000'))
    sw = _mm_to_pt(float(elem.get('stroke-width', '0.2')))

    pl = PolyLine(points)
    pl.strokeColor = stroke
    pl.strokeWidth = sw
    group.add(pl)


def _add_polygon(elem: ET.Element, group: Group, dh: float) -> None:
    """Convert SVG <polygon> to ReportLab Polygon."""
    points = _parse_points(elem.get('points', ''), dh)
    if len(points) < 6:  # Need at least 3 points (6 values)
        return

    fill = _parse_color(elem.get('fill', 'none'))
    stroke = _parse_color(elem.get('stroke', 'none'))
    sw = _mm_to_pt(float(elem.get('stroke-width', '0.2')))

    pg = Polygon(points)
    pg.fillColor = fill
    pg.strokeColor = stroke
    pg.strokeWidth = sw if stroke else 0
    group.add(pg)


def _add_text(elem: ET.Element, group: Group, dh: float) -> None:
    """Convert SVG <text> to ReportLab String."""
    content = elem.text or ''
    if not content.strip():
        return

    x = _mm_to_pt(float(elem.get('x', '0')))
    y = _flip_y(float(elem.get('y', '0')), dh)

    font_size = _mm_to_pt(float(elem.get('font-size', '2.5')))
    fill = _parse_color(elem.get('fill', '#000000'))

    # Font selection
    font_weight = elem.get('font-weight', 'normal')
    if font_weight == 'bold':
        font_name = 'Helvetica-Bold'
    else:
        font_name = 'Helvetica'

    # Text anchor
    anchor = elem.get('text-anchor', 'start')
    if anchor == 'middle':
        text_anchor = 'middle'
    elif anchor == 'end':
        text_anchor = 'end'
    else:
        text_anchor = 'start'

    s = String(x, y, content)
    s.fontSize = font_size
    s.fontName = font_name
    s.fillColor = fill
    s.textAnchor = text_anchor
    group.add(s)


# ======================================================================
# Tier 3: rasterize fallback
# ======================================================================

def _rasterize(svg_path: str, max_width: float) -> object:
    """Rasterize SVG to PNG using svg_to_png, return ReportLab Image.

    Falls back to a placeholder Paragraph if rasterization fails.
    """
    try:
        # Import the existing rasterizer
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from svg_to_png import svg_to_png

        fd, png_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        svg_to_png(svg_path, png_path, dpi=300)

        img = Image(png_path)
        # Scale to fit max_width
        if img.drawWidth > max_width:
            scale = max_width / img.drawWidth
            img.drawWidth *= scale
            img.drawHeight *= scale
        return img
    except Exception:
        pass

    # Final fallback: placeholder paragraph
    try:
        styles = getSampleStyleSheet()
        style = styles['Normal']
        style.alignment = TA_CENTER
        basename = os.path.basename(svg_path)
        return Paragraph(
            f'<i>[Could not render SVG: {basename}]</i>', style)
    except Exception:
        # Should never happen, but be safe
        return Paragraph('[SVG rendering failed]', getSampleStyleSheet()['Normal'])


# ======================================================================
# Scaling
# ======================================================================

def _scale_drawing(drawing: Drawing, max_width: float) -> Drawing:
    """Scale a Drawing to fit within max_width, preserving aspect ratio.

    Uses renderScale to avoid distorting internal coordinates.
    """
    if drawing.width <= 0:
        return drawing

    if drawing.width <= max_width:
        return drawing

    factor = max_width / drawing.width
    drawing.renderScale = factor
    # Update reported dimensions so platypus layout knows the actual size
    drawing.width = drawing.width * factor
    drawing.height = drawing.height * factor
    return drawing


# ======================================================================
# Coordinate helpers
# ======================================================================

def _mm_to_pt(val_mm: float) -> float:
    """Convert millimeters to points."""
    return val_mm * MM_TO_PT


def _flip_y(y_mm: float, drawing_height_pt: float) -> float:
    """Flip Y coordinate from SVG (top-down) to ReportLab (bottom-up).

    y_mm is in SVG mm coordinates.
    drawing_height_pt is the full drawing height in points.
    Returns Y in points.
    """
    return drawing_height_pt - (y_mm * MM_TO_PT)


def _parse_points(points_str: str, dh: float) -> list:
    """Parse SVG points string to flat list with Y-flip.

    Input:  "x1,y1 x2,y2 ..." (mm coordinates)
    Output: [x1_pt, y1_pt_flipped, x2_pt, y2_pt_flipped, ...]
    """
    result = []
    if not points_str or not points_str.strip():
        return result

    for pt in points_str.strip().split():
        parts = pt.split(',')
        if len(parts) >= 2:
            x = _mm_to_pt(float(parts[0]))
            y = dh - _mm_to_pt(float(parts[1]))  # Y-flip
            result.append(x)
            result.append(y)
    return result


def _parse_dim(dim_str: str) -> float:
    """Parse a dimension string like '297mm', '210pt', or bare number (mm).

    Returns value in mm (the viewBox unit for our SVGs).
    """
    dim_str = dim_str.strip()
    if dim_str.endswith('mm'):
        return float(dim_str[:-2])
    elif dim_str.endswith('pt'):
        return float(dim_str[:-2]) / MM_TO_PT
    elif dim_str.endswith('in'):
        return float(dim_str[:-2]) * 25.4
    elif dim_str.endswith('cm'):
        return float(dim_str[:-2]) * 10.0
    elif dim_str.endswith('px'):
        # Assume 96 DPI default for SVG px
        return float(dim_str[:-2]) * 25.4 / 96.0
    else:
        # Bare number — assume mm (our SVGs use mm viewBox)
        return float(dim_str)


def _parse_color(color_str: Optional[str]) -> Optional[Color]:
    """Parse SVG color string to ReportLab Color.

    Handles hex (#rrggbb, #rgb), 'none', ``url(#id)`` gradient
    references (degraded to first stop color), and named colors
    via toColor.
    """
    if not color_str or color_str.strip().lower() == 'none':
        return None

    color_str = color_str.strip()

    # Gradient reference: url(#grad_1) -> resolve to first stop color
    if color_str.startswith('url(#'):
        grad_id = color_str[5:].rstrip(')')
        fallback = _gradient_lookup.get(grad_id)
        if fallback:
            try:
                return HexColor(fallback)
            except Exception:
                return None
        return None

    # Hex colors
    if color_str.startswith('#'):
        try:
            return HexColor(color_str)
        except Exception:
            return None

    # Named colors and rgb() via ReportLab's toColor
    try:
        return toColor(color_str)
    except Exception:
        return None

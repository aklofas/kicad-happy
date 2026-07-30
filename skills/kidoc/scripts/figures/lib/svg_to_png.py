"""Lightweight SVG-to-PNG rasterizer using Pillow.

Handles the limited SVG subset produced by kidoc's svg_builder:
lines, rects, circles, polylines/polygons, paths (arcs), and text.
No CSS, no gradients, no masks, no external references.

This exists to avoid the Cairo dependency (svglib/rl-renderPM/pycairo
all require libcairo2-dev system package, which is not cross-platform).

Zero native dependencies beyond Pillow (which has prebuilt wheels everywhere).
"""

from __future__ import annotations

import math
import os
import re
import xml.etree.ElementTree as ET
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def svg_to_png(svg_path: str, png_path: str, dpi: int = 300,
               background: str = '#ffffff') -> str:
    """Convert an SVG file to PNG using Pillow.

    Only handles the SVG subset produced by kidoc's svg_builder.
    Returns the output PNG path.
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()
    ns = 'http://www.w3.org/2000/svg'

    # Parse viewBox and dimensions
    viewbox = root.get('viewBox', '0 0 297 210')
    vb_parts = viewbox.split()
    vb_x, vb_y = float(vb_parts[0]), float(vb_parts[1])
    vb_w, vb_h = float(vb_parts[2]), float(vb_parts[3])

    # Compute pixel dimensions from mm at given DPI
    px_w = int(vb_w * dpi / 25.4)
    px_h = int(vb_h * dpi / 25.4)

    # Scale factor: SVG mm coords -> pixel coords
    scale_x = px_w / vb_w
    scale_y = px_h / vb_h

    img = Image.new('RGB', (px_w, px_h), _parse_color(background))
    draw = ImageDraw.Draw(img)

    # Try to load a font for text rendering
    font_cache: dict[float, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def _get_font(size_mm: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        size_px = max(8, int(size_mm * scale_y))
        if size_px not in font_cache:
            try:
                font_cache[size_px] = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size_px)
            except (OSError, IOError):
                try:
                    font_cache[size_px] = ImageFont.truetype("arial.ttf", size_px)
                except (OSError, IOError):
                    font_cache[size_px] = ImageFont.load_default()
        return font_cache[size_px]

    def _tx(x: float) -> float:
        """Transform X coordinate from SVG to pixel space."""
        return (x - vb_x) * scale_x

    def _ty(y: float) -> float:
        """Transform Y coordinate from SVG to pixel space."""
        return (y - vb_y) * scale_y

    def _tw(w: float) -> float:
        """Transform width from SVG to pixel space."""
        return w * scale_x

    def _render_element(elem: ET.Element, parent_transform=None) -> None:
        """Recursively render an SVG element."""
        tag = elem.tag.replace(f'{{{ns}}}', '')

        if tag == 'g':
            # Group — recurse into children
            for child in elem:
                _render_element(child)
            return

        if tag == 'line':
            x1 = _tx(float(elem.get('x1', '0')))
            y1 = _ty(float(elem.get('y1', '0')))
            x2 = _tx(float(elem.get('x2', '0')))
            y2 = _ty(float(elem.get('y2', '0')))
            stroke = _parse_color(elem.get('stroke', '#000000'))
            width = max(1, int(_tw(float(elem.get('stroke-width', '0.2')))))
            if stroke:
                draw.line([(x1, y1), (x2, y2)], fill=stroke, width=width)

        elif tag == 'rect':
            x = _tx(float(elem.get('x', '0')))
            y = _ty(float(elem.get('y', '0')))
            w = _tw(float(elem.get('width', '0')))
            h = _tw(float(elem.get('height', '0')))  # Use same scale
            stroke = _parse_color(elem.get('stroke', 'none'))
            fill = _parse_color(elem.get('fill', 'none'))
            width = max(1, int(_tw(float(elem.get('stroke-width', '0.2')))))
            if fill:
                draw.rectangle([(x, y), (x + w, y + h)], fill=fill)
            if stroke:
                draw.rectangle([(x, y), (x + w, y + h)], outline=stroke, width=width)

        elif tag == 'circle':
            cx = _tx(float(elem.get('cx', '0')))
            cy = _ty(float(elem.get('cy', '0')))
            r = _tw(float(elem.get('r', '0')))
            stroke = _parse_color(elem.get('stroke', 'none'))
            fill = _parse_color(elem.get('fill', 'none'))
            width = max(1, int(_tw(float(elem.get('stroke-width', '0.2')))))
            bbox = [(cx - r, cy - r), (cx + r, cy + r)]
            if fill:
                draw.ellipse(bbox, fill=fill)
            if stroke:
                draw.ellipse(bbox, outline=stroke, width=width)

        elif tag in ('polyline', 'polygon'):
            points_str = elem.get('points', '')
            if not points_str:
                return
            points = []
            for pt in points_str.strip().split():
                parts = pt.split(',')
                if len(parts) >= 2:
                    points.append((_tx(float(parts[0])), _ty(float(parts[1]))))
            if len(points) < 2:
                return
            stroke = _parse_color(elem.get('stroke', 'none'))
            fill = _parse_color(elem.get('fill', 'none'))
            width = max(1, int(_tw(float(elem.get('stroke-width', '0.2')))))
            if tag == 'polygon' and fill:
                draw.polygon(points, fill=fill, outline=stroke, width=width)
            elif stroke:
                draw.line(points, fill=stroke, width=width)

        elif tag == 'path':
            # Simplified path rendering — handle M, L, A, C commands
            d = elem.get('d', '')
            stroke = _parse_color(elem.get('stroke', 'none'))
            fill = _parse_color(elem.get('fill', 'none'))
            width = max(1, int(_tw(float(elem.get('stroke-width', '0.2')))))
            _render_path(draw, d, stroke, fill, width, _tx, _ty, _tw)

        elif tag == 'text':
            x = _tx(float(elem.get('x', '0')))
            y = _ty(float(elem.get('y', '0')))
            content = elem.text or ''
            if not content.strip():
                return
            font_size = float(elem.get('font-size', '1.27'))
            fill = _parse_color(elem.get('fill', '#000000'))
            font = _get_font(font_size)
            anchor = elem.get('text-anchor', 'start')

            # Approximate text positioning
            try:
                bbox = font.getbbox(content)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            except (AttributeError, TypeError):
                text_w = len(content) * font_size * scale_x * 0.6
                text_h = font_size * scale_y

            if anchor == 'middle':
                x -= text_w / 2
            elif anchor == 'end':
                x -= text_w

            db = elem.get('dominant-baseline', 'auto')
            if db == 'central':
                y -= text_h / 2

            if fill:
                draw.text((x, y), content, fill=fill, font=font)

    def _render_path(draw, d, stroke, fill, width, tx, ty, tw):
        """Render a simplified SVG path (M, L, A, C commands)."""
        # Extract points for line segments from the path
        points = []
        tokens = re.findall(r'[MmLlAaCcZz]|[-+]?\d*\.?\d+', d)
        i = 0
        cx, cy = 0.0, 0.0
        while i < len(tokens):
            cmd = tokens[i]
            if cmd in ('M', 'm'):
                i += 1
                if i + 1 < len(tokens):
                    cx, cy = float(tokens[i]), float(tokens[i + 1])
                    points.append((tx(cx), ty(cy)))
                    i += 2
            elif cmd in ('L', 'l'):
                i += 1
                if i + 1 < len(tokens):
                    if cmd == 'L':
                        cx, cy = float(tokens[i]), float(tokens[i + 1])
                    else:
                        cx += float(tokens[i])
                        cy += float(tokens[i + 1])
                    points.append((tx(cx), ty(cy)))
                    i += 2
            elif cmd in ('A', 'a'):
                # Arc: rx ry rotation large-arc sweep x y
                i += 1
                if i + 6 < len(tokens):
                    ex, ey = float(tokens[i + 5]), float(tokens[i + 6])
                    if cmd == 'a':
                        ex += cx
                        ey += cy
                    # Approximate arc with line to endpoint
                    cx, cy = ex, ey
                    points.append((tx(cx), ty(cy)))
                    i += 7
            elif cmd in ('C', 'c'):
                # Cubic bezier: x1 y1 x2 y2 x y
                i += 1
                if i + 5 < len(tokens):
                    ex, ey = float(tokens[i + 4]), float(tokens[i + 5])
                    if cmd == 'c':
                        ex += cx
                        ey += cy
                    cx, cy = ex, ey
                    points.append((tx(cx), ty(cy)))
                    i += 6
            elif cmd in ('Z', 'z'):
                if points:
                    points.append(points[0])
                i += 1
            else:
                # Try to parse as coordinate continuation
                try:
                    x_val = float(tokens[i])
                    if i + 1 < len(tokens):
                        y_val = float(tokens[i + 1])
                        cx, cy = x_val, y_val
                        points.append((tx(cx), ty(cy)))
                        i += 2
                    else:
                        i += 1
                except ValueError:
                    i += 1

        if len(points) >= 2 and stroke:
            draw.line(points, fill=stroke, width=width)

    # Render all elements
    for child in root:
        _render_element(child)

    # Save
    os.makedirs(os.path.dirname(os.path.abspath(png_path)) or '.', exist_ok=True)
    img.save(png_path, 'PNG', optimize=True)
    return png_path


_NAMED_COLORS = {
    'white': (255, 255, 255), 'black': (0, 0, 0),
    'red': (255, 0, 0), 'green': (0, 128, 0), 'blue': (0, 0, 255),
}


def _parse_color(color_str: str | None) -> tuple | None:
    """Parse SVG color string to PIL color tuple."""
    if not color_str or color_str == 'none':
        return None
    color_str = color_str.strip()
    if color_str.startswith('#'):
        from .theme import hex_to_rgb
        try:
            return hex_to_rgb(color_str)
        except (ValueError, IndexError):
            return None
    return _NAMED_COLORS.get(color_str.lower())


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.svg> <output.png> [dpi]")
        sys.exit(1)
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    svg_to_png(sys.argv[1], sys.argv[2], dpi=dpi)
    print(f"Written: {sys.argv[2]}", file=sys.stderr)

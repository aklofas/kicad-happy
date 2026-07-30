"""Shared SVG-to-PNG rasterization utility.

Used by kidoc_docx.py and kidoc_odt.py for embedding figures in
document formats that don't support inline SVG.  Wraps the Pillow-based
rasterizer from ``figures.lib.svg_to_png``.
"""

from __future__ import annotations

import os
import tempfile

try:
    from figures.lib.svg_to_png import svg_to_png as _svg_to_png_impl
    _HAS_SVG_RENDER = True
except ImportError:
    _HAS_SVG_RENDER = False


def has_svg_render() -> bool:
    """Check whether SVG rasterization is available."""
    return _HAS_SVG_RENDER


def svg_to_png(svg_path: str, dpi: int = 300) -> str | None:
    """Convert SVG to a temporary PNG file.  Returns PNG path or None."""
    if not _HAS_SVG_RENDER or not os.path.isfile(svg_path):
        return None
    try:
        fd, png_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        _svg_to_png_impl(svg_path, png_path, dpi=dpi)
        return png_path
    except Exception:
        return None


def get_dpi(config: dict) -> int:
    """Extract schematic rendering DPI from config."""
    return config.get('reports', {}).get('rendering', {}).get('schematic_dpi', 300)

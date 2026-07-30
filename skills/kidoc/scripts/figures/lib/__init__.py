"""Shared figure generation library.

Re-exports core primitives, theming, and drawing helpers so generators
can do::

    from figures.lib import SvgBuilder, FigureTheme, draw_header_box
"""

from .svg_builder import SvgBuilder, three_point_arc
from .theme import FigureTheme, lighten, darken, blend, hex_to_rgb, rgb_to_hex
from .analysis_helpers import build_pin_nets
from .styles import (
    # Legacy constants
    BOX_FILL, BOX_STROKE, BOX_FONT,
    POWER_FILL, POWER_STROKE, POWER_FONT,
    BUS_FILL, BUS_STROKE, BUS_FONT,
    IO_FILL, IO_STROKE, IO_FONT,
    ARROW_COLOR, LABEL_FONT, BG_COLOR,
    BOX_CORNER_RADIUS, BOX_PADDING, FONT_SIZE, SMALL_FONT, ARROW_HEAD_SIZE,
    # Legacy drawing helpers
    _draw_box, _draw_arrow, _draw_bus_line, _format_cap_summary,
    # Advanced drawing helpers
    draw_gradient_box, draw_shadow_box, draw_header_box,
    draw_pill, draw_port, draw_curved_arrow, draw_right_angle_arrow,
)

__all__ = [
    'SvgBuilder', 'three_point_arc',
    'FigureTheme', 'lighten', 'darken', 'blend', 'hex_to_rgb', 'rgb_to_hex',
    # Drawing helpers
    'draw_gradient_box', 'draw_shadow_box', 'draw_header_box',
    'draw_pill', 'draw_port', 'draw_curved_arrow', 'draw_right_angle_arrow',
    '_draw_box', '_draw_arrow', '_draw_bus_line', '_format_cap_summary',
    'build_pin_nets',
]

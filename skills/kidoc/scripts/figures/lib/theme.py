"""Centralized figure theme consumed by all figure generators.

Built from branding config colors (`.kicad-happy.json`) with sensible
defaults.  Contains semantic color roles, font sizes, and layout constants.
All color values are CSS hex strings (#rrggbb).

Zero external dependencies — Python 3.8+ stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


# ======================================================================
# Color math helpers
# ======================================================================

def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Parse '#rrggbb' or '#rgb' to (r, g, b) ints."""
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (r, g, b) ints to '#rrggbb'."""
    return f"#{min(255,max(0,r)):02x}{min(255,max(0,g)):02x}{min(255,max(0,b)):02x}"


# Backward-compatible aliases
_hex_to_rgb = hex_to_rgb
_rgb_to_hex = rgb_to_hex


def lighten(hex_color: str, factor: float = 0.15) -> str:
    """Lighten a hex color toward white.  factor 0.0=unchanged, 1.0=white."""
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return _rgb_to_hex(r, g, b)


def darken(hex_color: str, factor: float = 0.08) -> str:
    """Darken a hex color toward black.  factor 0.0=unchanged, 1.0=black."""
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r * (1 - factor))
    g = int(g * (1 - factor))
    b = int(b * (1 - factor))
    return _rgb_to_hex(r, g, b)


def blend(color1: str, color2: str, t: float = 0.5) -> str:
    """Blend two hex colors.  t=0.0 returns color1, t=1.0 returns color2."""
    r1, g1, b1 = _hex_to_rgb(color1)
    r2, g2, b2 = _hex_to_rgb(color2)
    return _rgb_to_hex(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


# ======================================================================
# FigureTheme
# ======================================================================

# Type aliases for color tuples (fill, stroke, font)
ColorTriple = Tuple[str, str, str]


@dataclass(frozen=True)
class FigureTheme:
    """Centralized theme consumed by all figure generators.

    Built from `.kicad-happy.json` branding config via ``from_config()``.
    Calling ``FigureTheme()`` with no args gives the current hardcoded
    defaults, ensuring full backward compatibility.
    """

    # -- Brand foundation (from .kicad-happy.json reports.branding.colors) --
    primary: str = "#1a1a2e"
    accent: str = "#0f4c75"
    highlight: str = "#1b6ca8"

    # -- Domain: generic boxes --
    box_fill: str = "#e8e8ff"
    box_stroke: str = "#4040c0"
    box_font: str = "#202060"

    # -- Domain: power --
    power_fill: str = "#fff0e0"
    power_stroke: str = "#c06000"
    power_font: str = "#804000"

    # -- Domain: bus / communication --
    bus_fill: str = "#e0ffe0"
    bus_stroke: str = "#008040"
    bus_font: str = "#004020"

    # -- Domain: I/O / connectors --
    io_fill: str = "#ffe0e0"
    io_stroke: str = "#c04040"
    io_font: str = "#802020"

    # -- Neutral / labels / arrows --
    arrow_color: str = "#606060"
    label_font: str = "#404040"
    bg_color: str = "#ffffff"
    title_color: str = "#1a1a1a"

    # -- Power tree palette --
    pt_input_fill: str = "#1a3c5c"
    pt_input_text: str = "#ffffff"
    pt_input_subtext: str = "#8ab4e0"
    pt_reg_fill: str = "#f0f4f8"
    pt_reg_stroke: str = "#4a6fa5"
    pt_reg_text: str = "#1a3c5c"
    pt_prot_fill: str = "#eceff1"
    pt_prot_stroke: str = "#78909c"
    pt_prot_text: str = "#37474f"
    pt_arrow_color: str = "#4a6fa5"
    pt_enable_color: str = "#888888"
    pt_output_colors: Tuple[ColorTriple, ...] = (
        ("#a5d6a7", "#2e7d32", "#1b5e20"),
        ("#ffcc80", "#e65100", "#bf360c"),
        ("#90caf9", "#0d47a1", "#0a3474"),
        ("#ce93d8", "#6a1b9a", "#4a148c"),
        ("#fff176", "#f57f17", "#e65100"),
        ("#ef9a9a", "#c62828", "#b71c1c"),
    )

    # -- Pinout palette --
    pin_power: ColorTriple = ("#ffebee", "#c62828", "#b71c1c")
    pin_ground: ColorTriple = ("#eceff1", "#37474f", "#263238")
    pin_signal: ColorTriple = ("#e3f2fd", "#1565c0", "#0d47a1")
    pin_nc: ColorTriple = ("#f5f5f5", "#bdbdbd", "#9e9e9e")
    pin_esd_ok: str = "#43a047"
    pin_esd_missing: str = "#c62828"

    # -- Architecture cluster color map --
    arch_color_map: Dict[str, ColorTriple] = field(default_factory=dict)

    # -- Font sizes (mm, matching KiCad coordinate system) --
    font_title: float = 5.0
    font_heading: float = 3.5
    font_body: float = 2.5
    font_small: float = 1.8
    font_caption: float = 2.8

    # -- Layout constants (mm) --
    box_corner_radius: float = 2.0
    box_padding: float = 3.0
    arrow_head_size: float = 1.5

    # -- Advanced rendering flags --
    use_gradients: bool = True
    shadow_opacity: float = 0.08
    shadow_offset: float = 0.5

    def __post_init__(self) -> None:
        """Populate arch_color_map default if empty."""
        if not self.arch_color_map:
            object.__setattr__(self, 'arch_color_map', {
                'MCU / CPU': (self.box_fill, self.box_stroke, self.box_font),
                'Power': (self.power_fill, self.power_stroke, self.power_font),
                'Communication': (self.bus_fill, self.bus_stroke, self.bus_font),
                'Memory': ('#e8f0ff', '#4060c0', '#203060'),
                'Sensors': ('#f0ffe0', '#40a040', '#204020'),
                'Connectors': (self.io_fill, self.io_stroke, self.io_font),
                'Protection': ('#fff0f0', '#c06060', '#804040'),
                'LEDs / Display': ('#fff8e0', '#c0a000', '#806000'),
                'Audio / Output': ('#f0f0ff', '#6060c0', '#404080'),
                'Other ICs': ('#f0f0f0', '#808080', '#404040'),
            })

    @classmethod
    def from_config(cls, config: Optional[dict] = None) -> 'FigureTheme':
        """Build a theme from .kicad-happy.json config dict.

        Reads ``reports.branding.colors``, derives figure colors from
        the brand palette, and fills defaults for anything missing.
        Returns the default theme if *config* is None or has no colors.
        """
        if not config:
            return cls()

        colors = (config.get('reports', {})
                  .get('branding', {})
                  .get('colors', {}))
        if not colors:
            return cls()

        primary = colors.get('primary', '#1a1a2e')
        accent = colors.get('accent', '#0f4c75')
        highlight = colors.get('highlight', '#1b6ca8')

        # Derive figure-specific colors from brand palette.
        # The idea: brand primary drives headings/titles and power tree
        # input rails; accent drives strokes and structural lines;
        # highlight drives interactive/emphasis elements.
        primary_light = lighten(primary, 0.85)
        accent_light = lighten(accent, 0.80)

        return cls(
            primary=primary,
            accent=accent,
            highlight=highlight,
            # Generic boxes pick up accent for stroke
            box_stroke=accent,
            box_font=primary,
            box_fill=accent_light,
            # Title
            title_color=primary,
            # Power tree: primary for input rails
            pt_input_fill=primary,
            pt_input_text='#ffffff',
            pt_input_subtext=lighten(primary, 0.50),
            pt_reg_stroke=accent,
            pt_reg_text=primary,
            pt_arrow_color=accent,
            # Architecture: MCU uses brand colors
            # (arch_color_map auto-populated from these in __post_init__)
        )

    @classmethod
    def flat(cls) -> 'FigureTheme':
        """Return a theme with gradients and shadows disabled."""
        return cls(use_gradients=False, shadow_opacity=0.0)

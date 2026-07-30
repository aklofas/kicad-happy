"""Schematic rendering constants (KiCad convention mappings).

Named constants for magic numbers used in the schematic SVG renderer.
All dimensions are in millimetres unless noted otherwise.
"""

# ======================================================================
# Font rendering
# ======================================================================

# KiCad's Hershey font glyphs use a 4/3 height-to-em ratio when
# rendered as SVG <text> elements.  This is a KiCad convention and
# should not be changed without verifying against KiCad output.
FONT_SCALE = 4 / 3

# Font sizes in mm — multiply by FONT_SCALE for SVG em size.
JUNCTION_LABEL_FONT_MM = 1.27
GRID_BORDER_FONT_MM = 1.3
TITLE_BLOCK_BODY_FONT_MM = 1.5
TITLE_BLOCK_TITLE_FONT_MM = 2.0

# ======================================================================
# Pin layout
# ======================================================================

# Pin-to-text margin: KiCad's PIN_TEXT_MARGIN is 4 mils = 0.1016 mm.
PIN_TEXT_MARGIN_MM = 0.1016

# Gap between pin tip and label text, as a fraction of label font size.
PIN_LABEL_GAP_FACTOR = 0.3

# ======================================================================
# Page layout
# ======================================================================

# Margin from paper edge to inner drawing border (mm).
DEFAULT_PAGE_MARGIN_MM = 10.0

# KiCad uses a fixed 50 mm grid step for the drawing sheet border.
GRID_STEP_MM = 50.0

# Tick mark length on the inner border (mm).
TICK_LENGTH_MM = 2.0

# Schematic SVG Rendering Notes

## Coordinate System

KiCad uses two coordinate conventions that must be reconciled:

- **Schematic placement** (`.kicad_sch` top level): millimetres, Y-down (screen convention)
- **Symbol library internals** (`lib_symbols`): millimetres, Y-up (math convention)

The transform pipeline for each symbol graphic primitive:

1. **Mirror** (before rotation): if `mirror_x`, negate Y; if `mirror_y`, negate X
2. **Rotate**: standard 2D rotation by component angle (CCW positive, degrees)
3. **Translate + Y-flip**: `abs_x = cx + rpx`, `abs_y = cy - rpy`

This matches `compute_pin_positions()` in `analyze_schematic.py`.

## SVG Constraints (svglib compatibility)

The SVGs must be parseable by svglib for downstream PDF embedding via ReportLab.
svglib has limited SVG support, so we constrain output to:

- Inline style attributes only (no `<style>` blocks, no CSS classes)
- No gradients (`<linearGradient>`, `<radialGradient>`)
- No masks or clipping (beyond simple rectangles)
- No `<use>` / `<defs>` reuse (each element rendered inline)
- No `<foreignObject>`
- Basic shapes: `<line>`, `<rect>`, `<circle>`, `<ellipse>`, `<polyline>`, `<polygon>`, `<path>`, `<text>`, `<g>`

## Arc Conversion

KiCad arcs are defined by 3 points (start, mid, end).  SVG arcs use the
centre-point parameterisation (`A rx,ry rotation large-arc-flag sweep-flag x,y`).

Conversion in `svg_builder.three_point_arc()`:
1. Find circle centre from 3 points via perpendicular bisector intersection
2. Compute radius as distance from centre to any point
3. Determine sweep direction from cross product of (start→mid) × (start→end)
4. Determine large-arc flag by checking if midpoint lies on the minor arc

## Color Theme

Colors are hardcoded in `color_theme.py` to match the **KiCad Default** color
theme (the built-in theme shipped with KiCad, not a custom user theme).

Schematic element colors:
- Component outlines: dark red (#840000), fills: light yellow (#ffffc8)
- Wires/junctions: green (#00841a), buses: blue (#0000c8)
- Pins: dark red (#840000), pin names: teal (#006464), pin numbers: #A90000
- Labels: green (#00841a), global labels: dark red, hier labels: #840064
- Power symbols: dark red, references/values: green
- Sheet borders: purple (#72009a), title block: dark red

PCB documentation uses a separate muted palette (`PCB_DOC_COLORS`) designed
for white-background output: F.Cu red (#cc3333), B.Cu blue (#3333cc),
silk dark gray, fab light gray.

## Font Scaling

KiCad's Hershey stroke font stores glyph height in mm, but SVG `font-size`
is an em-box metric.  The conversion factor is **4/3**:

    SVG font-size = KiCad stored height * (4/3)

This is applied globally via `FONT_SCALE = 4 / 3` in `figures/renderers/schematic.py`.
A 1.27mm stored height becomes ~1.69mm rendered, matching KiCad's on-screen
appearance.

## Dash Patterns (ISO 128-2)

Line styles (dash, dot, dash_dot, dash_dot_dot) use stroke-width-proportional
patterns per ISO 128-2.  The `_dash_pattern()` function scales dash/gap
lengths relative to line width `w`:

| Style | Pattern |
|-------|---------|
| dash | 11w on, 4w off |
| dot | 0.2w on, 4w off |
| dash_dot | 11w, 4w, 0.2w, 4w |
| dash_dot_dot | 11w, 4w, 0.2w, 4w, 0.2w, 4w |

## Pin Text Rendering

Pin text uses KiCad's two-mode `PlotPinTexts` logic, controlled by the
symbol's `pin_name_offset` value:

- **text_inside** (`pin_name_offset > 0`): pin name is placed inside the
  symbol body, offset from the body edge by `pin_name_offset` mm.  Pin number
  is at the midpoint of the pin line.
- **text_outside** (`pin_name_offset == 0`): both name and number are stacked
  at the midpoint of the pin line.

A 4-mil (`PIN_TEXT_MARGIN_MM = 0.1016`) margin separates text from the pin
line, matching KiCad's `PIN_TEXT_MARGIN` constant.

## Net Annotations

The `--pin-nets` option accepts a JSON file mapping `{ "ref": { "pin_number": "net_name" } }`.
When provided, net names are rendered as annotations on pin tips, allowing
schematic SVGs to show connectivity information without requiring full netlists.

## PCB Rendering

`figures/renderers/pcb.py` renders `.kicad_pcb` files to SVG using named layer presets
defined in `layer_presets.py`.  Available presets:

| Preset | Layers shown | Use case |
|--------|-------------|----------|
| `assembly-front` | Edge.Cuts, F.SilkS, F.Fab, F.CrtYd | Assembly drawing |
| `assembly-back` | Edge.Cuts, B.SilkS, B.Fab, B.CrtYd | Back assembly |
| `routing-front` | Edge.Cuts, F.Cu, F.SilkS (dimmed) | Front copper review |
| `routing-back` | Edge.Cuts, B.Cu, B.SilkS (dimmed) | Back copper review |
| `routing-all` | Edge.Cuts, all Cu, F.SilkS (dimmed) | Full routing overview |
| `power` | Edge.Cuts, F.Cu/B.Cu (dimmed) | Power net highlighting |

All presets use white backgrounds and muted documentation colors.  Custom
presets can be built via `custom_preset()` with per-layer color, opacity,
and stroke width control.

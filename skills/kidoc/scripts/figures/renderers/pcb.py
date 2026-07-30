#!/usr/bin/env python3
"""PCB SVG renderer for kidoc documentation.

Renders ``.kicad_pcb`` files to publication-quality SVG output using
layer visibility presets.  Supports assembly views, routing views,
net highlighting, and region cropping.

Usage:
    python3 pcb_render.py board.kicad_pcb --output out/ --preset assembly-front
    python3 pcb_render.py board.kicad_pcb --output out/ --preset routing-front
    python3 pcb_render.py board.kicad_pcb --output out/ --preset routing-all \\
        --highlight-nets GND,+3V3

Zero external dependencies -- Python 3.8+ stdlib only (+ kicad skill's sexp_parser).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ._path_setup import setup_kicad_imports
setup_kicad_imports()

from figures.lib.svg_builder import SvgBuilder, three_point_arc, _f  # noqa: E402
from .pcb_graphics import (  # noqa: E402
    extract_pcb, BoardOutline, FootprintInfo, PadInfo,
    TrackInfo, ArcTrackInfo, ViaInfo, ZoneOutline, FpGraphic,
)
from figures.lib.layer_presets import (  # noqa: E402
    LayerPreset, LayerStyle, PRESETS, get_preset,
    layer_visible, layer_style,
)
from figures.lib.color_theme import (  # noqa: E402
    PCB_PAD_COLOR, PCB_VIA_COLOR, PCB_DRILL_COLOR,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MARGIN = 5.0       # mm around board bbox
_HIGHLIGHT_COLOR = "#ff6600"
_HIGHLIGHT_OPACITY = 1.0
_ZONE_DASH = "1.0,0.5"     # dashed zone outlines
_REF_FONT_SIZE = 0.8        # mm
_REF_FONT_FAMILY = "sans-serif"
_ANNOTATION_FONT_SIZE = 0.8 # mm


# ---------------------------------------------------------------------------
# PCB region crop (Task 18)
# ---------------------------------------------------------------------------

def compute_pcb_crop(footprints: List[FootprintInfo], refs: List[str],
                     padding: float = _DEFAULT_MARGIN) -> Optional[Tuple[float, float, float, float]]:
    """Compute a crop bbox around the specified component references.

    Uses footprint positions and courtyard bounding boxes to determine the
    tightest region containing the listed refs, then adds *padding* mm on
    each side.

    Returns:
        ``(x, y, w, h)`` in mm, or ``None`` if no matching footprints.
    """
    xs: List[float] = []
    ys: List[float] = []
    ref_set = set(refs)
    for fp in footprints:
        if fp.reference in ref_set:
            xs.append(fp.x)
            ys.append(fp.y)
            if fp.courtyard_bbox:
                # courtyard_bbox is (min_x, min_y, max_x, max_y)
                xs.extend([fp.courtyard_bbox[0], fp.courtyard_bbox[2]])
                ys.extend([fp.courtyard_bbox[1], fp.courtyard_bbox[3]])
    if not xs:
        return None
    return (min(xs) - padding, min(ys) - padding,
            max(xs) - min(xs) + 2 * padding,
            max(ys) - min(ys) + 2 * padding)


# ---------------------------------------------------------------------------
# Annotation overlays (Task 19)
# ---------------------------------------------------------------------------

def render_annotations(svg: SvgBuilder, annotations: List[Dict]) -> None:
    """Render callout-box annotations on the SVG.

    Each annotation dict may contain:
        x, y        -- position in mm (board coordinates)
        text        -- label string
        color       -- stroke/text color (default ``#2060c0``)
        bg          -- background fill (default ``#e8f0ff``)
        arrow_to    -- optional ``[tx, ty]`` target for a leader line
    """
    font_size = _ANNOTATION_FONT_SIZE
    for ann in annotations:
        x, y = ann["x"], ann["y"]
        text = ann["text"]
        color = ann.get("color", "#2060c0")
        bg = ann.get("bg", "#e8f0ff")
        text_w = len(text) * font_size * 0.55
        pad = 0.4
        svg.rect(x - pad, y - font_size * 0.7 - pad,
                 text_w + 2 * pad, font_size * 1.4 + 2 * pad,
                 stroke=color, fill=bg, stroke_width=0.08, rx=0.3)
        svg.text(x, y, text, font_size=font_size, fill=color,
                 dominant_baseline="central")
        arrow_to = ann.get("arrow_to")
        if arrow_to:
            svg.line(x + text_w / 2, y + font_size * 0.7 + pad,
                     arrow_to[0], arrow_to[1],
                     stroke=color, stroke_width=0.1)


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _resolve_style(preset: LayerPreset, layer: str) -> Optional[LayerStyle]:
    """Return the LayerStyle for *layer* within *preset*, or None."""
    return layer_style(preset, layer)


def _is_highlighted(net_name: str, highlight_nets: Optional[Set[str]]) -> bool:
    """Check if a net should be highlighted."""
    if not highlight_nets:
        return False
    return net_name in highlight_nets


# ---------------------------------------------------------------------------
# Board outline
# ---------------------------------------------------------------------------

def render_board_outline(svg: SvgBuilder, outline: BoardOutline,
                         color: str, stroke_width: float) -> None:
    """Render Edge.Cuts edges (line, rect, circle, arc, polygon)."""
    for edge in outline.edges:
        etype = edge["type"]

        if etype == "line":
            sx, sy = edge["start"]
            ex, ey = edge["end"]
            svg.line(sx, sy, ex, ey, stroke=color, stroke_width=stroke_width)

        elif etype == "rect":
            sx, sy = edge["start"]
            ex, ey = edge["end"]
            x = min(sx, ex)
            y = min(sy, ey)
            w = abs(ex - sx)
            h = abs(ey - sy)
            svg.rect(x, y, w, h, stroke=color, fill="none",
                     stroke_width=stroke_width)

        elif etype == "circle":
            cx, cy = edge["center"]
            ex, ey = edge["end"]
            r = math.hypot(ex - cx, ey - cy)
            svg.circle(cx, cy, r, stroke=color, fill="none",
                       stroke_width=stroke_width)

        elif etype == "arc":
            sx, sy = edge["start"]
            ex, ey = edge["end"]
            mid = edge.get("mid")
            if mid:
                mx, my = mid
                _cx, _cy, r, large_arc, sweep = three_point_arc(
                    sx, sy, mx, my, ex, ey)
                svg.arc(sx, sy, ex, ey, r, large_arc, sweep,
                        stroke=color, fill="none", stroke_width=stroke_width)
            else:
                # Fallback: straight line if no midpoint
                svg.line(sx, sy, ex, ey, stroke=color,
                         stroke_width=stroke_width)

        elif etype == "polygon":
            pts = edge["points"]
            svg.polyline(pts, stroke=color, fill="none",
                         stroke_width=stroke_width, closed=True)


# ---------------------------------------------------------------------------
# Pads
# ---------------------------------------------------------------------------

def _render_pad_shape(svg: SvgBuilder, pad: PadInfo, x: float, y: float,
                      w: float, h: float, color: str) -> None:
    """Render the pad shape geometry (no drill, no rotation wrapper)."""
    if pad.shape == "circle":
        r = w / 2 if w > 0 else 0.5
        svg.circle(x, y, r, stroke="none", fill=color, stroke_width=0)
    elif pad.shape == "roundrect":
        corner_radius = pad.corner_ratio * min(w, h)
        svg.rect(x - w / 2, y - h / 2, w, h,
                 stroke="none", fill=color, stroke_width=0, rx=corner_radius)
    elif pad.shape == "rect":
        svg.rect(x - w / 2, y - h / 2, w, h,
                 stroke="none", fill=color, stroke_width=0)
    elif pad.shape == "oval":
        svg.rect(x - w / 2, y - h / 2, w, h,
                 stroke="none", fill=color, stroke_width=0,
                 rx=min(w, h) / 2)
    elif pad.shape == "trapezoid":
        # Approximate as rect
        svg.rect(x - w / 2, y - h / 2, w, h,
                 stroke="none", fill=color, stroke_width=0)
    elif pad.shape == "custom":
        # Approximate as circle from pad size
        r = max(w, h) / 2 if (w > 0 or h > 0) else 0.5
        svg.circle(x, y, r, stroke="none", fill=color, stroke_width=0)
    else:
        # Unknown shape -- small circle fallback
        svg.circle(x, y, max(w, h) / 2 if (w > 0 or h > 0) else 0.5,
                   stroke="none", fill=color, stroke_width=0)


def render_pad(svg: SvgBuilder, pad: PadInfo, color: str) -> None:
    """Render a single pad shape, with rotation if needed."""
    x, y = pad.abs_x, pad.abs_y
    w, h = pad.width, pad.height

    if pad.pad_angle != 0 and pad.shape not in ("circle",):
        with svg.group(transform=f"rotate({_f(pad.pad_angle)},{_f(x)},{_f(y)})"):
            _render_pad_shape(svg, pad, x, y, w, h, color)
    else:
        _render_pad_shape(svg, pad, x, y, w, h, color)


# ---------------------------------------------------------------------------
# Footprint graphics (silk, fab, courtyard)
# ---------------------------------------------------------------------------

def render_footprint_graphics(svg: SvgBuilder, fp: FootprintInfo,
                              preset: LayerPreset) -> None:
    """Render fp_line/fp_rect/fp_circle/fp_arc/fp_poly on visible layers."""
    for g in fp.graphics:
        style = _resolve_style(preset, g.layer)
        if style is None:
            continue

        color = style.color
        sw = style.stroke_width if style.stroke_width > 0 else max(g.width, 0.1)

        with svg.group(opacity=style.opacity):
            if g.gtype == "line":
                s = g.points["start"]
                e = g.points["end"]
                svg.line(s[0], s[1], e[0], e[1],
                         stroke=color, stroke_width=sw)

            elif g.gtype == "rect":
                s = g.points["start"]
                e = g.points["end"]
                x = min(s[0], e[0])
                y = min(s[1], e[1])
                w = abs(e[0] - s[0])
                h = abs(e[1] - s[1])
                svg.rect(x, y, w, h, stroke=color, fill="none",
                         stroke_width=sw)

            elif g.gtype == "circle":
                c = g.points["center"]
                e = g.points["end"]
                r = math.hypot(e[0] - c[0], e[1] - c[1])
                svg.circle(c[0], c[1], r, stroke=color, fill="none",
                           stroke_width=sw)

            elif g.gtype == "arc":
                s = g.points["start"]
                e = g.points["end"]
                mid = g.points.get("mid")
                if mid:
                    _cx, _cy, r, large_arc, sweep = three_point_arc(
                        s[0], s[1], mid[0], mid[1], e[0], e[1])
                    svg.arc(s[0], s[1], e[0], e[1], r, large_arc, sweep,
                            stroke=color, fill="none", stroke_width=sw)
                else:
                    svg.line(s[0], s[1], e[0], e[1],
                             stroke=color, stroke_width=sw)

            elif g.gtype == "poly":
                pts = g.points.get("points", [])
                if pts:
                    svg.polyline(pts, stroke=color, fill="none",
                                 stroke_width=sw, closed=True)


# ---------------------------------------------------------------------------
# Reference designator text
# ---------------------------------------------------------------------------

def render_footprint_ref(svg: SvgBuilder, fp: FootprintInfo,
                         color: str, font_size: float) -> None:
    """Render reference designator text at the footprint center."""
    if not fp.reference:
        return
    svg.text(fp.x, fp.y, fp.reference,
             font_size=font_size, font_family=_REF_FONT_FAMILY,
             anchor="middle", dominant_baseline="central",
             fill=color, bold=True)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

def render_tracks(svg: SvgBuilder, segments: List[TrackInfo],
                  arcs: List[ArcTrackInfo], preset: LayerPreset,
                  highlight_nets: Optional[Set[str]] = None,
                  highlight_color: str = _HIGHLIGHT_COLOR) -> None:
    """Render track segments and arcs on visible layers."""
    for seg in segments:
        style = _resolve_style(preset, seg.layer)
        if style is None:
            continue

        hi = _is_highlighted(seg.net_name, highlight_nets)
        color = highlight_color if hi else style.color
        opacity = _HIGHLIGHT_OPACITY if hi else style.opacity
        sw = seg.width if seg.width > 0 else 0.25

        with svg.group(opacity=opacity):
            svg.line(seg.x1, seg.y1, seg.x2, seg.y2,
                     stroke=color, stroke_width=sw)

    for arc in arcs:
        style = _resolve_style(preset, arc.layer)
        if style is None:
            continue

        hi = _is_highlighted(arc.net_name, highlight_nets)
        color = highlight_color if hi else style.color
        opacity = _HIGHLIGHT_OPACITY if hi else style.opacity
        sw = arc.width if arc.width > 0 else 0.25

        with svg.group(opacity=opacity):
            sx, sy = arc.start
            ex, ey = arc.end
            if arc.mid:
                mx, my = arc.mid
                _cx, _cy, r, large_arc, sweep = three_point_arc(
                    sx, sy, mx, my, ex, ey)
                svg.arc(sx, sy, ex, ey, r, large_arc, sweep,
                        stroke=color, fill="none", stroke_width=sw)
            else:
                svg.line(sx, sy, ex, ey, stroke=color, stroke_width=sw)


# ---------------------------------------------------------------------------
# Vias
# ---------------------------------------------------------------------------

def render_vias(svg: SvgBuilder, vias: List[ViaInfo],
                color: str, drill_color: str,
                highlight_nets: Optional[Set[str]] = None,
                highlight_color: str = _HIGHLIGHT_COLOR) -> None:
    """Render via circles (drill knockout handled by render_drill_marks)."""
    for via in vias:
        hi = _is_highlighted(via.net_name, highlight_nets)
        c = highlight_color if hi else color
        r = via.size / 2 if via.size > 0 else 0.3
        svg.circle(via.x, via.y, r, stroke="none", fill=c, stroke_width=0)


# ---------------------------------------------------------------------------
# Drill marks (knockout circles)
# ---------------------------------------------------------------------------

def render_drill_marks(svg: SvgBuilder, footprints: List[FootprintInfo],
                       vias: List[ViaInfo],
                       drill_color: str = '#ffffff') -> None:
    """Render drill holes as knockout circles (white) over pads and vias."""
    for fp in footprints:
        for pad in fp.pads:
            if pad.drill > 0:
                svg.circle(pad.abs_x, pad.abs_y, pad.drill / 2,
                           fill=drill_color, stroke='none', stroke_width=0)
    for via in vias:
        if via.drill > 0:
            svg.circle(via.x, via.y, via.drill / 2,
                       fill=drill_color, stroke='none', stroke_width=0)


# ---------------------------------------------------------------------------
# Zone outlines
# ---------------------------------------------------------------------------

def render_zone_outlines(svg: SvgBuilder, zones: List[ZoneOutline],
                         preset: LayerPreset,
                         highlight_nets: Optional[Set[str]] = None,
                         highlight_color: str = _HIGHLIGHT_COLOR) -> None:
    """Render dashed zone boundary outlines on visible layers."""
    for zone in zones:
        style = _resolve_style(preset, zone.layer)
        if style is None:
            continue

        hi = _is_highlighted(zone.net_name, highlight_nets)
        color = highlight_color if hi else style.color
        opacity = _HIGHLIGHT_OPACITY if hi else style.opacity * 0.5

        with svg.group(opacity=opacity):
            svg.polyline(zone.points, stroke=color, fill="none",
                         stroke_width=0.15, closed=True)
            # Apply dash via direct attribute (polyline returns element)
            # Re-render with dash -- svg_builder polyline doesn't support dash,
            # so we draw it as a path instead.
        # Redraw as dashed path
        if len(zone.points) >= 2:
            d_parts = [f"M {_f(zone.points[0][0])},{_f(zone.points[0][1])}"]
            for pt in zone.points[1:]:
                d_parts.append(f"L {_f(pt[0])},{_f(pt[1])}")
            d_parts.append("Z")
            with svg.group(opacity=opacity):
                elem = svg.path(" ".join(d_parts), stroke=color, fill="none",
                                stroke_width=0.15)
                elem.set("stroke-dasharray", _ZONE_DASH)


# ---------------------------------------------------------------------------
# Main render pipeline
# ---------------------------------------------------------------------------

def render_pcb(pcb_path: str, output_dir: str,
               preset_name: str = "assembly-front",
               highlight_nets: Optional[List[str]] = None,
               crop_bbox: Optional[Tuple[float, float, float, float]] = None,
               crop_refs: Optional[List[str]] = None,
               mirror: bool = False,
               annotations: Optional[List[Dict]] = None) -> str:
    """Render a .kicad_pcb file to SVG using a layer preset.

    Args:
        pcb_path:       Path to .kicad_pcb file.
        output_dir:     Directory for output SVG.
        preset_name:    Layer preset name (from PRESETS).
        highlight_nets: Optional list of net names to highlight.
        crop_bbox:      Optional (x, y, w, h) in mm for viewport cropping.
        crop_refs:      Optional list of reference designators to crop around.
                        Overrides *crop_bbox* if both are given.
        mirror:         If True, mirror the X axis (for back-side views).
        annotations:    Optional list of annotation dicts for callout overlays.

    Returns:
        Path to the generated SVG file.
    """
    preset = get_preset(preset_name)
    data = extract_pcb(pcb_path)

    outline: BoardOutline = data["outline"]
    footprints: List[FootprintInfo] = data["footprints"]
    segments: List[TrackInfo] = data["track_segments"]
    arcs: List[ArcTrackInfo] = data["track_arcs"]
    vias_list: List[ViaInfo] = data["vias"]
    zones: List[ZoneOutline] = data["zones"]

    hl_set: Optional[Set[str]] = set(highlight_nets) if highlight_nets else None

    # Compute crop from reference designators if requested
    if crop_refs:
        computed = compute_pcb_crop(footprints, crop_refs)
        if computed:
            crop_bbox = computed

    # Determine viewport
    if crop_bbox:
        vx, vy, vw, vh = crop_bbox
    elif outline.bbox:
        bx1, by1, bx2, by2 = outline.bbox
        margin = _DEFAULT_MARGIN
        vx = bx1 - margin
        vy = by1 - margin
        vw = (bx2 - bx1) + 2 * margin
        vh = (by2 - by1) + 2 * margin
    else:
        # Fallback: compute from all geometry
        all_x: List[float] = []
        all_y: List[float] = []
        for fp in footprints:
            all_x.append(fp.x)
            all_y.append(fp.y)
            for pad in fp.pads:
                all_x.append(pad.abs_x)
                all_y.append(pad.abs_y)
        for seg in segments:
            all_x.extend([seg.x1, seg.x2])
            all_y.extend([seg.y1, seg.y2])
        for via in vias_list:
            all_x.append(via.x)
            all_y.append(via.y)
        if all_x and all_y:
            margin = _DEFAULT_MARGIN
            vx = min(all_x) - margin
            vy = min(all_y) - margin
            vw = (max(all_x) - min(all_x)) + 2 * margin
            vh = (max(all_y) - min(all_y)) + 2 * margin
        else:
            vx, vy, vw, vh = 0, 0, 100, 100

    # Create SVG
    svg = SvgBuilder(width_mm=vw, height_mm=vh)
    svg.set_viewbox(vx, vy, vw, vh)

    # Apply mirror transform for back-side views
    if mirror:
        # Flip around the board center X axis
        center_x = vx + vw / 2
        with svg.group(transform=f"translate({_f(2 * center_x)},0) scale(-1,1)"):
            _render_all_layers(svg, preset, outline, footprints, segments,
                               arcs, vias_list, zones, hl_set)
    else:
        _render_all_layers(svg, preset, outline, footprints, segments,
                           arcs, vias_list, zones, hl_set)

    # Annotation overlays (rendered last, on top of everything)
    if annotations:
        render_annotations(svg, annotations)

    # Write output
    os.makedirs(output_dir, exist_ok=True)
    stem = Path(pcb_path).stem
    out_path = os.path.join(output_dir, f"{stem}-{preset_name}.svg")
    svg.write(out_path)
    return out_path


def _render_all_layers(svg: SvgBuilder, preset: LayerPreset,
                       outline: BoardOutline,
                       footprints: List[FootprintInfo],
                       segments: List[TrackInfo],
                       arcs: List[ArcTrackInfo],
                       vias_list: List[ViaInfo],
                       zones: List[ZoneOutline],
                       hl_set: Optional[Set[str]]) -> None:
    """Render all layers in correct z-order (back to front).

    Render order (documentation-oriented -- zones behind tracks):
        1. Background rect
        2. Zone outlines (lowest -- copper fills)
        3. Footprint graphics (silk/fab/courtyard)
        4. Pads
        5. Tracks and arcs (on top of pads/zones -- active routing)
        6. Vias (on top of tracks for visibility)
        7. Board outline (on top of everything)
        8. Drill marks (white knockout circles over pads/vias)
        9. Reference designator text (topmost)
    """
    # 1. Background
    vb = svg.root.get("viewBox", "0 0 100 100").split()
    bx, by, bw, bh = float(vb[0]), float(vb[1]), float(vb[2]), float(vb[3])
    svg.rect(bx, by, bw, bh, stroke="none", fill=preset.background,
             stroke_width=0)

    # 2. Zone outlines
    if preset.show_zones and zones:
        render_zone_outlines(svg, zones, preset, hl_set)

    # 3. Footprint graphics
    for fp in footprints:
        render_footprint_graphics(svg, fp, preset)

    # 4. Pads
    if preset.show_pads:
        for fp in footprints:
            for pad in fp.pads:
                hi = _is_highlighted(pad.net_name, hl_set)
                color = _HIGHLIGHT_COLOR if hi else PCB_PAD_COLOR
                render_pad(svg, pad, color)

    # 5. Tracks and arcs
    render_tracks(svg, segments, arcs, preset, hl_set)

    # 6. Vias
    if preset.show_vias and vias_list:
        render_vias(svg, vias_list, PCB_VIA_COLOR, PCB_DRILL_COLOR, hl_set)

    # 7. Board outline
    edge_style = _resolve_style(preset, "Edge.Cuts")
    if edge_style:
        sw = edge_style.stroke_width if edge_style.stroke_width > 0 else 0.15
        render_board_outline(svg, outline, edge_style.color, sw)

    # 8. Drill marks (knockout circles)
    if preset.show_pads or (preset.show_vias and vias_list):
        drill_fps = footprints if preset.show_pads else []
        drill_vias = vias_list if preset.show_vias else []
        render_drill_marks(svg, drill_fps, drill_vias, preset.background)

    # 9. Reference designator text
    # Use silk color from the preset; pick front or back based on
    # which silk layer is visible.
    ref_color = "#333333"
    for lname in ("F.SilkS", "F.Silkscreen", "B.SilkS", "B.Silkscreen"):
        style = _resolve_style(preset, lname)
        if style:
            ref_color = style.color
            break

    for fp in footprints:
        # Only show refs for footprints on layers visible in the preset
        fp_side_layers = []
        if "F" in fp.layer:
            fp_side_layers = ["F.SilkS", "F.Silkscreen", "F.Fab", "F.Cu"]
        else:
            fp_side_layers = ["B.SilkS", "B.Silkscreen", "B.Fab", "B.Cu"]
        if any(layer_visible(preset, l) for l in fp_side_layers):
            render_footprint_ref(svg, fp, ref_color, _REF_FONT_SIZE)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    preset_names = list(PRESETS.keys())
    parser = argparse.ArgumentParser(
        description="Render a .kicad_pcb file to SVG")
    parser.add_argument("pcb", help="Path to .kicad_pcb file")
    parser.add_argument("--output", "-o", required=True,
                        help="Output directory")
    parser.add_argument("--preset", default="assembly-front",
                        choices=preset_names,
                        help="Layer visibility preset (default: assembly-front)")
    parser.add_argument("--highlight-nets", default=None,
                        help="Comma-separated net names to highlight")
    parser.add_argument("--crop", default=None,
                        help="Crop region: x,y,w,h in mm")
    parser.add_argument("--crop-refs", default=None,
                        help="Comma-separated refs to crop around (e.g. U1,R1)")
    parser.add_argument("--mirror", action="store_true",
                        help="Mirror X axis (for back-side views)")
    parser.add_argument("--overlay", default=None,
                        help="Path to annotation JSON file for callout overlays")
    args = parser.parse_args()

    highlight = None
    if args.highlight_nets:
        highlight = [n.strip() for n in args.highlight_nets.split(",")]

    crop = None
    if args.crop:
        parts = [float(p.strip()) for p in args.crop.split(",")]
        if len(parts) == 4:
            crop = (parts[0], parts[1], parts[2], parts[3])
        else:
            parser.error("--crop requires exactly 4 values: x,y,w,h")

    crop_ref_list = None
    if args.crop_refs:
        crop_ref_list = [r.strip() for r in args.crop_refs.split(",")]

    overlay_annotations = None
    if args.overlay:
        with open(args.overlay) as f:
            overlay_annotations = json.load(f)

    out = render_pcb(args.pcb, args.output, args.preset,
                     highlight_nets=highlight, crop_bbox=crop,
                     crop_refs=crop_ref_list, mirror=args.mirror,
                     annotations=overlay_annotations)
    print(f"Rendered: {out}")


if __name__ == "__main__":
    main()

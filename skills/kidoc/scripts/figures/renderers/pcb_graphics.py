#!/usr/bin/env python3
"""PCB element extraction for kidoc rendering.

Extracts render-ready data structures from ``.kicad_pcb`` files: board outline,
footprints with absolute pad coordinates, tracks, vias, and zone outlines.

Zero external dependencies -- Python 3.8+ stdlib only (+ kicad skill's sexp_parser).

Usage::

    from pcb_graphics import extract_pcb
    data = extract_pcb('board.kicad_pcb')
    print(data['outline'].edges)
    print(data['footprints'])
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, List, NamedTuple, Optional, Tuple

from ._path_setup import setup_kicad_imports
setup_kicad_imports()

from sexp_parser import (parse_file, find_all, find_first, get_value,
                          get_at, get_property)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class BoardOutline(NamedTuple):
    """Board outline edges and bounding box."""
    edges: List[dict]
    bbox: Optional[Tuple[float, float, float, float]]  # min_x, min_y, max_x, max_y


class PadInfo(NamedTuple):
    """Pad with absolute (board-space) coordinates."""
    number: str
    pad_type: str       # smd, thru_hole, np_thru_hole
    shape: str          # circle, rect, oval, roundrect, custom, trapezoid
    abs_x: float
    abs_y: float
    width: float
    height: float
    drill: float        # 0 for SMD pads
    layers: List[str]
    net_name: str
    corner_ratio: float  # roundrect corner radius ratio (0-0.5)
    pad_angle: float     # total pad rotation in degrees (footprint + pad)


class FpGraphic(NamedTuple):
    """Footprint graphic primitive in absolute coordinates."""
    gtype: str          # line, rect, circle, arc, poly
    layer: str
    points: dict        # type-specific coordinate data (absolute)
    width: float        # stroke width


class FootprintInfo(NamedTuple):
    """Footprint with pads, courtyard, and silk/fab graphics."""
    reference: str
    value: str
    x: float
    y: float
    angle: float
    layer: str
    fp_type: str        # smd, through_hole
    pads: List[PadInfo]
    courtyard_bbox: Optional[Tuple[float, float, float, float]]
    graphics: List[FpGraphic]


class TrackInfo(NamedTuple):
    """Track segment."""
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    layer: str
    net: int
    net_name: str


class ArcTrackInfo(NamedTuple):
    """Arc track (three-point arc)."""
    start: Tuple[float, float]
    mid: Optional[Tuple[float, float]]
    end: Tuple[float, float]
    width: float
    layer: str
    net: int
    net_name: str


class ViaInfo(NamedTuple):
    """Via."""
    x: float
    y: float
    size: float
    drill: float
    layers: List[str]
    net: int
    net_name: str


class ZoneOutline(NamedTuple):
    """Zone boundary polygon (not the fill)."""
    points: List[Tuple[float, float]]
    layer: str
    net_name: str
    is_keepout: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rotate_point(px: float, py: float, angle_deg: float) -> Tuple[float, float]:
    """Rotate point (px, py) by angle_deg degrees around origin."""
    if angle_deg == 0:
        return px, py
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    return px * cos_a - py * sin_a, px * sin_a + py * cos_a


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert to float with fallback."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _build_net_map(root: list) -> dict:
    """Build {net_id: net_name} from top-level (net N "name") declarations.

    KiCad <=9: (net <int> "name") declarations at root.
    KiCad 10: no declarations -- net names used directly.
    Returns {int: str} for <=9, empty dict for KiCad 10.
    """
    nets: dict = {0: ""}
    for item in root:
        if isinstance(item, list) and len(item) >= 3 and item[0] == "net":
            try:
                net_num = int(item[1])
            except (ValueError, TypeError):
                continue
            nets[net_num] = item[2]
    return nets


def _net_id_and_name(node: list, keyword: str, net_map: dict) -> Tuple[int, str]:
    """Extract net ID and name from a node's (net ...) child.

    Handles both KiCad <=9 (net is integer) and KiCad 10 (net is name string).
    """
    net_val = get_value(node, keyword)
    if not net_val:
        return 0, ""
    try:
        net_num = int(net_val)
        return net_num, net_map.get(net_num, "")
    except (ValueError, TypeError):
        # KiCad 10: net value is the name itself
        return 0, net_val


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

def extract_board_outline(root: list) -> BoardOutline:
    """Extract Edge.Cuts edges and compute bounding box.

    Handles gr_line, gr_arc, gr_rect, gr_circle, and gr_poly on Edge.Cuts.
    """
    edges: List[dict] = []

    for item_type in ("gr_line", "gr_arc", "gr_circle", "gr_rect", "gr_poly"):
        for item in find_all(root, item_type):
            layer = get_value(item, "layer")
            if layer != "Edge.Cuts":
                continue

            if item_type == "gr_line":
                start = find_first(item, "start")
                end = find_first(item, "end")
                if start and end:
                    edges.append({
                        "type": "line",
                        "start": (float(start[1]), float(start[2])),
                        "end": (float(end[1]), float(end[2])),
                    })
            elif item_type == "gr_arc":
                start = find_first(item, "start")
                mid = find_first(item, "mid")
                end = find_first(item, "end")
                if start and end:
                    edge: dict = {
                        "type": "arc",
                        "start": (float(start[1]), float(start[2])),
                        "end": (float(end[1]), float(end[2])),
                    }
                    if mid:
                        edge["mid"] = (float(mid[1]), float(mid[2]))
                    edges.append(edge)
            elif item_type == "gr_rect":
                start = find_first(item, "start")
                end = find_first(item, "end")
                if start and end:
                    edges.append({
                        "type": "rect",
                        "start": (float(start[1]), float(start[2])),
                        "end": (float(end[1]), float(end[2])),
                    })
            elif item_type == "gr_circle":
                center = find_first(item, "center")
                end = find_first(item, "end")
                if center and end:
                    edges.append({
                        "type": "circle",
                        "center": (float(center[1]), float(center[2])),
                        "end": (float(end[1]), float(end[2])),
                    })
            elif item_type == "gr_poly":
                pts = find_first(item, "pts")
                if pts:
                    coords = [(float(xy[1]), float(xy[2]))
                              for xy in find_all(pts, "xy")]
                    if coords:
                        edges.append({
                            "type": "polygon",
                            "points": coords,
                        })

    # Compute bounding box from all edge geometry
    all_x: List[float] = []
    all_y: List[float] = []
    for e in edges:
        etype = e["type"]
        if etype == "circle":
            cx, cy = e["center"]
            ex, ey = e["end"]
            r = math.sqrt((ex - cx) ** 2 + (ey - cy) ** 2)
            all_x.extend([cx - r, cx + r])
            all_y.extend([cy - r, cy + r])
        elif etype == "polygon":
            for px, py in e["points"]:
                all_x.append(px)
                all_y.append(py)
        elif etype == "arc" and "mid" in e:
            sx, sy = e["start"]
            mx, my = e["mid"]
            ex, ey = e["end"]
            all_x.extend([sx, ex, mx])
            all_y.extend([sy, ey, my])
            # Include cardinal extrema the arc passes through
            D = 2.0 * (sx * (my - ey) + mx * (ey - sy) + ex * (sy - my))
            if abs(D) > 1e-10:
                ss = sx * sx + sy * sy
                ms = mx * mx + my * my
                es = ex * ex + ey * ey
                ucx = (ss * (my - ey) + ms * (ey - sy) + es * (sy - my)) / D
                ucy = (ss * (ex - mx) + ms * (sx - ex) + es * (mx - sx)) / D
                r = math.sqrt((sx - ucx) ** 2 + (sy - ucy) ** 2)
                a_s = math.atan2(sy - ucy, sx - ucx)
                a_m = math.atan2(my - ucy, mx - ucx)
                a_e = math.atan2(ey - ucy, ex - ucx)
                nm = (a_m - a_s) % (2.0 * math.pi)
                ne = (a_e - a_s) % (2.0 * math.pi)
                sweep = ne if nm <= ne else -((2.0 * math.pi) - ne)
                for cardinal, dx, dy in [(0, 1, 0), (math.pi / 2, 0, 1),
                                         (math.pi, -1, 0), (3 * math.pi / 2, 0, -1)]:
                    offset = (cardinal - a_s) % (2.0 * math.pi)
                    if sweep > 0 and offset <= sweep:
                        all_x.append(ucx + r * dx)
                        all_y.append(ucy + r * dy)
                    elif sweep < 0 and offset >= (2.0 * math.pi + sweep):
                        all_x.append(ucx + r * dx)
                        all_y.append(ucy + r * dy)
        else:
            # Lines, rects, arcs without mid
            for key in ("start", "end", "center", "mid"):
                pt = e.get(key)
                if pt is not None:
                    all_x.append(pt[0])
                    all_y.append(pt[1])

    bbox = None
    if all_x and all_y:
        bbox = (min(all_x), min(all_y), max(all_x), max(all_y))

    return BoardOutline(edges=edges, bbox=bbox)


def extract_footprints(root: list, net_map: dict) -> List[FootprintInfo]:
    """Extract footprints with pads (absolute coords) and silk/fab graphics.

    Handles both KiCad 6+ (footprint ...) and KiCad 5 (module ...).
    """
    footprints: List[FootprintInfo] = []

    fp_nodes = find_all(root, "footprint") or find_all(root, "module")

    for fp in fp_nodes:
        fp_lib = fp[1] if len(fp) > 1 else ""
        at = get_at(fp)
        x, y, angle = at if at else (0.0, 0.0, 0.0)

        layer = get_value(fp, "layer") or "F.Cu"

        # Reference: KiCad 6+ property vs KiCad 5 fp_text
        ref = get_property(fp, "Reference") or ""
        value = get_property(fp, "Value") or ""
        if not ref:
            for ft in find_all(fp, "fp_text"):
                if len(ft) >= 3:
                    if ft[1] == "reference":
                        ref = ft[2]
                    elif ft[1] == "value":
                        value = ft[2]

        # Footprint type (SMD vs THT)
        attr_node = find_first(fp, "attr")
        if attr_node and len(attr_node) > 1:
            attr_flags = [a for a in attr_node[1:] if isinstance(a, str)]
            fp_type = attr_flags[0] if attr_flags else "smd"
        else:
            has_tht = any(p[2] == "thru_hole" for p in find_all(fp, "pad")
                          if len(p) > 2)
            fp_type = "through_hole" if has_tht else "smd"

        # Extract pads with absolute coordinates
        pads: List[PadInfo] = []
        for pad in find_all(fp, "pad"):
            if len(pad) < 4:
                continue
            pad_num = str(pad[1])
            pad_type = pad[2]   # smd, thru_hole, np_thru_hole
            pad_shape = pad[3]  # circle, rect, oval, roundrect, custom, trapezoid

            pad_at = get_at(pad)
            pad_size = find_first(pad, "size")
            pad_drill = find_first(pad, "drill")
            pad_layers_node = find_first(pad, "layers")

            # Compute absolute position
            px, py = 0.0, 0.0
            if pad_at:
                px, py = pad_at[0], pad_at[1]
                # Rotate pad position by footprint angle
                px, py = _rotate_point(px, py, angle)
            abs_x = round(x + px, 4)
            abs_y = round(y + py, 4)

            # Pad size
            pw = _safe_float(pad_size[1]) if pad_size and len(pad_size) >= 3 else 0.0
            ph = _safe_float(pad_size[2]) if pad_size and len(pad_size) >= 3 else 0.0

            # Drill
            drill_val = 0.0
            if pad_drill and len(pad_drill) >= 2:
                d = pad_drill[1]
                if d == "oval" and len(pad_drill) >= 3:
                    drill_val = _safe_float(pad_drill[2])
                else:
                    drill_val = _safe_float(d)

            # Layers
            pad_layers: List[str] = []
            if pad_layers_node and len(pad_layers_node) > 1:
                pad_layers = [l for l in pad_layers_node[1:] if isinstance(l, str)]

            # Net name
            pad_net = find_first(pad, "net")
            net_name = ""
            if pad_net and len(pad_net) >= 3:
                # KiCad <=9: (net number "name")
                net_name = pad_net[2]
            elif pad_net and len(pad_net) == 2:
                # KiCad 10: (net "name")
                net_name = pad_net[1]

            # Corner ratio for roundrect pads
            corner_ratio = 0.25  # KiCad default
            rratio_node = find_first(pad, "roundrect_rratio")
            if rratio_node and len(rratio_node) >= 2:
                try:
                    corner_ratio = float(rratio_node[1])
                except (ValueError, TypeError):
                    pass

            # Pad angle (from pad's own at node, relative to footprint)
            pad_angle_val = pad_at[2] if pad_at and len(pad_at) > 2 else 0.0
            # Total angle = footprint angle + pad angle
            total_pad_angle = angle + pad_angle_val

            pads.append(PadInfo(
                number=pad_num,
                pad_type=pad_type,
                shape=pad_shape,
                abs_x=abs_x,
                abs_y=abs_y,
                width=pw,
                height=ph,
                drill=drill_val,
                layers=pad_layers,
                net_name=net_name,
                corner_ratio=corner_ratio,
                pad_angle=total_pad_angle,
            ))

        # Extract courtyard bounding box
        crtyd_pts: List[Tuple[float, float]] = []
        for gtype in ("fp_line", "fp_rect", "fp_circle", "fp_poly", "fp_arc"):
            for item in find_all(fp, gtype):
                item_layer = get_value(item, "layer")
                if not item_layer or "CrtYd" not in item_layer:
                    continue
                if gtype == "fp_poly":
                    pts = find_first(item, "pts")
                    if pts:
                        for xy in find_all(pts, "xy"):
                            if len(xy) >= 3:
                                lx, ly = float(xy[1]), float(xy[2])
                                lx, ly = _rotate_point(lx, ly, angle)
                                crtyd_pts.append((x + lx, y + ly))
                    continue
                for key in ("start", "end", "center", "mid"):
                    node = find_first(item, key)
                    if node and len(node) >= 3:
                        lx, ly = float(node[1]), float(node[2])
                        lx, ly = _rotate_point(lx, ly, angle)
                        crtyd_pts.append((x + lx, y + ly))

        courtyard_bbox = None
        if crtyd_pts:
            cxs = [p[0] for p in crtyd_pts]
            cys = [p[1] for p in crtyd_pts]
            courtyard_bbox = (min(cxs), min(cys), max(cxs), max(cys))

        # Extract footprint graphics (silk, fab layers)
        graphics: List[FpGraphic] = []
        _RENDER_LAYERS = {"F.SilkS", "B.SilkS", "F.Fab", "B.Fab",
                          "F.Silkscreen", "B.Silkscreen"}
        for gtype in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
            for item in find_all(fp, gtype):
                item_layer = get_value(item, "layer") or ""
                if item_layer not in _RENDER_LAYERS:
                    continue

                # Stroke width
                stroke_node = find_first(item, "stroke")
                sw = 0.0
                if stroke_node:
                    sw = _safe_float(get_value(stroke_node, "width"))
                else:
                    sw = _safe_float(get_value(item, "width"))

                pts_data: dict = {}

                if gtype == "fp_line":
                    s = find_first(item, "start")
                    e = find_first(item, "end")
                    if s and e:
                        sx, sy = _rotate_point(float(s[1]), float(s[2]), angle)
                        ex, ey = _rotate_point(float(e[1]), float(e[2]), angle)
                        pts_data = {
                            "start": (round(x + sx, 4), round(y + sy, 4)),
                            "end": (round(x + ex, 4), round(y + ey, 4)),
                        }
                elif gtype == "fp_rect":
                    s = find_first(item, "start")
                    e = find_first(item, "end")
                    if s and e:
                        sx, sy = _rotate_point(float(s[1]), float(s[2]), angle)
                        ex, ey = _rotate_point(float(e[1]), float(e[2]), angle)
                        pts_data = {
                            "start": (round(x + sx, 4), round(y + sy, 4)),
                            "end": (round(x + ex, 4), round(y + ey, 4)),
                        }
                elif gtype == "fp_circle":
                    c = find_first(item, "center")
                    e = find_first(item, "end")
                    if c and e:
                        cx, cy = _rotate_point(float(c[1]), float(c[2]), angle)
                        ex, ey = _rotate_point(float(e[1]), float(e[2]), angle)
                        pts_data = {
                            "center": (round(x + cx, 4), round(y + cy, 4)),
                            "end": (round(x + ex, 4), round(y + ey, 4)),
                        }
                elif gtype == "fp_arc":
                    s = find_first(item, "start")
                    m = find_first(item, "mid")
                    e = find_first(item, "end")
                    if s and e:
                        sx, sy = _rotate_point(float(s[1]), float(s[2]), angle)
                        ex, ey = _rotate_point(float(e[1]), float(e[2]), angle)
                        pts_data = {
                            "start": (round(x + sx, 4), round(y + sy, 4)),
                            "end": (round(x + ex, 4), round(y + ey, 4)),
                        }
                        if m:
                            mx, my = _rotate_point(float(m[1]), float(m[2]), angle)
                            pts_data["mid"] = (round(x + mx, 4), round(y + my, 4))
                elif gtype == "fp_poly":
                    pts = find_first(item, "pts")
                    if pts:
                        coords = []
                        for xy in find_all(pts, "xy"):
                            if len(xy) >= 3:
                                lx, ly = _rotate_point(
                                    float(xy[1]), float(xy[2]), angle)
                                coords.append((round(x + lx, 4),
                                               round(y + ly, 4)))
                        if coords:
                            pts_data = {"points": coords}

                if pts_data:
                    short_type = gtype.replace("fp_", "")
                    graphics.append(FpGraphic(
                        gtype=short_type,
                        layer=item_layer,
                        points=pts_data,
                        width=sw,
                    ))

        footprints.append(FootprintInfo(
            reference=ref,
            value=value,
            x=x,
            y=y,
            angle=angle,
            layer=layer,
            fp_type=fp_type,
            pads=pads,
            courtyard_bbox=courtyard_bbox,
            graphics=graphics,
        ))

    return footprints


def extract_tracks(root: list, net_map: dict) -> Tuple[List[TrackInfo], List[ArcTrackInfo]]:
    """Extract track segments and arcs with net names."""
    segments: List[TrackInfo] = []
    arcs: List[ArcTrackInfo] = []

    for seg in find_all(root, "segment"):
        start = find_first(seg, "start")
        end = find_first(seg, "end")
        width_val = get_value(seg, "width")
        layer = get_value(seg, "layer") or ""
        net_id, net_name = _net_id_and_name(seg, "net", net_map)

        if start and end:
            segments.append(TrackInfo(
                x1=float(start[1]), y1=float(start[2]),
                x2=float(end[1]), y2=float(end[2]),
                width=_safe_float(width_val),
                layer=layer,
                net=net_id,
                net_name=net_name,
            ))

    for arc in find_all(root, "arc"):
        start = find_first(arc, "start")
        mid = find_first(arc, "mid")
        end = find_first(arc, "end")
        width_val = get_value(arc, "width")
        layer = get_value(arc, "layer") or ""
        net_id, net_name = _net_id_and_name(arc, "net", net_map)

        if start and end:
            arcs.append(ArcTrackInfo(
                start=(float(start[1]), float(start[2])),
                mid=(float(mid[1]), float(mid[2])) if mid else None,
                end=(float(end[1]), float(end[2])),
                width=_safe_float(width_val),
                layer=layer,
                net=net_id,
                net_name=net_name,
            ))

    return segments, arcs


def extract_vias(root: list, net_map: dict) -> List[ViaInfo]:
    """Extract vias with position, size, drill, layers, and net."""
    vias: List[ViaInfo] = []

    for via in find_all(root, "via"):
        at = get_at(via)
        size = get_value(via, "size")
        drill = get_value(via, "drill")
        layers_node = find_first(via, "layers")
        net_id, net_name = _net_id_and_name(via, "net", net_map)

        via_layers: List[str] = []
        if layers_node and len(layers_node) > 1:
            via_layers = [l for l in layers_node[1:] if isinstance(l, str)]

        vias.append(ViaInfo(
            x=at[0] if at else 0.0,
            y=at[1] if at else 0.0,
            size=_safe_float(size),
            drill=_safe_float(drill),
            layers=via_layers,
            net=net_id,
            net_name=net_name,
        ))

    return vias


def extract_zone_outlines(root: list, net_map: dict) -> List[ZoneOutline]:
    """Extract zone boundary polygons (outline only, not fills)."""
    zones: List[ZoneOutline] = []

    for zone in find_all(root, "zone"):
        # Net name
        net_val = get_value(zone, "net")
        net_name_val = get_value(zone, "net_name")
        if net_val:
            try:
                net_num = int(net_val)
                net_name = net_name_val or net_map.get(net_num, "")
            except (ValueError, TypeError):
                # KiCad 10: net value is the name
                net_name = net_val
        else:
            net_name = net_name_val or ""

        # Layer(s)
        layer = get_value(zone, "layer") or ""
        layers_node = find_first(zone, "layers")
        zone_layers: List[str] = []
        if layers_node and len(layers_node) > 1:
            zone_layers = [l for l in layers_node[1:] if isinstance(l, str)]
        elif layer:
            zone_layers = [layer]

        # Keepout
        is_keepout = find_first(zone, "keepout") is not None

        # Outline polygon
        polygon = find_first(zone, "polygon")
        if not polygon:
            continue
        pts = find_first(polygon, "pts")
        if not pts:
            continue
        coords = [(float(xy[1]), float(xy[2]))
                   for xy in find_all(pts, "xy")
                   if len(xy) >= 3]
        if not coords:
            continue

        # Emit one ZoneOutline per layer for multi-layer zones
        if zone_layers:
            for zl in zone_layers:
                zones.append(ZoneOutline(
                    points=coords,
                    layer=zl,
                    net_name=net_name,
                    is_keepout=is_keepout,
                ))
        else:
            zones.append(ZoneOutline(
                points=coords,
                layer="",
                net_name=net_name,
                is_keepout=is_keepout,
            ))

    return zones


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def extract_pcb(pcb_path: str) -> dict:
    """Parse a .kicad_pcb file and extract all render-ready data.

    Returns a dict with keys:
        outline:        BoardOutline
        footprints:     list[FootprintInfo]
        track_segments: list[TrackInfo]
        track_arcs:     list[ArcTrackInfo]
        vias:           list[ViaInfo]
        zones:          list[ZoneOutline]
        net_map:        dict[int, str]
    """
    root = parse_file(pcb_path)
    net_map = _build_net_map(root)

    outline = extract_board_outline(root)
    footprints = extract_footprints(root, net_map)
    segments, arcs = extract_tracks(root, net_map)
    vias = extract_vias(root, net_map)
    zones = extract_zone_outlines(root, net_map)

    return {
        "outline": outline,
        "footprints": footprints,
        "track_segments": segments,
        "track_arcs": arcs,
        "vias": vias,
        "zones": zones,
        "net_map": net_map,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pcb_graphics.py <file.kicad_pcb>")
        sys.exit(1)

    data = extract_pcb(sys.argv[1])
    outline = data["outline"]
    fps = data["footprints"]
    segs = data["track_segments"]
    arcs = data["track_arcs"]
    vias = data["vias"]
    zones = data["zones"]

    print(f"Board outline: {len(outline.edges)} edges, "
          f"bbox={outline.bbox}")
    print(f"Footprints: {len(fps)}")
    if fps:
        total_pads = sum(len(f.pads) for f in fps)
        total_graphics = sum(len(f.graphics) for f in fps)
        print(f"  Total pads: {total_pads}")
        print(f"  Total fp graphics: {total_graphics}")
    print(f"Track segments: {len(segs)}")
    print(f"Track arcs: {len(arcs)}")
    print(f"Vias: {len(vias)}")
    print(f"Zones: {len(zones)}")

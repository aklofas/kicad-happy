"""Lightweight SVG builder using xml.etree.ElementTree.

Produces svglib-compatible SVGs (inline styles only, no CSS classes,
no masks, no <use> elements).  Supports ``<linearGradient>`` and
``<radialGradient>`` definitions (svglib 0.9+ handles these natively;
the Tier-2 custom converter in kidoc_svg_embed falls back to the
first stop color for graceful degradation).

Zero external dependencies — Python stdlib only.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from xml.etree.ElementTree import Element, SubElement, tostring


class SvgBuilder:
    """Build an SVG document element by element.

    All coordinates are in millimetres (matching KiCad conventions).
    The SVG uses ``mm`` units with a viewBox for the visible region.
    """

    def __init__(self, width_mm: float = 297.0, height_mm: float = 210.0):
        self._root = Element("svg", {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": f"{width_mm}mm",
            "height": f"{height_mm}mm",
            "viewBox": f"0 0 {width_mm} {height_mm}",
        })
        self._width = width_mm
        self._height = height_mm
        # Stack of current parent elements (<svg> or <g>).
        self._stack: list[Element] = [self._root]
        # Gradient definitions (lazy-created <defs> block).
        self._defs: Element | None = None
        self._gradient_count: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def root(self) -> Element:
        return self._root

    # ------------------------------------------------------------------
    # ViewBox / sizing
    # ------------------------------------------------------------------

    def set_viewbox(self, min_x: float, min_y: float,
                    width: float, height: float) -> None:
        """Set the viewBox (visible region) of the SVG."""
        self._root.set("viewBox", f"{min_x} {min_y} {width} {height}")
        self._root.set("width", f"{width}mm")
        self._root.set("height", f"{height}mm")
        self._width = width
        self._height = height

    # ------------------------------------------------------------------
    # Primitive elements
    # ------------------------------------------------------------------

    def line(self, x1: float, y1: float, x2: float, y2: float,
             stroke: str = "#000000", stroke_width: float = 0.254,
             dash: str | None = None) -> Element:
        """Draw a line segment."""
        attrs = {
            "x1": _f(x1), "y1": _f(y1),
            "x2": _f(x2), "y2": _f(y2),
            "stroke": stroke,
            "stroke-width": _f(stroke_width),
            "stroke-linecap": "round",
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        return SubElement(self._parent, "line", attrs)

    def rect(self, x: float, y: float, w: float, h: float,
             stroke: str = "none", fill: str = "none",
             stroke_width: float = 0.254, rx: float = 0,
             dash: str | None = None,
             opacity: float | None = None) -> Element:
        """Draw a rectangle.  *x, y* is the top-left corner."""
        attrs = {
            "x": _f(x), "y": _f(y),
            "width": _f(w), "height": _f(h),
            "stroke": stroke, "fill": fill,
            "stroke-width": _f(stroke_width),
        }
        if rx > 0:
            attrs["rx"] = _f(rx)
        if dash:
            attrs["stroke-dasharray"] = dash
        if opacity is not None and opacity < 1.0:
            attrs["opacity"] = _f(opacity)
        return SubElement(self._parent, "rect", attrs)

    def circle(self, cx: float, cy: float, r: float,
               stroke: str = "none", fill: str = "none",
               stroke_width: float = 0.254,
               dash: str | None = None) -> Element:
        """Draw a circle."""
        attrs = {
            "cx": _f(cx), "cy": _f(cy), "r": _f(r),
            "stroke": stroke, "fill": fill,
            "stroke-width": _f(stroke_width),
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        return SubElement(self._parent, "circle", attrs)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float,
                stroke: str = "none", fill: str = "none",
                stroke_width: float = 0.254) -> Element:
        """Draw an ellipse."""
        return SubElement(self._parent, "ellipse", {
            "cx": _f(cx), "cy": _f(cy),
            "rx": _f(rx), "ry": _f(ry),
            "stroke": stroke, "fill": fill,
            "stroke-width": _f(stroke_width),
        })

    def polyline(self, points: list[tuple[float, float]],
                 stroke: str = "none", fill: str = "none",
                 stroke_width: float = 0.254,
                 closed: bool = False,
                 dash: str | None = None) -> Element:
        """Draw a polyline (or polygon if *closed*)."""
        pts = " ".join(f"{_f(x)},{_f(y)}" for x, y in points)
        tag = "polygon" if closed else "polyline"
        attrs = {
            "points": pts,
            "stroke": stroke, "fill": fill,
            "stroke-width": _f(stroke_width),
            "stroke-linejoin": "round",
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        return SubElement(self._parent, tag, attrs)

    def path(self, d: str, stroke: str = "none", fill: str = "none",
             stroke_width: float = 0.254,
             dash: str | None = None) -> Element:
        """Draw an arbitrary SVG path from a *d* string."""
        attrs = {
            "d": d,
            "stroke": stroke, "fill": fill,
            "stroke-width": _f(stroke_width),
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        return SubElement(self._parent, "path", attrs)

    def arc(self, x1: float, y1: float, x2: float, y2: float,
            r: float, large_arc: bool, sweep: bool,
            stroke: str = "none", fill: str = "none",
            stroke_width: float = 0.254,
            dash: str | None = None) -> Element:
        """Draw an arc from (x1,y1) to (x2,y2) with radius *r*.

        *large_arc*: True for the major arc.
        *sweep*: True for clockwise.
        """
        la = 1 if large_arc else 0
        sw = 1 if sweep else 0
        d = f"M {_f(x1)},{_f(y1)} A {_f(r)},{_f(r)} 0 {la},{sw} {_f(x2)},{_f(y2)}"
        return self.path(d, stroke=stroke, fill=fill,
                         stroke_width=stroke_width, dash=dash)

    def bezier(self, points: list[tuple[float, float]],
               stroke: str = "none", fill: str = "none",
               stroke_width: float = 0.254,
               dash: str | None = None) -> Element:
        """Draw a cubic Bezier curve through *points* (4 points)."""
        if len(points) < 4:
            return self.polyline(points, stroke=stroke, fill=fill,
                                 stroke_width=stroke_width, dash=dash)
        d = f"M {_f(points[0][0])},{_f(points[0][1])}"
        # Process groups of 3 control points after the start
        i = 1
        while i + 2 < len(points):
            d += (f" C {_f(points[i][0])},{_f(points[i][1])}"
                  f" {_f(points[i+1][0])},{_f(points[i+1][1])}"
                  f" {_f(points[i+2][0])},{_f(points[i+2][1])}")
            i += 3
        return self.path(d, stroke=stroke, fill=fill,
                         stroke_width=stroke_width, dash=dash)

    def text(self, x: float, y: float, content: str,
             font_size: float = 1.27,
             font_family: str = "sans-serif",
             anchor: str = "start",
             dominant_baseline: str = "auto",
             fill: str = "#000000",
             bold: bool = False, italic: bool = False,
             rotation: float = 0) -> Element:
        """Draw a text element.

        *anchor*: ``start``, ``middle``, or ``end``.
        *dominant_baseline*: ``auto``, ``central``, ``hanging``, etc.
        """
        attrs: dict[str, str] = {
            "x": _f(x), "y": _f(y),
            "font-size": _f(font_size),
            "font-family": font_family,
            "text-anchor": anchor,
            "dominant-baseline": dominant_baseline,
            "fill": fill,
        }
        if bold:
            attrs["font-weight"] = "bold"
        if italic:
            attrs["font-style"] = "italic"
        if rotation:
            attrs["transform"] = f"rotate({_f(rotation)},{_f(x)},{_f(y)})"
        elem = SubElement(self._parent, "text", attrs)
        elem.text = content
        return elem

    # ------------------------------------------------------------------
    # Gradient definitions
    # ------------------------------------------------------------------

    def _ensure_defs(self) -> Element:
        """Create ``<defs>`` element if it doesn't exist yet.

        Inserted as the first child of ``<svg>`` so gradient
        definitions precede any references.
        """
        if self._defs is None:
            self._defs = Element("defs")
            self._root.insert(0, self._defs)
        return self._defs

    def linear_gradient(self, color1: str, color2: str,
                        x1: str = "0%", y1: str = "0%",
                        x2: str = "0%", y2: str = "100%",
                        grad_id: str | None = None) -> str:
        """Define a linear gradient and return its CSS ``url(#id)`` ref.

        Default direction is top-to-bottom (y1=0%, y2=100%).

        Parameters:
            color1: Start color (hex string).
            color2: End color (hex string).
            x1, y1, x2, y2: Gradient vector as percentages.
            grad_id: Optional explicit ID.  Auto-generated if *None*.

        Returns:
            ``"url(#grad_N)"`` string suitable for *fill* or *stroke*.
        """
        defs = self._ensure_defs()
        if grad_id is None:
            self._gradient_count += 1
            grad_id = f"grad_{self._gradient_count}"
        grad = SubElement(defs, "linearGradient", {
            "id": grad_id, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        })
        SubElement(grad, "stop", {"offset": "0%", "stop-color": color1})
        SubElement(grad, "stop", {"offset": "100%", "stop-color": color2})
        return f"url(#{grad_id})"

    def radial_gradient(self, center_color: str, edge_color: str,
                        cx: str = "50%", cy: str = "50%", r: str = "50%",
                        grad_id: str | None = None) -> str:
        """Define a radial gradient and return its CSS ``url(#id)`` ref."""
        defs = self._ensure_defs()
        if grad_id is None:
            self._gradient_count += 1
            grad_id = f"grad_{self._gradient_count}"
        grad = SubElement(defs, "radialGradient", {
            "id": grad_id, "cx": cx, "cy": cy, "r": r,
        })
        SubElement(grad, "stop", {"offset": "0%", "stop-color": center_color})
        SubElement(grad, "stop", {"offset": "100%", "stop-color": edge_color})
        return f"url(#{grad_id})"

    def multi_stop_gradient(self, stops: list[tuple[str, str]],
                            direction: str = "vertical",
                            grad_id: str | None = None) -> str:
        """Define a multi-stop linear gradient.

        Parameters:
            stops: List of ``(offset_percent, color)`` tuples,
                   e.g. ``[("0%", "#fff"), ("50%", "#aaa"), ("100%", "#fff")]``.
            direction: ``"vertical"`` (top→bottom) or ``"horizontal"``
                       (left→right).
            grad_id: Optional explicit ID.

        Returns:
            ``"url(#grad_N)"`` reference string.
        """
        defs = self._ensure_defs()
        if grad_id is None:
            self._gradient_count += 1
            grad_id = f"grad_{self._gradient_count}"
        if direction == "horizontal":
            attrs = {"id": grad_id, "x1": "0%", "y1": "0%",
                     "x2": "100%", "y2": "0%"}
        else:
            attrs = {"id": grad_id, "x1": "0%", "y1": "0%",
                     "x2": "0%", "y2": "100%"}
        grad = SubElement(defs, "linearGradient", attrs)
        for offset, color in stops:
            SubElement(grad, "stop", {"offset": offset, "stop-color": color})
        return f"url(#{grad_id})"

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------

    @contextmanager
    def group(self, transform: str | None = None, opacity: float | None = None, **attrs: str):
        """Context manager that creates a ``<g>`` element.

        All elements created inside the ``with`` block become children
        of this group.

        Usage::

            with svg.group(transform="translate(10,20)"):
                svg.line(0, 0, 5, 5)
        """
        g_attrs: dict[str, str] = dict(attrs)
        if transform:
            g_attrs["transform"] = transform
        if opacity is not None and opacity < 1.0:
            g_attrs["opacity"] = _f(opacity)
        g = SubElement(self._parent, "g", g_attrs)
        self._stack.append(g)
        try:
            yield g
        finally:
            self._stack.pop()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_string(self) -> str:
        """Serialise the SVG to a UTF-8 string."""
        return tostring(self._root, encoding="unicode",
                        xml_declaration=False)

    def write(self, path: str) -> None:
        """Write the SVG to a file."""
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + self.to_string()
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @property
    def _parent(self) -> Element:
        """Current parent element (top of the stack)."""
        return self._stack[-1]


# ======================================================================
# Geometry helpers
# ======================================================================

def three_point_arc(sx: float, sy: float,
                    mx: float, my: float,
                    ex: float, ey: float
                    ) -> tuple[float, float, float, bool, bool]:
    """Convert a 3-point arc (start, mid, end) to SVG arc parameters.

    Returns ``(cx, cy, radius, large_arc, sweep)`` where:
    - *cx, cy* is the centre of the circle through the 3 points
    - *radius* is the radius
    - *large_arc* is True if the arc subtends > 180°
    - *sweep* is True for clockwise (SVG convention: positive Y-down)
    """
    # Perpendicular bisector intersection to find center
    ax, ay = (sx + mx) / 2, (sy + my) / 2
    bx, by = (mx + ex) / 2, (my + ey) / 2
    # Direction vectors (perpendicular to chords)
    dx1, dy1 = -(my - sy), mx - sx
    dx2, dy2 = -(ey - my), ex - mx

    # Solve: A + t1 * D1 = B + t2 * D2
    denom = dx1 * dy2 - dy1 * dx2
    if abs(denom) < 1e-10:
        # Degenerate (collinear points) — return a huge arc
        cx = (sx + ex) / 2
        cy = (sy + ey) / 2
        radius = math.hypot(ex - sx, ey - sy) / 2
        return cx, cy, radius, False, True

    t1 = ((bx - ax) * dy2 - (by - ay) * dx2) / denom
    cx = ax + t1 * dx1
    cy = ay + t1 * dy1
    radius = math.hypot(sx - cx, sy - cy)

    # Determine sweep direction via cross product
    # Vector from start to mid, start to end
    cross = (mx - sx) * (ey - sy) - (my - sy) * (ex - sx)
    # In SVG Y-down: positive cross = clockwise (sweep=1)
    sweep = cross > 0

    # Determine large_arc: does the midpoint lie on the major arc?
    # Angle from center to each point
    a_start = math.atan2(sy - cy, sx - cx)
    a_mid = math.atan2(my - cy, mx - cx)
    a_end = math.atan2(ey - cy, ex - cx)

    # Normalize angles relative to start
    def _norm(a: float, ref: float) -> float:
        d = a - ref
        while d < 0:
            d += 2 * math.pi
        while d >= 2 * math.pi:
            d -= 2 * math.pi
        return d

    n_mid = _norm(a_mid, a_start)
    n_end = _norm(a_end, a_start)

    if sweep:
        # Clockwise: angles should decrease, but we normalised to positive.
        # Mid should be between start and end in the sweep direction.
        large_arc = not (0 < n_mid < n_end) if n_end > 0 else True
    else:
        large_arc = not (0 < n_mid < n_end) if n_end > 0 else True

    # Simpler approach: check if mid-point is on the arc we'd draw
    # with the current large_arc=False.  If not, flip it.
    # The arc from start to end with large_arc=False subtends <= 180°.
    # The midpoint should lie on this arc if large_arc is False.
    # Test: angle from center to mid should be between start and end
    # in the sweep direction.
    if sweep:
        # CW in SVG: angles go from a_start toward smaller values
        mid_between = _angle_between_cw(a_start, a_end, a_mid)
    else:
        mid_between = _angle_between_ccw(a_start, a_end, a_mid)

    large_arc = not mid_between

    return cx, cy, radius, large_arc, sweep


def _angle_between_cw(a_start: float, a_end: float, a_test: float) -> bool:
    """Check if *a_test* lies between *a_start* and *a_end* going clockwise."""
    def _norm(a: float) -> float:
        return a % (2 * math.pi)
    s = _norm(a_start)
    e = _norm(a_end)
    t = _norm(a_test)
    # CW means decreasing angle
    span = (s - e) % (2 * math.pi)
    test = (s - t) % (2 * math.pi)
    return test <= span


def _angle_between_ccw(a_start: float, a_end: float, a_test: float) -> bool:
    """Check if *a_test* lies between *a_start* and *a_end* going counter-clockwise."""
    def _norm(a: float) -> float:
        return a % (2 * math.pi)
    s = _norm(a_start)
    e = _norm(a_end)
    t = _norm(a_test)
    # CCW means increasing angle
    span = (e - s) % (2 * math.pi)
    test = (t - s) % (2 * math.pi)
    return test <= span


# ======================================================================
# Formatting helpers
# ======================================================================

def _f(v: float) -> str:
    """Format a float for SVG attributes — strip trailing zeros."""
    if v == int(v):
        return str(int(v))
    # Up to 4 decimal places, strip trailing zeros
    return f"{v:.4f}".rstrip("0").rstrip(".")

"""Switching-regulator hot-loop area proxy, shared by the PCB analyzer and EMC SW-003.

The proxy is the triangle through the footprint centres of the input capacitor,
the regulator and the inductor. It is not the hot loop itself (that runs through
the pads, vias and the ground return), so when the centres lie in a line the
triangle says nothing about the loop and no area is given.
"""

# Below this area a triangle whose longest side reaches DEGENERATE_MIN_SPAN_MM
# is a line of parts, not a compact loop.
DEGENERATE_MAX_AREA_MM2 = 1.0
DEGENERATE_MIN_SPAN_MM = 2.0


def triangle_loop_area(vertices) -> float | None:
    """Shoelace area in mm² of three (x, y) centres, or None when the triangle is degenerate.

    Degenerate: two centres coincide, or the area is under DEGENERATE_MAX_AREA_MM2
    while the longest side is at least DEGENERATE_MIN_SPAN_MM.
    """
    (ax, ay), (bx, by), (cx, cy) = vertices
    if (ax, ay) == (bx, by) or (bx, by) == (cx, cy) or (ax, ay) == (cx, cy):
        return None
    twice = 0.0
    for i in range(3):
        j = (i + 1) % 3
        twice += vertices[i][0] * vertices[j][1]
        twice -= vertices[j][0] * vertices[i][1]
    area = abs(twice) / 2.0
    longest = max(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5,
                  ((cx - bx) ** 2 + (cy - by) ** 2) ** 0.5,
                  ((ax - cx) ** 2 + (ay - cy) ** 2) ** 0.5)
    if area < DEGENERATE_MAX_AREA_MM2 and longest >= DEGENERATE_MIN_SPAN_MM:
        return None
    return area

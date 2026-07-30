"""Architecture block diagram generator.

Clusters ICs by function using signal analysis data, component types,
and library ID keywords.  Renders a 3-column layout with connection
arrows from the central MCU/CPU cluster to peripheral clusters.
"""

from __future__ import annotations

import os
from typing import Optional

from figures.registry import register
from figures.lib import (
    SvgBuilder, FigureTheme,
    draw_header_box,
    draw_right_angle_arrow,
    lighten,
)


# ======================================================================
# Component classification helper
# ======================================================================

def _classify_component(comp: dict, regulator_refs: set,
                        protection_refs: set) -> str | None:
    """Classify a component into an architecture cluster.

    Uses multiple signals in priority order:
    1. Known regulator refs from findings (detect_power_regulators)
    2. Component type field (most reliable)
    3. Library ID keywords (fallback)

    Returns cluster name or None to skip.
    """
    ref = comp.get('reference', '')
    ctype = comp.get('type', '')
    lib_id = comp.get('lib_id', '')

    # Skip passives and non-functional components
    if ctype in ('resistor', 'capacitor', 'inductor', 'ferrite_bead',
                  'diode', 'test_point', 'mounting_hole', 'fiducial',
                  'power_symbol', 'graphic'):
        return None
    if ref.startswith('#'):
        return None

    # 1. Explicit regulator match from signal analysis
    if ref in regulator_refs:
        return 'Power'

    # 2. Protection devices (ESD, TVS)
    lib_lower = lib_id.lower()
    if ref in protection_refs or 'protection' in lib_lower or 'tvs' in lib_lower:
        return 'Protection'

    # 3. Type-based classification
    if ctype == 'connector':
        return 'Connectors'
    if ctype == 'battery':
        return 'Power'
    if ctype == 'fuse':
        return 'Protection'
    if ctype == 'led':
        return 'LEDs / Display'
    if ctype == 'buzzer':
        return 'Audio / Output'
    if ctype in ('crystal', 'oscillator'):
        return None

    # 4. MCU / processor detection
    mcu_keywords = ('mcu', 'stm32', 'esp32', 'rp2040', 'atmega', 'pic16',
                    'pic32', 'nrf', 'samd', 'microcontroller', 'processor',
                    'esp32-s', 'esp32-c', 'wroom', 'wrover')
    if any(k in lib_lower for k in mcu_keywords):
        return 'MCU / CPU'

    if any(k in lib_lower for k in ('memory', 'flash', 'eeprom',
                                      'sram', 'sdram', 'w25q', 'at24')):
        return 'Memory'

    if any(k in lib_lower for k in ('uart', 'ethernet', 'can_',
                                      'wifi', 'bluetooth', 'rf_',
                                      'transceiver', 'phy', 'lora')):
        return 'Communication'

    if any(k in lib_lower for k in ('sensor', 'accel', 'gyro', 'temp',
                                      'humidity', 'pressure', 'bme', 'bmp',
                                      'mpu', 'lsm', 'lis')):
        return 'Sensors'

    if any(k in lib_lower for k in ('regulator', 'ldo', 'buck', 'boost',
                                      'charge', 'pmic', 'dcdc')):
        return 'Power'

    if ctype in ('ic', 'transistor', 'mosfet', 'relay', 'switch'):
        return 'Other ICs'

    return None


def _comp_label(comp: dict) -> str:
    """Build a display label for a component."""
    ref = comp.get('reference', '?')
    value = comp.get('value', '')
    desc = comp.get('description', '')
    if comp.get('type') == 'connector' and desc and len(desc) < 30:
        return f"{ref}: {desc}"
    if value:
        return f"{ref}: {value}"
    return ref


# ======================================================================
# Generator
# ======================================================================

@register(name="architecture", output="architecture.svg")
class ArchitectureGenerator:
    """System architecture block diagram."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> dict | None:
        """Extract and classify components into architecture clusters.

        Builds regulator/protection ref sets from signal analysis, then
        classifies every component.  Returns None if no MCU found or
        fewer than 3 clusters.
        """
        components = analysis.get('components', [])
        if not components:
            return None

        # Build detector-keyed lookup from flat findings[]
        from finding_schema import Det, group_findings
        _sa = group_findings(analysis)

        # Collect regulator refs from signal analysis
        regulator_refs = {
            r['ref'] for r in _sa.get(Det.POWER_REGULATORS, [])
            if isinstance(r, dict) and r.get('ref')
        }

        # Collect protection (ESD) device refs
        protection_refs: set[str] = set()
        for e in _sa.get(Det.ESD_AUDIT, []):
            if isinstance(e, dict):
                for dev in e.get('esd_devices', []):
                    if isinstance(dev, dict) and dev.get('ref'):
                        protection_refs.add(dev['ref'])

        # Classify each component into clusters
        clusters: dict[str, list[dict]] = {}
        for comp in components:
            cluster = _classify_component(comp, regulator_refs, protection_refs)
            if cluster:
                entry = {
                    'ref': comp.get('reference', '?'),
                    'value': comp.get('value', ''),
                    'description': comp.get('description', ''),
                    'type': comp.get('type', ''),
                }
                clusters.setdefault(cluster, []).append(entry)

        # Filter empty and validate
        clusters = {k: v for k, v in clusters.items() if v}
        if not clusters or 'MCU / CPU' not in clusters or len(clusters) < 3:
            return None

        return {
            'clusters': clusters,
        }

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        """Render architecture SVG from prepared cluster data.

        Layout: 3-column grid (left, center, right) with MCU/CPU in
        the center column.  Right-angle arrows connect MCU to each
        peripheral cluster.
        """
        theme = theme or FigureTheme()

        clusters = data.get('clusters', {})
        if not clusters or 'MCU / CPU' not in clusters:
            return None

        # Ordered rendering sequence
        layout_order = [
            'Power', 'MCU / CPU', 'Communication', 'Memory',
            'Sensors', 'Connectors', 'Protection',
            'LEDs / Display', 'Audio / Output', 'Other ICs',
        ]
        ordered = [(k, clusters[k]) for k in layout_order if k in clusters]

        # Column assignments
        left_clusters = ['Power', 'Protection', 'Other ICs']
        center_clusters = ['MCU / CPU']
        right_clusters = [
            'Communication', 'Memory', 'Sensors', 'Connectors',
            'LEDs / Display', 'Audio / Output',
        ]

        # Measure widths
        cluster_spacing_x = 12.0
        cluster_spacing_y = 10.0
        margin = 12.0
        char_width = theme.font_small * 0.55

        cluster_widths: dict[str, float] = {}
        for name, comps in clusters.items():
            labels = [_comp_label(c) for c in comps[:8]]
            max_label_len = max((len(lbl) for lbl in labels), default=0)
            title_len = len(name)
            max_chars = max(max_label_len, title_len)
            cluster_widths[name] = max(30, max_chars * char_width + 8)

        # Layout positions
        positions: dict[str, tuple[float, float, float, float]] = {}

        def _layout_column(cluster_names: list[str], col_x: float,
                           start_y: float) -> None:
            y = start_y
            for name in cluster_names:
                if name not in clusters:
                    continue
                comps = clusters[name]
                w = cluster_widths.get(name, 50)
                n_items = min(len(comps), 8)
                h = max(14, 6 + 3.5 + n_items * (theme.font_small + 1.2) + 2)
                positions[name] = (col_x, y, w, h)
                y += h + cluster_spacing_y

        left_w = max(
            (cluster_widths.get(n, 30) for n in left_clusters if n in clusters),
            default=40,
        )
        center_w = max(
            (cluster_widths.get(n, 40) for n in center_clusters if n in clusters),
            default=50,
        )

        col1_x = margin
        col2_x = col1_x + left_w + cluster_spacing_x
        col3_x = col2_x + center_w + cluster_spacing_x

        start_y = margin + 8
        _layout_column(left_clusters, col1_x, start_y)
        _layout_column(center_clusters, col2_x, start_y)
        _layout_column(right_clusters, col3_x, start_y)

        if not positions:
            return None
        max_x = max(p[0] + p[2] for p in positions.values()) + margin
        max_y = max(p[1] + p[3] for p in positions.values()) + margin
        total_w = max(max_x, 150)
        total_h = max(max_y, 80)

        # Build SVG
        svg = SvgBuilder(total_w, total_h)
        svg.rect(0, 0, total_w, total_h, fill=theme.bg_color, stroke='none')
        svg.text(total_w / 2, 5, "System Architecture",
                 font_size=theme.font_heading, fill=theme.title_color,
                 anchor='middle', bold=True)

        color_map = theme.arch_color_map

        # Draw cluster boxes
        for name, comps in ordered:
            if name not in positions:
                continue
            x, y, w, h = positions[name]
            fill, stroke, font_color = color_map.get(
                name, (theme.box_fill, theme.box_stroke, theme.box_font))

            body_lines = [_comp_label(c) for c in comps[:8]]
            if len(comps) > 8:
                body_lines.append(f"+{len(comps) - 8} more")

            draw_header_box(svg, x, y, w, h,
                            header_text=name,
                            body_lines=body_lines,
                            header_color=stroke,
                            header_font_color='#ffffff',
                            body_fill=fill,
                            stroke=stroke,
                            body_font_color=font_color,
                            header_h=6.0,
                            theme=theme)

        # Draw connection arrows between MCU and other clusters
        mcu_pos = positions.get('MCU / CPU')
        if mcu_pos:
            for name in positions:
                if name == 'MCU / CPU':
                    continue
                other = positions[name]
                mcu_cx = mcu_pos[0] + mcu_pos[2] / 2
                other_cx = other[0] + other[2] / 2
                if other_cx < mcu_cx:
                    ax1 = mcu_pos[0]
                    ax2 = other[0] + other[2]
                else:
                    ax1 = mcu_pos[0] + mcu_pos[2]
                    ax2 = other[0]
                ay1 = mcu_pos[1] + mcu_pos[3] / 2
                ay2 = other[1] + other[3] / 2

                _, _, a_stroke = color_map.get(
                    name, (theme.box_fill, theme.box_stroke, theme.box_font))
                arrow_color = lighten(a_stroke, 0.45)
                draw_right_angle_arrow(svg, ax1, ay1, ax2, ay2,
                                       color=arrow_color, stroke_width=0.3,
                                       theme=theme)

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        svg.write(output_path)
        return output_path

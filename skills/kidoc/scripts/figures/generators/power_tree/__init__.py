"""Power tree diagram generator.

Renders a publication-quality power distribution tree showing input rails,
protection devices, regulators, and output rails with enable chains.

Input schema (power_tree.json)::

    {
      "input_rails": [{"name": "VBUS", "voltage_hint": "5.0V (USB)"}],
      "regulators": [{
        "ref": "U2", "value": "AMS1117-3.3",
        "input_rail": "VBUS", "output_rail": "+3V3",
        "vout": 3.3, "topology": "LDO",
        "inductor": null, "output_caps": "C1: 10uF"
      }],
      "protection": [{"ref": "D1", "type": "TVS", "value": "5V", "rail": "VBUS"}],
      "enable_chains": [{"source_ref": "U1", "target_ref": "U2"}],
      "output_rails": [{"name": "+3V3", "voltage": 3.3}]
    }
"""

from __future__ import annotations

import math
import os
import re
from typing import Optional

from figures.registry import register
from figures.lib import (
    SvgBuilder, FigureTheme,
    draw_gradient_box, draw_header_box, _format_cap_summary,
)


# ======================================================================
# Helpers
# ======================================================================

_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


def _is_bad_rail(name) -> bool:
    """Return True for rail names that should be filtered from the diagram."""
    if name is None or name == '?':
        return True
    s = str(name)
    if s.startswith('__unnamed_') or s.startswith('__unnamed-'):
        return True
    if _UUID_RE.search(s):
        return True
    # Tuple-like strings from upstream bugs: "(4.5, 40)Vin"
    if s.startswith('(') and ')' in s:
        return True
    return False


def _clean_rail_name(name) -> str:
    """Sanitize a rail name for display.

    Strips hierarchical path prefixes (``/uuid/.../RailName`` → ``RailName``)
    and other upstream artifacts.
    """
    if name is None:
        return '?'
    s = str(name)
    # Strip hierarchical path prefixes containing UUIDs
    if '/' in s and _UUID_RE.search(s):
        # Take the last path segment
        s = s.rsplit('/', 1)[-1]
    return s


def _infer_voltage(rail_name: str) -> str:
    """Extract a voltage hint from a rail name like '+3V3', 'VBUS'."""
    if not rail_name:
        return ""
    name = rail_name.strip().upper()
    m = re.match(r'[+]?(\d+)[Vv](\d+)', name)
    if m:
        return f"{m.group(1)}.{m.group(2)}V"
    m = re.match(r'[+]?(\d+\.?\d*)\s*[Vv]', name)
    if m:
        return f"{m.group(1)}V"
    return {'VBUS': '5.0V (USB)', 'VUSB': '5.0V', 'VIN': 'Input'}.get(name, '')


def _format_topology(topology: str) -> str:
    """Format topology string for display."""
    if not topology:
        return 'Regulator'
    return {
        'ldo': 'LDO', 'linear': 'Linear', 'buck': 'Buck',
        'boost': 'Boost', 'buck-boost': 'Buck-Boost',
        'switching': 'Switching', 'charge_pump': 'Charge Pump',
    }.get(topology.lower(), topology.capitalize())


def _draw_arrow(svg: SvgBuilder, x1: float, y1: float,
                x2: float, y2: float,
                color: str, width: float, head: float,
                dash: str | None = None,
                label: str = "", font_size: float = 2.5) -> None:
    """Arrow with triangular head for power tree diagrams."""
    svg.line(x1, y1, x2, y2, stroke=color, stroke_width=width, dash=dash)
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 0.5:
        return
    nx, ny = dx / dist, dy / dist
    px, py = -ny, nx
    svg.polyline([
        (x2 - nx * head + px * head * 0.4, y2 - ny * head + py * head * 0.4),
        (x2, y2),
        (x2 - nx * head - px * head * 0.4, y2 - ny * head - py * head * 0.4),
    ], stroke=color, fill=color, stroke_width=width * 0.5, closed=True)
    if label:
        svg.text((x1 + x2) / 2, (y1 + y2) / 2 - 2.0, label,
                 font_size=font_size, fill=color, anchor='middle')


# ======================================================================
# Generator
# ======================================================================

@register(name="power_tree", output="power_tree.svg")
class PowerTreeGenerator:
    """Power distribution tree diagram."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> dict | None:
        """Extract power tree data from analysis.

        Derives rail hierarchy, resolves inductor values from component
        lookup, summarizes output capacitors.  Returns None if no
        regulators found.
        """
        regs_raw = [f for f in analysis.get('findings', [])
                    if f.get('detector') == 'detect_power_regulators']
        if not regs_raw:
            return None

        # Component lookup for inductor/cap values
        comp_lookup = {}
        for comp in analysis.get('components', []):
            ref = comp.get('reference', '')
            if ref:
                comp_lookup[ref] = comp

        # Build regulator entries, filtering out bad rails
        regulators = []
        input_rail_set = set()
        output_rail_set = set()
        for reg in regs_raw:
            in_rail = reg.get('input_rail', '?')
            out_rail = reg.get('output_rail', '?')
            # Skip regulators where both rails are bad (unnamed, None, ?, etc.)
            if _is_bad_rail(in_rail) and _is_bad_rail(out_rail):
                continue
            # Clean individual rail names for display
            in_rail = _clean_rail_name(in_rail) if not _is_bad_rail(in_rail) else in_rail
            out_rail = _clean_rail_name(out_rail) if not _is_bad_rail(out_rail) else out_rail
            # Skip regulators where the output is unnamed (nothing useful to show)
            if _is_bad_rail(out_rail):
                continue
            # If only input is bad, label it generically
            if _is_bad_rail(in_rail):
                in_rail = 'VIN'
            input_rail_set.add(in_rail)
            output_rail_set.add(out_rail)

            # Resolve inductor value
            ind_ref = reg.get('inductor', '')
            ind_text = None
            if ind_ref:
                ind_val = comp_lookup.get(ind_ref, {}).get('value', '')
                ind_text = f"{ind_ref}: {ind_val}" if ind_val else ind_ref

            # Summarize output caps
            cap_summary = _format_cap_summary(reg.get('output_capacitors', []))

            regulators.append({
                'ref': reg.get('ref', '?'),
                'value': reg.get('value', ''),
                'input_rail': in_rail,
                'output_rail': out_rail,
                'vout': reg.get('estimated_vout'),
                'topology': _format_topology(reg.get('topology', '')),
                'inductor': ind_text,
                'output_caps': cap_summary,
                'cross_sheet_loads': reg.get('cross_sheet_loads', []),
            })

        # Input rails (roots: appear as input but not as another reg's output)
        input_rail_set.discard(None)
        output_rail_set.discard(None)
        root_inputs = sorted(input_rail_set - output_rail_set)
        if not root_inputs:
            root_inputs = sorted(input_rail_set)
        cascade_inputs = sorted(input_rail_set - set(root_inputs))

        input_rails = [
            {'name': r, 'voltage_hint': _infer_voltage(r)}
            for r in root_inputs + cascade_inputs
        ]

        # Build input rail voltage lookup (for regulator voltage conversion display)
        # Maps rail name -> voltage (from regulators whose output is that rail)
        rail_voltage: dict[str, float] = {}
        for reg in regulators:
            if reg['vout'] and reg['output_rail']:
                rail_voltage[reg['output_rail']] = reg['vout']

        # Resolve input voltage for each regulator
        for reg in regulators:
            vin = rail_voltage.get(reg['input_rail'])
            if vin is None:
                hint = _infer_voltage(reg['input_rail'])
                m = re.match(r'(\d+\.?\d*)\s*V', hint)
                if m:
                    vin = float(m.group(1))
            reg['vin'] = vin

        output_rails = []
        for r in sorted(output_rail_set):
            # Find voltage from regulators
            v = next((reg['vout'] for reg in regulators
                      if reg['output_rail'] == r and reg['vout']), None)

            # Collect load context for this rail
            loads: list[str] = []
            # Cascade: other regulators fed by this rail
            for reg in regulators:
                if reg['input_rail'] == r:
                    loads.append(f"{reg['ref']} ({reg['topology']})")
            # Cross-sheet loads from regulators that output to this rail
            for reg in regulators:
                if reg['output_rail'] == r:
                    for load in reg.get('cross_sheet_loads', []):
                        # Trim to just ref + value: "U3 (STM32, Sheet2)" -> "U3 (STM32)"
                        trimmed = re.sub(r',\s*Sheet\d+\)', ')', str(load))
                        loads.append(trimmed)

            output_rails.append({'name': r, 'voltage': v, 'loads': loads})

        # Protection devices
        prot_raw = [f for f in analysis.get('findings', [])
                    if f.get('detector') == 'detect_protection_devices']
        protection = []
        for pd in prot_raw:
            rail = pd.get('rail', pd.get('net', pd.get('input_rail', '')))
            if rail:
                protection.append({
                    'ref': pd.get('ref', '?'),
                    'type': pd.get('type', ''),
                    'value': pd.get('value', ''),
                    'rail': rail,
                })

        # Enable chains
        chains_raw = (analysis.get('design_analysis', {})
                      .get('power_sequencing', {})
                      .get('enable_chains', []))
        enable_chains = [
            {'source_ref': c.get('source_ref', ''),
             'target_ref': c.get('target_ref', '')}
            for c in (chains_raw or [])
            if c.get('source_ref') and c.get('target_ref')
        ]

        return {
            'input_rails': input_rails,
            'regulators': regulators,
            'protection': protection,
            'enable_chains': enable_chains,
            'output_rails': output_rails,
        }

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        """Render power tree SVG from prepared data.

        Layout: Input rails (left) → Protection (opt) → Regulators
        (center) → Output rails (right).
        """
        theme = theme or FigureTheme()
        regulators = data.get('regulators', [])
        if not regulators:
            return None

        input_rails = data.get('input_rails', [])
        output_rails = data.get('output_rails', [])
        protection = data.get('protection', [])
        enable_chains = data.get('enable_chains', [])

        # Group regulators by input rail
        regs_by_input: dict[str, list[dict]] = {}
        for reg in regulators:
            regs_by_input.setdefault(reg['input_rail'], []).append(reg)
        for key in regs_by_input:
            regs_by_input[key].sort(key=lambda r: r.get('vout') or 0)

        # Output color assignment
        all_output_names = [r['name'] for r in output_rails]
        output_color_map = {}
        for i, name in enumerate(all_output_names):
            output_color_map[name] = theme.pt_output_colors[
                i % len(theme.pt_output_colors)]

        # Protection by rail
        prot_by_rail: dict[str, list[dict]] = {}
        for pd in protection:
            prot_by_rail.setdefault(pd['rail'], []).append(pd)
        has_protection = bool(prot_by_rail)

        # -- Layout geometry --
        arrow_width = 0.8
        arrow_head = 2.5
        box_radius = 3.0
        margin = 15.0
        title_h = 12.0
        legend_h = 15.0

        input_col_w = 50.0
        prot_col_w = 50.0 if has_protection else 0.0
        reg_col_w = 65.0
        output_col_w = 45.0
        col_gap = 25.0

        input_col_x = margin
        prot_col_x = input_col_x + input_col_w + (col_gap if has_protection else 0)
        reg_col_x = prot_col_x + prot_col_w + col_gap
        output_col_x = reg_col_x + reg_col_w + col_gap

        row_h = 32.0
        input_rail_gap = 8.0

        # Count rows
        all_input_names = [r['name'] for r in input_rails]
        total_reg_rows = 0
        for name in all_input_names:
            n = len(regs_by_input.get(name, []))
            total_reg_rows += max(n, 1)

        body_h = total_reg_rows * row_h + max(len(all_input_names) - 1, 0) * input_rail_gap
        total_w = max(output_col_x + output_col_w + margin, 200.0)
        total_h = max(margin + title_h + body_h + legend_h + margin, 100.0)

        svg = SvgBuilder(total_w, total_h)
        svg.rect(0, 0, total_w, total_h, fill=theme.bg_color, stroke='none')
        svg.text(total_w / 2, margin + theme.font_title * 0.6,
                 "Power Distribution Tree",
                 font_size=theme.font_title, fill=theme.title_color,
                 anchor='middle', bold=True)

        body_top = margin + title_h
        input_box_pos: dict[str, tuple[float, float]] = {}
        reg_box_pos: dict[str, tuple[float, float, float, float]] = {}
        output_box_pos: dict[str, tuple[float, float]] = {}
        reg_center_y: dict[str, float] = {}
        _pending: dict[str, list[tuple[float, float, float | None]]] = {}

        current_y = body_top
        for in_rail in input_rails:
            name = in_rail['name']
            regs_for_rail = regs_by_input.get(name, [])
            n_regs = max(len(regs_for_rail), 1)
            group_h = n_regs * row_h

            # Input rail box
            input_box_h = min(group_h, 20.0)
            input_box_y = current_y + (group_h - input_box_h) / 2
            draw_gradient_box(svg, input_col_x, input_box_y,
                              input_col_w, input_box_h,
                              label='', fill=theme.pt_input_fill,
                              stroke='none', font_color=theme.pt_input_text,
                              theme=theme)
            svg.text(input_col_x + input_col_w / 2,
                     input_box_y + input_box_h / 2 - 1.0,
                     name, font_size=4.5, fill=theme.pt_input_text,
                     anchor='middle', dominant_baseline='central', bold=True)
            if in_rail.get('voltage_hint'):
                svg.text(input_col_x + input_col_w / 2,
                         input_box_y + input_box_h / 2 + 3.5,
                         in_rail['voltage_hint'], font_size=3.0,
                         fill=theme.pt_input_subtext,
                         anchor='middle', dominant_baseline='central')
            input_box_pos[name] = (input_col_x + input_col_w,
                                   input_box_y + input_box_h / 2)

            # Protection
            prot_devices = prot_by_rail.get(name, [])
            if has_protection and prot_devices:
                prot_box_h = min(len(prot_devices) * 10.0 + 6.0, group_h)
                prot_box_y = current_y + (group_h - prot_box_h) / 2
                svg.rect(prot_col_x, prot_box_y, prot_col_w, prot_box_h,
                         stroke=theme.pt_prot_stroke, fill=theme.pt_prot_fill,
                         stroke_width=0.4, rx=box_radius)
                for pi, pd in enumerate(prot_devices[:3]):
                    pd_label = pd['ref']
                    if pd.get('type'):
                        pd_label += f" \u2014 {pd['type']}"
                    if pd.get('value'):
                        pd_label += f" ({pd['value']})"
                    svg.text(prot_col_x + prot_col_w / 2,
                             prot_box_y + 5.0 + pi * 8.0,
                             pd_label, font_size=theme.font_small + 0.7,
                             fill=theme.pt_prot_text, anchor='middle',
                             dominant_baseline='central')

            # Regulators
            for reg_idx, reg in enumerate(regs_for_rail):
                reg_y = current_y + reg_idx * row_h
                reg_box_h = row_h - 4.0
                ref = reg['ref']

                # Voltage conversion line (e.g. "5.0V → 3.3V" or "→ 3.3V")
                body_lines = []
                vin = reg.get('vin')
                vout = reg.get('vout')
                if vin and vout:
                    body_lines.append(f"{vin:.1f}V \u2192 {vout:.1f}V")
                elif vout:
                    body_lines.append(f"\u2192 {vout:.1f}V")

                # Topology + inductor
                topo_line = reg['topology']
                if reg.get('inductor'):
                    topo_line += f", {reg['inductor']}"
                body_lines.append(topo_line)

                if reg.get('output_caps'):
                    cap_text = f"Cout: {reg['output_caps']}"
                    if len(cap_text) > 35:
                        cap_text = cap_text[:33] + "\u2026"
                    body_lines.append(cap_text)

                hdr_text = f"{ref} \u2014 {reg['value']}" if reg.get('value') else ref
                if len(hdr_text) > 28:
                    hdr_text = hdr_text[:26] + "\u2026"

                draw_header_box(svg, reg_col_x, reg_y, reg_col_w, reg_box_h,
                                header_text=hdr_text, body_lines=body_lines,
                                header_color=theme.pt_reg_stroke,
                                header_font_color='#ffffff',
                                body_fill=theme.pt_reg_fill,
                                stroke=theme.pt_reg_stroke,
                                body_font_color=theme.pt_reg_text,
                                header_h=6.0, theme=theme)

                reg_box_pos[ref] = (reg_col_x, reg_y, reg_col_w, reg_box_h)
                reg_center_y[ref] = reg_y + reg_box_h / 2
                _pending.setdefault(reg['output_rail'], []).append(
                    (reg_y, reg_box_h, reg.get('vout')))

            current_y += group_h + input_rail_gap

        # Output rail boxes
        for out_rail in output_rails:
            oname = out_rail['name']
            entries = _pending.get(oname, [])
            if not entries:
                continue
            out_fill, out_stroke, out_text = output_color_map.get(
                oname, theme.pt_output_colors[0])
            out_box_h = 18.0
            if len(entries) == 1:
                ry, rh, _ = entries[0]
                out_box_y = ry + (rh - out_box_h) / 2
            else:
                ys = [ry + rh / 2 for ry, rh, _ in entries]
                out_box_y = (min(ys) + max(ys)) / 2 - out_box_h / 2
            v = out_rail.get('voltage')

            draw_gradient_box(svg, output_col_x, out_box_y,
                              output_col_w, out_box_h, label='',
                              fill=out_fill, stroke=out_stroke,
                              font_color=out_text, theme=theme)
            svg.text(output_col_x + output_col_w / 2,
                     out_box_y + out_box_h / 2 - 1.0,
                     oname, font_size=4.5, fill=out_text,
                     anchor='middle', dominant_baseline='central', bold=True)
            # Voltage subtitle
            subtitle_y = out_box_y + out_box_h / 2 + 3.5
            if v:
                svg.text(output_col_x + output_col_w / 2, subtitle_y,
                         f"{v:.2f}V", font_size=3.0, fill=out_stroke,
                         anchor='middle', dominant_baseline='central')
                subtitle_y += 4.0

            # Load context subtitle (KH-202)
            loads = out_rail.get('loads', [])
            if loads:
                if len(loads) <= 2:
                    load_text = ', '.join(loads)
                else:
                    load_text = f"{loads[0]}, {loads[1]} (+{len(loads) - 2})"
                if len(load_text) > 30:
                    load_text = load_text[:28] + "\u2026"
                svg.text(output_col_x + output_col_w / 2, subtitle_y,
                         load_text, font_size=2.5, fill=out_stroke,
                         anchor='middle', dominant_baseline='central')

            output_box_pos[oname] = (output_col_x, out_box_y + out_box_h / 2)

        # Arrows: input → regulators
        for in_rail in input_rails:
            name = in_rail['name']
            regs_for_rail = regs_by_input.get(name, [])
            if not regs_for_rail:
                continue
            in_rx, in_cy = input_box_pos.get(name, (0, 0))

            if len(regs_for_rail) == 1:
                ref = regs_for_rail[0]['ref']
                if ref in reg_box_pos:
                    rx, ry, rw, rh = reg_box_pos[ref]
                    rcy = ry + rh / 2
                    if abs(in_cy - rcy) < 0.5:
                        # Aligned — single horizontal arrow
                        _draw_arrow(svg, in_rx + 2, in_cy, rx - 2, in_cy,
                                    color=theme.pt_arrow_color,
                                    width=arrow_width, head=arrow_head)
                    else:
                        # Misaligned — orthogonal L-route
                        mid_x = in_rx + (rx - in_rx) * 0.5
                        svg.line(in_rx + 2, in_cy, mid_x, in_cy,
                                 stroke=theme.pt_arrow_color,
                                 stroke_width=arrow_width)
                        svg.line(mid_x, in_cy, mid_x, rcy,
                                 stroke=theme.pt_arrow_color,
                                 stroke_width=arrow_width)
                        _draw_arrow(svg, mid_x, rcy, rx - 2, rcy,
                                    color=theme.pt_arrow_color,
                                    width=arrow_width, head=arrow_head)
            else:
                trunk_x = in_rx + (reg_col_x - in_rx) * 0.35
                reg_ys = []
                for reg in regs_for_rail:
                    if reg['ref'] in reg_box_pos:
                        rx, ry, rw, rh = reg_box_pos[reg['ref']]
                        reg_ys.append(ry + rh / 2)
                if reg_ys:
                    svg.line(in_rx + 2, in_cy, trunk_x, in_cy,
                             stroke=theme.pt_arrow_color, stroke_width=arrow_width)
                    svg.line(trunk_x, min(min(reg_ys), in_cy),
                             trunk_x, max(max(reg_ys), in_cy),
                             stroke=theme.pt_arrow_color, stroke_width=arrow_width)
                    for reg in regs_for_rail:
                        if reg['ref'] in reg_box_pos:
                            rx, ry, rw, rh = reg_box_pos[reg['ref']]
                            _draw_arrow(svg, trunk_x, ry + rh / 2,
                                        rx - 2, ry + rh / 2,
                                        color=theme.pt_arrow_color,
                                        width=arrow_width, head=arrow_head)

            # Output arrows
            out_groups: dict[str, list[dict]] = {}
            for reg in regs_for_rail:
                out_groups.setdefault(reg['output_rail'], []).append(reg)
            for oname, gregs in out_groups.items():
                if oname not in output_box_pos:
                    continue
                olx, ocy = output_box_pos[oname]
                if len(gregs) == 1:
                    ref = gregs[0]['ref']
                    if ref in reg_box_pos:
                        rx, ry, rw, rh = reg_box_pos[ref]
                        rcy = ry + rh / 2
                        if abs(rcy - ocy) < 0.5:
                            # Aligned — single horizontal arrow
                            _draw_arrow(svg, rx + rw + 2, rcy,
                                        olx - 2, rcy,
                                        color=theme.pt_arrow_color,
                                        width=arrow_width, head=arrow_head)
                        else:
                            # Misaligned — orthogonal L-route
                            mid_x = rx + rw + (olx - rx - rw) * 0.5
                            svg.line(rx + rw + 2, rcy, mid_x, rcy,
                                     stroke=theme.pt_arrow_color,
                                     stroke_width=arrow_width)
                            svg.line(mid_x, rcy, mid_x, ocy,
                                     stroke=theme.pt_arrow_color,
                                     stroke_width=arrow_width)
                            _draw_arrow(svg, mid_x, ocy, olx - 2, ocy,
                                        color=theme.pt_arrow_color,
                                        width=arrow_width, head=arrow_head)
                else:
                    trunk_x = reg_col_x + reg_col_w + (output_col_x - reg_col_x - reg_col_w) * 0.65
                    reg_ys = []
                    for reg in gregs:
                        if reg['ref'] in reg_box_pos:
                            rx, ry, rw, rh = reg_box_pos[reg['ref']]
                            reg_ys.append(ry + rh / 2)
                    if reg_ys:
                        for reg in gregs:
                            if reg['ref'] in reg_box_pos:
                                rx, ry, rw, rh = reg_box_pos[reg['ref']]
                                svg.line(rx + rw + 2, ry + rh / 2, trunk_x, ry + rh / 2,
                                         stroke=theme.pt_arrow_color, stroke_width=arrow_width)
                        svg.line(trunk_x, min(min(reg_ys), ocy),
                                 trunk_x, max(max(reg_ys), ocy),
                                 stroke=theme.pt_arrow_color, stroke_width=arrow_width)
                        _draw_arrow(svg, trunk_x, ocy, olx - 2, ocy,
                                    color=theme.pt_arrow_color,
                                    width=arrow_width, head=arrow_head)

        # Enable chains
        for chain in enable_chains:
            src = chain.get('source_ref', '')
            tgt = chain.get('target_ref', '')
            if src in reg_box_pos and tgt in reg_box_pos:
                sx, sy, sw, sh = reg_box_pos[src]
                tx, ty, tw, th = reg_box_pos[tgt]
                _draw_arrow(svg, sx + sw + 3, sy + sh * 0.8,
                            tx - 3, ty + th * 0.2,
                            color=theme.pt_enable_color, width=0.5,
                            head=2.0, dash="2,1.5", label="PG\u2192EN",
                            font_size=theme.font_small + 0.7)

        # Legend
        legend_y = total_h - legend_h - margin / 2
        svg.line(margin, legend_y - 2, total_w - margin, legend_y - 2,
                 stroke='#e0e0e0', stroke_width=0.3)
        items = [
            ("Input Rail", theme.pt_input_fill, 'none'),
            ("Regulator", theme.pt_reg_fill, theme.pt_reg_stroke),
        ]
        if has_protection:
            items.append(("Protection", theme.pt_prot_fill, theme.pt_prot_stroke))
        if all_output_names:
            if len(all_output_names) <= 5:
                for oname in all_output_names:
                    of, os_, _ = output_color_map.get(
                        oname, theme.pt_output_colors[0])
                    items.append((oname, of, os_))
            else:
                of, os_, _ = theme.pt_output_colors[0]
                items.append(("Output Rails", of, os_))

        cx = margin
        for label, fill, stroke in items:
            svg.rect(cx, legend_y, 8.0, 5.0, fill=fill,
                     stroke=stroke if stroke != 'none' else fill,
                     stroke_width=0.3, rx=1.0)
            svg.text(cx + 10.0, legend_y + 2.5, label,
                     font_size=theme.font_caption, fill='#555555',
                     anchor='start', dominant_baseline='central')
            cx += 10.0 + len(label) * theme.font_caption * 0.55 + 4.0

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        svg.write(output_path)
        return output_path

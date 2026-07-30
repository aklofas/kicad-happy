"""Pinout diagram generator (class-based).

Renders publication-quality SVG pinout diagrams for connectors.
Shows physical pin arrangement with signal names, direction arrows,
color coding, and ESD protection indicators.

Multi-output generator: produces one SVG per connector.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from figures.registry import register
from figures.lib import SvgBuilder, FigureTheme
from figures.lib.theme import darken


# ======================================================================
# Constants (layout dimensions in mm, not theme-dependent)
# ======================================================================

DIRECTION_ARROWS = {
    'input': '\u2192', 'output': '\u2190', 'bidirectional': '\u2194',
    'passive': '', 'power_in': '', 'power_out': '', 'no_connect': '',
    'unspecified': '', 'tri_state': '\u2194',
    'open_collector': '\u2190', 'open_emitter': '\u2190', 'free': '',
}

PIN_W = 8.0
PIN_H = 5.0
PIN_GAP = 1.5
PIN_RADIUS = 1.0
DUAL_COL_GAP = 1.5
LABEL_FONT = 3.0
NET_FONT = 2.2
TITLE_FONT = 4.5
LEGEND_FONT = 2.5
PIN_NUM_FONT = 2.5
ESD_DOT_R = 0.75
MARGIN = 8.0
TITLE_H = 10.0
LEGEND_H = 12.0
LABEL_GAP = 2.5


# ======================================================================
# Theme-aware color helpers
# ======================================================================

def _pin_colors(theme: FigureTheme) -> dict[str, tuple[str, str, str]]:
    """Return pin classification color map from theme."""
    return {
        'power':  theme.pin_power,
        'ground': theme.pin_ground,
        'signal': theme.pin_signal,
        'nc':     theme.pin_nc,
    }


# ======================================================================
# Classification helpers
# ======================================================================

def _detect_layout(lib_id: str, value: str, pin_count: int) -> tuple[str, int]:
    """Detect connector layout from library ID."""
    lib_lower = (lib_id + ' ' + value).lower()
    m = re.search(r'(?:pinheader|conn)[_ ]?0?2x(\d+)', lib_lower)
    if m:
        return ('dual', int(m.group(1)))
    m = re.search(r'(?:pinheader|conn)[_ ]?0?1x(\d+)', lib_lower)
    if m:
        return ('single', int(m.group(1)))
    if 'usb_c' in lib_lower or 'usb-c' in lib_lower:
        return ('usb_c', 12)
    if 'barrel' in lib_lower:
        return ('barrel', pin_count)
    if 'rj45' in lib_lower or '8p8c' in lib_lower:
        return ('single', 8)
    if 'rj11' in lib_lower or '6p6c' in lib_lower:
        return ('single', 6)
    m = re.search(r'screw_terminal[_ ]?0?1x(\d+)', lib_lower)
    if m:
        return ('single', int(m.group(1)))
    m = re.search(r'screw_terminal[_ ](\d+)', lib_lower)
    if m:
        return ('single', int(m.group(1)))
    if pin_count <= 6:
        return ('single', pin_count)
    return ('dual', (pin_count + 1) // 2)


def _classify_pin(pin_name: str, net_name: str, pin_type: str) -> str:
    """Classify pin for color coding."""
    name_lower = (pin_name + ' ' + net_name).lower()
    if pin_type == 'no_connect' or 'nc' in name_lower or net_name.startswith('__unnamed'):
        return 'nc'
    if any(g in name_lower for g in ('gnd', 'vss', 'ground', 'pgnd', 'agnd', 'dgnd')):
        return 'ground'
    if any(p in name_lower for p in ('vcc', 'vdd', 'vin', 'vbus', '5v', '3v3', '3.3v',
                                      '12v', 'vbat', 'vsys', 'vout', '+5v', '+3v3', '+12v')):
        return 'power'
    return 'signal'


def _sort_key(pin_number: str) -> tuple[int, str]:
    m = re.match(r'^(\d+)', pin_number)
    if m:
        return (int(m.group(1)), pin_number)
    return (999999, pin_number)


def _estimate_text_width(text: str, font_size: float) -> float:
    return len(text) * font_size * 0.55


# ======================================================================
# Drawing helpers
# ======================================================================

def _draw_pin_rect(svg: SvgBuilder, x: float, y: float,
                   pin_number: str, classification: str,
                   colors: dict[str, tuple[str, str, str]],
                   theme: FigureTheme) -> None:
    """Draw a single pin rectangle with its number centered."""
    fill, stroke, _text = colors[classification]
    if theme.use_gradients:
        grad = svg.linear_gradient(fill, darken(fill, 0.06))
        svg.rect(x, y, PIN_W, PIN_H, stroke=stroke, fill=grad,
                 stroke_width=0.3, rx=PIN_RADIUS)
    else:
        svg.rect(x, y, PIN_W, PIN_H, stroke=stroke, fill=fill,
                 stroke_width=0.3, rx=PIN_RADIUS)
    svg.text(x + PIN_W / 2, y + PIN_H / 2, pin_number,
             font_size=PIN_NUM_FONT, fill=stroke,
             anchor='middle', dominant_baseline='central', bold=True)


def _draw_esd_dot(svg: SvgBuilder, cx: float, cy: float,
                  protected: bool, theme: FigureTheme) -> None:
    color = theme.pin_esd_ok if protected else theme.pin_esd_missing
    svg.circle(cx, cy, ESD_DOT_R, fill=color, stroke='none')


def _draw_label(svg: SvgBuilder, x: float, y: float,
                pin_name: str, net_name: str, pin_type: str,
                classification: str,
                colors: dict[str, tuple[str, str, str]],
                anchor: str = 'start') -> float:
    """Draw signal name, direction arrow, and net name."""
    _fill, _stroke, text_color = colors[classification]
    arrow = DIRECTION_ARROWS.get(pin_type, '')

    if pin_name and pin_name != '~':
        display = pin_name
    elif net_name and not net_name.startswith('__unnamed'):
        display = net_name
    else:
        display = 'NC'

    if arrow:
        if anchor == 'end':
            display = arrow + ' ' + display
        else:
            display = display + ' ' + arrow

    svg.text(x, y, display,
             font_size=LABEL_FONT, fill=text_color,
             anchor=anchor, dominant_baseline='central')

    width = _estimate_text_width(display, LABEL_FONT)

    show_net = (net_name and pin_name and pin_name != '~'
                and net_name != pin_name
                and not net_name.startswith('__unnamed'))
    if show_net:
        svg.text(x, y + LABEL_FONT + 0.5, net_name,
                 font_size=NET_FONT, fill='#888888',
                 anchor=anchor, dominant_baseline='central',
                 italic=True)
        net_w = _estimate_text_width(net_name, NET_FONT)
        width = max(width, net_w)

    return width


# ======================================================================
# Layout renderers
# ======================================================================

def _render_single(svg: SvgBuilder, pins: list[dict],
                   esd_map: dict[str, bool],
                   start_x: float, start_y: float,
                   has_esd: bool,
                   colors: dict[str, tuple[str, str, str]],
                   theme: FigureTheme) -> tuple[float, float]:
    pins_sorted = sorted(pins, key=lambda p: _sort_key(p['pin_number']))

    max_label_w = 0.0
    for pin in pins_sorted:
        arrow = DIRECTION_ARROWS.get(pin['pin_type'], '')
        name = pin['pin_name'] if pin['pin_name'] != '~' else pin['net_name']
        if not name or name.startswith('__unnamed'):
            name = 'NC'
        display = name + (' ' + arrow if arrow else '')
        w = _estimate_text_width(display, LABEL_FONT)
        if (pin['net_name'] and pin['pin_name'] != '~'
                and pin['net_name'] != pin['pin_name']
                and not pin['net_name'].startswith('__unnamed')):
            net_w = _estimate_text_width(pin['net_name'], NET_FONT)
            w = max(w, net_w)
        max_label_w = max(max_label_w, w)

    esd_col_w = (ESD_DOT_R * 2 + 3.0) if has_esd else 0.0
    total_w = PIN_W + LABEL_GAP + max_label_w + LABEL_GAP + esd_col_w
    total_h = len(pins_sorted) * (PIN_H + PIN_GAP) - PIN_GAP

    for i, pin in enumerate(pins_sorted):
        cls = _classify_pin(pin['pin_name'], pin['net_name'], pin['pin_type'])
        py = start_y + i * (PIN_H + PIN_GAP)
        _draw_pin_rect(svg, start_x, py, pin['pin_number'], cls, colors, theme)
        label_x = start_x + PIN_W + LABEL_GAP
        label_cy = py + PIN_H / 2
        _draw_label(svg, label_x, label_cy,
                    pin['pin_name'], pin['net_name'],
                    pin['pin_type'], cls, colors, anchor='start')
        if has_esd:
            net = pin['net_name']
            protected = esd_map.get(net, None)
            if protected is not None:
                dot_x = start_x + total_w - ESD_DOT_R - 1.0
                _draw_esd_dot(svg, dot_x, label_cy, protected, theme)

    return (total_w, total_h)


def _render_dual(svg: SvgBuilder, pins: list[dict],
                 esd_map: dict[str, bool],
                 start_x: float, start_y: float,
                 has_esd: bool,
                 colors: dict[str, tuple[str, str, str]],
                 theme: FigureTheme) -> tuple[float, float]:
    pins_sorted = sorted(pins, key=lambda p: _sort_key(p['pin_number']))
    left_pins = [p for p in pins_sorted if _sort_key(p['pin_number'])[0] % 2 == 1]
    right_pins = [p for p in pins_sorted if _sort_key(p['pin_number'])[0] % 2 == 0]
    if not left_pins and not right_pins:
        left_pins = pins_sorted[::2]
        right_pins = pins_sorted[1::2]
    elif not left_pins:
        left_pins = pins_sorted[:len(pins_sorted) // 2]
        right_pins = pins_sorted[len(pins_sorted) // 2:]
    elif not right_pins:
        left_pins = pins_sorted[:len(pins_sorted) // 2]
        right_pins = pins_sorted[len(pins_sorted) // 2:]
    n_rows = max(len(left_pins), len(right_pins))

    def _measure_side(side_pins: list[dict]) -> float:
        max_w = 0.0
        for pin in side_pins:
            arrow = DIRECTION_ARROWS.get(pin['pin_type'], '')
            name = pin['pin_name'] if pin['pin_name'] != '~' else pin['net_name']
            if not name or name.startswith('__unnamed'):
                name = 'NC'
            display = (arrow + ' ' + name) if arrow else name
            w = _estimate_text_width(display, LABEL_FONT)
            if (pin['net_name'] and pin['pin_name'] != '~'
                    and pin['net_name'] != pin['pin_name']
                    and not pin['net_name'].startswith('__unnamed')):
                net_w = _estimate_text_width(pin['net_name'], NET_FONT)
                w = max(w, net_w)
            max_w = max(max_w, w)
        return max_w

    left_label_w = _measure_side(left_pins)
    right_label_w = _measure_side(right_pins)
    esd_col_w = (ESD_DOT_R * 2 + 3.0) if has_esd else 0.0

    left_esd_x = start_x
    left_label_start = start_x + esd_col_w
    left_pin_x = left_label_start + left_label_w + LABEL_GAP
    right_pin_x = left_pin_x + PIN_W + DUAL_COL_GAP
    right_label_x = right_pin_x + PIN_W + LABEL_GAP
    right_esd_x = right_label_x + right_label_w + LABEL_GAP
    total_w = right_esd_x + esd_col_w - start_x
    total_h = n_rows * (PIN_H + PIN_GAP) - PIN_GAP

    for row in range(n_rows):
        py = start_y + row * (PIN_H + PIN_GAP)
        if row < len(left_pins):
            pin = left_pins[row]
            cls = _classify_pin(pin['pin_name'], pin['net_name'], pin['pin_type'])
            _draw_pin_rect(svg, left_pin_x, py, pin['pin_number'], cls, colors, theme)
            label_x = left_pin_x - LABEL_GAP
            label_cy = py + PIN_H / 2
            _draw_label(svg, label_x, label_cy,
                        pin['pin_name'], pin['net_name'],
                        pin['pin_type'], cls, colors, anchor='end')
            if has_esd:
                protected = esd_map.get(pin['net_name'], None)
                if protected is not None:
                    _draw_esd_dot(svg, left_esd_x + ESD_DOT_R + 0.5,
                                  label_cy, protected, theme)
        if row < len(right_pins):
            pin = right_pins[row]
            cls = _classify_pin(pin['pin_name'], pin['net_name'], pin['pin_type'])
            _draw_pin_rect(svg, right_pin_x, py, pin['pin_number'], cls, colors, theme)
            label_x = right_pin_x + PIN_W + LABEL_GAP
            label_cy = py + PIN_H / 2
            _draw_label(svg, label_x, label_cy,
                        pin['pin_name'], pin['net_name'],
                        pin['pin_type'], cls, colors, anchor='start')
            if has_esd:
                protected = esd_map.get(pin['net_name'], None)
                if protected is not None:
                    _draw_esd_dot(svg, right_esd_x - ESD_DOT_R - 0.5,
                                  label_cy, protected, theme)

    return (total_w, total_h)


# ======================================================================
# Legend
# ======================================================================

def _draw_legend(svg: SvgBuilder, x: float, y: float,
                 width: float, has_esd: bool,
                 colors: dict[str, tuple[str, str, str]],
                 theme: FigureTheme) -> None:
    svg.line(x, y - 2, x + width, y - 2,
             stroke='#e0e0e0', stroke_width=0.3)
    cx = x
    swatch_w = 6.0
    swatch_h = 4.0
    gap = 3.0
    items = [('Power', 'power'), ('Ground', 'ground'),
             ('Signal', 'signal'), ('NC', 'nc')]
    for label, cls in items:
        fill, stroke, _text = colors[cls]
        svg.rect(cx, y, swatch_w, swatch_h,
                 fill=fill, stroke=stroke,
                 stroke_width=0.3, rx=PIN_RADIUS)
        svg.text(cx + swatch_w + 1.5, y + swatch_h / 2, label,
                 font_size=LEGEND_FONT, fill='#555555',
                 anchor='start', dominant_baseline='central')
        cx += swatch_w + 1.5 + _estimate_text_width(label, LEGEND_FONT) + gap
    if has_esd:
        svg.circle(cx + ESD_DOT_R, y + swatch_h / 2, ESD_DOT_R,
                   fill=theme.pin_esd_ok, stroke='none')
        svg.text(cx + ESD_DOT_R * 2 + 1.5, y + swatch_h / 2, 'Protected',
                 font_size=LEGEND_FONT, fill='#555555',
                 anchor='start', dominant_baseline='central')
        cx += ESD_DOT_R * 2 + 1.5 + _estimate_text_width('Protected', LEGEND_FONT) + gap
        svg.circle(cx + ESD_DOT_R, y + swatch_h / 2, ESD_DOT_R,
                   fill=theme.pin_esd_missing, stroke='none')
        svg.text(cx + ESD_DOT_R * 2 + 1.5, y + swatch_h / 2, 'Unprotected',
                 font_size=LEGEND_FONT, fill='#555555',
                 anchor='start', dominant_baseline='central')


# ======================================================================
# Generator class
# ======================================================================

@register(name="pinouts", output="pinouts/", multi_output=True)
class PinoutGenerator:
    """Connector pinout diagram generator (multi-output).

    Produces one SVG per connector found in the schematic analysis.
    """

    @staticmethod
    def prepare(analysis: dict, config: dict) -> list[tuple[str, dict]] | None:
        """Extract connector pin data from schematic analysis.

        Returns a list of (key, data) tuples where key is like
        ``"pinout_J1"`` and data contains everything needed to render
        that connector's pinout SVG.  Returns None if no connectors.
        """
        components = analysis.get('components', [])
        nets = analysis.get('nets', {})
        from finding_schema import Det, get_findings
        esd_audit = get_findings(analysis, Det.ESD_AUDIT)

        # ESD data indexed by connector reference
        esd_by_ref: dict[str, dict] = {}
        for entry in esd_audit:
            ref = entry.get('connector_ref', '')
            if ref:
                esd_by_ref[ref] = entry

        # Build pin-to-net mapping: (component_ref, pin_number) -> (net, name, type)
        pin_net_map: dict[tuple[str, str], tuple[str, str, str]] = {}
        for net_name, net_info in nets.items():
            if isinstance(net_info, dict):
                for pin_entry in net_info.get('pins', []):
                    comp = pin_entry.get('component', '')
                    pin_num = pin_entry.get('pin_number', '')
                    pin_name = pin_entry.get('pin_name', '~')
                    pin_type = pin_entry.get('pin_type', 'passive')
                    if comp and pin_num:
                        pin_net_map[(comp, pin_num)] = (net_name, pin_name, pin_type)

        connectors = [c for c in components if c.get('type') == 'connector']
        if not connectors:
            return None

        results: list[tuple[str, dict]] = []
        for connector in connectors:
            ref = connector.get('reference', '')
            if not ref:
                continue

            # Collect pins for this connector from the net map
            connector_pins: dict[str, tuple[str, str, str]] = {}
            for (comp, pin_num), (net_name, pin_name, pin_type) in pin_net_map.items():
                if comp == ref:
                    connector_pins[pin_num] = (net_name, pin_name, pin_type)

            pin_uuids = connector.get('pin_uuids', {})
            pin_data: list[dict] = []

            if pin_uuids:
                for pin_num in pin_uuids:
                    if pin_num in connector_pins:
                        net_name, pin_name, pin_type = connector_pins[pin_num]
                    else:
                        net_name = ''
                        pin_name = '~'
                        pin_type = 'no_connect'
                    pin_data.append({
                        'pin_number': str(pin_num),
                        'pin_name': pin_name,
                        'net_name': net_name,
                        'pin_type': pin_type,
                    })
            else:
                for pin_num, (net_name, pin_name, pin_type) in sorted(
                        connector_pins.items(), key=lambda x: _sort_key(x[0])):
                    pin_data.append({
                        'pin_number': str(pin_num),
                        'pin_name': pin_name,
                        'net_name': net_name,
                        'pin_type': pin_type,
                    })

            if not pin_data:
                continue

            # ESD protection data for this connector
            esd_entry = esd_by_ref.get(ref)
            esd: dict | None = None
            if esd_entry:
                esd = {
                    'protected_nets': esd_entry.get('protected_nets', []),
                    'unprotected_nets': esd_entry.get('unprotected_nets', []),
                }

            data = {
                'ref': ref,
                'value': connector.get('value', ''),
                'lib_id': connector.get('lib_id', ''),
                'description': connector.get('description', ''),
                'pins': pin_data,
                'esd': esd,
            }

            results.append((f"pinout_{ref}", data))

        return results if results else None

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        """Render a single connector's pinout SVG from prepared data.

        Args:
            data: prepared dict with ref, value, lib_id, description,
                  pins, and optional esd fields.
            output_path: full path for the output SVG file.
            theme: FigureTheme for colors/fonts.

        Returns: path to generated SVG, or None if no pins.
        """
        theme = theme or FigureTheme()

        pin_data = data.get('pins', [])
        if not pin_data:
            return None

        colors = _pin_colors(theme)

        ref = data.get('ref', '?')
        value = data.get('value', '')
        lib_id = data.get('lib_id', '')
        description = data.get('description', '')

        # Build ESD map
        esd_map: dict[str, bool] = {}
        has_esd = False
        esd_info = data.get('esd')
        if esd_info:
            has_esd = True
            for net in esd_info.get('protected_nets', []):
                esd_map[net] = True
            for net in esd_info.get('unprotected_nets', []):
                esd_map[net] = False

        layout_type, _pins_per_side = _detect_layout(lib_id, value, len(pin_data))

        # Title
        title_text = f"{ref} \u2014 {value}" if value else ref
        if description and description != value:
            desc = description
            if len(desc) > 50:
                desc = desc[:48] + '\u2026'
            title_text += f"  ({desc})"

        # Estimate dimensions for initial render pass
        n_pins = len(pin_data)
        if layout_type in ('dual', 'usb_c'):
            n_rows = (n_pins + 1) // 2
            est_body_w = 140.0
        else:
            n_rows = n_pins
            est_body_w = 100.0

        est_body_h = n_rows * (PIN_H + PIN_GAP) - PIN_GAP
        svg_w = MARGIN * 2 + est_body_w
        svg_h = MARGIN * 2 + TITLE_H + est_body_h + LEGEND_H

        # First pass: measure actual dimensions
        svg = SvgBuilder(svg_w, svg_h)
        svg.rect(0, 0, svg_w, svg_h, fill=theme.bg_color, stroke='none')
        svg.text(svg_w / 2, MARGIN + TITLE_FONT * 0.6, title_text,
                 font_size=TITLE_FONT, fill=theme.title_color,
                 anchor='middle', dominant_baseline='auto', bold=True)
        body_y = MARGIN + TITLE_H

        renderers = {
            'single': _render_single,
            'dual': _render_dual,
            'barrel': _render_single,
            'usb_c': _render_dual,
        }
        renderer = renderers.get(layout_type, _render_single)

        actual_w, actual_h = renderer(svg, pin_data, esd_map,
                                      MARGIN, body_y, has_esd,
                                      colors, theme)

        # Rebuild SVG with correct dimensions
        final_w = max(MARGIN * 2 + actual_w,
                      MARGIN * 2 + _estimate_text_width(title_text, TITLE_FONT))
        final_h = MARGIN + TITLE_H + actual_h + LEGEND_H + MARGIN

        svg = SvgBuilder(final_w, final_h)
        svg.rect(0, 0, final_w, final_h, fill=theme.bg_color, stroke='none')
        svg.text(final_w / 2, MARGIN + TITLE_FONT * 0.6, title_text,
                 font_size=TITLE_FONT, fill=theme.title_color,
                 anchor='middle', dominant_baseline='auto', bold=True)

        body_x = (final_w - actual_w) / 2
        body_y = MARGIN + TITLE_H
        renderer(svg, pin_data, esd_map, body_x, body_y, has_esd,
                 colors, theme)

        legend_y = MARGIN + TITLE_H + actual_h + 5.0
        _draw_legend(svg, MARGIN, legend_y, final_w - MARGIN * 2, has_esd,
                     colors, theme)

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        svg.write(output_path)
        return output_path

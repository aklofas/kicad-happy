"""Bus topology diagram generator.

Renders a bus topology SVG showing I2C, SPI, UART, and CAN buses
with their connected devices.

Input schema (from prepare)::

    {
      "buses": [
        {
          "type": "I2C",
          "devices": [
            {"ref": "U1", "value": "MCU", "role": "master"},
            {"ref": "U3", "value": "EEPROM", "role": ""}
          ],
          "master": "U1",
          "signals": ["SDA", "SCL"]
        }
      ]
    }
"""

from __future__ import annotations

import os
from typing import Optional

from figures.registry import register
from figures.lib import SvgBuilder, FigureTheme, _draw_bus_line, draw_shadow_box


@register(name="bus_topology", output="bus_topology.svg")
class BusTopologyGenerator:
    """Bus topology diagram showing I2C, SPI, UART, CAN buses."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> dict | None:
        """Extract bus topology data from analysis.

        Scans ``design_analysis.bus_analysis`` for i2c, spi, uart, and
        can buses.  For each bus instance collects the device list,
        master/controller, and signal names.  Returns None if no buses
        are found.
        """
        bus_analysis = (analysis
                        .get('design_analysis', {})
                        .get('bus_analysis', {}))

        buses: list[dict] = []
        for bus_type in ('i2c', 'spi', 'uart', 'can'):
            bus_list = bus_analysis.get(bus_type, [])
            if not isinstance(bus_list, list):
                continue
            for bus in bus_list:
                if not isinstance(bus, dict):
                    continue

                # Collect devices from various key names
                devices: list[dict] = []
                for key in ('devices', 'peripherals', 'members', 'endpoints'):
                    devs = bus.get(key, [])
                    if isinstance(devs, list):
                        devices.extend(devs)

                # Resolve master / controller
                master_ref: str | None = None
                master = bus.get('master') or bus.get('controller')
                if master:
                    if isinstance(master, str):
                        master_ref = master
                        devices.insert(0, {'ref': master, 'role': 'master'})
                    elif isinstance(master, dict):
                        master_ref = master.get('ref', '')
                        master['role'] = 'master'
                        devices.insert(0, master)

                # De-duplicate by ref
                seen: set[str] = set()
                unique_devices: list[dict] = []
                for d in devices:
                    if isinstance(d, dict):
                        ref = d.get('ref', '')
                        role = d.get('role', '')
                        value = d.get('value', '')
                    else:
                        ref = str(d)
                        role = ''
                        value = ''
                    if ref and ref not in seen:
                        seen.add(ref)
                        unique_devices.append({
                            'ref': ref,
                            'value': value,
                            'role': role,
                        })

                # Signals / nets
                raw_signals = bus.get('signals', bus.get('nets', []))
                signals: list[str] = []
                if isinstance(raw_signals, list):
                    for sig in raw_signals:
                        if isinstance(sig, dict):
                            signals.append(sig.get('name', str(sig)))
                        else:
                            signals.append(str(sig))

                buses.append({
                    'type': bus_type.upper(),
                    'devices': unique_devices,
                    'master': master_ref,
                    'signals': signals,
                })

        if not buses:
            return None

        return {'buses': buses}

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        """Render bus topology SVG from prepared data.

        Layout: one horizontal bus line per bus instance.  Devices hang
        above/below the line in alternating positions, connected by
        vertical stubs.  Signal names are shown when a bus has no
        devices.
        """
        theme = theme or FigureTheme()

        buses = data.get('buses', [])
        if not buses:
            return None

        # Layout constants
        bus_h = 30.0
        bus_spacing = 10.0
        margin = 15.0
        device_w = 25.0
        device_h = 10.0
        device_spacing = 8.0

        total_h = margin * 2 + len(buses) * (bus_h + bus_spacing)
        total_w = 250.0

        svg = SvgBuilder(total_w, total_h)
        svg.rect(0, 0, total_w, total_h, fill=theme.bg_color, stroke='none')
        svg.text(total_w / 2, 6, "Bus Topology",
                 font_size=4, fill=theme.title_color, anchor='middle',
                 bold=True)

        y_offset = margin + 5

        for bus_entry in buses:
            bus_type = bus_entry['type']
            devices = bus_entry.get('devices', [])
            signals = bus_entry.get('signals', [])

            # Bus type label
            svg.text(margin, y_offset + 4, bus_type,
                     font_size=theme.font_body, fill=theme.bus_font,
                     bold=True)

            # Horizontal bus line
            bus_line_y = y_offset + bus_h / 2
            bus_line_x1 = margin + 20
            bus_line_x2 = total_w - margin
            _draw_bus_line(svg, bus_line_x1, bus_line_y,
                           bus_line_x2, bus_line_y,
                           color=theme.bus_stroke, width=0.8)

            n_devices = len(devices)
            if n_devices == 0:
                # No devices -- show signal names along the bus line
                for i, sig_name in enumerate(signals[:8]):
                    x = bus_line_x1 + 10 + i * (device_w + 3)
                    svg.text(x, bus_line_y - 3, sig_name,
                             font_size=theme.font_small,
                             fill=theme.label_font)
            else:
                spacing = min(
                    device_spacing + device_w,
                    (bus_line_x2 - bus_line_x1 - 10) / max(n_devices, 1),
                )
                for i, dev in enumerate(devices):
                    ref = dev.get('ref', '?')
                    role = dev.get('role', '')
                    value = dev.get('value', '')

                    dx = bus_line_x1 + 10 + i * spacing
                    # Alternate above / below the bus line
                    dy = bus_line_y - device_h - 3
                    if i % 2 == 1:
                        dy = bus_line_y + 3

                    # Style: master devices use power palette
                    if role == 'master':
                        fill = theme.power_fill
                        stroke = theme.power_stroke
                        font_color = theme.power_font
                    else:
                        fill = theme.box_fill
                        stroke = theme.box_stroke
                        font_color = theme.box_font

                    draw_shadow_box(
                        svg, dx, dy, device_w, device_h, ref,
                        sublabel=value[:15] if value else role,
                        fill=fill, stroke=stroke,
                        font_color=font_color, theme=theme,
                    )

                    # Vertical stub connecting device box to bus line
                    conn_y = dy + device_h if dy < bus_line_y else dy
                    svg.line(dx + device_w / 2, conn_y,
                             dx + device_w / 2, bus_line_y,
                             stroke=theme.arrow_color, stroke_width=0.3)

            y_offset += bus_h + bus_spacing

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        svg.write(output_path)
        return output_path

"""PCB view figure generator.

Renders PCB layer views (assembly, routing) using layer presets.
Multi-output: one SVG per preset.

Input schema (per view, e.g. pcb_assembly_front.json)::

    {
      "pcb_path": "/path/to/board.kicad_pcb",
      "preset": "assembly-front",
      "highlight_nets": ["GND", "+3V3"]
    }
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from figures.registry import register
from figures.lib.theme import FigureTheme

# Default presets to render
_DEFAULT_PRESETS = ['assembly-front', 'routing-front']


@register(name="pcb_views", output="pcb/",
          multi_output=True)
class PcbViewsGenerator:
    """PCB layer preset renders."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> list[tuple[str, dict]] | None:
        pcb_path = analysis.get('_pcb_path')
        if not pcb_path or not os.path.isfile(pcb_path):
            return None

        # Allow config to override which presets to render
        presets = (config.get('reports', {})
                   .get('pcb_presets', _DEFAULT_PRESETS))

        highlight_nets = analysis.get('_pcb_highlight_nets', [])

        views = []
        for preset in presets:
            key = f"pcb_{preset.replace('-', '_')}"
            views.append((key, {
                'pcb_path': pcb_path,
                'preset': preset,
                'highlight_nets': highlight_nets,
            }))

        return views if views else None

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        pcb_path = data.get('pcb_path')
        if not pcb_path or not os.path.isfile(pcb_path):
            return None

        preset = data.get('preset', 'assembly-front')
        highlight_nets = data.get('highlight_nets') or None

        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)

        try:
            from figures.renderers import render_pcb
            path = render_pcb(pcb_path, output_dir,
                              preset_name=preset,
                              highlight_nets=highlight_nets)
            # render_pcb names the file based on preset, rename to match
            if path and path != output_path:
                try:
                    os.replace(path, output_path)
                    return output_path
                except OSError:
                    return path
            return path
        except Exception as exc:
            print(f"  [pcb_views/{preset}] render failed: {exc}",
                  file=sys.stderr)
            return None

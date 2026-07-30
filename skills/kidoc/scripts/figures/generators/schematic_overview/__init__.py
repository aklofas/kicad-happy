"""Schematic overview figure generator.

Renders full-sheet schematic SVGs for system overview and appendix
sections.  Uses kicad-cli when available, falls back to the custom
renderer.

Input schema (schematic_overview.json)::

    {
      "sch_path": "/path/to/design.kicad_sch",
      "pin_nets": {"U1": {"1": "VCC", "2": "GND"}, ...},
      "use_kicad_cli": true
    }
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from figures.registry import register
from figures.lib.theme import FigureTheme
from figures.lib.analysis_helpers import build_pin_nets


@register(name="schematic_overview", output="schematics/",
          multi_output=True)
class SchematicOverviewGenerator:
    """Full-sheet schematic SVG renders."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> list[tuple[str, dict]] | None:
        sch_path = analysis.get('_sch_path')
        if not sch_path or not os.path.isfile(sch_path):
            return None

        pin_nets = build_pin_nets(analysis)

        # Check kicad-cli availability
        try:
            from kicad_cli import find_kicad_cli
            kicad_cli = find_kicad_cli()
        except ImportError:
            kicad_cli = None

        data = {
            'sch_path': sch_path,
            'pin_nets': pin_nets,
            'use_kicad_cli': bool(kicad_cli),
            'kicad_cli_cmd': kicad_cli,
        }

        return [('schematic_overview', data)]

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        sch_path = data.get('sch_path')
        if not sch_path or not os.path.isfile(sch_path):
            return None

        # output_path for multi_output is like "schematics/schematic_overview.svg"
        # We want the directory part as our output dir
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)

        kicad_cli_cmd = data.get('kicad_cli_cmd')
        pin_nets = data.get('pin_nets')

        if kicad_cli_cmd and data.get('use_kicad_cli'):
            try:
                from kicad_cli import export_sch_svg
                ok = export_sch_svg(kicad_cli_cmd, sch_path, output_dir)
                if ok:
                    paths = sorted(str(p) for p in Path(output_dir).glob('*.svg'))
                    return paths[0] if paths else None
            except Exception as exc:
                print(f"  [schematic_overview] kicad-cli failed: {exc}, "
                      f"falling back to custom", file=sys.stderr)

        # Fallback: custom renderer
        try:
            from figures.renderers import render_schematic
            paths = render_schematic(sch_path, output_dir, pin_nets=pin_nets)
            return paths[0] if paths else None
        except Exception as exc:
            print(f"  [schematic_overview] custom render failed: {exc}",
                  file=sys.stderr)
            return None

"""Schematic crop figure generator.

Renders subsystem crops of schematics, focused on specific components
with optional net highlighting.  Multi-output: one SVG per section
that requests a crop.

Input schema (per crop, e.g. crop_power_design.json)::

    {
      "sch_path": "/path/to/design.kicad_sch",
      "section_id": "power_design",
      "focus_refs": ["U1", "U2", "R1"],
      "highlight_nets": ["VCC", "GND"],
      "pin_nets": {"U1": {"1": "VCC"}, ...}
    }
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from figures.registry import register
from figures.lib.theme import FigureTheme
from figures.lib.analysis_helpers import build_pin_nets


@register(name="schematic_crops", output="crops/",
          multi_output=True)
class SchematicCropGenerator:
    """Subsystem crop renders from schematics."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> list[tuple[str, dict]] | None:
        sch_path = analysis.get('_sch_path')
        if not sch_path or not os.path.isfile(sch_path):
            return None

        sections = analysis.get('_spec_sections', [])
        if not sections:
            return None

        pin_nets = build_pin_nets(analysis)

        crops = []
        for section in sections:
            focus_refs = section.get('focus_refs', [])
            if not focus_refs:
                continue
            section_id = section.get('id', 'crop')
            crops.append((f"crop_{section_id}", {
                'sch_path': sch_path,
                'section_id': section_id,
                'focus_refs': focus_refs,
                'highlight_nets': section.get('highlight_nets', []),
                'pin_nets': pin_nets,
            }))

        return crops if crops else None

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        sch_path = data.get('sch_path')
        if not sch_path or not os.path.isfile(sch_path):
            return None

        focus_refs = data.get('focus_refs', [])
        if not focus_refs:
            return None

        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)

        highlight_nets = data.get('highlight_nets') or None
        pin_nets = data.get('pin_nets')

        try:
            from figures.renderers import render_schematic
            paths = render_schematic(
                sch_path, output_dir,
                crop_refs=focus_refs,
                focus_refs=focus_refs,
                highlight_nets=highlight_nets,
                pin_nets=pin_nets,
            )
            if not paths:
                return None
            # Rename to match expected output path
            generated = paths[0]
            if generated != output_path:
                try:
                    os.replace(generated, output_path)
                    return output_path
                except OSError:
                    return generated
            return generated
        except Exception as exc:
            print(f"  [schematic_crop/{data.get('section_id')}] "
                  f"render failed: {exc}", file=sys.stderr)
            return None

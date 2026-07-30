"""Schematic and PCB renderers as composable library APIs.

High-level (file-to-file)::

    from figures.renderers import render_schematic, render_pcb

    paths = render_schematic(sch_path, output_dir, crop_refs=["U1"])
    path = render_pcb(pcb_path, output_dir, preset_name="assembly-front")

Mid-level (file-to-SvgBuilder, for composition)::

    from figures.renderers.schematic import render_schematic_to_svg
    svg = render_schematic_to_svg(sch_path, crop_refs=["U1"])
    # ... add overlays ...
    svg.write("annotated.svg")
"""

from .schematic import render_schematic
from .pcb import render_pcb

__all__ = ['render_schematic', 'render_pcb']

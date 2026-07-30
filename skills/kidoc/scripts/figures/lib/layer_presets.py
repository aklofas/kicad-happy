"""PCB layer visibility presets for kidoc rendering.

Defines named presets that control which PCB layers are visible and how
they are styled (color, opacity, stroke width).  Used by ``pcb_render.py``
to produce themed SVG output (assembly views, routing views, etc.).

Zero external dependencies -- constants and simple NamedTuples only.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Tuple


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class LayerStyle(NamedTuple):
    """Visual style for a single PCB layer."""
    color: str          # hex RRGGBB
    opacity: float      # 0.0--1.0
    stroke_width: float # mm (0 = use element default)


class LayerPreset(NamedTuple):
    """Named set of layer visibility and styling rules."""
    name: str
    description: str
    layers: Dict[str, LayerStyle]
    show_pads: bool
    show_vias: bool
    show_zones: bool
    background: str     # background fill color


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS: Dict[str, LayerPreset] = {

    "assembly-front": LayerPreset(
        name="assembly-front",
        description="Front assembly drawing -- silk, fab, courtyard",
        layers={
            "Edge.Cuts":    LayerStyle("#000000", 1.0,  0.15),
            "F.SilkS":     LayerStyle("#333333", 1.0,  0),
            "F.Silkscreen": LayerStyle("#333333", 1.0, 0),
            "F.Fab":        LayerStyle("#999999", 0.6,  0),
            "F.CrtYd":     LayerStyle("#cccccc", 0.3,  0),
            "F.Courtyard":  LayerStyle("#cccccc", 0.3,  0),
        },
        show_pads=True,
        show_vias=False,
        show_zones=False,
        background="#ffffff",
    ),

    "assembly-back": LayerPreset(
        name="assembly-back",
        description="Back assembly drawing -- silk, fab, courtyard (mirrored)",
        layers={
            "Edge.Cuts":    LayerStyle("#000000", 1.0,  0.15),
            "B.SilkS":     LayerStyle("#333333", 1.0,  0),
            "B.Silkscreen": LayerStyle("#333333", 1.0, 0),
            "B.Fab":        LayerStyle("#999999", 0.6,  0),
            "B.CrtYd":     LayerStyle("#cccccc", 0.3,  0),
            "B.Courtyard":  LayerStyle("#cccccc", 0.3,  0),
        },
        show_pads=True,
        show_vias=False,
        show_zones=False,
        background="#ffffff",
    ),

    "routing-front": LayerPreset(
        name="routing-front",
        description="Front copper routing with silk overlay",
        layers={
            "Edge.Cuts":    LayerStyle("#000000", 1.0,  0.15),
            "F.Cu":         LayerStyle("#cc3333", 1.0,  0),
            "F.SilkS":     LayerStyle("#333333", 0.25, 0),
            "F.Silkscreen": LayerStyle("#333333", 0.25, 0),
        },
        show_pads=True,
        show_vias=True,
        show_zones=True,
        background="#ffffff",
    ),

    "routing-back": LayerPreset(
        name="routing-back",
        description="Back copper routing with silk overlay (mirrored)",
        layers={
            "Edge.Cuts":    LayerStyle("#000000", 1.0,  0.15),
            "B.Cu":         LayerStyle("#3333cc", 1.0,  0),
            "B.SilkS":     LayerStyle("#333333", 0.25, 0),
            "B.Silkscreen": LayerStyle("#333333", 0.25, 0),
        },
        show_pads=True,
        show_vias=True,
        show_zones=True,
        background="#ffffff",
    ),

    "routing-all": LayerPreset(
        name="routing-all",
        description="All copper layers with silk overlay",
        layers={
            "Edge.Cuts":    LayerStyle("#000000", 1.0,  0.15),
            "F.Cu":         LayerStyle("#cc3333", 0.8,  0),
            "B.Cu":         LayerStyle("#3333cc", 0.8,  0),
            "In1.Cu":       LayerStyle("#cc9933", 0.6,  0),
            "In2.Cu":       LayerStyle("#33cc33", 0.6,  0),
            "F.SilkS":     LayerStyle("#333333", 0.15, 0),
            "F.Silkscreen": LayerStyle("#333333", 0.15, 0),
        },
        show_pads=True,
        show_vias=True,
        show_zones=True,
        background="#ffffff",
    ),

    "power": LayerPreset(
        name="power",
        description="Power net highlighting -- dimmed copper and silk",
        layers={
            "Edge.Cuts":    LayerStyle("#000000", 1.0,  0.15),
            "F.Cu":         LayerStyle("#cc3333", 0.2,  0),
            "B.Cu":         LayerStyle("#3333cc", 0.2,  0),
            "F.SilkS":     LayerStyle("#333333", 0.1,  0),
            "F.Silkscreen": LayerStyle("#333333", 0.1, 0),
        },
        show_pads=True,
        show_vias=True,
        show_zones=True,
        background="#ffffff",
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_preset(name: str) -> LayerPreset:
    """Return a preset by name.  Raises ``KeyError`` if not found."""
    return PRESETS[name]


def layer_visible(preset: LayerPreset, layer: str) -> bool:
    """Return True if *layer* is visible in *preset*."""
    return layer in preset.layers


def layer_style(preset: LayerPreset, layer: str) -> Optional[LayerStyle]:
    """Return the ``LayerStyle`` for *layer*, or ``None`` if not visible."""
    return preset.layers.get(layer)


def custom_preset(
    layers: Dict[str, LayerStyle],
    *,
    name: str = "custom",
    description: str = "Custom layer preset",
    show_pads: bool = True,
    show_vias: bool = True,
    show_zones: bool = True,
    background: str = "#ffffff",
) -> LayerPreset:
    """Build an ad-hoc ``LayerPreset`` from a layer style dict."""
    return LayerPreset(
        name=name,
        description=description,
        layers=layers,
        show_pads=show_pads,
        show_vias=show_vias,
        show_zones=show_zones,
        background=background,
    )

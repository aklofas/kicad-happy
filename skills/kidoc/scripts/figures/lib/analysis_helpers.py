"""Shared analysis data extraction helpers.

Utility functions for extracting common data structures from
schematic analysis JSON.  Used by multiple figure generators to
avoid duplicating extraction logic.
"""

from __future__ import annotations


def build_pin_nets(analysis: dict) -> dict[str, dict[str, str]]:
    """Build component pin-to-net mapping from analysis nets.

    Returns ``{component_ref: {pin_number: net_name}}`` for all named
    nets in the analysis.  Skips unnamed nets (``__unnamed_*``).
    """
    pin_nets: dict[str, dict[str, str]] = {}
    for net_name, net_info in analysis.get('nets', {}).items():
        if net_name.startswith('__unnamed_'):
            continue
        if isinstance(net_info, dict):
            for p in net_info.get('pins', []):
                comp = p.get('component', '')
                pin = p.get('pin_number', '')
                if comp and pin:
                    pin_nets.setdefault(comp, {})[pin] = net_name
    return pin_nets

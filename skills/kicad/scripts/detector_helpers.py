"""Shared helper functions for signal and domain detectors.

Extracted from repeated patterns across signal_detectors.py and
domain_detectors.py to eliminate boilerplate and reduce copy-paste risk.
"""

from __future__ import annotations

from kicad_core.classify import classify_ic_function
from kicad_core.netnames import net_leaf
from kicad_types import AnalysisContext


def index_two_pin_components(
    ctx: AnalysisContext,
    components: list[dict],
) -> tuple[dict[str, tuple[str, str]], dict[str, list[str]]]:
    """Index 2-pin components by their connected nets.

    Returns:
        comp_nets: ``{ref: (net1, net2)}`` for each valid component
        net_to_comps: ``{net_name: [ref, ...]}`` reverse index

    Skips components with missing nets, single-net connections, or
    same net on both pins (shorted).
    """
    comp_nets: dict[str, tuple[str, str]] = {}
    net_to_comps: dict[str, list[str]] = {}
    for comp in components:
        ref = comp["reference"]
        n1, n2 = ctx.get_two_pin_nets(ref)
        if not n1 or not n2 or n1 == n2:
            continue
        comp_nets[ref] = (n1, n2)
        net_to_comps.setdefault(n1, []).append(ref)
        net_to_comps.setdefault(n2, []).append(ref)
    return comp_nets, net_to_comps


def get_components_by_type(
    ctx: AnalysisContext,
    comp_type: str | tuple[str, ...],
    with_parsed_values: bool = False,
) -> list[dict]:
    """Filter ctx.components by type, optionally requiring a parsed value.

    Args:
        comp_type: Single type string or tuple of types.
        with_parsed_values: If True, only include components whose reference
            appears in ``ctx.parsed_values``.
    """
    if isinstance(comp_type, str):
        comp_type = (comp_type,)
    result = [c for c in ctx.components if c["type"] in comp_type]
    if with_parsed_values:
        result = [c for c in result if c["reference"] in ctx.parsed_values]
    return result


def get_unique_ics(ctx) -> list:
    """Return deduplicated list of IC components.

    Components with duplicate references are collapsed (keeps first seen).
    """
    return list({c["reference"]: c for c in ctx.components if c["type"] == "ic"}.values())


def match_ic_keywords(component: dict, keywords: list[str] | tuple[str, ...]) -> bool:
    """Check if an IC's value+lib_id contains any of the given keywords.

    Performs case-insensitive matching against the concatenation of the
    component's ``value`` and ``lib_id`` fields.  Only matches components
    with ``type == 'ic'``.
    """
    if component.get("type") != "ic":
        return False
    val_lib = (component.get("value", "") + " " + component.get("lib_id", "")).lower()
    return any(k in val_lib for k in keywords)


# TVS/ESD part-name fragments: the protection-device and USB VBUS keyword sets, plus
# SRV05, SM712 and CDSOT families and the USBUF/NUF2 USB filters with ESD clamps.
_PROTECTION_KEYWORDS = ("tvs", "esd", "pesd", "prtr", "usblc", "sp0", "tpd", "ip4", "rclamp",
                        "smaj", "smbj", "p6ke", "1.5ke", "lesd", "nup", "srv05", "sm712", "cdsot",
                        "usbuf", "nuf2")
_DRIVER_PIN_TYPES = ("output", "tri_state", "power_out")


def is_protection_part(comp: dict, ctx: AnalysisContext, pair_suffixes) -> bool:
    """True when *comp* is a clamp (TVS/ESD diode or array, varistor), not a protected device.

    An IC without a protection name still counts when it only reaches ground, supplies and
    differential-pair lines (upper-case net suffixes in *pair_suffixes*) and drives none of
    them: an unnamed ESD array.
    """
    ctype = comp.get("type")
    if ctype in ("varistor", "surge_arrester"):
        return True
    if ctype not in ("diode", "ic", "other"):
        return False
    text = " ".join((comp.get("value") or "", comp.get("lib_id") or "", comp.get("mpn") or "")).lower()
    if any(k in text for k in _PROTECTION_KEYWORDS):
        return True
    if ctype != "ic":
        return False
    if classify_ic_function(comp.get("lib_id", ""), comp.get("value", ""),
                            comp.get("description", "")) == "protection":
        return True
    ref = comp.get("reference")
    if any(p.get("type") in _DRIVER_PIN_TYPES
           for c in ctx.components if c.get("reference") == ref for p in c.get("pins") or []):
        return False
    nets = {net for net, _ in ctx.ref_pins.get(ref, {}).values() if net}
    if not any(ctx.is_ground(n) for n in nets):
        return False
    signals = [net_leaf(n).upper() for n in sorted(nets)
               if not ctx.is_ground(n) and not ctx.is_power_net(n)]
    return len(signals) >= 2 and all(s.endswith(tuple(pair_suffixes)) for s in signals)

"""Shared helper functions for signal and domain detectors.

Extracted from repeated patterns across signal_detectors.py and
domain_detectors.py to eliminate boilerplate and reduce copy-paste risk.
"""

from __future__ import annotations

from collections.abc import Iterable

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


def match_family(comp: dict, families: dict[str, Iterable[str]]) -> str | None:
    """Return the family of a part's longest keyword, or None.

    Reads the first of ``mpn``, ``value``, ``lib_id`` that contains any keyword
    (case-insensitive substring). A tie in length between two families is None.
    ``families`` holds one detector's own tables; never pool families across
    detectors, since a part can belong to one family in each.
    """
    for field in ("mpn", "value", "lib_id"):
        text = (comp.get(field) or "").lower()
        if not text:
            continue
        best: dict[str, int] = {}
        for fam, keywords in families.items():
            n = max((len(k) for k in keywords if k in text), default=0)
            if n:
                best[fam] = n
        if best:
            top = max(best.values())
            winners = [f for f, n in best.items() if n == top]
            return winners[0] if len(winners) == 1 else None
    return None


# TVS/ESD part-name fragments: the protection-device and USB VBUS keyword sets, plus
# families without either word in their names (SRV05, SM712, CDSOT, USBUF/USBULC,
# NUF2/STF202 USB filters, AOZ89xx, H5VU, CM121x/CM123x, BSD5C, SP300x/SP301x,
# Wurth 82400xxx, CDDFN, ECMF).  Not "sp30": SP30xx also names RS-485 transceivers.
_PROTECTION_KEYWORDS = ("tvs", "esd", "pesd", "prtr", "usblc", "sp0", "tpd", "ip4", "rclamp",
                        "smaj", "smbj", "p6ke", "1.5ke", "lesd", "nup", "srv05", "sm712", "cdsot",
                        "usbuf", "usbulc", "nuf2", "stf202", "aoz89", "h5vu", "cm121", "cm123",
                        "bsd5c", "sp300", "sp301", "82400", "cddfn", "ecmf")
_DRIVER_PIN_TYPES = ("output", "tri_state", "power_out")


def _only_this_part_drives(ctx: AnalysisContext, ref: str, net: str) -> bool:
    """True when every other part on *net* has passive pins and *ref* has no input there.

    Such a net is a clamp's own supply/reference node (an ESD array's VP pin left open or
    decoupled), not a line the part protects.
    """
    pins = [p for p in ctx.nets.get(net, {}).get("pins", []) if not p["component"].startswith("#")]
    return (all(p.get("pin_type") == "passive" for p in pins if p["component"] != ref)
            and not any(p.get("pin_type") == "input" for p in pins if p["component"] == ref))


def is_protection_part(comp: dict, ctx: AnalysisContext, pair_suffixes) -> bool:
    """True when *comp* is a clamp (TVS/ESD diode or array, varistor), not a protected device.

    SPICE source symbols and unfitted parts (DNP or off the board) never count.  An IC without a
    protection name still counts when it only reaches ground, supplies, at most one node of
    its own (open or decoupled) and differential-pair lines (upper-case net suffixes in
    *pair_suffixes*) and drives none of them: an unnamed ESD array.
    """
    if (comp.get("dnp") or comp.get("on_board") is False
            or (comp.get("lib_id") or "").startswith("Simulation_SPICE:")):
        return False
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
    # A part that drives a pin is a transceiver or buffer even when its description
    # mentions its own ESD rating ("CAN transceiver with ESD protection").
    ref = comp.get("reference")
    if any(p.get("type") in _DRIVER_PIN_TYPES
           for c in ctx.components if c.get("reference") == ref for p in c.get("pins") or []):
        return False
    if classify_ic_function(comp.get("lib_id", ""), comp.get("value", ""),
                            comp.get("description", "")) == "protection":
        return True
    nets = {net for net, _ in ctx.ref_pins.get(ref, {}).values() if net}
    if not any(ctx.is_ground(n) for n in nets):
        return False
    suffixes = tuple(pair_suffixes)
    pair_lines = own_nodes = 0
    for n in sorted(nets):
        if ctx.is_ground(n) or ctx.is_power_net(n):
            continue
        if net_leaf(n).upper().endswith(suffixes):
            pair_lines += 1
        elif _only_this_part_drives(ctx, ref, n):
            own_nodes += 1
        else:
            return False
    # One own node is an array's VP/VBUS pin; an MCU or switch leaves several such nets.
    return pair_lines >= 2 and own_nodes <= 1

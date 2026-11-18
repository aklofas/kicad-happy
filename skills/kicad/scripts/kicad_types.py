"""
Typed data structures for KiCad analysis.

Provides AnalysisContext — the shared state object passed between all
analysis functions, replacing repeated comp_lookup/parsed_values/known_power_rails
construction.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from kicad_core.model import PinNetEntry
from kicad_core.netquery import build_pin_to_net_map
from kicad_core.netnames import (
    configured_rail_voltage, is_earth_name, is_ground_name, is_pin_gated_rail_name,
    is_pin_guarded_signal, is_power_net_name, is_vss_name, net_leaf, rail_matches,
)
from kicad_core.diagnostics import record
from kicad_core.values import AmbiguousValueSeparator, ambiguous_separator, parse_value

if TYPE_CHECKING:
    from netlist_queries import NetlistQueries

_AMBIGUOUS_RECORD_CAP = 20
_AMBIGUOUS_EFFECT = "value not parsed; value-based checks skip the part"


def index_components(components: list[dict], diagnostics: list | None = None
                     ) -> tuple[dict[str, dict], dict[str, float]]:
    comp_lookup = {c["reference"]: c for c in components}
    parsed_values: dict[str, float] = {}
    ambiguous: list[str] = []
    for c in components:
        val = parse_value(c.get("value", ""), component_type=c.get("type"))
        if val is not None:
            parsed_values[c["reference"]] = val
        elif (c.get("type") in ("resistor", "capacitor", "inductor")
              and ambiguous_separator(c.get("value", ""))):
            ambiguous.append(f"{c['reference']} value {c.get('value')!r}: separator may be a "
                             f"decimal mark or a thousands separator")
    if diagnostics is not None:
        for message in ambiguous[:_AMBIGUOUS_RECORD_CAP]:
            record(diagnostics, "kicad_types.index_components",
                   AmbiguousValueSeparator(message), _AMBIGUOUS_EFFECT)
        if len(ambiguous) > _AMBIGUOUS_RECORD_CAP:
            record(diagnostics, "kicad_types.index_components",
                   AmbiguousValueSeparator(f"{len(ambiguous) - _AMBIGUOUS_RECORD_CAP} more "
                                           f"ambiguous values not listed"),
                   _AMBIGUOUS_EFFECT)
    return comp_lookup, parsed_values


def scan_power_rails(nets: dict[str, dict]) -> set[str]:
    rails: set[str] = set()
    for net_name, net_info in nets.items():
        for p in net_info.get("pins", []):
            if p["component"].startswith("#PWR") or p["component"].startswith("#FLG"):
                rails.add(net_name)
                break
    return rails


def power_symbol_com_nets(nets: dict[str, dict], comp_lookup: dict[str, dict]) -> set[str]:
    """``COM`` nets a ``power_symbol``-typed part sits on, whatever its reference (an
    imported symbol can keep ``#U$01``)."""
    return {name for name, info in nets.items()
            if net_leaf(name).upper() == "COM"
            and any((comp_lookup.get(p["component"]) or {}).get("type") == "power_symbol"
                    for p in info.get("pins", []))}


_SYMBOL_TYPES = ("power_symbol", "power_flag", "flag")
# An isolated converter's output pins carry a sign (VOUT+, -VOUT, VO-): a part with those and
# a COM pin returns its output to COM.
_CONVERTER_OUTPUT_PIN = re.compile(r'^[+-]V_?OUT$|^V_?OUT[+-]$|^[+-]VO$|^VO[+-]$')
_NEGATIVE_CONVERTER_OUTPUT_PIN = re.compile(r'^-V_?OUT$|^V_?OUT-$|^-VO$|^VO-$')
_POSITIVE_CONVERTER_OUTPUT_PIN = re.compile(r'^\+V_?OUT$|^V_?OUT\+$|^\+VO$|^VO\+$')


def _is_ground_symbol_pin(pin: dict, comp: dict) -> bool:
    """*pin* is the pin of a one-pin power symbol drawn as a ground: the symbol's value and its
    library symbol both read as ground (``power:GND``, ``power:GNDREF``) or are the SPICE ground
    ``0`` (``Simulation_SPICE:0``, ``pspice:0``), and the pin itself carries no other name. An
    earth-class symbol (``power:Earth``, ``Earth_Protective``, ``Chassis``) is not one."""
    if comp.get("type") != "power_symbol" or len(comp.get("pins") or ()) > 1:
        return False
    pin_name = str(pin.get("pin_name") or "")
    names = (str(comp.get("value") or ""), str(comp.get("lib_id") or "").rsplit(":", 1)[-1])
    return ((pin_name in ("", "~", "0") or is_ground_name(pin_name))
            and all(n == "0" or is_ground_name(n) and not is_earth_name(n) for n in names))


def ground_evidence_nets(nets: dict[str, dict], comp_lookup: dict[str, dict],
                         shared_refs: set[str]) -> frozenset[str]:
    """Nets that are ground by what sits on them, whatever they are called.

    A ground power symbol (``GND``, or the SPICE ground ``0``) on a net another label names
    makes that net ground (a global label ``THERMISTOR_B`` drawn on the board ground, or a board
    ground KiCad names ``Earth``), unless the name reads as a supply or nothing but power
    symbols sits on the net. A ``COM`` net is
    ground when a ground label is also on it, an IC ground pin (``GND1``, ``AGND``) sits on
    it, or it is the common pin of an isolated converter (a part with ``VOUT+`` / ``VOUT-``
    pins); a relay, switch, multiplexer or transformer ``COM`` is a common, not a return. A
    reference two parts share (``#PWR?``) does not say which part sits on the net, so it is
    no evidence."""
    found = set()
    for name, info in nets.items():
        pins = info.get("pins", [])
        if (not is_power_net_name(name)
                and any(p["component"] not in shared_refs
                        and _is_ground_symbol_pin(p, comp_lookup.get(p["component"]) or {})
                        for p in pins)
                and (info.get("labels") or any(
                    (comp_lookup.get(p["component"]) or {}).get("type") not in _SYMBOL_TYPES
                    for p in pins))):
            found.add(name)
            continue
        if net_leaf(name).upper() != "COM":
            continue
        if any(is_ground_name(lab.get("name")) for lab in info.get("labels", [])):
            found.add(name)
            continue
        for p in pins:
            comp = {} if p["component"] in shared_refs else comp_lookup.get(p["component"]) or {}
            if comp.get("type") != "ic":
                continue
            pin_name = (p.get("pin_name") or "").upper()
            if is_ground_name(pin_name) or pin_name == "COM" and any(
                    _CONVERTER_OUTPUT_PIN.match(str(q.get("name") or "").upper())
                    for q in comp.get("pins", [])):
                found.add(name)
                break
    return frozenset(found)


def index_ref_pins(pin_net: dict) -> dict[str, dict[str, PinNetEntry]]:
    rp: dict[str, dict[str, PinNetEntry]] = {}
    for (comp_ref, pin_num), val in pin_net.items():
        rp.setdefault(comp_ref, {})[pin_num] = val
    return rp


@dataclass
class AnalysisContext:
    """Shared state passed to all 40+ signal and domain detector functions.

    Construct through ``build_analysis_context()``; a directly constructed context gets
    no derived indexes.  Built after components, nets, and pin_net are fully resolved.  Provides indexed lookups and helper methods so
    detectors don't rebuild these structures individually.

    Attributes:
        components: All placed components (excluding power symbols/flags).
            Each dict has: reference, value, type, lib_id, footprint,
            properties, pins, and optionally mpn, datasheet.
        nets: Net connectivity graph.  ``{net_name: {"pins": [{"component": ref,
            "pin_number": num, "pin_name": name, "x": float, "y": float}], ...}}``.
        lib_symbols: Library symbol definitions extracted from the schematic's
            embedded ``lib_symbols`` section.  ``{lib_id: {value, pins, ...}}``.
        pin_net: Pin-to-net mapping.  ``{(ref, pin_number): (net_name, net_record)}`` — the full net record, not a pin name.
            Covers every pin on every placed component.
        comp_lookup: Quick component lookup by reference.  ``{ref: component_dict}``.
            Built from *components* by ``build_analysis_context``.
        parsed_values: Parsed SI values (ohms, farads, henries) per component.
            ``{ref: float}``.  Only components whose value string parses
            successfully are included.  Built by ``build_analysis_context``.
        known_power_rails: Net names connected to power symbols (``#PWR``, ``#FLG``).
            Used by ``is_power_net()`` to distinguish power rails from signal nets.
        ground_name_rails: The rail set ``is_ground()`` reads (it decides ``COM`` and
            ``0``): ``known_power_rails`` plus every ``COM`` net a ``power_symbol``-typed
            part names, whatever its reference. Built by ``build_analysis_context``.
        ground_evidence: Nets ``is_ground()`` accepts whatever they are called, by the
            ground symbol or ground pins on them (``ground_evidence_nets``). Built by
            ``build_analysis_context`` from the power-symbol scan.
        ref_pins: Per-component pin map.  ``{ref: {pin_number: (net_name, net_record)}}``.
            Derived from *pin_net* for quick per-component pin enumeration.
        no_connects: List of no-connect markers from the schematic.
        nq: ``NetlistQueries`` object for multi-hop net tracing.  Detectors
            require a context built by ``build_analysis_context``, which always
            installs ``nq``.
        diagnostics: Sink for guarded failures (``kicad_core.diagnostics.record``); the
            schematic pipeline merges it into the envelope's ``diagnostics``.
        rail_by_net: Rail voltages keyed by full net name, filled by the schematic
            pipeline; two instances of one sheet keep separate entries.
        rail_overrides: ``analysis.power_rails.voltage_overrides`` from the project
            config, ``{net_name: volts}``.
        rail_ignore: ``analysis.power_rails.ignore`` glob patterns.
        parallel_group_cache: ``detector_helpers.parallel_groups`` results per part type.

    Methods:
        is_power_net(name): True if *name* is a known power rail, matches
            common power net name patterns (VCC, +3V3, VBUS, etc.) or is in
            ``vss_supply_rails``.
        is_ground(name): True if *name* matches ground patterns (GND, VSS, etc.) or the
            net is in ``ground_evidence``, and is not in ``vss_supply_rails``.
        rail_voltage(net): The configured voltage, else the exact net's entry in
            ``rail_by_net``; None for an ignored rail.
        config_rail_voltage(net): The user's override for *net*, or None.
        rail_ignored(net): True if *net* matches an ``ignore`` pattern.
        rail_voltage_or(net, estimate): None for an ignored rail, else the override,
            else ``estimate(net)``.
        rail_source_fields(*nets): The finding key marking a config-sourced voltage.
        get_two_pin_nets(ref): Returns ``(net1, net2)`` for a 2-pin component.
            Handles standard "1"/"2" numbering and falls back to enumerating
            all pins for non-standard numbering (Eagle imports, diodes A/K).
    """

    components: list[dict]
    nets: dict[str, dict]
    lib_symbols: dict
    pin_net: dict[tuple[str, str], PinNetEntry]
    comp_lookup: dict[str, dict] = field(default_factory=dict)
    parsed_values: dict[str, float] = field(default_factory=dict)
    known_power_rails: set[str] = field(default_factory=set)
    ground_name_rails: frozenset = field(default_factory=frozenset, repr=False)
    ground_evidence: frozenset = field(default_factory=frozenset, repr=False)
    ref_pins: dict[str, dict[str, PinNetEntry]] = field(default_factory=dict)
    no_connects: list[dict] = field(default_factory=list)
    source: str = "unknown"
    nq: 'NetlistQueries | None' = field(default=None, repr=False)
    cache_dir: Path | None = field(default=None, repr=False)
    project_dir: str | None = field(default=None, repr=False)
    diagnostics: list = field(default_factory=list, repr=False)
    pin_guarded_signals: frozenset = field(default_factory=frozenset, repr=False)
    topology_rails: frozenset = field(default_factory=frozenset, repr=False)
    pin_gated_rails: frozenset = field(default_factory=frozenset, repr=False)
    vss_supply_rails: frozenset = field(default_factory=frozenset, repr=False)
    rail_by_net: dict[str, float] = field(default_factory=dict, repr=False)
    rail_overrides: dict[str, float] = field(default_factory=dict, repr=False)
    rail_ignore: tuple[str, ...] = field(default=(), repr=False)
    parallel_group_cache: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def is_power_net(self, name: str | None, *, by_pins: bool = True) -> bool:
        """*by_pins* False leaves out the rails known only by their pins (``topology_rails``,
        ``pin_gated_rails``). A VSS net a regulator drives (``vss_supply_rails``) is a rail
        whatever its name."""
        return name not in self.pin_guarded_signals and (
            is_power_net_name(name, self.known_power_rails) or name in self.vss_supply_rails
            or (by_pins and (name in self.topology_rails or name in self.pin_gated_rails)))

    def is_ground(self, name: str | None) -> bool:
        """Ground by name or by what sits on the net (``ground_evidence``); a VSS net a
        regulator drives (``vss_supply_rails``) is a supply, not ground."""
        return name not in self.vss_supply_rails and (
            name in self.ground_evidence or is_ground_name(name, self.ground_name_rails))

    def rail_voltage(self, net: str | None) -> float | None:
        """Voltage of the exact net *net* (full hierarchical name) from the rail map.

        The user's override comes first and an ignored rail has none. The map is built
        by the schematic pipeline (``build_rail_map``); a context it has not run on
        knows only the overrides.
        """
        return self.rail_voltage_or(net, self.rail_by_net.get)

    def config_rail_voltage(self, net: str | None) -> float | None:
        """The configured voltage for *net* (``configured_rail_voltage``), or None."""
        return configured_rail_voltage(self.rail_overrides, net)

    def rail_ignored(self, net: str | None) -> bool:
        return rail_matches(self.rail_ignore, net)

    def rail_source_fields(self, *nets: str | None) -> dict:
        """``{"rail_voltage_source": "config"}`` for a finding whose rail voltage came
        from a config override on one of *nets*, else ``{}``."""
        if any(not self.rail_ignored(n) and self.config_rail_voltage(n) is not None
               for n in nets):
            return {"rail_voltage_source": "config"}
        return {}

    def rail_voltage_or(self, net: str | None, estimate) -> float | None:
        """None for an ignored rail, else the configured voltage, else ``estimate(net)``."""
        if not net:
            return None
        if self.rail_ignored(net):
            return None
        v = self.config_rail_voltage(net)
        return v if v is not None else estimate(net)

    def get_two_pin_nets(self, ref: str) -> tuple[str | None, str | None]:
        n1, _ = self.pin_net.get((ref, "1"), (None, None))
        n2, _ = self.pin_net.get((ref, "2"), (None, None))
        if n1 is not None and n2 is not None:
            return n1, n2
        # Fallback for non-"1"/"2" pin numbering (Eagle imports, diodes A/K, etc.)
        pins = self.ref_pins.get(ref, {})
        if len(pins) == 2:
            nets = [net for net, _ in pins.values()]
            return nets[0], nets[1]
        return n1, n2


def pin_guarded_signal_nets(nets: dict[str, dict], comp_lookup: dict[str, dict],
                            power_rails: set[str] | None = None) -> frozenset[str]:
    """Nets named VPP/VM that carry an IC signal pin and no power pin (is_pin_guarded_signal)."""
    rails = power_rails or set()
    return frozenset(
        name for name, info in nets.items()
        if name not in rails and is_pin_guarded_signal(name, [
            (p.get("pin_type"), (comp_lookup.get(p.get("component")) or {}).get("type") == "ic")
            for p in info.get("pins", [])]))


def pin_gated_rail_nets(nets: dict[str, dict], comp_lookup: dict[str, dict]) -> frozenset[str]:
    """Nets whose name is a rail only beside a supply pin (``is_pin_gated_rail_name``) and
    that carry a power_in or power_out pin of a part other than a power symbol or flag."""
    return frozenset(
        name for name, info in nets.items()
        if is_pin_gated_rail_name(name) and any(
            str(p.get("pin_type") or "").split("+")[0] in ("power_in", "power_out")
            and not str(p.get("component") or "").startswith("#")
            and (comp_lookup.get(p.get("component")) or {}).get("type")
            not in ("power_symbol", "power_flag", "flag")
            for p in info.get("pins", [])))


def vss_supply_rail_nets(ctx: AnalysisContext) -> frozenset[str]:
    """Ground-named VSS nets that are a supply, not ground: a regulator output drives them or
    the project config gives them a negative voltage.

    A power output pin not itself named ground or VSS sits on the net, and its part has a
    pin on another, ground-named net (its own reference): a negative LDO's OUT on VSS, a
    charge pump's -VOUT beside its GND. A converter with both +Vout and -Vout counts only
    beside its common pin (``COM``, ``0V``) on ground: without one, -Vout is the output's own
    return, and a pin such as ``GND`` or ``-Vin`` is its input return. A ground symbol other
    than VSS (``power:GND``) on the net joins it to the board ground, so it stays ground
    whatever drives it."""
    shared_refs = {ref for ref, n in Counter(c["reference"] for c in ctx.components).items()
                   if n > 1}
    found = set()
    for name, info in ctx.nets.items():
        if not (is_vss_name(name) and is_ground_name(name, ctx.ground_name_rails)):
            continue
        override = ctx.config_rail_voltage(name)
        if override is not None and override < 0 and not ctx.rail_ignored(name):
            found.add(name)
            continue
        symbols = ((p, ctx.comp_lookup.get(p["component"]) or {}) for p in info.get("pins", [])
                   if p["component"] not in shared_refs)
        if any(_is_ground_symbol_pin(p, comp) and not is_vss_name(str(comp.get("value") or ""))
               for p, comp in symbols):
            continue
        for p in info.get("pins", []):
            pin_name = p.get("pin_name") or ""
            if (str(p.get("pin_type") or "").split("+")[0] != "power_out"
                    or is_ground_name(pin_name) or is_vss_name(pin_name)):
                continue
            ref = p.get("component")
            part_pins = [(q.get("pin_name") or "", n)
                         for n in {n for n, _ in ctx.ref_pins.get(ref, {}).values()}
                         for q in ctx.nets.get(n, {}).get("pins", []) if q.get("component") == ref]
            if (_NEGATIVE_CONVERTER_OUTPUT_PIN.match(pin_name.upper())
                    and any(_POSITIVE_CONVERTER_OUTPUT_PIN.match(q.upper()) for q, _ in part_pins)):
                part_pins = [(q, n) for q, n in part_pins if q.upper() in ("COM", "COMMON", "0V")]
            if any(n != name and ctx.is_ground(n) and not is_vss_name(n) for _, n in part_pins):
                found.add(name)
                break
    return frozenset(found)


def build_analysis_context(components: list[dict], nets: dict[str, dict], lib_symbols: dict, *,
                           no_connects: list[dict] | None = None,
                           source: str = "unknown",
                           cache_dir: Path | None = None, project_dir: str | None = None,
                           known_power_rails: set[str] | None = None,
                           power_rails_config: dict | None = None) -> AnalysisContext:
    """The single construction point for production contexts.

    Builds ``pin_net`` and every index, installs the ``NetlistQueries`` layer and
    returns a context no detector has to complete. ``known_power_rails`` overrides
    the power-symbol scan and the ground evidence it brings (synthetic fixtures); an
    explicit set (including an empty one) is used as given; ``no_connects`` is kept by reference. ``power_rails_config``
    is the project config's ``analysis.power_rails`` (its ``voltage_overrides`` and
    ``ignore`` reach every detector).
    """
    pin_net = build_pin_to_net_map(nets)
    diagnostics: list = []
    comp_lookup, parsed_values = index_components(components, diagnostics)
    shared_refs = {ref for ref, n in Counter(c["reference"] for c in components).items() if n > 1}
    rails = scan_power_rails(nets) if known_power_rails is None else known_power_rails
    ground_rails = frozenset(rails if known_power_rails is not None
                             else rails | power_symbol_com_nets(nets, comp_lookup))
    ctx = AnalysisContext(
        components=components, nets=nets, lib_symbols=lib_symbols, pin_net=pin_net,
        comp_lookup=comp_lookup, parsed_values=parsed_values, known_power_rails=rails,
        ground_name_rails=ground_rails,
        ground_evidence=(ground_evidence_nets(nets, comp_lookup, shared_refs)
                         if known_power_rails is None else frozenset()),
        ref_pins=index_ref_pins(pin_net),
        no_connects=no_connects if no_connects is not None else [],
        source=source,
        cache_dir=cache_dir, project_dir=project_dir, diagnostics=diagnostics,
        pin_guarded_signals=pin_guarded_signal_nets(nets, comp_lookup, rails),
        pin_gated_rails=pin_gated_rail_nets(nets, comp_lookup),
    )
    if power_rails_config:
        ctx.rail_overrides = {
            k: v for k, v in (power_rails_config.get("voltage_overrides") or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
        ctx.rail_ignore = tuple(
            p for p in (power_rails_config.get("ignore") or ()) if isinstance(p, str))
    ctx.vss_supply_rails = vss_supply_rail_nets(ctx)
    from schematic.net_analysis import topology_rail_nets  # local: net_analysis imports this module
    ctx.topology_rails = topology_rail_nets(
        nets, comp_lookup, ctx.ref_pins, ctx.is_power_net, ctx.is_ground)
    from netlist_queries import NetlistQueries  # local: netlist_queries annotates with this class
    ctx.nq = NetlistQueries(ctx)
    return ctx

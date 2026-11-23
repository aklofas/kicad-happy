"""Shared helper functions for signal and domain detectors.

Extracted from repeated patterns across signal_detectors.py and
domain_detectors.py to eliminate boilerplate and reduce copy-paste risk.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from kicad_core.classify import classify_ic_function
from kicad_core.netnames import net_leaf
from kicad_core.parts import LED_VF_BY_COLOR, LED_VF_DEFAULT, led_color
from kicad_core.values import highest_rated_voltage
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


def get_pin_net(ctx: AnalysisContext, ref: str, pin_names: tuple[str, ...]) -> str | None:
    """Find the net connected to a pin matching any of the given names."""
    pins = ctx.ref_pins.get(ref, {})
    for pnum, (net, _) in pins.items():
        comp = ctx.comp_lookup.get(ref)
        if not comp:
            continue
        for p in comp.get('pins', []):
            if p.get('number') == pnum and p.get('name', '').upper() in pin_names:
                return net
    # Fallback: check net pin_name via ctx.nets
    for pnum, (net, _) in pins.items():
        if not net or net not in ctx.nets:
            continue
        for np in ctx.nets[net]['pins']:
            if np['component'] == ref and np.get('pin_name', '').upper() in pin_names:
                return net
    return None


# SDA / SCL as a word of a net name, with an optional bus number: SDA, SDA2, SCL_2,
# OLED_SDA, SDA_3V3. SDAT, SCLK and ESDA are other signals.
I2C_SDA_WORD = re.compile(r'(?<![A-Z0-9])SDA\d*(?![A-Z0-9])')
I2C_SCL_WORD = re.compile(r'(?<![A-Z0-9])SCL\d*(?![A-Z0-9])')
_I2C_LINE_WORD = re.compile(r'(?<![A-Z0-9])(SDA|SCL)(\d*)(?![A-Z0-9])')
# A serial audio interface names its data line SDA too (SAI2_SDA).
_SAI_WORD = re.compile(r'(?<![A-Z])SAI\d*(?![A-Z])')
_SPI_SELECT_WORD = re.compile(r'^(?:N?CS[NB]?\d*|NSS|SS|SSEL|DC|D~?C~?)$')
_SPI_CLOCK_WORD = re.compile(r'^(?:SCK|SCLK|CLK)$')
_SPI_DATA_IN_WORD = re.compile(r'^(?:MOSI|SDI|DIN|SI|COPI)$')
_I2C_PIN_WORD = re.compile(r'^(?:SDA|SCL)\d*$|^I2C|^TWI|^SMB')
_DISPLAY_NET_WORD = re.compile(r'LCD|TFT|DISP|OLED|SCREEN|EPD|EINK|ST77|ILI9|GC9A|SSD1')


def not_i2c_despite_name(ctx: AnalysisContext, net_name: str) -> bool:
    """A net with SDA / SCL in its name that is another kind of signal. A net with a
    pull-up (a fitted resistor to a supply rail other than ground) is I2C. The words
    are read from the net's own name, never from its sheet path.

    - A 3-wire SPI line: a display's ``LCD_SDA`` / ``LCD_SCL`` next to ``LCD_CS`` or
      ``LCD_DC``. The net's family is every net whose own name (sheet path aside) has
      the same text around the SDA / SCL word. A chip-select or data/command sibling
      makes the family SPI, unless it has its own SPI clock and data-in nets as well
      (then SDA / SCL are a separate I2C bus). Outside display names, an IC pin named
      SDA / SCL keeps the net I2C (a sensor with a strapped CS).
    - A numbered word with no partner line in the design (``SDA12`` on a sound CPU's
      address bus, no SCL net anywhere) and no IC pin named SDA / SCL.
    - A serial audio data line (``SAI2_SDA``).
    """
    leaf = net_leaf(net_name).upper()
    word = None
    for word in _I2C_LINE_WORD.finditer(leaf):
        pass
    if word is None:
        return False
    pins = ctx.nets.get(net_name, {}).get("pins", [])
    for p in pins:
        comp = ctx.comp_lookup.get(p["component"])
        if comp and comp.get("type") == "resistor" and is_fitted(comp):
            far = [n for n in ctx.get_two_pin_nets(p["component"]) if n and n != net_name]
            if far and ((ctx.is_power_net(far[0]) and not ctx.is_ground(far[0]))
                        or rail_behind_bridged_jumper(ctx, far[0])):
                return False
    if _SAI_WORD.search(leaf):
        return True

    def i2c_pin_on_net():
        return any(
            ctx.comp_lookup.get(p["component"], {}).get("type") == "ic" and any(
                _I2C_PIN_WORD.match(w)
                for w in re.split(r"[^A-Z0-9]+", (p.get("pin_name") or "").upper()) if w)
            for p in pins)

    if word.group(2):
        if "I2C" not in leaf:
            partner = I2C_SCL_WORD if word.group(1) == "SDA" else I2C_SDA_WORD
            if not any(partner.search(n.upper()) for n in ctx.nets) and not i2c_pin_on_net():
                return True
        return False  # a numbered bus (MCU_SCL2) is not a display's serial line
    prefix, suffix = leaf[:word.start()], leaf[word.end():]
    if not (prefix or suffix):
        return False  # a bare SDA / SCL has no family
    siblings = []
    for other in ctx.nets:
        o = net_leaf(other).upper()
        if (other != net_name and len(o) > len(prefix) + len(suffix)
                and o.startswith(prefix) and o.endswith(suffix)):
            siblings.append(o[len(prefix):len(o) - len(suffix)])
    if not any(_SPI_SELECT_WORD.match(w) for w in siblings):
        return False
    if (any(_SPI_CLOCK_WORD.match(w) for w in siblings)
            and any(_SPI_DATA_IN_WORD.match(w) for w in siblings)):
        return False
    return bool(_DISPLAY_NET_WORD.search(leaf)) or not i2c_pin_on_net()


# SolderJumper_3_Bridged12, SolderJumper-3_P1.3mm_Bridged2Bar12_..., SolderJumper_2_Bridged
_BRIDGED_PADS = re.compile(r"bridged(?:2bar)?(\d*)")


def bridged_jumper_pads(comp: dict, pin_count: int) -> frozenset[str]:
    """The pad numbers a jumper joins as built: ``SolderJumper_3_Bridged12`` joins pads 1
    and 2, ``..._Bridged123`` all three, a two-pad ``..._Bridged`` both. The footprint
    name is read first (it is the copper), then the symbol name; an ``_Open`` footprint
    joins nothing whatever the symbol says. Empty for an open or unfitted jumper and for
    a three-pad name that does not say which pads."""
    if comp.get("type") != "jumper" or not is_fitted(comp):
        return frozenset()
    footprint = comp.get("footprint") or ""
    if "_open" in footprint.lower():
        return frozenset()
    for name in (footprint, comp.get("lib_id") or ""):
        m = _BRIDGED_PADS.search(name.rsplit(":", 1)[-1].lower())
        if m:
            if m.group(1):
                return frozenset(m.group(1))
            return frozenset(("1", "2")) if pin_count == 2 else frozenset()
    return frozenset()


def rail_behind_bridged_jumper(ctx: AnalysisContext, net: str | None) -> tuple[str, str] | None:
    """``(rail, jumper ref)`` when *net* reaches a supply rail other than ground through
    pads a jumper joins as built (a pull-up's far side on a cuttable I2C pull-up jumper);
    else None. One hop only, and a pad the jumper leaves open is not followed, so a VCC /
    GND select jumper bridged to VCC reaches VCC only."""
    if not net:
        return None
    for p in ctx.nets.get(net, {}).get("pins", []):
        ref = p["component"]
        comp = ctx.comp_lookup.get(ref)
        if not comp or comp.get("type") != "jumper":
            continue
        pins = ctx.ref_pins.get(ref) or {}
        pads = bridged_jumper_pads(comp, len(pins))
        if p["pin_number"] not in pads:
            continue
        for pad in sorted(pads):
            other = (pins.get(pad) or (None, None))[0]
            if other and other != net and ctx.is_power_net(other) and not ctx.is_ground(other):
                return other, ref
    return None


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

    Components with duplicate references are collapsed: the list keeps the
    position of a reference's first occurrence and the record of its last.
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


def symbol_name(lib_id: str) -> str:
    """The symbol part of a lib_id, without its library nickname or a rescue library's suffix.

    KiCad's rescue renames a symbol after where it came from: ``<name>-RESCUE-<project>`` (KiCad 4/5),
    or ``<name>-<library>`` in a ``<project>-rescue`` library. A symbol rescued twice also carries the
    earlier rescue library, named after the project (``<name>-<library>-<project>-rescue``); the
    project name can hold dashes, so only the text before the first dash is kept. The nickname
    ends at the first ``:``, as in KiCad. The original case is kept; callers lowercase.
    """
    sym = (lib_id or "").split(":", 1)[-1]
    if "-RESCUE-" in sym:
        return sym.split("-RESCUE-", 1)[0]
    if sym.lower().endswith("-rescue"):
        return sym.split("-", 1)[0]
    return sym


def match_family(comp: dict, families: dict[str, Iterable[str]]) -> str | None:
    """Return the family of a part's longest keyword, or None.

    Reads the first of ``mpn``, ``value``, ``lib_id`` that contains any keyword
    (case-insensitive substring); of ``lib_id`` only the symbol name counts (see
    ``symbol_name``), since the library nickname and a rescue suffix name a library or
    project, not the part. A tie in length between two
    families is None.
    ``families`` holds one detector's own tables; never pool families across
    detectors, since a part can belong to one family in each.
    """
    for field in ("mpn", "value", "lib_id"):
        text = comp.get(field) or ""
        if field == "lib_id":
            text = symbol_name(text)
        text = text.lower()
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


def is_fitted(comp: dict) -> bool:
    """False for a part marked DNP or excluded from the board."""
    return not (comp.get("dnp") or comp.get("on_board") is False)


# IEC 60384-14 safety class: Y1 / Y2 (or X1Y2) capacitors bridge an isolation barrier.
_SAFETY_CLASS_RE = re.compile(r"(?<![A-Za-z0-9])(?:X1)?Y[12](?![A-Za-z0-9])", re.IGNORECASE)


def is_safety_rated_cap(comp: dict) -> bool:
    """A Y-class or isolation-barrier capacitor: its value names a rating of 1 kV or more or a
    Y1/Y2 safety class."""
    value = comp.get("value") or ""
    rating = highest_rated_voltage(value)
    return (rating is not None and rating >= 1000) or bool(_SAFETY_CLASS_RE.search(value))


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


_PARALLEL_VALUE_NOUN = {"resistor": "resistors", "inductor": "inductors", "capacitor": "caps"}


def parallel_groups(ctx: AnalysisContext, comp_type: str) -> dict[str, dict]:
    """``{member_ref: group}`` for two-terminal parts of ``comp_type`` (resistor, inductor
    or capacitor) that share both nets; every such part has a group, alone or not.

    A group is ``{"refs": [sorted refs], "nets": (n1, n2), "value": float | None}``;
    ``refs[0]`` represents it.  Resistors and inductors combine as 1/sum(1/x), capacitors
    as sum(x); a lone member keeps its parsed value.  A member whose value did not parse
    makes the value None.  A DNP part beside a fitted one maps to a one-ref group marked
    ``"excluded"``.  Potentiometers and networks (not two pins) and parts sharing a
    reference with another part have no group.
    """
    cache = ctx.parallel_group_cache
    if comp_type in cache:
        return cache[comp_type]
    of_type = [c for c in ctx.components if c.get("type") == comp_type]
    ref_count: dict[str, int] = {}
    for comp in of_type:
        ref_count[comp["reference"]] = ref_count.get(comp["reference"], 0) + 1
    by_nets: dict[frozenset, dict[str, bool]] = {}
    nets_of: dict[frozenset, tuple[str, str]] = {}
    for comp in of_type:
        ref = comp["reference"]
        if ref_count[ref] != 1 or len(ctx.ref_pins.get(ref, {})) != 2:
            continue
        n1, n2 = ctx.get_two_pin_nets(ref)
        if not n1 or not n2 or n1 == n2:
            continue
        key = frozenset((n1, n2))
        by_nets.setdefault(key, {})[ref] = not comp.get("dnp")
        nets_of.setdefault(key, (n1, n2))
    groups: dict[str, dict] = {}
    for key, members in by_nets.items():
        fitted = sorted(r for r, fit in members.items() if fit)
        refs = fitted or sorted(members)
        if fitted:
            for r in sorted(set(members) - set(fitted)):
                groups[r] = {"refs": [r], "nets": nets_of[key], "value": None, "excluded": True}
        vals = [ctx.parsed_values.get(r) for r in refs]
        if any(v is None for v in vals):
            value = None
        elif len(vals) == 1:
            value = vals[0]
        elif comp_type == "capacitor":
            value = sum(vals)
        elif any(v <= 0 for v in vals):
            value = 0.0
        else:
            value = 1.0 / sum(1.0 / v for v in vals)
        group = {"refs": refs, "nets": nets_of[key], "value": value}
        for r in refs:
            groups[r] = group
    cache[comp_type] = groups
    return groups


def _group_of(ctx: AnalysisContext, ref: str) -> dict | None:
    comp = ctx.comp_lookup.get(ref)
    if not comp or comp.get("type") not in _PARALLEL_VALUE_NOUN:
        return None
    return parallel_groups(ctx, comp["type"]).get(ref)


def group_reps(ctx: AnalysisContext, components: list[dict]) -> list[dict]:
    """``components`` with each parallel group reduced to its representative (first ref);
    groups whose value is unknown and DNP parts beside fitted ones are dropped."""
    out = []
    seen: set[str] = set()
    for c in components:
        g = _group_of(ctx, c["reference"])
        if g is None:
            out.append(c)
            continue
        rep = g["refs"][0]
        if g.get("excluded") or g["value"] is None or rep in seen:
            continue
        seen.add(rep)
        out.append(ctx.comp_lookup[rep])
    return out


def group_value(ctx: AnalysisContext, ref: str) -> float | None:
    """The equivalent value of ``ref``'s parallel group, else its own parsed value."""
    g = _group_of(ctx, ref)
    return ctx.parsed_values.get(ref) if g is None else g["value"]


def group_members(ctx: AnalysisContext, ref: str) -> list[str]:
    """Every fitted member of ``ref``'s parallel group, sorted; ``[ref]`` when alone."""
    g = _group_of(ctx, ref)
    return list(g["refs"]) if g else [ref]


def group_part(ctx: AnalysisContext, ref: str, unit_key: str) -> dict:
    """The part dict a detector records for ``ref``'s parallel group:
    ``{"ref", "value", unit_key, "parallel_refs"?}`` (``parallel_refs`` only for more
    than one member; capacitor groups also keep ``parallel_caps``)."""
    g = _group_of(ctx, ref)
    if not g or len(g["refs"]) == 1:
        return {"ref": ref, "value": ctx.comp_lookup[ref]["value"], unit_key: group_value(ctx, ref)}
    comp_type = ctx.comp_lookup[ref]["type"]
    part = {"ref": g["refs"][0], "value": f"{len(g['refs'])} {_PARALLEL_VALUE_NOUN[comp_type]} parallel",
            unit_key: g["value"], "parallel_refs": list(g["refs"])}
    if comp_type == "capacitor":
        part["parallel_caps"] = list(g["refs"])
    return part


_SUPPLY_PIN_TYPES = ("power_in", "power_out")


def _is_led_node(ctx: AnalysisContext, pins: list[dict]) -> bool:
    """True when every part on a net other than resistors is an LED and no pin takes or
    gives power: the node LEDs share with their resistor, whatever its name."""
    types = [ctx.comp_lookup.get(p["component"], {}).get("type") for p in pins]
    return ("led" in types and all(t in ("led", "resistor") for t in types)
            and not any(p.get("pin_type") in _SUPPLY_PIN_TYPES for p in pins))


def is_led_rail(ctx: AnalysisContext, net: str) -> bool:
    """True when *net* is a supply rail as an LED sees it: a net with a power symbol, or a
    power-like name with more than three pins that is not an LED node (``+5V_LED`` shared
    by parallel LEDs and their resistor, ``VBUS_LED_A``)."""
    if net in ctx.known_power_rails:
        return True
    pins = ctx.nets.get(net, {}).get("pins", [])
    return ctx.is_power_net(net) and len(pins) > 3 and not _is_led_node(ctx, pins)


def led_string(ctx: AnalysisContext, ref: str) -> tuple[list[str], str | None, str | None]:
    """The series string *ref* belongs to: its LEDs in order, and the string's end nets on
    the side of pin 1 and of pin 2.  Two LEDs are in series when a net holds exactly their
    two pins.  A lone LED is a string of one ending on its own nets."""
    n1, n2 = ctx.get_two_pin_nets(ref)
    seen = {ref}

    def walk(net):
        chain = []
        while net and not ctx.is_ground(net) and not is_led_rail(ctx, net):
            pins = ctx.nets.get(net, {}).get("pins", [])
            others = [p["component"] for p in pins if p["component"] not in seen]
            if len(pins) != 2 or len(others) != 1:
                break
            nxt = others[0]
            if (ctx.comp_lookup.get(nxt, {}).get("type") != "led"
                    or len(ctx.ref_pins.get(nxt, {})) != 2):
                break
            seen.add(nxt)
            chain.append(nxt)
            a, b = ctx.get_two_pin_nets(nxt)
            net = b if a == net else a
        return chain, net

    up, end1 = walk(n1)
    down, end2 = walk(n2)
    return list(reversed(up)) + [ref] + down, end1, end2


def led_forward_voltage(comp: dict) -> float:
    """Nominal forward voltage for the LED's colour word, else LED_VF_DEFAULT."""
    color = led_color(comp)
    return LED_VF_BY_COLOR[color][0] if color else LED_VF_DEFAULT


_ADDRESSABLE_LED_WORDS = ("ws2812", "ws2813", "ws2815", "sk6812", "sk6805", "sk6803",
                          "apa102", "apa104", "sk9822", "ws2811", "neopixel", "dotstar")


def is_addressable_led(comp: dict) -> bool:
    """An LED with its own driver (WS2812, SK6812, APA102, ...): one of the family words
    appears anywhere in its value or its whole lib_id, library nickname included. Such an
    LED sets its own current from its supply pins, so it has no series resistor."""
    val = (comp.get("value") or "").lower()
    lib = (comp.get("lib_id") or "").lower()
    return any(k in val or k in lib for k in _ADDRESSABLE_LED_WORDS)


# TVS series named without a protection word: Vishay/ST SMF, ST SM4T-SM15T, P4KE, SMCJ/SMDJ/SMLJ,
# 1.5SMC, 5KP and Vishay TPSMA-TPSMP. Not a bare SMA/SMB/SMC: those name rectifier packages too.
_TVS_FAMILIES = re.compile(r"(?<![a-z0-9])(?:smf\d|sm[468]t\d|sm15t\d|p4ke\d|smcj\d|smdj\d|smlj\d"
                           r"|1\.5smc\d|5kp\d|tpsm[abcp]\d)")
# What a description or symbol keywords call a clamp diode. Not a bare "ESD": "ESD sensitive"
# describes the part being protected.
_TVS_WORDS = re.compile(r"\btvs\b|transient[- ]?voltage[- ]?suppress|\btransil\b|transzorb"
                        r"|\besd (?:protection|suppress|diode)")


def is_tvs_diode(comp: dict) -> bool:
    """A TVS or ESD clamp diode: a protection name in its value, lib_id or MPN, a TVS series,
    or a description or symbol keywords that call it one."""
    name = " ".join((comp.get("value") or "", comp.get("lib_id") or "", comp.get("mpn") or "")).lower()
    if any(k in name for k in _PROTECTION_KEYWORDS) or _TVS_FAMILIES.search(name):
        return True
    words = " ".join((comp.get("description") or "", comp.get("keywords") or "")).lower()
    return bool(_TVS_WORDS.search(words))


# USB Type-C source Rp by pull-up rail: (nominal ohms, tolerance, status, text) for default USB,
# 1.5 A and 3 A current. USB Type-C Cable and Connector Specification Release 2.5 (March 2026),
# Table 4-27 Source CC Termination (Rp) Requirements; a sink's Rd is 5.1 kohm (Table 4-28).
TYPE_C_RP_BY_RAIL = {
    5.0: ((56000, 0.20, "source_default", "default USB current"),
          (22000, 0.05, "source_1_5A", "1.5A advertisement"),
          (10000, 0.05, "source_3A", "3A advertisement")),
    3.3: ((36000, 0.20, "source_default", "default USB current"),
          (12000, 0.05, "source_1_5A", "1.5A advertisement"),
          (4700, 0.05, "source_3A", "3A advertisement")),
}


def type_c_rp_rows(rail_v: float | None, any_rail: bool = False) -> tuple | None:
    """The Rp rows for a pull-up rail of *rail_v* volts, or None for a rail outside the 5 V and
    3.3 V windows. An unknown rail takes both tables when *any_rail* is set."""
    if rail_v is None:
        return TYPE_C_RP_BY_RAIL[5.0] + TYPE_C_RP_BY_RAIL[3.3] if any_rail else None
    if 4.5 <= rail_v <= 5.5:
        return TYPE_C_RP_BY_RAIL[5.0]
    if 3.0 <= rail_v <= 3.6:
        return TYPE_C_RP_BY_RAIL[3.3]
    return None


def type_c_rp(ohms: float, rail_v: float | None, any_rail: bool = False) -> tuple | None:
    """The Rp row matching a pull-up of *ohms* to a *rail_v* rail, else None. An unknown rail
    matches either table when *any_rail* is set."""
    rows = type_c_rp_rows(rail_v, any_rail) or ()
    return next((r for r in rows if r[0] * (1 - r[1]) <= ohms <= r[0] * (1 + r[1])), None)

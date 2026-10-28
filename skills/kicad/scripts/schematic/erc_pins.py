"""ERC pin semantics as KiCad 10 applies them by default: the pin-conflict map, the driver
sets, stacked pins and the default severities.

Sources: eeschema/erc/erc_settings.cpp (m_defaultPinMap, default severities), eeschema/erc/erc.cpp
(DrivingPinTypes, DrivingPowerPinTypes, DrivenPinTypes, TestPinToPin) and
eeschema/sch_pin.cpp (SCH_PIN::IsStacked).
"""
from __future__ import annotations

from kicad_core.coords import to_iu

_ORDER = ("input", "output", "bidirectional", "tri_state", "passive", "free",
          "unspecified", "power_in", "power_out", "open_collector", "open_emitter", "no_connect")
_IDX = {t: i for i, t in enumerate(_ORDER)}
OK, WARNING, ERROR = 0, 1, 2
_O, _W, _E = OK, WARNING, ERROR
_PIN_MAP = (
    #  I   O   Bi  3S  Pas NIC UnS PwI PwO OC  OE  NC
    (_O, _O, _O, _O, _O, _O, _W, _O, _O, _O, _O, _E),  # I
    (_O, _E, _O, _W, _O, _O, _W, _O, _E, _E, _E, _E),  # O
    (_O, _O, _O, _O, _O, _O, _W, _O, _W, _O, _W, _E),  # Bi
    (_O, _W, _O, _O, _O, _O, _W, _W, _E, _W, _W, _E),  # 3S
    (_O, _O, _O, _O, _O, _O, _W, _O, _O, _O, _O, _E),  # Pas
    (_O, _O, _O, _O, _O, _O, _O, _O, _O, _O, _O, _E),  # NIC
    (_W, _W, _W, _W, _W, _O, _W, _W, _W, _W, _W, _E),  # UnS
    (_O, _O, _O, _W, _O, _O, _W, _O, _O, _O, _O, _E),  # PwI
    (_O, _E, _W, _E, _O, _O, _W, _O, _E, _E, _E, _E),  # PwO
    (_O, _E, _O, _W, _O, _O, _W, _O, _E, _O, _O, _E),  # OC
    (_O, _E, _W, _W, _O, _O, _W, _O, _E, _O, _O, _E),  # OE
    (_E, _E, _E, _E, _E, _E, _E, _E, _E, _E, _E, _E),  # NC
)
DRIVING = frozenset({"output", "power_out", "passive", "tri_state", "bidirectional"})
DRIVING_POWER = frozenset({"power_out"})
DRIVEN = frozenset({"input", "power_in"})
# Pin kinds that actively drive a net (multi_driver_nets keeps conflicts among these).
DRIVERS = frozenset({"output", "power_out", "tri_state", "bidirectional",
                     "open_collector", "open_emitter"})
SEVERITY = {ERROR: "error", WARNING: "warning"}


def pin_kind(t: str | None) -> str:
    """A pin type string as a KiCad electrical type (the legacy 'unconnected' is no_connect)."""
    t = (t or "unspecified").lower()
    if t == "unconnected":
        return "no_connect"
    return t if t in _IDX else "unspecified"


def pair_level(a: str | None, b: str | None) -> int:
    return _PIN_MAP[_IDX[pin_kind(a)]][_IDX[pin_kind(b)]]


def pin_positions(components: list[dict]) -> dict:
    """(ref, pin number) -> (sheet, x, y, name), positions in schematic IU."""
    pos = {}
    for c in components:
        for p in c.get("pins") or []:
            if p.get("x") is None or p.get("y") is None:
                continue
            pos[(c["reference"], p.get("number", ""))] = (
                c.get("_sheet", 0), to_iu(p["x"]), to_iu(p["y"]), p.get("name"))
    return pos


def is_stacked(a: dict, b: dict, positions: dict) -> bool:
    """SCH_PIN::IsStacked: same symbol, position and name; same type or one passive/free."""
    if a["component"] != b["component"]:
        return False
    pa = positions.get((a["component"], a["pin_number"]))
    if pa is None or pa != positions.get((b["component"], b["pin_number"])):
        return False
    ta, tb = pin_kind(a.get("pin_type")), pin_kind(b.get("pin_type"))
    return ta == tb or ta in ("passive", "free") or tb in ("passive", "free")


def net_pin_conflicts(pins: list[dict], positions: dict) -> list[tuple[int, int, int]]:
    """Every non-OK pin pair on one net as (i, j, level) with i < j, stacked pins skipped."""
    by_kind: dict[int, list[int]] = {}
    for i, p in enumerate(pins):
        by_kind.setdefault(_IDX[pin_kind(p.get("pin_type"))], []).append(i)
    kinds = sorted(by_kind)
    out = []
    for n, ka in enumerate(kinds):
        for kb in kinds[n:]:
            level = _PIN_MAP[ka][kb]
            if not level:
                continue
            for i in by_kind[ka]:
                for j in by_kind[kb]:
                    if ka == kb and j <= i:
                        continue
                    if not is_stacked(pins[i], pins[j], positions):
                        out.append((min(i, j), max(i, j), level))
    out.sort()
    return out


def undriven_kind(pins: list[dict]) -> str | None:
    """TestPinToPin's drive test: 'pin_not_driven', 'power_pin_not_driven' or None.

    A net with a power input pin is a power net, driven only by a power output pin.
    """
    kinds = {pin_kind(p.get("pin_type")) for p in pins}
    if not kinds & DRIVEN:
        return None
    power = "power_in" in kinds
    if kinds & (DRIVING_POWER if power else DRIVING):
        return None
    return "power_pin_not_driven" if power else "pin_not_driven"

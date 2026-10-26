"""Legacy schematic reader: KiCad 5 .sch / .lib → component and wire records.

Verbatim moves from analyze_schematic.py; no behaviour change.
"""
from __future__ import annotations

import re
from pathlib import Path

from kicad_core.sexp import find_all, parse_file
from kicad_core.coords import to_iu
from kicad_core.values import _MIL_MM, snap_to_mil_grid as _snap_mil
from kicad_core.classify import classify_component
from kicad_core.fields import (
    MPN_FIELD_ALIASES_PRIMARY, MPN_FIELD_ALIASES_GENERIC,
    DIGIKEY_FIELD_ALIASES, normalize_field_name,
)
from schematic.reader import (
    _ANGLE_TRANSFORM, _MANUFACTURER_KEYS, _MOUSER_KEYS, _LCSC_KEYS, _ELEMENT14_KEYS,
)


# KiCad 5 legacy .lib pin type codes → KiCad 6+ type strings
_LEGACY_PIN_TYPE_MAP = {
    "I": "input",
    "O": "output",
    "B": "bidirectional",
    "T": "tri_state",
    "P": "passive",
    "W": "power_in",
    "w": "power_out",
    "C": "open_collector",
    "E": "open_emitter",
    "N": "unconnected",
    "U": "unspecified",
}

# Built-in pin definitions for standard KiCad 4/5 library symbols that won't
# be found in project .lib files (power/device/conn libs).  Offsets are in mm
# at the connection endpoint (where wires attach), matching the output of
# _parse_legacy_lib() after mil→mm conversion.
#
# Values derived from the most common pin positions across 1292 KiCad 4/5
# cache libraries.  Different KiCad versions use slightly different offsets
# (e.g., R/C at ±100, ±150, ±200, or ±250 mils); the wire-snap fallback
# (_snap_pins_to_wires) handles version mismatches automatically.
_M = 0.0254  # 1 mil in mm — shorthand for readability

def _conn_1xN(n):
    """Generate pin list for CONN_01X{n} (single-row, n pins, x=-200 mils)."""
    half = (n - 1) * 50  # half-span in mils
    return [{"number": str(i + 1), "name": f"P{i + 1}", "type": "passive",
             "offset": [-200 * _M, (half - i * 100) * _M]} for i in range(n)]

def _conn_2xN(n):
    """Generate pin list for CONN_02X{n} (2-row, 2n pins, x=±250 mils)."""
    half = (n - 1) * 50
    pins = []
    for i in range(n):
        y = (half - i * 100) * _M
        pins.append({"number": str(2 * i + 1), "name": f"P{2*i+1}", "type": "passive",
                      "offset": [-250 * _M, y]})
        pins.append({"number": str(2 * i + 2), "name": f"P{2*i+2}", "type": "passive",
                      "offset": [250 * _M, y]})
    return pins

_STANDARD_LIB_PINS = {
    # --- Passives (most common: ±150 mils vertical) ---
    "R": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 150 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -150 * _M]},
    ],
    "C": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 150 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -150 * _M]},
    ],
    "L": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 150 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -150 * _M]},
    ],
    "CP": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 150 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -150 * _M]},
    ],
    "CP1": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 150 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -150 * _M]},
    ],
    "C_Polarized": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 150 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -150 * _M]},
    ],
    "INDUCTOR": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 300 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -300 * _M]},
    ],
    # --- Small passives (±100 mils vertical) ---
    "C_Small": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 100 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -100 * _M]},
    ],
    "R_Small": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 100 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -100 * _M]},
    ],
    "L_Small": [
        {"number": "1", "name": "~", "type": "passive", "offset": [0, 100 * _M]},
        {"number": "2", "name": "~", "type": "passive", "offset": [0, -100 * _M]},
    ],
    "INDUCTOR_SMALL": [
        {"number": "1", "name": "~", "type": "passive", "offset": [-250 * _M, 0]},
        {"number": "2", "name": "~", "type": "passive", "offset": [250 * _M, 0]},
    ],
    # --- Diodes (±150 mils horizontal, A=anode K=cathode) ---
    "D": [
        {"number": "1", "name": "K", "type": "passive", "offset": [-150 * _M, 0]},
        {"number": "2", "name": "A", "type": "passive", "offset": [150 * _M, 0]},
    ],
    "D_Schottky": [
        {"number": "1", "name": "K", "type": "passive", "offset": [-150 * _M, 0]},
        {"number": "2", "name": "A", "type": "passive", "offset": [150 * _M, 0]},
    ],
    "D_Zener": [
        {"number": "1", "name": "K", "type": "passive", "offset": [-150 * _M, 0]},
        {"number": "2", "name": "A", "type": "passive", "offset": [150 * _M, 0]},
    ],
    "DIODESCH": [
        {"number": "1", "name": "K", "type": "passive", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "A", "type": "passive", "offset": [200 * _M, 0]},
    ],
    "LED": [
        {"number": "1", "name": "K", "type": "passive", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "A", "type": "passive", "offset": [200 * _M, 0]},
    ],
    # --- Crystals ---
    "CRYSTAL": [
        {"number": "1", "name": "1", "type": "passive", "offset": [-300 * _M, 0]},
        {"number": "2", "name": "2", "type": "passive", "offset": [300 * _M, 0]},
    ],
    "Crystal": [
        {"number": "1", "name": "1", "type": "passive", "offset": [-150 * _M, 0]},
        {"number": "2", "name": "2", "type": "passive", "offset": [150 * _M, 0]},
    ],
    "Crystal_GND24": [
        {"number": "1", "name": "1", "type": "passive", "offset": [-150 * _M, 0]},
        {"number": "2", "name": "2", "type": "passive", "offset": [0, -200 * _M]},
        {"number": "3", "name": "3", "type": "passive", "offset": [150 * _M, 0]},
        {"number": "4", "name": "4", "type": "passive", "offset": [0, 200 * _M]},
    ],
    # --- Switches ---
    "SW_PUSH": [
        {"number": "1", "name": "1", "type": "passive", "offset": [-300 * _M, 0]},
        {"number": "2", "name": "2", "type": "passive", "offset": [300 * _M, 0]},
    ],
    "SW_Push": [
        {"number": "1", "name": "1", "type": "passive", "offset": [-300 * _M, 0]},
        {"number": "2", "name": "2", "type": "passive", "offset": [300 * _M, 0]},
    ],
    # --- Transistors ---
    "Q_NPN_BEC": [
        {"number": "1", "name": "B", "type": "input", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "E", "type": "passive", "offset": [100 * _M, -200 * _M]},
        {"number": "3", "name": "C", "type": "passive", "offset": [100 * _M, 200 * _M]},
    ],
    "Q_PNP_BEC": [
        {"number": "1", "name": "B", "type": "input", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "E", "type": "passive", "offset": [100 * _M, 200 * _M]},
        {"number": "3", "name": "C", "type": "passive", "offset": [100 * _M, -200 * _M]},
    ],
    "Q_NMOS_GSD": [
        {"number": "1", "name": "G", "type": "input", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "S", "type": "passive", "offset": [100 * _M, -200 * _M]},
        {"number": "3", "name": "D", "type": "passive", "offset": [100 * _M, 200 * _M]},
    ],
    "Q_PMOS_GSD": [
        {"number": "1", "name": "G", "type": "input", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "S", "type": "passive", "offset": [100 * _M, 200 * _M]},
        {"number": "3", "name": "D", "type": "passive", "offset": [100 * _M, -200 * _M]},
    ],
    "MOSFET_N": [
        {"number": "1", "name": "G", "type": "input", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "S", "type": "passive", "offset": [100 * _M, -200 * _M]},
        {"number": "3", "name": "D", "type": "passive", "offset": [100 * _M, 200 * _M]},
    ],
    "MOSFET_P": [
        {"number": "1", "name": "G", "type": "input", "offset": [-200 * _M, 0]},
        {"number": "2", "name": "S", "type": "passive", "offset": [100 * _M, 200 * _M]},
        {"number": "3", "name": "D", "type": "passive", "offset": [100 * _M, -200 * _M]},
    ],
    # --- Resistor packs ---
    "R_PACK4": [
        {"number": str(i + 1), "name": f"P{i+1}", "type": "passive",
         "offset": [-200 * _M, (150 - i * 100) * _M]} for i in range(4)
    ] + [
        {"number": str(i + 5), "name": f"R{4-i}", "type": "passive",
         "offset": [200 * _M, (-150 + i * 100) * _M]} for i in range(4)
    ],
    "R_PACK8": [
        {"number": str(i + 1), "name": f"P{i+1}", "type": "passive",
         "offset": [-200 * _M, (350 - i * 100) * _M]} for i in range(8)
    ] + [
        {"number": str(i + 9), "name": f"R{8-i}", "type": "passive",
         "offset": [200 * _M, (-350 + i * 100) * _M]} for i in range(8)
    ],
    # --- Single-row connectors (CONN_01X01 through CONN_01X20) ---
    **{f"CONN_01X{n:02d}": _conn_1xN(n) for n in range(1, 21)},
    # --- Short-form single-row connectors (CONN_1 through CONN_20) ---
    **{f"CONN_{n}": _conn_1xN(n) for n in range(1, 21)},
    # --- Dual-row connectors (CONN_02Xnn format) ---
    **{f"CONN_02X{n:02d}": _conn_2xN(n) for n in range(2, 21)},
    # --- Short-form dual-row connectors (CONN_NX2 format) ---
    **{f"CONN_{n}X2": _conn_2xN(n) for n in range(2, 21)},
    "CONN_5X2": _conn_2xN(5),
}


_MATRIX_LINE = re.compile(r"-?\d+\s+-?\d+\s+-?\d+\s+-?\d+$")


def _legacy_orientation_table() -> dict:
    """Raw legacy matrix -> (angle, mirror_x, mirror_y) that places pins identically.

    KiCad's legacy loader negates the second column of the file matrix, so the
    KiCad 6 transform (x1, y1, x2, y2) corresponds to the file matrix
    (x1, -y1, x2, -y2).  Candidates are tried in KiCad's GetOrientation order,
    so an unmirrored orientation wins over an equivalent mirrored one.
    """
    table = {}
    candidates = [(a, False, False) for a in (0, 90, 180, 270)]
    candidates += [(0, True, False), (90, True, False), (270, True, False)]
    candidates += [(a, False, True) for a in (0, 90, 180, 270)]
    for angle, mx, my in candidates:
        x1, y1, x2, y2 = _ANGLE_TRANSFORM[angle]
        if mx:
            x2, y2 = -x2, -y2
        if my:
            x1, y1 = -x1, -y1
        table.setdefault((x1, -y1, x2, -y2), (angle, mx, my))
    return table


_LEGACY_ORIENTATION = _legacy_orientation_table()


def _parse_legacy_lib(path: str) -> dict:
    """Parse a KiCad 5 .lib file and return symbol definitions.

    Returns dict matching extract_lib_symbols() format:
    {symbol_name: {"pins": [...], "unit_pins": {unit: [...]}, ...}}
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {}

    if not lines or not lines[0].startswith("EESchema-LIBRARY"):
        return {}

    MIL_TO_MM = _MIL_MM
    symbols = {}
    current_name = None
    current_aliases = []  # KH-142: track ALIAS names
    current_pins = []
    current_unit_pins = {}
    current_alt_pins = []
    current_alt_unit_pins = {}
    current_has_alt = False
    current_datasheet = ""
    in_draw = False

    for line in lines:
        line = line.strip()

        if line.startswith("DEF "):
            parts = line.split()
            if len(parts) >= 2:
                current_name = parts[1].lstrip("~")
                current_aliases = []
                current_pins = []
                current_unit_pins = {}
                current_alt_pins = []
                current_alt_unit_pins = {}
                current_has_alt = False
                current_datasheet = ""
                in_draw = False

        elif line.startswith("ALIAS ") and current_name is not None:
            # KH-142: Parse ALIAS directives — alternate names for this symbol
            current_aliases.extend(line.split()[1:])

        elif line.startswith("F3 ") and current_name is not None:
            m = re.match(r'F3\s+"([^"]*)"', line)
            if m:
                current_datasheet = m.group(1)

        elif line == "DRAW":
            in_draw = True

        elif line == "ENDDRAW":
            in_draw = False

        elif line.startswith("X ") and in_draw and current_name is not None:
            # X name number x y length dir sz1 sz2 unit convert elec_type [shape]
            parts = line.split()
            if len(parts) >= 12:
                pin_name = parts[1]
                pin_number = parts[2]
                try:
                    px = int(parts[3]) * MIL_TO_MM
                    py = int(parts[4]) * MIL_TO_MM
                    unit_num = int(parts[9])
                except (ValueError, IndexError):
                    continue
                body_style = int(parts[10]) if parts[10].isdigit() else 0
                elec_code = parts[11]
                pin_type = _LEGACY_PIN_TYPE_MAP.get(elec_code, "unspecified")

                pin = {
                    "number": pin_number,
                    "name": pin_name if pin_name != "~" else "",
                    "type": pin_type,
                    "shape": "",
                    "offset": [round(px, 4), round(py, 4)],
                    # an N anywhere in the shape token makes the pin invisible
                    "hidden": len(parts) >= 13 and "N" in parts[12],
                }
                # body style 0 is common to both bodies, 2 is the De Morgan alternate
                if body_style != 2:
                    current_pins.append(pin)
                    current_unit_pins.setdefault(unit_num, []).append(pin)
                if body_style != 1:
                    current_has_alt = current_has_alt or body_style == 2
                    current_alt_pins.append(pin)
                    current_alt_unit_pins.setdefault(unit_num, []).append(pin)

        elif line == "ENDDEF" and current_name is not None:
            # Check if multi-unit: has pins in more than one non-zero unit
            non_zero_units = {u for u in current_unit_pins if u != 0}
            has_multi_unit = len(non_zero_units) > 1

            sym_def = {
                "pins": current_pins,
                "unit_pins": current_unit_pins if has_multi_unit else None,
                "description": "",
                "keywords": "",
                "is_power": False,
                "ki_fp_filters": "",
                "alternates": None,
            }
            if current_datasheet:
                sym_def["datasheet"] = current_datasheet
            if current_has_alt:
                sym_def["alt_unit_pins"] = current_alt_unit_pins if has_multi_unit else None
                sym_def["alt_pins"] = current_alt_pins
            symbols[current_name] = sym_def
            # KH-142: Register same definition under each alias name
            for alias in current_aliases:
                symbols[alias.lstrip("~")] = sym_def
            current_name = None

    return symbols


def _read_sym_lib_table(base_dir: Path) -> list:
    """Legacy-type entries of the project sym-lib-table as (nickname, existing lib path).

    ${KIPRJMOD} is the project directory and relative paths start there; any other
    variable leaves the entry out.
    A missing or malformed table, or an unreadable library, yields nothing.
    """
    table = base_dir / "sym-lib-table"
    if not table.exists():
        return []
    entries = []
    try:
        root = parse_file(str(table))
        lib_nodes = find_all(root, "lib")
    except (ValueError, IndexError, KeyError, OSError):
        return []  # Don't crash on malformed sym-lib-table
    for lib_entry in lib_nodes:
        try:
            nick = lib_type = lib_uri = ""
            for child in lib_entry:
                if isinstance(child, list) and len(child) >= 2:
                    if child[0] == "name":
                        nick = str(child[1])
                    elif child[0] == "type":
                        lib_type = str(child[1])
                    elif child[0] == "uri":
                        lib_uri = str(child[1])
            if lib_type != "Legacy" or not lib_uri:
                continue
            lib_uri = lib_uri.replace("${KIPRJMOD}", str(base_dir))
            if "${" in lib_uri:
                continue
            lib_path = base_dir / lib_uri  # an absolute URI replaces base_dir
            if lib_path.is_file():
                entries.append((nick, lib_path))
        except (ValueError, IndexError, KeyError, OSError):
            continue
    return entries


def _resolve_legacy_libs(sch_path: str, all_sch_lines: dict) -> tuple:
    """Find and parse .lib files for legacy schematics.

    Args:
        sch_path: Path to the root .sch file.
        all_sch_lines: Dict mapping sheet paths to their lines (for LIBS: extraction).

    Strategy:
    1. Look for *-cache.lib alongside the root .sch file (self-contained, preferred)
    2. Parse LIBS: directives, search for each .lib in project directory tree
    3. Fall back to built-in defaults for standard KiCad symbols

    Returns:
        (symbols, resolution_info) where resolution_info describes which strategy
        was used and how many symbols came from parsed vs built-in sources.
    """
    base = Path(sch_path)
    base_dir = base.parent
    stem = base.stem

    resolution_info = {
        "cache_lib_found": False,
        "sym_lib_table_used": False,
        "libs_directive_used": False,
        "builtin_fallback_count": 0,
        "parsed_lib_count": 0,
    }

    # Strategy 1: cache lib — if present, it contains ALL symbols
    cache_path = base_dir / f"{stem}-cache.lib"
    if cache_path.exists():
        symbols = _parse_legacy_lib(str(cache_path))
        # Project libraries the cache does not hold, addressed as nick:name
        for nick, lib_path in _read_sym_lib_table(base_dir):
            for name, sym_def in _parse_legacy_lib(str(lib_path)).items():
                symbols.setdefault(f"{nick}:{name}", sym_def)
        # Also add standard library fallbacks for anything missing
        for name, pins in _STANDARD_LIB_PINS.items():
            if name not in symbols:
                symbols[name] = {
                    "pins": pins, "unit_pins": None, "description": "",
                    "keywords": "", "is_power": False, "ki_fp_filters": "",
                    "alternates": None, "_builtin": True,
                }
        resolution_info["cache_lib_found"] = True
        resolution_info["parsed_lib_count"] = max(0, len(symbols) - len(_STANDARD_LIB_PINS))
        resolution_info["builtin_fallback_count"] = len(_STANDARD_LIB_PINS)
        return symbols, resolution_info

    # Strategy 2.5: Parse sym-lib-table for legacy library paths (KH-141)
    # KiCad 5 file version 4 uses sym-lib-table instead of LIBS: header directives
    slt_entries = _read_sym_lib_table(base_dir)
    if slt_entries:
        slt_symbols = {}
        for _nick, lib_path in slt_entries:
            slt_symbols.update(_parse_legacy_lib(str(lib_path)))
        if slt_symbols:
            # Add standard library fallbacks
            for name, pins in _STANDARD_LIB_PINS.items():
                if name not in slt_symbols:
                    slt_symbols[name] = {
                        "pins": pins, "unit_pins": None, "description": "",
                        "keywords": "", "is_power": False, "ki_fp_filters": "",
                        "alternates": None, "_builtin": True,
                    }
            resolution_info["sym_lib_table_used"] = True
            resolution_info["parsed_lib_count"] = max(0, len(slt_symbols) - len(_STANDARD_LIB_PINS))
            resolution_info["builtin_fallback_count"] = len(_STANDARD_LIB_PINS)
            return slt_symbols, resolution_info

    # Strategy 2: collect LIBS: directives from all parsed sheets
    lib_names = []
    seen_lib_names = set()
    for sheet_lines in all_sch_lines.values():
        for line in sheet_lines:
            if line.startswith("LIBS:"):
                name = line[5:].strip()
                # Skip cache lib references (they reference the missing cache)
                if name.endswith("-cache") or name.endswith("-rescue"):
                    continue
                # Skip standard KiCad libs we handle with built-in defaults
                if name in ("power", "device", "conn", "transistors",
                            "linear", "regul", "74xx", "cmos4000",
                            "adc-dac", "memory", "xilinx", "microcontrollers",
                            "dsp", "microchip", "analog_switches",
                            "motorola", "texas", "intel", "audio",
                            "interface", "digital-audio", "philips",
                            "display", "cypress", "siliconi", "opto",
                            "atmel", "contrib", "valves"):
                    continue
                if name not in seen_lib_names:
                    lib_names.append(name)
                    seen_lib_names.add(name)

    # Search for each .lib file
    # Build search dirs: from .sch dir, walk up to 4 levels
    search_dirs = []
    d = base_dir
    for _ in range(5):
        search_dirs.append(d)
        # Also check lib/ subdirectory
        lib_subdir = d / "lib"
        if lib_subdir.is_dir():
            search_dirs.append(lib_subdir)
        parent = d.parent
        if parent == d:
            break
        d = parent

    symbols = {}
    for lib_name in lib_names:
        lib_file = f"{lib_name}.lib"
        for search_dir in search_dirs:
            candidate = search_dir / lib_file
            if candidate.exists():
                parsed = _parse_legacy_lib(str(candidate))
                symbols.update(parsed)
                break

    # Add standard library fallbacks
    for name, pins in _STANDARD_LIB_PINS.items():
        if name not in symbols:
            symbols[name] = {
                "pins": pins, "unit_pins": None, "description": "",
                "keywords": "", "is_power": False, "ki_fp_filters": "",
                "alternates": None, "_builtin": True,
            }

    resolution_info["libs_directive_used"] = bool(lib_names)
    resolution_info["parsed_lib_count"] = max(0, len(symbols) - len(_STANDARD_LIB_PINS))
    resolution_info["builtin_fallback_count"] = len(_STANDARD_LIB_PINS)
    return symbols, resolution_info


def _snap_pins_to_wires(components: list[dict], wires: list[dict],
                        occupied: list[dict]) -> None:
    """Snap built-in fallback pins to nearby free wire endpoints.

    Legacy KiCad standard library pin offsets vary between versions (±100, ±150,
    ±200, ±250 mils for R/C/L/D).  A pin of a component whose symbol came from
    the built-in table (``_pin_source == "builtin"``) that is not exactly on a wire
    endpoint may move to the free wire endpoint nearest to it among
    those within _MAX_SNAP_DIST of the component center, roughly in the pin's
    direction.

    A wire endpoint held by a parsed-library pin, a built-in pin that sits on
    it, a power symbol or one of the ``occupied`` points (labels and no-connect
    markers: dicts with x, y, _sheet) is never a target.  Each free endpoint
    takes at most one pin: when several pins want the same endpoint the nearest
    pin wins (ties in component order) and the others stay where they are.
    Pins from parsed libraries are where KiCad puts them and never move.
    """
    _MAX_SNAP_DIST = 12.0  # mm (~470 mils) — covers all standard symbols
    def key(x, y):
        return (to_iu(x), to_iu(y))

    wire_eps_by_sheet: dict[int, set[tuple[int, int]]] = {}
    for w in wires:
        sheet = w.get("_sheet", 0)
        for x, y in ((w["x1"], w["y1"]), (w["x2"], w["y2"])):
            wire_eps_by_sheet.setdefault(sheet, set()).add(key(x, y))

    held: dict[int, set[tuple[int, int]]] = {}
    for comp in components:
        sheet = comp.get("_sheet", 0)
        if comp.get("type") in ("power_symbol", "power_flag", "flag"):
            held.setdefault(sheet, set()).add(key(comp["x"], comp["y"]))
        elif comp.get("_pin_source") != "builtin":
            for pin in comp.get("pins") or []:
                held.setdefault(sheet, set()).add(key(pin["x"], pin["y"]))
        else:
            # a built-in pin already on a wire end holds it too
            for pin in comp.get("pins") or []:
                sk = key(pin["x"], pin["y"])
                if sk in wire_eps_by_sheet.get(sheet, ()):
                    held.setdefault(sheet, set()).add(sk)
    for pt in occupied:
        held.setdefault(pt.get("_sheet", 0), set()).add(key(pt["x"], pt["y"]))

    free_pts_by_sheet: dict[int, list[tuple[float, float]]] = {}
    for w in wires:
        sheet = w.get("_sheet", 0)
        for x, y in ((w["x1"], w["y1"]), (w["x2"], w["y2"])):
            if key(x, y) not in held.get(sheet, ()):
                free_pts_by_sheet.setdefault(sheet, []).append((x, y))

    # each unmatched built-in pin's nearest acceptable endpoint:
    # (distance from the pin, comp index, pin index, sheet, endpoint)
    wanted = []
    for ci, comp in enumerate(components):
        if comp.get("_pin_source") != "builtin":
            continue
        if comp.get("type") in ("power_symbol", "power_flag", "flag"):
            continue
        sheet = comp.get("_sheet", 0)
        wire_set = wire_eps_by_sheet.get(sheet, set())
        free_list = free_pts_by_sheet.get(sheet, [])
        cx, cy = comp["x"], comp["y"]
        for pi, pin in enumerate(comp.get("pins") or []):
            if key(pin["x"], pin["y"]) in wire_set:
                continue
            opx, opy = pin["x"] - cx, pin["y"] - cy
            best = None
            for wx, wy in free_list:
                dx = wx - cx
                dy = wy - cy
                if (dx * dx + dy * dy) ** 0.5 >= _MAX_SNAP_DIST:
                    continue
                # only endpoints roughly in the direction of the computed pin
                if not (dx * opx + dy * opy > 0 or (opx == 0 and opy == 0)):
                    continue
                d = ((wx - pin["x"]) ** 2 + (wy - pin["y"]) ** 2) ** 0.5
                if best is None or d < best[0]:
                    best = (d, (wx, wy))
            if best is not None:
                wanted.append((best[0], ci, pi, sheet, best[1]))

    # A pin that loses its endpoint does not fall back to a farther one: the
    # winner is the likelier owner and the loser's offset is likely wrong.
    taken: set[tuple[int, tuple[int, int]]] = set()
    for _d, ci, pi, sheet, (wx, wy) in sorted(wanted, key=lambda w: w[:3]):
        end = (sheet, key(wx, wy))
        if end in taken:
            continue
        taken.add(end)
        comp = components[ci]
        pin = comp["pins"][pi]
        pin["x"] = _snap_mil(wx)
        pin["y"] = _snap_mil(wy)
        comp["_pin_source"] = "snapped_to_wire"


_AR_LINE = re.compile(r'AR\s+Path="([^"]*)"\s+Ref="([^"]*)"\s+Part="([^"]*)"')
_SHEET_PIN_LINE = re.compile(r'F(\d+)\s+"([^"]*)"\s+\S+\s+\S+\s+(-?\d+)\s+(-?\d+)')


def _parse_legacy_single_sheet(path: str) -> tuple:
    """Parse a single legacy .sch file and return raw extracted data.

    Returns: (components, wires, labels, junctions, no_connects, sub_sheet_paths, lib_lines)
    where sub_sheet_paths is a list of (resolved path, sheet timestamp) for $Sheet
    references, and lib_lines is a list of raw 'LIBS:...' lines from the file header.
    Sheet pins come back as hierarchical labels carrying ``_sheet_uuid``; a component's
    ``AR`` records come back as ``_ar`` = {upper-cased path: (reference, unit)}.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    components = []
    wires = []
    labels = []
    junctions = []
    no_connects = []
    sub_sheet_paths = []

    MIL_TO_MM = _MIL_MM
    base_dir = Path(path).parent

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Component block
        if line == "$Comp":
            comp = {
                "reference": "", "value": "", "lib_id": "", "footprint": "",
                "datasheet": "", "description": "", "mpn": "", "manufacturer": "",
                "digikey": "", "mouser": "", "lcsc": "", "element14": "",
                "x": 0, "y": 0, "angle": 0,
                "mirror_x": False, "mirror_y": False,
                "uuid": "", "in_bom": True, "dnp": False, "on_board": True,
                "pin_uuids": {}, "pins": [], "type": "other",
            }
            i += 1
            while i < len(lines) and lines[i].strip() != "$EndComp":
                cl = lines[i].strip()

                # L Library:Symbol Reference
                if cl.startswith("L "):
                    parts = cl.split()
                    if len(parts) >= 3:
                        comp["lib_id"] = parts[1]
                        comp["reference"] = parts[2]

                # U unit convert timestamp
                elif cl.startswith("U "):
                    parts = cl.split()
                    if len(parts) >= 4:
                        comp["uuid"] = parts[3]
                        try:
                            comp["unit"] = int(parts[1])
                        except (ValueError, IndexError):
                            pass
                        try:
                            comp["_body_style"] = int(parts[2])
                        except ValueError:
                            pass

                # AR Path="/<sheet ts>/.../<symbol ts>" Ref="R10"  Part="1"
                elif cl.startswith("AR "):
                    am = _AR_LINE.match(cl)
                    if am:
                        comp.setdefault("_ar", {})[am.group(1).upper()] = (am.group(2), am.group(3))

                # P x y
                elif cl.startswith("P "):
                    parts = cl.split()
                    if len(parts) >= 3:
                        comp["x"] = _snap_mil(int(parts[1]) * MIL_TO_MM)
                        comp["y"] = _snap_mil(int(parts[2]) * MIL_TO_MM)

                # F N "value" orientation x y size flags visibility hjustify [font [italic bold]]
                elif cl.startswith("F "):
                    # Parse field: F N "value" ...
                    fm = re.match(r'F\s+(\d+)\s+"([^"]*)"', cl)
                    if fm:
                        field_num = int(fm.group(1))
                        field_val = fm.group(2)
                        if field_num == 0:
                            comp["reference"] = field_val
                        elif field_num == 1:
                            comp["value"] = field_val
                        elif field_num == 2:
                            comp["footprint"] = field_val
                        elif field_num == 3:
                            comp["datasheet"] = field_val
                        # Fields 4+ are custom — try to capture them
                        elif field_num >= 4 and field_val:
                            # Check if the field has a name after the positional data
                            # Format: F N "value" H x y size flags visibility hjustify "FieldName"
                            name_match = re.search(r'"([^"]*)"[^"]*$', cl[fm.end():])
                            fname = name_match.group(1) if name_match else f"Field{field_num}"
                            if name_match:
                                fl = normalize_field_name(fname)
                                if fl in MPN_FIELD_ALIASES_PRIMARY:
                                    # Final wave fix: a blank primary may still SET
                                    # an unset mpn (old last-wins behaviour for
                                    # blank-only symbols) but may not OVERWRITE a
                                    # populated one.
                                    if field_val.strip() or not comp.get("mpn"):
                                        comp["mpn"] = field_val
                                elif fl in MPN_FIELD_ALIASES_GENERIC:
                                    if not (comp.get("mpn") or "").strip():
                                        comp["mpn"] = field_val
                                elif fl in _MANUFACTURER_KEYS:
                                    comp["manufacturer"] = field_val
                                elif fl in DIGIKEY_FIELD_ALIASES:
                                    comp["digikey"] = field_val
                                elif fl in _MOUSER_KEYS:
                                    comp["mouser"] = field_val
                                elif fl in _LCSC_KEYS:
                                    comp["lcsc"] = field_val
                                elif fl in _ELEMENT14_KEYS:
                                    comp["element14"] = field_val
                                elif fl == "dnp":
                                    comp["dnp"] = field_val.strip() not in ("", "0", "false")
                                elif fl in ("note", "notes", "comment"):
                                    if any(dnp_kw in field_val.upper() for dnp_kw in ("DNP", "DO NOT POPULATE", "DO NOT PLACE")):
                                        comp["dnp"] = True
                                elif fl in ("description", "desc"):
                                    comp["description"] = field_val
                            # Track generic-named fields for positional fallback
                            if re.match(r'^Field\d+$', fname):
                                comp.setdefault("_generic_fields", {})[fname] = field_val

                # Orientation matrix line (after position line): four signed ints
                # a b c d; the 3-token redundant position line never matches.
                elif _MATRIX_LINE.match(cl):
                    a, b, c, d = [int(p) for p in cl.split()]
                    comp["transform_matrix"] = (a, b, c, d)
                    orient = _LEGACY_ORIENTATION.get((a, b, c, d))
                    if orient:
                        comp["angle"], comp["mirror_x"], comp["mirror_y"] = orient

                i += 1
            # Positional fallback for generic field names (Field1=manufacturer, Field2=MPN)
            gf = comp.pop("_generic_fields", {})
            if not comp.get("mpn") and gf:
                if "Field2" in gf and gf["Field2"]:
                    comp["mpn"] = gf["Field2"]
                if not comp.get("manufacturer") and "Field1" in gf and gf["Field1"]:
                    comp["manufacturer"] = gf["Field1"]

            # Legacy power symbol detection: #PWR/#FLG refs or library named "power"
            lib_prefix = comp["lib_id"].split(":")[0].lower()
            is_power = (comp["reference"].startswith("#")
                        or lib_prefix == "power"
                        or lib_prefix.endswith("_power"))
            # Check value field for DNP indication
            if not comp["dnp"] and comp["value"].upper() in ("DNP", "DO NOT POPULATE", "DO NOT PLACE", "NP"):
                comp["dnp"] = True
            comp["type"] = classify_component(comp["reference"], comp["lib_id"], comp["value"], is_power, comp.get("footprint", ""),
                                              description=comp.get("description", ""))
            components.append(comp)

        # Hierarchical sheet block — subsheet filename, timestamp and pins
        elif line == "$Sheet":
            sheet_file = None
            sheet_ts = ""
            sheet_pins = []
            i += 1
            while i < len(lines) and lines[i].strip() != "$EndSheet":
                sl = lines[i].strip()
                # F1 "filename.sch" size — the sheet filename field
                sm = re.match(r'F1\s+"([^"]+\.sch)"', sl)
                if sm:
                    sheet_file = sm.group(1)
                um = re.match(r'U\s+([0-9A-Fa-f]+)', sl)
                if um:
                    sheet_ts = um.group(1).upper()
                # F<n> "NAME" shape side x y size, n >= 2 — a sheet pin
                pm = _SHEET_PIN_LINE.match(sl)
                if pm and int(pm.group(1)) >= 2:
                    sheet_pins.append((pm.group(2), int(pm.group(3)), int(pm.group(4))))
                i += 1
            for pin_name, px, py in sheet_pins:
                labels.append({"name": pin_name, "type": "hierarchical_label",
                               "x": _snap_mil(px * MIL_TO_MM), "y": _snap_mil(py * MIL_TO_MM),
                               "angle": 0, "_sheet_uuid": sheet_ts})
            if sheet_file:
                sub_path = base_dir / sheet_file
                if sub_path.exists():
                    sub_sheet_paths.append((str(sub_path.resolve()), sheet_ts))

        # Wire
        elif line == "Wire Wire Line":
            i += 1
            if i < len(lines):
                parts = lines[i].strip().split()
                if len(parts) >= 4:
                    wires.append({
                        "x1": _snap_mil(int(parts[0]) * MIL_TO_MM),
                        "y1": _snap_mil(int(parts[1]) * MIL_TO_MM),
                        "x2": _snap_mil(int(parts[2]) * MIL_TO_MM),
                        "y2": _snap_mil(int(parts[3]) * MIL_TO_MM),
                    })

        # Junction / Connection
        elif line.startswith("Connection ~"):
            parts = line.split()
            if len(parts) >= 4:
                junctions.append({
                    "x": _snap_mil(int(parts[2]) * MIL_TO_MM),
                    "y": _snap_mil(int(parts[3]) * MIL_TO_MM),
                })

        # No-connect
        elif line.startswith("NoConn ~"):
            parts = line.split()
            if len(parts) >= 4:
                no_connects.append({
                    "x": _snap_mil(int(parts[2]) * MIL_TO_MM),
                    "y": _snap_mil(int(parts[3]) * MIL_TO_MM),
                })

        # Labels
        elif line.startswith("Text Label "):
            parts = line.split()
            if len(parts) >= 5:
                x = _snap_mil(int(parts[2]) * MIL_TO_MM)
                y = _snap_mil(int(parts[3]) * MIL_TO_MM)
                # Next line is the label text
                i += 1
                if i < len(lines):
                    name = lines[i].strip()
                    labels.append({"name": name, "type": "label", "x": x, "y": y, "angle": 0})

        elif line.startswith("Text GLabel "):
            parts = line.split()
            if len(parts) >= 5:
                x = _snap_mil(int(parts[2]) * MIL_TO_MM)
                y = _snap_mil(int(parts[3]) * MIL_TO_MM)
                i += 1
                if i < len(lines):
                    name = lines[i].strip()
                    labels.append({"name": name, "type": "global_label", "x": x, "y": y, "angle": 0})

        elif line.startswith("Text HLabel "):
            parts = line.split()
            if len(parts) >= 5:
                x = _snap_mil(int(parts[2]) * MIL_TO_MM)
                y = _snap_mil(int(parts[3]) * MIL_TO_MM)
                i += 1
                if i < len(lines):
                    name = lines[i].strip()
                    labels.append({"name": name, "type": "hierarchical_label", "x": x, "y": y, "angle": 0})

        i += 1

    # Collect LIBS: directives from header for lib resolution
    lib_lines = [l.strip() for l in lines if l.strip().startswith("LIBS:")]

    return components, wires, labels, junctions, no_connects, sub_sheet_paths, lib_lines

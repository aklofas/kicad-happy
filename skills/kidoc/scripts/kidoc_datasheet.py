#!/usr/bin/env python3
"""Datasheet integration module for kidoc engineering reports.

Loads extracted datasheet data for components in a schematic analysis and
generates comparison tables, pin audits, and deviation flags for report
sections.

Zero external dependencies — Python stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import datasheet_extract_cache from the datasheets skill
# ---------------------------------------------------------------------------

_ds_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', '..', 'datasheets', 'scripts')
if os.path.isdir(_ds_scripts):
    sys.path.insert(0, os.path.abspath(_ds_scripts))

try:
    from datasheet_extract_cache import (
        resolve_extract_dir,
        get_cached_extraction,
        list_extractions,
    )
except ImportError:
    # Graceful degradation if cache module is unavailable
    def resolve_extract_dir(analysis_json=None, project_dir=None, override_dir=None):
        if override_dir:
            return Path(override_dir)
        if project_dir:
            return Path(project_dir) / "datasheets" / "extracted"
        return Path("/tmp/kicad-happy/datasheets/extracted")

    def get_cached_extraction(extract_dir, mpn):
        return None

    def list_extractions(extract_dir):
        return []


# ---------------------------------------------------------------------------
# Value parsing helpers
# ---------------------------------------------------------------------------

_SI_PREFIXES = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "\u00b5": 1e-6,
    "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
}


def _parse_cap_value(text: str) -> float | None:
    """Parse a capacitance string like '10uF', '100nF', '4.7 uF' to farads.

    Returns None if unparseable.
    """
    if not text:
        return None
    # Normalize: strip common suffixes, rejoin space-separated units
    s = text.strip()
    s = re.sub(r'\s*(ceramic|x[57]r|x7s|x8r|c0g|np0)\b.*', '', s, flags=re.I)
    s = re.sub(r'\s*x\s*\d+$', '', s)  # strip "x2", "x3" multiplier
    parts = s.split()
    if len(parts) >= 2 and parts[1] and parts[1][0].lower() in "pnuµ":
        s = parts[0] + parts[1]
    else:
        s = parts[0] if parts else ""
    s = s.rstrip("Ff")
    if not s:
        return None
    # Trailing SI prefix
    if s[-1] in _SI_PREFIXES:
        mult = _SI_PREFIXES[s[-1]]
        try:
            return float(s[:-1]) * mult
        except ValueError:
            return None
    # Embedded prefix: "4u7" -> 4.7e-6
    for ch, mult in _SI_PREFIXES.items():
        if ch in s and not s.endswith(ch):
            idx = s.index(ch)
            before, after = s[:idx], s[idx + 1:]
            if before.replace(".", "").isdigit() and after.isdigit():
                try:
                    return float(f"{before}.{after}") * mult
                except ValueError:
                    pass
    # Bare number — assume farads (caller should know context)
    try:
        return float(s)
    except ValueError:
        return None


def _parse_inductance(text: str) -> float | None:
    """Parse an inductance string like '10uH', '1uH' to henries."""
    if not text:
        return None
    s = text.strip()
    # Strip current rating and other suffixes
    s = re.sub(r',.*', '', s)
    s = re.sub(r'\s+Isat.*', '', s, flags=re.I)
    parts = s.split()
    if len(parts) >= 2 and parts[1] and parts[1][0].lower() in "pnuµm":
        s = parts[0] + parts[1]
    else:
        s = parts[0] if parts else ""
    s = s.rstrip("Hh")
    if not s:
        return None
    if s[-1] in _SI_PREFIXES:
        mult = _SI_PREFIXES[s[-1]]
        try:
            return float(s[:-1]) * mult
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _cap_multiplier(text: str) -> int:
    """Extract a 'xN' multiplier from a recommendation string like '47uF x2'."""
    m = re.search(r'x\s*(\d+)', text, re.I)
    return int(m.group(1)) if m else 1


def _format_farads(f: float) -> str:
    """Format farads as a human-readable string."""
    if f >= 1e-3:
        return f"{f * 1e3:.0f}mF"
    if f >= 1e-6:
        v = f * 1e6
        return f"{v:.1f}\u00b5F" if v != int(v) else f"{int(v)}\u00b5F"
    if f >= 1e-9:
        v = f * 1e9
        return f"{v:.1f}nF" if v != int(v) else f"{int(v)}nF"
    v = f * 1e12
    return f"{v:.1f}pF" if v != int(v) else f"{int(v)}pF"


def _format_henries(h: float) -> str:
    """Format henries as a human-readable string."""
    if h >= 1e-3:
        v = h * 1e3
        return f"{v:.1f}mH" if v != int(v) else f"{int(v)}mH"
    if h >= 1e-6:
        v = h * 1e6
        return f"{v:.1f}\u00b5H" if v != int(v) else f"{int(v)}\u00b5H"
    v = h * 1e9
    return f"{v:.1f}nH" if v != int(v) else f"{int(v)}nH"


# ---------------------------------------------------------------------------
# 1. load_project_extractions
# ---------------------------------------------------------------------------

def load_project_extractions(project_dir: str,
                             analysis: dict) -> dict[str, dict]:
    """Load datasheet extractions for components in the analysis.

    Args:
        project_dir: KiCad project directory (contains datasheets/extracted/)
        analysis: loaded schematic analysis JSON

    Returns:
        dict mapping MPN -> extraction dict. Only includes MPNs that
        have cached extractions.
    """
    extract_dir = resolve_extract_dir(project_dir=project_dir)

    # Collect unique MPNs from all components
    mpns: set[str] = set()
    for comp in analysis.get("components", []):
        for key in ("mpn", "mfg_part", "MPN"):
            val = comp.get(key, "")
            if val and isinstance(val, str) and val.strip():
                mpns.add(val.strip())
                break
        # Also check properties dict if present
        props = comp.get("properties", {})
        if isinstance(props, dict):
            for key in ("MPN", "mpn", "Mfg Part", "mfg_part", "Part Number"):
                val = props.get(key, "")
                if val and isinstance(val, str) and val.strip():
                    mpns.add(val.strip())
                    break

    # Load cached extractions
    result: dict[str, dict] = {}
    for mpn in mpns:
        extraction = get_cached_extraction(extract_dir, mpn)
        if extraction is not None:
            result[mpn] = extraction

    return result


# ---------------------------------------------------------------------------
# 2. build_component_comparison
# ---------------------------------------------------------------------------

def _find_caps_on_net(analysis: dict, net_name: str) -> list[dict]:
    """Find all capacitors connected to a given net in the analysis.

    Returns list of dicts with 'ref', 'value', 'farads'.
    """
    caps = []
    if not net_name:
        return caps
    nets = analysis.get("nets", {})
    net_info = nets.get(net_name)
    if not net_info:
        return caps
    comp_lookup = {}
    for c in analysis.get("components", []):
        comp_lookup[c["reference"]] = c
    for pin in net_info.get("pins", []):
        comp = comp_lookup.get(pin["component"])
        if comp and comp.get("type") == "capacitor":
            val = comp.get("value", "")
            farads = _parse_cap_value(val)
            caps.append({
                "ref": pin["component"],
                "value": val,
                "farads": farads,
            })
    return caps


def _find_inductor_for_regulator(analysis: dict, reg: dict) -> dict | None:
    """Find the inductor associated with a power regulator."""
    ind_ref = reg.get("inductor")
    if not ind_ref:
        return None
    for comp in analysis.get("components", []):
        if comp["reference"] == ind_ref:
            val = comp.get("value", "")
            henries = _parse_inductance(val)
            return {"ref": ind_ref, "value": val, "henries": henries}
    return None


def _compare_capacitance(actual_farads: float | None,
                         recommended_text: str) -> tuple[str, str]:
    """Compare actual capacitance against a recommendation string.

    Returns (status, note).
    """
    rec_farads = _parse_cap_value(recommended_text)
    rec_count = _cap_multiplier(recommended_text)
    if rec_farads is not None:
        rec_total = rec_farads * rec_count
    else:
        rec_total = None

    if actual_farads is None:
        return "missing", "No capacitor found on this net"

    if rec_total is None:
        # Can't parse recommendation — assume ok if something is present
        return "ok", "Capacitor present (could not parse recommendation)"

    ratio = actual_farads / rec_total if rec_total > 0 else 0
    if ratio >= 0.9:
        return "ok", ""
    elif ratio >= 0.4:
        return "warning", f"Below recommended ({_format_farads(actual_farads)} vs {_format_farads(rec_total)})"
    else:
        return "mismatch", f"Significantly below ({_format_farads(actual_farads)} vs {_format_farads(rec_total)})"


def _compare_inductance(actual_henries: float | None,
                        recommended_text: str) -> tuple[str, str]:
    """Compare actual inductance against a recommendation string.

    Returns (status, note).
    """
    rec_henries = _parse_inductance(recommended_text)

    if actual_henries is None:
        return "missing", "No inductor found"

    if rec_henries is None:
        return "ok", "Inductor present (could not parse recommendation)"

    ratio = actual_henries / rec_henries if rec_henries > 0 else 0
    # Inductors can vary widely; 0.5x-3x is generally acceptable
    if 0.5 <= ratio <= 3.0:
        return "ok", ""
    elif 0.2 <= ratio < 0.5 or 3.0 < ratio <= 5.0:
        return "warning", f"Outside typical range ({_format_henries(actual_henries)} vs {_format_henries(rec_henries)} recommended)"
    else:
        return "mismatch", f"Significantly different ({_format_henries(actual_henries)} vs {_format_henries(rec_henries)} recommended)"


def build_component_comparison(analysis: dict,
                               extractions: dict) -> list[dict]:
    """Compare actual components vs datasheet recommendations.

    For each IC with an extraction, check:
    - Input cap: does the schematic have the recommended input capacitance?
    - Output cap: does the schematic have the recommended output capacitance?
    - Inductor: is the inductor value within the recommended range?
    - Feedback resistors: do they produce the correct Vout given Vref?

    Returns list of comparison dicts:
    {
        'ref': 'U1',
        'mpn': 'TPS54360',
        'parameter': 'Input Capacitor',
        'recommended': '10uF ceramic',
        'actual': 'C1: 4.7uF',
        'status': 'warning',  # ok | warning | mismatch | missing
        'note': 'Below recommended value'
    }
    """
    comparisons: list[dict] = []
    regulators = [f for f in analysis.get("findings", [])
                  if f.get("detector") == "detect_power_regulators"]

    # Build ref -> regulator lookup
    reg_by_ref: dict[str, dict] = {}
    for reg in regulators:
        reg_by_ref[reg.get("ref", "")] = reg

    # Build ref -> MPN lookup from components
    ref_to_mpn: dict[str, str] = {}
    for comp in analysis.get("components", []):
        for key in ("mpn", "mfg_part", "MPN"):
            val = comp.get(key, "")
            if val and isinstance(val, str) and val.strip():
                ref_to_mpn[comp["reference"]] = val.strip()
                break

    # For each regulator with an extraction
    for reg in regulators:
        ref = reg.get("ref", "")
        mpn = ref_to_mpn.get(ref, "")
        extraction = extractions.get(mpn)
        if not extraction:
            continue

        app = extraction.get("application_circuit")
        if not app:
            continue

        # --- Input capacitor check ---
        input_cap_rec = app.get("input_cap_recommended")
        if input_cap_rec:
            input_rail = reg.get("input_rail")
            input_caps = _find_caps_on_net(analysis, input_rail)
            total_farads = sum(c["farads"] for c in input_caps if c["farads"])
            if input_caps:
                actual_str = ", ".join(
                    f"{c['ref']}: {c['value']}" for c in input_caps)
            else:
                actual_str = "—"
                total_farads = None

            status, note = _compare_capacitance(total_farads, input_cap_rec)
            comparisons.append({
                "ref": ref,
                "mpn": mpn,
                "parameter": "Input Capacitor",
                "recommended": input_cap_rec,
                "actual": actual_str,
                "status": status,
                "note": note,
            })

        # --- Output capacitor check ---
        output_cap_rec = app.get("output_cap_recommended")
        if output_cap_rec:
            output_rail = reg.get("output_rail")
            output_caps = _find_caps_on_net(analysis, output_rail)
            total_farads = sum(c["farads"] for c in output_caps if c["farads"])
            if output_caps:
                actual_str = ", ".join(
                    f"{c['ref']}: {c['value']}" for c in output_caps)
            else:
                actual_str = "—"
                total_farads = None

            status, note = _compare_capacitance(total_farads, output_cap_rec)
            comparisons.append({
                "ref": ref,
                "mpn": mpn,
                "parameter": "Output Capacitor",
                "recommended": output_cap_rec,
                "actual": actual_str,
                "status": status,
                "note": note,
            })

        # --- Inductor check ---
        ind_rec = app.get("inductor_recommended")
        if ind_rec:
            inductor = _find_inductor_for_regulator(analysis, reg)
            if inductor:
                actual_str = f"{inductor['ref']}: {inductor['value']}"
                actual_henries = inductor.get("henries")
            else:
                actual_str = "—"
                actual_henries = None

            status, note = _compare_inductance(actual_henries, ind_rec)
            comparisons.append({
                "ref": ref,
                "mpn": mpn,
                "parameter": "Inductor",
                "recommended": ind_rec,
                "actual": actual_str,
                "status": status,
                "note": note,
            })

        # --- Feedback resistor / Vout check ---
        vout_formula = app.get("vout_formula")
        e_chars = extraction.get("electrical_characteristics", {})
        vref = e_chars.get("vref_v")
        if vref and reg.get("estimated_vout") and reg.get("feedback_divider"):
            fb = reg["feedback_divider"]
            r_top = fb.get("r_top", {})
            r_bottom = fb.get("r_bottom", {})
            actual_str = (
                f"R_top={r_top.get('ref', '?')} ({r_top.get('value', '?')}), "
                f"R_bot={r_bottom.get('ref', '?')} ({r_bottom.get('value', '?')})"
            )
            est_vout = reg["estimated_vout"]
            rec_str = f"Vref={vref}V"
            if vout_formula:
                rec_str += f", {vout_formula}"

            # Check if output voltage is reasonable
            rec_vout = extraction.get("recommended_operating_conditions", {})
            vout_max = rec_vout.get("vout_max_v")
            vout_min = rec_vout.get("vout_min_v")

            if vout_max and est_vout > vout_max * 1.05:
                status = "mismatch"
                note = f"Estimated Vout ({est_vout:.2f}V) exceeds max ({vout_max}V)"
            elif vout_min and est_vout < vout_min * 0.95:
                status = "warning"
                note = f"Estimated Vout ({est_vout:.2f}V) below min ({vout_min}V)"
            else:
                status = "ok"
                note = f"Estimated Vout = {est_vout:.2f}V"

            comparisons.append({
                "ref": ref,
                "mpn": mpn,
                "parameter": "Feedback / Vout",
                "recommended": rec_str,
                "actual": actual_str,
                "status": status,
                "note": note,
            })

    return comparisons


# ---------------------------------------------------------------------------
# 3. build_pin_audit
# ---------------------------------------------------------------------------

def _find_connected_components(analysis: dict, ic_ref: str,
                               pin_number: str) -> list[dict]:
    """Find components connected to a specific IC pin.

    Returns list of dicts with 'ref', 'value', 'type'.
    """
    result = []
    ic_analysis = analysis.get("ic_pin_analysis", [])
    for ic in ic_analysis:
        if ic.get("reference") != ic_ref:
            continue
        for pin in ic.get("pins", []):
            if str(pin.get("pin_number")) != str(pin_number):
                continue
            # Parse connected_to list
            for conn in pin.get("connected_to", []):
                if isinstance(conn, dict):
                    result.append({
                        "ref": conn.get("ref", conn.get("component", "")),
                        "value": conn.get("value", ""),
                        "type": conn.get("type", ""),
                    })
                elif isinstance(conn, str):
                    # Format: "R1 (10K)" or just "R1"
                    m = re.match(r'(\S+)\s*\(([^)]*)\)', conn)
                    if m:
                        result.append({"ref": m.group(1), "value": m.group(2), "type": ""})
                    else:
                        result.append({"ref": conn.strip(), "value": "", "type": ""})
            break
        break
    return result


def _get_pin_net(analysis: dict, ic_ref: str, pin_number: str) -> str | None:
    """Get the net name connected to a specific IC pin."""
    ic_analysis = analysis.get("ic_pin_analysis", [])
    for ic in ic_analysis:
        if ic.get("reference") != ic_ref:
            continue
        for pin in ic.get("pins", []):
            if str(pin.get("pin_number")) != str(pin_number):
                continue
            net = pin.get("net", "")
            if net and net not in ("UNCONNECTED", "NO_CONNECT"):
                return net
            return None
        break
    return None


def _fuzzy_match_requirement(required_text: str,
                             connected: list[dict],
                             net_name: str | None) -> tuple[str, str]:
    """Fuzzy-match a required_external description against actual connections.

    Returns (status, summary_string).
    """
    req_lower = required_text.lower()

    # Handle "no connect" / "do not connect" requirements
    nc_keywords = ("no connect", "do not connect", "nc pin", "leave open",
                   "leave floating")
    if any(kw in req_lower for kw in nc_keywords):
        if not connected and (net_name is None or net_name == ""):
            return "nc_ok", "Not connected (correct)"
        elif connected:
            names = ", ".join(c["ref"] for c in connected if c["ref"])
            return "warning", f"Connected to {names} but datasheet says NC"
        return "nc_ok", "Not connected (correct)"

    # Handle "do not float" — pin must be connected to something
    if "do not float" in req_lower or "must not float" in req_lower:
        if connected or net_name:
            summary = ", ".join(
                f"{c['ref']} ({c['value']})" if c.get("value") else c['ref']
                for c in connected
            ) if connected else (net_name or "")
            return "ok", summary
        return "missing", "Pin is floating but datasheet says do not float"

    # Build summary of what's connected
    summary_parts = []
    for c in connected:
        if c.get("value"):
            summary_parts.append(f"{c['ref']} ({c['value']})")
        elif c.get("ref"):
            summary_parts.append(c['ref'])
    if not summary_parts and net_name:
        summary_parts.append(net_name)
    summary = ", ".join(summary_parts)

    # Check for ground connection requirements first — a GND pin with
    # "connect to ground plane" is satisfied by the net being GND even
    # when no discrete components appear in connected_to.
    ground_nets = ("GND", "VSS", "AGND", "DGND", "PGND")
    if "ground" in req_lower or "gnd" in req_lower or "vss" in req_lower:
        if net_name and net_name.upper() in ground_nets:
            return "ok", net_name
        if connected:
            return "ok", summary
        return "missing", f"Requires ground connection: {required_text}"

    # Check for power connection requirements
    power_kw = ("vcc", "vdd", "power", "supply", "vin", "vbus")
    if any(kw in req_lower for kw in power_kw):
        if net_name and any(kw in net_name.upper() for kw in
                           ("VCC", "VDD", "+3", "+5", "+12", "VBUS", "VIN")):
            return "ok", net_name
        if connected:
            return "ok", summary
        return "missing", f"Requires power connection: {required_text}"

    # Nothing connected and not a ground/power pin — missing
    if not connected and not net_name:
        return "missing", "Not connected"

    # Check for capacitor requirements
    cap_match = re.search(r'(\d+(?:\.\d+)?)\s*([pnuµ])[Ff]?', req_lower)
    if cap_match or "cap" in req_lower or "bypass" in req_lower or "decouple" in req_lower:
        has_cap = any(c.get("ref", "").startswith("C") or
                      c.get("type", "") == "capacitor"
                      for c in connected)
        if has_cap:
            return "ok", summary
        return "missing", f"Requires capacitor: {required_text}"

    # Check for resistor requirements (pull-up, pull-down, series)
    res_match = re.search(r'(\d+(?:\.\d+)?)\s*([kKMR])\s*(pull|resistor|ohm)', req_lower)
    if res_match or "pull-up" in req_lower or "pull-down" in req_lower or "pullup" in req_lower:
        has_res = any(c.get("ref", "").startswith("R") or
                      c.get("type", "") == "resistor"
                      for c in connected)
        if has_res:
            return "ok", summary
        return "missing", f"Requires resistor: {required_text}"

    # Check for inductor requirements
    if "inductor" in req_lower or "coil" in req_lower or "ferrite" in req_lower:
        has_ind = any(c.get("ref", "").startswith(("L", "FB")) or
                      c.get("type", "") in ("inductor", "ferrite_bead")
                      for c in connected)
        if has_ind:
            return "ok", summary
        return "missing", f"Requires inductor: {required_text}"

    # Generic: if something is connected, assume ok
    if connected or net_name:
        return "ok", summary

    return "missing", f"Not connected — {required_text}"


def build_pin_audit(analysis: dict,
                    extractions: dict) -> list[dict]:
    """Audit pin connections against datasheet requirements.

    For each IC pin with 'required_external' in the extraction,
    check if the schematic has the required connection.

    Returns list of audit entries:
    {
        'ref': 'U1',
        'mpn': 'TPS54360',
        'pin_number': '1',
        'pin_name': 'BOOT',
        'required': '100nF bootstrap cap to SW pin',
        'connected_to': 'C5 (100nF)',
        'status': 'ok',  # ok | warning | missing | nc_ok
    }
    """
    audits: list[dict] = []

    # Build ref -> MPN lookup
    ref_to_mpn: dict[str, str] = {}
    for comp in analysis.get("components", []):
        for key in ("mpn", "mfg_part", "MPN"):
            val = comp.get(key, "")
            if val and isinstance(val, str) and val.strip():
                ref_to_mpn[comp["reference"]] = val.strip()
                break

    # Build ic_ref set from ic_pin_analysis
    ic_refs: dict[str, dict] = {}
    for ic in analysis.get("ic_pin_analysis", []):
        ic_refs[ic.get("reference", "")] = ic

    for ref, mpn in ref_to_mpn.items():
        extraction = extractions.get(mpn)
        if not extraction:
            continue

        pins = extraction.get("pins", [])
        if not pins:
            continue

        for ext_pin in pins:
            required = ext_pin.get("required_external")
            if not required:
                continue

            pin_number = str(ext_pin.get("number", ""))
            pin_name = ext_pin.get("name", "")

            # Find what's connected to this pin in the schematic
            connected = _find_connected_components(analysis, ref, pin_number)
            net_name = _get_pin_net(analysis, ref, pin_number)

            status, connected_summary = _fuzzy_match_requirement(
                required, connected, net_name)

            audits.append({
                "ref": ref,
                "mpn": mpn,
                "pin_number": pin_number,
                "pin_name": pin_name,
                "required": required,
                "connected_to": connected_summary,
                "status": status,
            })

    return audits


# ---------------------------------------------------------------------------
# 4. build_spec_summary
# ---------------------------------------------------------------------------

_CATEGORY_SPEC_KEYS: dict[str, list[tuple[str, str, str]]] = {
    # (json_key, display_label, section) where section is which top-level dict to look in
    "switching_regulator": [
        ("vin_min_v", "Vin Min", "roc"),
        ("vin_max_v", "Vin Max", "roc"),
        ("vref_v", "Vref", "ec"),
        ("switching_frequency_khz", "Freq", "ec"),
        ("quiescent_current_ua", "Iq", "ec"),
        ("output_current_max_ma", "Iout Max", "ec"),
        ("junction_temp_max_c", "Tj Max", "amr"),
    ],
    "linear_regulator": [
        ("vin_min_v", "Vin Min", "roc"),
        ("vin_max_v", "Vin Max", "roc"),
        ("dropout_mv", "Dropout", "ec"),
        ("output_current_max_a", "Iout Max", "ec"),
        ("quiescent_current_ua", "Iq", "ec"),
        ("junction_temp_max_c", "Tj Max", "amr"),
    ],
    "operational_amplifier": [
        ("gbw_hz", "GBW", "ec"),
        ("slew_vus", "Slew Rate", "ec"),
        ("vos_mv", "Vos", "ec"),
        ("aol_db", "Aol", "ec"),
        ("rin_ohms", "Rin", "ec"),
        ("cmrr_db", "CMRR", "ec"),
    ],
    "comparator": [
        ("propagation_delay_ns", "tPD", "ec"),
        ("vos_mv", "Vos", "ec"),
        ("vin_min_v", "Vin Min", "roc"),
        ("vin_max_v", "Vin Max", "roc"),
    ],
    "microcontroller": [
        ("vin_min_v", "Vin Min", "roc"),
        ("vin_max_v", "Vin Max", "roc"),
        ("quiescent_current_ua", "Iq", "ec"),
        ("io_voltage_max", "I/O Max V", "amr"),
        ("junction_temp_max_c", "Tj Max", "amr"),
        ("temp_min_c", "Temp Min", "roc"),
        ("temp_max_c", "Temp Max", "roc"),
    ],
    "esd_protection": [
        ("clamping_voltage_v", "Vclamp", "ec"),
        ("capacitance_pf", "Cpara", "ec"),
        ("esd_hbm_v", "ESD HBM", "amr"),
        ("esd_cdm_v", "ESD CDM", "amr"),
    ],
    "voltage_reference": [
        ("vref_v", "Vref", "ec"),
        ("vref_accuracy_pct", "Accuracy", "ec"),
        ("temp_coeff_ppm_c", "TC", "ec"),
    ],
}

# Default spec keys for unknown categories
_DEFAULT_SPEC_KEYS: list[tuple[str, str, str]] = [
    ("vin_min_v", "Vin Min", "roc"),
    ("vin_max_v", "Vin Max", "roc"),
    ("junction_temp_max_c", "Tj Max", "amr"),
    ("temp_min_c", "Temp Min", "roc"),
    ("temp_max_c", "Temp Max", "roc"),
]


def _format_spec_value(key: str, value) -> str:
    """Format a spec value for display based on its key name."""
    if value is None:
        return "\u2014"
    if "temp" in key or key.endswith("_c"):
        return f"{value}\u00b0C"
    if key.endswith("_v") or key == "io_voltage_max":
        return f"{value}V"
    if key.endswith("_mv"):
        return f"{value}mV"
    if key.endswith("_ma"):
        return f"{value}mA"
    if key.endswith("_a") and not key.endswith("_ua"):
        return f"{value}A"
    if key.endswith("_ua"):
        return f"{value}\u00b5A"
    if key.endswith("_khz"):
        return f"{value}kHz"
    if key.endswith("_hz"):
        if value >= 1e6:
            return f"{value / 1e6:.1f}MHz"
        if value >= 1e3:
            return f"{value / 1e3:.1f}kHz"
        return f"{value}Hz"
    if key.endswith("_db"):
        return f"{value}dB"
    if key.endswith("_pct"):
        return f"\u00b1{value}%"
    if key.endswith("_ohms"):
        if value >= 1e6:
            return f"{value / 1e6:.1f}M\u03a9"
        if value >= 1e3:
            return f"{value / 1e3:.1f}k\u03a9"
        return f"{value}\u03a9"
    if key.endswith("_pf"):
        return f"{value}pF"
    if key.endswith("_ppm_c"):
        return f"{value}ppm/\u00b0C"
    if key.endswith("_vus"):
        return f"{value}V/\u00b5s"
    if key.endswith("_ns"):
        return f"{value}ns"
    return str(value)


def build_spec_summary(extractions: dict) -> list[dict]:
    """Build key spec summary table for extracted components.

    Returns list of spec entries:
    {
        'mpn': 'TPS54360',
        'manufacturer': 'Texas Instruments',
        'category': 'switching_regulator',
        'key_specs': {
            'Vin Range': '3.5V \u2014 60V',
            'Vref': '0.8V',
            'Freq': '600 kHz',
            'Iq': '150 \u00b5A',
            'Tj Max': '150\u00b0C',
        }
    }
    """
    specs: list[dict] = []

    for mpn, extraction in sorted(extractions.items()):
        category = extraction.get("category", "")
        ec = extraction.get("electrical_characteristics", {}) or {}
        roc = extraction.get("recommended_operating_conditions", {}) or {}
        amr = extraction.get("absolute_maximum_ratings", {}) or {}

        section_map = {"ec": ec, "roc": roc, "amr": amr}

        spec_keys = _CATEGORY_SPEC_KEYS.get(category, _DEFAULT_SPEC_KEYS)

        key_specs: dict[str, str] = {}

        # Check for Vin range (combine min/max into one entry)
        vin_min = roc.get("vin_min_v")
        vin_max = roc.get("vin_max_v")
        if vin_min is not None and vin_max is not None:
            key_specs["Vin Range"] = f"{vin_min}V \u2014 {vin_max}V"
            # Skip individual vin_min_v/vin_max_v entries
            skip_keys = {"vin_min_v", "vin_max_v"}
        else:
            skip_keys = set()

        # Check for temp range (combine min/max)
        temp_min = roc.get("temp_min_c")
        temp_max = roc.get("temp_max_c")
        if temp_min is not None and temp_max is not None:
            key_specs["Temp Range"] = f"{temp_min}\u00b0C \u2014 {temp_max}\u00b0C"
            skip_keys |= {"temp_min_c", "temp_max_c"}

        for json_key, label, section in spec_keys:
            if json_key in skip_keys:
                continue
            source = section_map.get(section, {})
            value = source.get(json_key)
            if value is not None:
                key_specs[label] = _format_spec_value(json_key, value)

        specs.append({
            "mpn": mpn,
            "manufacturer": extraction.get("manufacturer", ""),
            "category": category,
            "key_specs": key_specs,
        })

    return specs


# ---------------------------------------------------------------------------
# 5. format_comparison_markdown
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "ok": "\u2705",
    "warning": "\u26a0\ufe0f",
    "mismatch": "\u274c",
    "missing": "\u2753",
    "nc_ok": "\u2705",
}


def format_comparison_markdown(comparisons: list[dict]) -> str:
    """Format comparison results as a markdown table for embedding in reports."""
    if not comparisons:
        return "*No datasheet comparisons available.*"

    lines = [
        "| Ref | MPN | Parameter | Recommended | Actual | Status | Note |",
        "|-----|-----|-----------|-------------|--------|--------|------|",
    ]

    for c in comparisons:
        icon = _STATUS_ICONS.get(c["status"], "")
        lines.append(
            f"| {c['ref']} "
            f"| {c['mpn']} "
            f"| {c['parameter']} "
            f"| {c['recommended']} "
            f"| {c['actual']} "
            f"| {icon} {c['status']} "
            f"| {c['note']} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. format_pin_audit_markdown
# ---------------------------------------------------------------------------

def format_pin_audit_markdown(audits: list[dict]) -> str:
    """Format pin audit results as a markdown table."""
    if not audits:
        return "*No pin audit data available.*"

    lines = [
        "| Ref | MPN | Pin | Name | Required | Connected To | Status |",
        "|-----|-----|-----|------|----------|--------------|--------|",
    ]

    for a in audits:
        icon = _STATUS_ICONS.get(a["status"], "")
        lines.append(
            f"| {a['ref']} "
            f"| {a['mpn']} "
            f"| {a['pin_number']} "
            f"| {a['pin_name']} "
            f"| {a['required']} "
            f"| {a['connected_to']} "
            f"| {icon} {a['status']} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. format_spec_summary_markdown
# ---------------------------------------------------------------------------

def format_spec_summary_markdown(specs: list[dict]) -> str:
    """Format spec summary as a markdown table."""
    if not specs:
        return "*No datasheet extractions available.*"

    # Collect all unique spec labels across all entries
    all_labels: list[str] = []
    seen: set[str] = set()
    for s in specs:
        for label in s.get("key_specs", {}):
            if label not in seen:
                all_labels.append(label)
                seen.add(label)

    headers = ["MPN", "Manufacturer", "Category"] + all_labels
    sep = "|" + "|".join("---" for _ in headers) + "|"
    header_line = "| " + " | ".join(headers) + " |"

    lines = [header_line, sep]
    for s in specs:
        row = [
            s.get("mpn", ""),
            s.get("manufacturer", ""),
            s.get("category", "").replace("_", " "),
        ]
        for label in all_labels:
            row.append(s.get("key_specs", {}).get(label, "\u2014"))
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Datasheet integration for kidoc reports")
    parser.add_argument("--project-dir", required=True,
                        help="KiCad project directory")
    parser.add_argument("--analysis", required=True,
                        help="Path to schematic analysis JSON")
    parser.add_argument("--output", default=None,
                        help="Output markdown file (optional)")
    args = parser.parse_args()

    # Load analysis
    with open(args.analysis) as f:
        analysis = json.load(f)

    # Load extractions
    extractions = load_project_extractions(args.project_dir, analysis)
    print(f"Found {len(extractions)} datasheet extraction(s)")

    # Build all sections
    comparisons = build_component_comparison(analysis, extractions)
    pin_audits = build_pin_audit(analysis, extractions)
    spec_summary = build_spec_summary(extractions)

    # Format output
    sections = []
    sections.append("## Datasheet Spec Summary\n")
    sections.append(format_spec_summary_markdown(spec_summary))
    sections.append("")

    if comparisons:
        sections.append("## Component vs Datasheet Comparison\n")
        sections.append(format_comparison_markdown(comparisons))
        sections.append("")

    if pin_audits:
        sections.append("## Pin Audit\n")
        sections.append(format_pin_audit_markdown(pin_audits))
        sections.append("")

    # Summary stats
    total_pins = len(pin_audits)
    ok_pins = sum(1 for a in pin_audits if a["status"] in ("ok", "nc_ok"))
    warn_pins = sum(1 for a in pin_audits if a["status"] == "warning")
    missing_pins = sum(1 for a in pin_audits if a["status"] == "missing")
    if total_pins > 0:
        sections.append(f"**Pin audit:** {ok_pins}/{total_pins} OK, "
                        f"{warn_pins} warnings, {missing_pins} missing")
    total_comp = len(comparisons)
    ok_comp = sum(1 for c in comparisons if c["status"] == "ok")
    warn_comp = sum(1 for c in comparisons if c["status"] == "warning")
    mismatch_comp = sum(1 for c in comparisons if c["status"] == "mismatch")
    missing_comp = sum(1 for c in comparisons if c["status"] == "missing")
    if total_comp > 0:
        sections.append(f"**Component comparison:** {ok_comp}/{total_comp} OK, "
                        f"{warn_comp} warnings, {mismatch_comp} mismatches, "
                        f"{missing_comp} missing")

    output_text = "\n".join(sections)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"Written to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()

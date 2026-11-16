#!/usr/bin/env python3
"""Schematic-to-PCB cross-verification.

Correlates schematic design intent with PCB physical implementation.
Detects component mismatches, differential pair length issues, power
trace width concerns, decoupling placement gaps, bus routing skew,
and thermal via adequacy.

Usage:
    python3 cross_verify.py --schematic sch.json --pcb pcb.json
    python3 cross_verify.py --schematic sch.json --pcb pcb.json --thermal thermal.json
    python3 cross_verify.py --schematic sch.json --pcb pcb.json --output report.json

Zero external dependencies — Python 3.10+ stdlib only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kicad_core.fileio import atomic_write_text, json_load  # noqa: E402
from kicad_core.pairing import pair_by_path  # noqa: E402


def cross_verify(sch: dict, pcb: dict,
                 thermal: dict | None = None) -> dict:
    """Run all cross-verification checks.

    Args:
        sch: Schematic analysis JSON (from analyze_schematic.py).
        pcb: PCB analysis JSON (from analyze_pcb.py).
        thermal: Optional thermal analysis JSON (from analyze_thermal.py).

    Returns:
        Structured report with per-check results and summary.
    """
    result = {
        "cross_verify_version": 1,
        "schematic_file": sch.get("file", ""),
        "pcb_file": pcb.get("file", ""),
    }

    checks_run = 0
    status_counts = {"pass": 0, "warning": 0, "fail": 0, "info": 0}

    # Check 1: Component reference matching
    comp_match = check_component_matching(sch, pcb)
    result["component_matching"] = comp_match
    checks_run += 1

    # Check 2: Differential pair length matching
    diff_pairs = check_diff_pair_routing(sch, pcb)
    if diff_pairs:
        result["diff_pair_routing"] = diff_pairs
        checks_run += 1

    # Check 3: Power trace width assessment
    power_traces = check_power_traces(sch, pcb)
    if power_traces:
        result["power_trace_analysis"] = power_traces
        checks_run += 1

    # Check 4: Decoupling cap placement
    decoupling = check_decoupling_placement(sch, pcb)
    if decoupling:
        result["decoupling_placement"] = decoupling
        checks_run += 1

    # Check 5: Bus routing advisory
    bus_routing = check_bus_routing(sch, pcb)
    if bus_routing:
        result["bus_routing"] = bus_routing
        checks_run += 1

    # Check 6: Thermal via adequacy
    if thermal:
        thermal_vias = check_thermal_vias(thermal, pcb)
        if thermal_vias:
            result["thermal_via_check"] = thermal_vias
            checks_run += 1

    # Count statuses across all checks
    for section in result.values():
        if isinstance(section, list):
            for item in section:
                if isinstance(item, dict) and "status" in item:
                    status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
        elif isinstance(section, dict):
            for item in section.values():
                if isinstance(item, list):
                    for entry in item:
                        if isinstance(entry, dict) and "status" in entry:
                            status_counts[entry["status"]] = status_counts.get(entry["status"], 0) + 1

    result["summary"] = {
        "total_checks": checks_run,
        **status_counts,
    }

    return result


def check_component_matching(sch: dict, pcb: dict) -> dict:
    """Check 1: Bidirectional component reference matching.

    Pairs footprints with schematic parts by schematic path, as KiCad's Update PCB does
    (kicad_core.pairing.pair_by_path). Detects orphans, missing components, value
    mismatches, references that differ between the paired parts, and DNP conflicts.
    Like KiCad's schematic parity check, board-only footprints are not orphans, parts
    excluded from the board are not missing, and DNP is compared with the footprint's
    DNP attribute.
    """
    # Build schematic ref lookup (exclude power symbols and flags)
    sch_comps = {}
    dnp_refs = set()
    on_board_refs = set()
    for c in sch.get("components", []):
        ref = c.get("reference", "")
        if not ref or ref.startswith("#"):
            continue
        sch_comps[ref] = {
            "value": c.get("value", ""),
            "type": c.get("type", ""),
            "footprint": c.get("footprint", ""),
        }
        if c.get("dnp"):
            dnp_refs.add(ref)
        if c.get("on_board") is not False:
            on_board_refs.add(ref)

    pairs, sch_only, pcb_only = pair_by_path(sch, pcb)
    pcb_by_ref = {}
    for fp in pcb.get("footprints", []):
        ref = fp.get("reference", "")
        if ref and not ref.startswith("#"):
            pcb_by_ref[ref] = fp
    matched = {}
    for ref, fp in pairs:
        matched[ref] = fp
    paired_ids = {id(fp) for _, fp in pairs}
    placed_unpaired = {fp.get("reference", "") for fp in pcb.get("footprints", [])
                       if id(fp) not in paired_ids and not fp.get("board_only")}

    orphans = []  # in PCB but not schematic
    missing = []  # in schematic but not PCB
    value_mismatches = []
    reference_mismatches = []
    dnp_conflicts = []

    # Orphans: in PCB but not in schematic
    for ref in sorted(pcb_only):
        if ref not in placed_unpaired:
            continue  # board-only footprints (logos, graphics) have no symbol
        orphans.append({
            "ref": ref,
            "pcb_value": pcb_by_ref[ref].get("value", ""),
            "status": "fail",
            "message": (f"{ref} in PCB is not linked to a schematic symbol (the reference is used by another symbol)"
                        if ref in sch_comps else f"{ref} in PCB but not in schematic (stale placement?)"),
        })

    # Missing: in schematic but not in PCB
    for ref in sorted(sch_only):
        if ref in dnp_refs:
            continue  # DNP components are expected to be absent from PCB
        if ref not in on_board_refs:
            continue  # excluded from the board, so not in the board netlist
        sc = sch_comps[ref]
        missing.append({
            "ref": ref,
            "sch_value": sc["value"],
            "sch_type": sc["type"],
            "status": "fail",
            "message": f"{ref} ({sc['value']}) in schematic but not placed in PCB",
        })

    # Value mismatches on matched refs
    for ref in sorted(matched):
        sv = sch_comps[ref]["value"]
        pv = matched[ref].get("value", "")
        if sv and pv and sv.lower() != pv.lower():
            value_mismatches.append({
                "ref": ref,
                "sch_value": sv,
                "pcb_value": pv,
                "status": "warning",
                "message": f"{ref}: schematic says '{sv}', PCB says '{pv}'",
            })

    # Paired by path but annotated differently on the PCB
    for ref in sorted(matched):
        pcb_ref = matched[ref].get("reference", "")
        if pcb_ref != ref:
            reference_mismatches.append({
                "ref": ref,
                "pcb_ref": pcb_ref,
                "status": "warning",
                "message": f"{ref} is {pcb_ref} on the PCB (annotation not synchronised)",
            })

    # DNP conflicts: the symbol's DNP differs from the footprint's DNP attribute.
    # Boards before file version 20230410 (KiCad 8) cannot carry the attribute.
    try:
        has_dnp_attr = int(pcb.get("file_version")) >= 20230410
    except (TypeError, ValueError):
        has_dnp_attr = False
    if has_dnp_attr:
        seen = set()
        for ref, fp in pairs:
            sch_dnp, pcb_dnp = ref in dnp_refs, bool(fp.get("dnp"))
            if sch_dnp == pcb_dnp or ref in seen:
                continue
            seen.add(ref)
            dnp_conflicts.append({
                "ref": ref,
                "status": "warning",
                "message": (f"{ref} is DNP in the schematic but not on the PCB footprint" if sch_dnp
                            else f"{ref} footprint is DNP on the PCB but not in the schematic"),
            })

    return {
        "schematic_count": len(sch_comps),
        "pcb_count": len(pcb_by_ref),
        "matched": len(matched),
        "orphans": orphans,
        "missing": missing,
        "value_mismatches": value_mismatches,
        "reference_mismatches": reference_mismatches,
        "dnp_conflicts": dnp_conflicts,
    }


def check_diff_pair_routing(sch: dict, pcb: dict) -> list[dict]:
    """Check 2: Differential pair length matching.

    Matches schematic-detected diff pairs against PCB per-net length data.
    Flags length mismatch, width mismatch, and layer mismatch.
    """
    diff_pairs = sch.get("design_analysis", {}).get("differential_pairs", [])
    if not diff_pairs:
        return []

    # Build net length lookup from PCB
    net_lengths = {}
    for nl in pcb.get("net_lengths", []):
        net_lengths[nl["net"]] = nl

    # Protocol-specific length tolerances (mm)
    _TOLERANCES = {
        "USB": 2.0,
        "Ethernet": 5.0,
        "HDMI": 1.0,
        "LVDS": 1.5,
        "MIPI": 1.5,
        "PCIe": 2.0,
        "SATA": 2.0,
    }

    results = []
    for dp in diff_pairs:
        pos_net = dp.get("positive", "")
        neg_net = dp.get("negative", "")
        protocol = dp.get("type", "differential")
        tolerance = _TOLERANCES.get(protocol, 2.0)

        pos_data = net_lengths.get(pos_net)
        neg_data = net_lengths.get(neg_net)

        entry = {
            "type": protocol,
            "positive": pos_net,
            "negative": neg_net,
            "tolerance_mm": tolerance,
        }

        if not pos_data and not neg_data:
            entry["status"] = "info"
            entry["message"] = f"Neither {pos_net} nor {neg_net} found in PCB routing"
            results.append(entry)
            continue

        if not pos_data or not neg_data:
            missing = pos_net if not pos_data else neg_net
            entry["status"] = "fail"
            entry["message"] = f"Only one net routed — {missing} not found in PCB"
            results.append(entry)
            continue

        pos_len = pos_data.get("total_length_mm", 0)
        neg_len = neg_data.get("total_length_mm", 0)
        delta = abs(pos_len - neg_len)

        entry["pos_length_mm"] = round(pos_len, 2)
        entry["neg_length_mm"] = round(neg_len, 2)
        entry["delta_mm"] = round(delta, 2)

        # Length matching check
        if delta > tolerance:
            entry["status"] = "fail"
            entry["message"] = (f"{protocol} pair {pos_net}/{neg_net}: "
                                f"{delta:.1f}mm length mismatch "
                                f"(tolerance {tolerance}mm)")
        elif delta > tolerance * 0.7:
            entry["status"] = "warning"
            entry["message"] = (f"{protocol} pair: {delta:.1f}mm mismatch "
                                f"approaching {tolerance}mm limit")
        else:
            entry["status"] = "pass"

        # Intra-pair skew: P vs N trace length within same pair
        # (tighter than the inter-pair length tolerance above)
        _intra_pair_tolerance = {
            "USB": 1.0,
            "Ethernet": 2.0,
            "HDMI": 0.5,
            "LVDS": 0.5,
            "MIPI": 0.5,
            "PCIe": 1.0,
            "SATA": 1.0,
        }

        intra_skew = delta  # same as abs(pos_len - neg_len) computed above
        intra_tol = _intra_pair_tolerance.get(protocol, 1.0)
        if intra_skew > intra_tol:
            entry["intra_pair_skew"] = {
                "skew_mm": round(intra_skew, 2),
                "tolerance_mm": intra_tol,
                "severity": "error" if intra_skew > intra_tol * 2 else "warning",
                "detail": (f"Differential pair {pos_net}/{neg_net} intra-pair "
                           f"skew {intra_skew:.1f}mm exceeds {protocol} "
                           f"tolerance ({intra_tol}mm)"),
            }
            # Upgrade entry status if the skew check is more severe
            if entry["status"] == "pass":
                entry["status"] = "warning"
                entry["message"] = (f"{protocol} pair {pos_net}/{neg_net}: "
                                    f"intra-pair skew {intra_skew:.1f}mm "
                                    f"exceeds {intra_tol}mm tolerance")
            elif (entry["status"] == "warning"
                  and intra_skew > intra_tol * 2):
                entry["status"] = "fail"

        # Layer check
        pos_layers = set(pos_data.get("layers", {}).keys())
        neg_layers = set(neg_data.get("layers", {}).keys())
        if pos_layers and neg_layers and pos_layers != neg_layers:
            entry["layer_mismatch"] = {
                "positive_layers": sorted(pos_layers),
                "negative_layers": sorted(neg_layers),
            }
            if entry["status"] == "pass":
                entry["status"] = "warning"
                entry["message"] = (f"{protocol} pair routes on different layers: "
                                    f"{sorted(pos_layers)} vs {sorted(neg_layers)}")

        results.append(entry)

    return results


def check_power_traces(sch: dict, pcb: dict) -> list[dict]:
    """Check 3: Power trace width assessment.

    Matches regulator output rails against PCB power net routing data.
    Surfaces trace widths and total lengths for reviewer assessment.
    """
    regulators = [f for f in sch.get("findings", [])
                  if f.get("detector") == "detect_power_regulators"]
    if not regulators:
        return []

    # Build power routing lookup from PCB
    power_routing = {}
    for pr in pcb.get("power_net_routing", []):
        power_routing[pr["net"]] = pr

    results = []
    for reg in regulators:
        rail = reg.get("output_rail")
        if not rail:
            continue

        entry = {
            "regulator_ref": reg.get("ref", ""),
            "output_rail": rail,
            "topology": reg.get("topology", "unknown"),
            "estimated_vout": reg.get("estimated_vout"),
        }

        pr = power_routing.get(rail)
        if not pr:
            entry["status"] = "info"
            entry["message"] = f"Output rail {rail} not found in PCB power routing"
            results.append(entry)
            continue

        min_w = pr.get("min_width_mm", 0)
        max_w = pr.get("max_width_mm", 0)
        total_len = pr.get("total_length_mm", 0)

        entry["min_trace_width_mm"] = round(min_w, 3)
        entry["max_trace_width_mm"] = round(max_w, 3)
        entry["total_length_mm"] = round(total_len, 1)
        entry["track_count"] = pr.get("track_count", 0)

        # Switching regulators need wider traces for same current
        # (higher di/dt, transient current demands)
        is_switching = reg.get("topology") in ("switching", "buck", "boost",
                                                "buck-boost", "inverting")
        width_threshold = 0.3 if is_switching else 0.2

        if min_w < width_threshold:
            entry["status"] = "warning"
            topo_note = " (switching — higher current demand)" if is_switching else ""
            entry["message"] = (f"{rail}: minimum trace width {min_w:.2f}mm"
                                f" is narrow for a power rail{topo_note}")
        else:
            entry["status"] = "pass"

        results.append(entry)

    return results


def check_decoupling_placement(sch: dict, pcb: dict) -> list[dict]:
    """Check 4: Decoupling cap placement cross-check.

    Reads each decoupling rail as DA-001 does: the rail's ICs are the fitted ICs with a
    pin on it. Each fitted cap is measured against the nearest of them, by the PCB
    decoupling_placement pad distance where the PCB analysis has one, otherwise by
    footprint centres. Only a pad distance over 5 mm warns; a centre distance cannot show
    which load the cap serves, and a bulk cap (1 uF or more) need not sit at the pins, so
    both are info.
    """
    sch_decoupling = [f for f in sch.get("findings", [])
                      if f.get("detector") == "detect_decoupling"]
    if not sch_decoupling or not isinstance(sch_decoupling, list):
        return []

    # Use PCB's pre-computed decoupling placement if available
    pcb_decoupling = pcb.get("decoupling_placement", [])
    pcb_decoup_lookup = {}
    for entry in pcb_decoupling:
        ic_ref = entry.get("ic", "")
        for cap in entry.get("nearby_caps", []):
            pcb_decoup_lookup[(ic_ref, cap.get("cap", ""))] = cap.get("distance_mm", 999)

    # Build PCB footprint position lookup
    fp_positions = {}
    for fp in pcb.get("footprints", []):
        ref = fp.get("reference", "")
        if ref:
            fp_positions[ref] = (fp.get("x", 0), fp.get("y", 0))

    comps = [c for c in sch.get("components", []) if isinstance(c, dict)]
    unfitted = {c.get("reference", "") for c in comps
                if c.get("dnp") or c.get("on_board") is False}
    ics = [c for c in comps if c.get("type") == "ic"
           and not c.get("dnp") and c.get("on_board") is not False]

    results = []
    for group in sch_decoupling:
        if not isinstance(group, dict):
            continue
        rail = group.get("rail", "")
        caps = group.get("capacitors", [])
        rail_ics = sorted({c.get("reference", "") for c in ics
                           if rail in set((c.get("pin_nets") or {}).values())} - {""})
        if not rail_ics or not caps:
            continue

        for cap in caps:
            if not isinstance(cap, dict):
                continue
            cap_ref = cap.get("ref", "")
            if not cap_ref or cap_ref in unfitted:
                continue

            # The PCB analysis measures pads only for U/IC refs within 10 mm, so a cap next
            # to another fitted IC (a flash or sensor ref) is judged by that IC's centres.
            nearest = None
            for ic in rail_ics:
                d, pads = pcb_decoup_lookup.get((ic, cap_ref)), True
                if d is None and ic in fp_positions and cap_ref in fp_positions:
                    d, pads = math.dist(fp_positions[ic], fp_positions[cap_ref]), False
                if d is not None and (nearest is None or d < nearest[0]):
                    nearest = (d, ic, pads)
            ic_ref = nearest[1] if nearest else rail_ics[0]
            measured = bool(nearest and nearest[2])

            entry = {
                "ic_ref": ic_ref,
                "cap_ref": cap_ref,
                "cap_value": cap.get("value", ""),
            }

            if nearest is not None:
                dist = nearest[0]
                entry["distance_mm"] = round(dist, 2)
                if dist > 5.0 and (cap.get("farads") or 0) >= 1e-6:
                    entry["status"] = "info"
                    entry["message"] = (f"{cap_ref} is {dist:.1f}mm from {ic_ref} "
                                        f"— bulk capacitance, distance is less critical")
                elif dist > 5.0 and not measured:
                    entry["status"] = "info"
                    entry["message"] = (f"{cap_ref} is {dist:.1f}mm from {ic_ref}, "
                                        f"measured between footprint centres")
                elif dist > 5.0:
                    entry["status"] = "warning"
                    entry["message"] = (f"{cap_ref} is {dist:.1f}mm from {ic_ref} "
                                        f"— should be within 5mm for effective decoupling")
                else:
                    entry["status"] = "pass"
            else:
                entry["status"] = "info"
                entry["message"] = f"{cap_ref} or {ic_ref} not found in PCB placement"

            results.append(entry)

    return results


def check_bus_routing(sch: dict, pcb: dict) -> list[dict]:
    """Check 5: High-speed bus signal routing advisory.

    Matches schematic-detected buses against PCB net lengths.
    Reports trace lengths and flags clock-to-data skew for SPI.
    """
    bus_analysis = sch.get("design_analysis", {}).get("bus_analysis", {})
    if not bus_analysis:
        return []

    # Build net length lookup
    net_lengths = {}
    for nl in pcb.get("net_lengths", []):
        net_lengths[nl["net"]] = nl.get("total_length_mm", 0)

    results = []

    for protocol, buses in bus_analysis.items():
        if not isinstance(buses, list):
            continue
        for bus in buses:
            signals = bus.get("signals", {})
            if not signals:
                continue

            bus_id = bus.get("bus_id", protocol)
            signal_lengths = {}
            missing_nets = []

            for sig_name, sig_data in signals.items():
                if isinstance(sig_data, dict):
                    net_name = sig_data.get("net", "")
                else:
                    net_name = str(sig_data)
                if not net_name:
                    continue
                length = net_lengths.get(net_name)
                if length is not None:
                    signal_lengths[sig_name] = round(length, 2)
                else:
                    missing_nets.append(net_name)

            if not signal_lengths:
                continue

            entry = {
                "protocol": protocol.upper(),
                "bus_id": bus_id,
                "signals": signal_lengths,
            }

            if missing_nets:
                entry["missing_nets"] = missing_nets

            lengths = list(signal_lengths.values())
            if len(lengths) >= 2:
                max_delta = max(lengths) - min(lengths)
                entry["max_delta_mm"] = round(max_delta, 2)

                # SPI clock-to-data skew check
                if protocol == "spi" and "SCK" in signal_lengths:
                    clk_len = signal_lengths["SCK"]
                    data_sigs = {k: v for k, v in signal_lengths.items() if k != "SCK"}
                    if data_sigs:
                        max_data = max(data_sigs.values())
                        clk_skew = abs(clk_len - max_data)
                        if clk_skew > 10.0:
                            entry["status"] = "warning"
                            entry["message"] = (f"SPI clock {clk_len:.1f}mm vs "
                                                f"longest data {max_data:.1f}mm — "
                                                f"{clk_skew:.1f}mm skew")
                        else:
                            entry["status"] = "pass"
                    else:
                        entry["status"] = "pass"
                else:
                    entry["status"] = "info"
            else:
                entry["status"] = "info"

            results.append(entry)

    return results


def check_thermal_vias(thermal: dict, pcb: dict) -> list[dict]:
    """Check 6: Thermal via adequacy.

    Cross-references thermal margins with PCB thermal pad via counts.
    Only runs when thermal JSON is provided.
    """
    assessments = thermal.get("assessments") or thermal.get("thermal_assessments", [])
    if not assessments:
        return []

    # Build thermal pad via lookup from PCB findings[].
    # Thermal pad via entries have detector="analyze_thermal_pad_vias".
    # Keys are "component" and "via_count".
    via_lookup = {}
    for tv in pcb.get("findings", []):
        if not isinstance(tv, dict):
            continue
        if tv.get("detector") != "analyze_thermal_pad_vias":
            continue
        ref = tv.get("component", "")
        if ref:
            via_lookup[ref] = tv.get("via_count", 0)

    results = []
    for a in assessments:
        ref = a.get("ref", "")
        tj = a.get("tj_estimated_c", 0)
        margin = a.get("margin_c", 999)
        pdiss = a.get("pdiss_w", 0)

        if margin > 30 or pdiss < 0.1:
            continue  # Skip components with comfortable margins

        via_count = via_lookup.get(ref, 0)

        entry = {
            "ref": ref,
            "value": a.get("value", ""),
            "tj_estimated_c": round(tj, 1),
            "margin_c": round(margin, 1),
            "pdiss_w": round(pdiss, 3),
            "thermal_vias": via_count,
        }

        if margin < 10 and via_count < 4:
            entry["status"] = "fail"
            entry["message"] = (f"{ref}: {margin:.0f}°C margin with only "
                                f"{via_count} thermal vias — insufficient cooling")
        elif margin < 20 and via_count < 2:
            entry["status"] = "warning"
            entry["message"] = (f"{ref}: {margin:.0f}°C margin with "
                                f"{via_count} thermal vias — consider adding more")
        elif margin < 20:
            entry["status"] = "info"
            entry["message"] = (f"{ref}: {margin:.0f}°C margin, "
                                f"{via_count} thermal vias")
        else:
            entry["status"] = "pass"

        results.append(entry)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Cross-verify schematic design intent against PCB implementation")
    parser.add_argument("--schematic", "-s", required=True,
                        help="Path to schematic analysis JSON")
    parser.add_argument("--pcb", "-p", required=True,
                        help="Path to PCB analysis JSON")
    parser.add_argument("--thermal", "-t", default=None,
                        help="Path to thermal analysis JSON (optional)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    with open(args.schematic, encoding="utf-8") as f:
        sch = json_load(f)
    with open(args.pcb, encoding="utf-8") as f:
        pcb = json_load(f)

    thermal = None
    if args.thermal:
        with open(args.thermal, encoding="utf-8") as f:
            thermal = json_load(f)

    report = cross_verify(sch, pcb, thermal)

    output = json.dumps(report, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        atomic_write_text(args.output, output + "\n", follow_symlinks=False)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    from kicad_core.cli import utf8_stdio
    utf8_stdio()
    main()

#!/usr/bin/env python3
"""
KiCad Schematic Analyzer — comprehensive single-pass extraction.

Parses a .kicad_sch file and outputs structured JSON with:
- Component inventory (BOM data, properties, positions)
- Net connectivity (wires, labels, junctions, no-connects, power symbols)
- Pin-level connectivity map (which pin connects to which net)
- Subcircuit identification hints
- Design statistics

Usage:
    python analyze_schematic.py <file.kicad_sch|file.kicad_pro|dir/> [--output file.json]

Output is JSON to stdout (or file if --output specified).
"""

import json
import math
import os
import re
import sys
from pathlib import Path

# Add scripts dir to path for kicad_core
sys.path.insert(0, str(Path(__file__).parent))
from kicad_core.sexp import (
    find_all,
    find_deep,
    find_first,
    get_at,
    get_properties,
    get_property,
    get_value,
    has_flag,
    parse_file,
)
from kicad_core.values import (
    COORD_EPSILON,
    _MIL_MM,
    format_frequency as _format_frequency,
    parse_value,
    snap_to_mil_grid as _snap_mil,
)
from kicad_core.parts import _OUTPUT_DRIVE_KEYWORDS
from kicad_core.classify import (
    classify_component,
    classify_connector,
    classify_ic_function,
)
from kicad_core.project import (
    extract_pro_text_variables,
    load_lib_tables,
    load_kicad_pro,
)
from kicad_core.netnames import (
    is_ground_name as _is_ground_name,
    is_usb_data_net_name,
    is_power_net_name as _is_power_net_name,
    parse_voltage_from_net_name as _parse_voltage_from_net_name,
    _UUID_RE,
    _clean_hierarchical_name,
)
from kicad_core.fields import (
    MPN_FIELD_ALIASES_PRIMARY, MPN_FIELD_ALIASES_GENERIC,
    DIGIKEY_FIELD_ALIASES, normalize_field_name, pick_field, pick_mpn,
)
from kicad_core.model import Component, Net, Pin, SheetData
from kicad_core.netquery import build_bridge_facts, build_ref_pins
from kicad_core.netquery import build_pin_to_net_map  # facade: kept for external importers (harness); retire round 9
from schematic.reader import (
    _MANUFACTURER_KEYS,
    _MOUSER_KEYS,
    _LCSC_KEYS,
    _ELEMENT14_KEYS,
    extract_lib_symbols,
    _ANGLE_TRANSFORM,
    compute_pin_positions,
    extract_symbol_instances,
    extract_components,
    extract_wires,
    extract_labels,
    extract_power_symbols,
    extract_junctions,
    extract_no_connects,
    extract_text_annotations,
    extract_bus_elements,
    extract_title_block,
    parse_single_sheet,
    detect_sub_sheet,
)
from schematic.legacy_reader import (
    _LEGACY_PIN_TYPE_MAP,
    _M,
    _conn_1xN,
    _conn_2xN,
    _STANDARD_LIB_PINS,
    _parse_legacy_lib,
    _resolve_legacy_libs,
    _snap_pins_to_wires,
    _parse_legacy_single_sheet,
)
from kicad_types import AnalysisContext, build_analysis_context
from schematic.connectivity import (
    BusGraph,
    expand_bus_name,
    match_ports,
    build_net_map,
    _INTERNAL_LABEL_KEYS,
    _labels_for_output,
    get_net_neighbors,
)
from schematic.hierarchy import (
    parse_all_sheets,
    merge_top_level_sheets,
)
from schematic.ic_analysis import (
    _IC_LIB_PREFIX_MAP,
    _IC_VALUE_KEYWORDS,
    _IC_DESC_KEYWORDS,
    _classify_ic_function,
    analyze_ic_pinouts,
    _pin_sort_key,
    identify_subcircuits,
)
from schematic.net_analysis import (
    analyze_connectivity,
    _classify_nets,
    _map_power_domains,
    _get_power_domains_for_refs,
    _get_io_domains_for_refs,
    _rails_voltage_compatible,
    _detect_cross_domain_signals,
    _enrich_device_ref,
    _detect_i2c_buses,
    _detect_spi_buses,
    _detect_uart_buses,
    _detect_sdio_buses,
    _detect_can_buses,
    _detect_rs485_buses,
    _analyze_bus_protocols,
    _guess_diff_protocol,
    _detect_differential_pairs,
    _check_erc_warnings,
    _check_passive_ratings,
    analyze_design_rules,
    _estimate_rail_voltage,
)
from schematic.audits import (
    check_annotation_completeness,
    validate_label_shapes,
    audit_pwr_flags,
    validate_footprint_filters,
    _bom_real_components,
    audit_datasheet_coverage,
    audit_sourcing_fields,
    audit_sourcing_gate,
    audit_dnp_rate,
    _GENERIC_TRANSISTOR_PREFIXES,
    _GENERIC_TYPE_LABELS,
    _PIN_LETTER_NAMES,
    check_generic_transistor_symbols,
    summarize_alternate_pins,
    classify_ground_domains,
    analyze_bus_topology,
    analyze_wire_geometry,
    check_simulation_readiness,
    audit_property_patterns,
    spatial_clustering,
    verify_pin_coverage,
    check_instance_consistency,
    validate_hierarchical_labels,
)
from schematic.system_analyses import (
    analyze_pdn_impedance,
    SLEEP_PULL_MIN_OHM,
    analyze_sleep_current,
    _DERATING_PROFILES,
    analyze_voltage_derating,
    analyze_protocol_compliance,
    analyze_power_budget,
    analyze_power_sequencing,
    analyze_bom_optimization,
    analyze_test_coverage,
    analyze_assembly_complexity,
    analyze_usb_compliance,
    analyze_inrush_current,
)
from signal_detectors import (
    audit_power_pin_dc_paths,
    audit_rail_sources,
    detect_bridge_circuits,
    detect_crystal_circuits,
    detect_current_sense,
    detect_decoupling,
    detect_design_observations,
    detect_integrated_ldos,
    detect_label_aliases,
    detect_lc_filters,
    detect_led_drivers,
    detect_opamp_circuits,
    detect_power_regulators,
    detect_protection_devices,
    detect_rc_filters,
    detect_shorted_two_pin_components,
    detect_solder_jumpers,
    detect_transistor_circuits,
    detect_voltage_dividers,
    postfilter_vd_and_dedup,
    _merge_series_dividers,
)
from domain_detectors import (
    audit_connector_ground_distribution,
    audit_esd_protection,
    audit_led_circuits,
    detect_adc_circuits,
    detect_addressable_leds,
    detect_audio_circuits,
    detect_battery_chargers,
    detect_bms_systems,
    detect_buzzer_speakers,
    detect_clock_distribution,
    detect_debug_interfaces,
    detect_display_interfaces,
    detect_ethernet_interfaces,
    detect_hdmi_dvi_interfaces,
    detect_isolation_barriers,
    detect_key_matrices,
    detect_lvds_interfaces,
    detect_led_driver_ics,
    detect_level_shifters,
    detect_memory_interfaces,
    detect_motor_drivers,
    detect_power_path,
    detect_reset_supervisors,
    detect_rf_chains,
    detect_rf_matching,
    detect_rtc_circuits,
    detect_sensor_interfaces,
    detect_thermocouple_rtd,
    suggest_certifications,
    validate_power_sequencing,
    detect_wireless_modules,
    detect_transformer_feedback,
    detect_i2c_address_conflicts,
    detect_energy_harvesting,
    detect_pwm_led_dimming,
    detect_headphone_jack,
)
from validation_detectors import (
    validate_pullups,
    validate_voltage_levels,
    validate_i2c_bus,
    validate_spi_bus,
    validate_can_bus,
    validate_usb_bus,
    validate_power_sequencing as validate_power_seq_deps,
    validate_led_resistors,
    validate_feedback_stability,
    validate_crystal_load_caps,
)
from lookup_detectors import (
    detect_absolute_max_violations,
    detect_vcc_outside_recommended,
    detect_5v_on_non_tolerant_pin,
    detect_wrong_signal_type,
    detect_missing_required_components,
)
from finding_schema import compute_trust_summary, sort_findings, make_finding, assign_finding_ids
from envelopes.schematic import SchematicEnvelope
from schema_codec import emit_schema
from inputs_builder import build_inputs, build_compat
from capability_mode import get_capability_mode_ref


def _resolve_lookup_paths(sch_path: str | Path,
                           analysis_dir: str | Path | None) -> Path | None:
    """Resolve the datasheets/extracted/ cache dir adjacent to the schematic.

    Returns None when the directory doesn't exist — `lookup()` already handles
    None gracefully. (The design_context severity channel this used to
    resolve was retired in v2.0; v3 removed the plumbing.)
    """
    sch_dir = Path(sch_path).resolve().parent
    candidates = [
        sch_dir / "datasheets" / "extracted",
        sch_dir.parent / "datasheets" / "extracted",
    ]
    return next((c for c in candidates if c.is_dir()), None)

ANALYZER_SOURCE = "sch"

MAX_TESTED_FORMAT_VERSION = 20260306  # bump when a newer corpus era is adopted


def _build_net_classifications(results: dict) -> dict[str, dict]:
    """Build net classification dict from existing detector results.

    Tags nets with signal type and characteristics for downstream PCB
    intelligence checks. Uses the 'nets' field from rich-format detections
    plus domain-specific fields where available.
    """
    classifications: dict[str, dict] = {}

    # Crystal circuits → clock nets (from load_cap nets and rich 'nets' field)
    for xc in results.get('crystal_circuits', []):
        freq = xc.get('frequency')
        # Rich format 'nets' field contains the crystal's connected nets
        for net in xc.get('nets', []):
            if net and net not in classifications:
                classifications[net] = {'type': 'clock', 'frequency_hz': freq, 'source': 'crystal_circuits'}
        # Load cap nets are clock-passive
        for lc in xc.get('load_caps', []):
            net = lc.get('net')
            if net and net not in classifications:
                classifications[net] = {'type': 'clock_passive', 'source': 'crystal_circuits'}

    # Power regulators → switching nodes and power rails
    for reg in results.get('power_regulators', []):
        sw_net = reg.get('sw_net')
        if sw_net:
            classifications[sw_net] = {'type': 'switching_node', 'frequency_hz': reg.get('switching_frequency_hz'), 'source': 'power_regulators'}
        output_rail = reg.get('output_rail')
        if output_rail and output_rail not in classifications:
            classifications[output_rail] = {'type': 'power_rail', 'source': 'power_regulators'}

    # Ethernet → differential nets (from rich 'nets' or domain-specific fields)
    for eth in results.get('ethernet_interfaces', []):
        # Try domain-specific differential net fields first
        for key in ('tx_p', 'tx_n', 'rx_p', 'rx_n', 'txp', 'txn', 'rxp', 'rxn'):
            net = eth.get(key)
            if net:
                classifications[net] = {'type': 'ethernet', 'differential': True, 'source': 'ethernet_interfaces'}
        # Fall back to rich 'nets' field
        for net in eth.get('nets', []):
            if net and net not in classifications:
                classifications[net] = {'type': 'ethernet', 'source': 'ethernet_interfaces'}

    # HDMI/DVI
    for hdmi in results.get('hdmi_dvi_interfaces', []):
        for net in hdmi.get('nets', []):
            if net and net not in classifications:
                classifications[net] = {'type': 'hdmi', 'differential': True, 'source': 'hdmi_dvi_interfaces'}

    # Memory interfaces
    for mem in results.get('memory_interfaces', []):
        for net in mem.get('nets', []):
            if net and net not in classifications:
                classifications[net] = {'type': 'memory', 'source': 'memory_interfaces'}

    # LVDS
    for lvds in results.get('lvds_interfaces', []):
        for net in lvds.get('nets', []):
            if net and net not in classifications:
                classifications[net] = {'type': 'lvds', 'differential': True, 'source': 'lvds_interfaces'}

    # RF chains
    for rf in results.get('rf_chains', []):
        for net in rf.get('nets', []):
            if net and net not in classifications:
                classifications[net] = {'type': 'rf', 'source': 'rf_chains'}

    # Clock distribution
    for clk in results.get('clock_distribution', []):
        freq = clk.get('frequency_hz')
        for net in clk.get('nets', []):
            if net and net not in classifications:
                classifications[net] = {'type': 'clock', 'frequency_hz': freq, 'source': 'clock_distribution'}

    # Validation findings → protocol nets (I2C, CAN, USB)
    for vf in results.get('validation_findings', []):
        rule = vf.get('rule_id', '')
        nets = vf.get('nets', [])
        if rule == 'PR-001':
            for net in nets:
                if net not in classifications:
                    classifications[net] = {'type': 'i2c', 'source': 'protocol_detection'}
        elif rule == 'PR-003':
            for net in nets:
                if net not in classifications:
                    classifications[net] = {'type': 'can', 'differential': True, 'source': 'protocol_detection'}
        elif rule == 'PR-004':
            for net in nets:
                if net not in classifications:
                    classifications[net] = {'type': 'usb', 'differential': True, 'source': 'protocol_detection'}

    return classifications


def analyze_signal_paths(ctx: AnalysisContext) -> dict:
    """Analyze signal processing circuits: filters, dividers, feedback networks.

    Orchestrator that calls individual detector functions from signal_detectors.py.
    Each detector takes an AnalysisContext and returns its detection results.
    """
    nets = ctx.nets

    # Run detectors in dependency order
    vd_result = detect_voltage_dividers(ctx)
    voltage_dividers = vd_result["voltage_dividers"]
    # KH-105/KH-115: Merge series resistors in divider chains
    voltage_dividers = _merge_series_dividers(voltage_dividers, ctx)
    feedback_networks = vd_result["feedback_networks"]

    lc_filters = detect_lc_filters(ctx)
    crystal_circuits = detect_crystal_circuits(ctx)
    # KH-145: Detect opamps BEFORE RC filters so feedback components can be excluded
    opamp_circuits = detect_opamp_circuits(ctx)
    # KH-107: Pass crystal_circuits to exclude crystal R/C from RC filter detection
    # KH-145: Pass opamp_circuits to exclude feedback R+C from RC filter detection
    rc_filters = detect_rc_filters(ctx, voltage_dividers, crystal_circuits, opamp_circuits)
    decoupling_analysis = detect_decoupling(ctx)
    current_sense = detect_current_sense(ctx)
    power_regulators = detect_power_regulators(ctx, voltage_dividers)
    integrated_ldos = detect_integrated_ldos(ctx, power_regulators)
    power_regulators.extend(integrated_ldos)

    # Build rail_voltages: net name → voltage from regulator outputs + power symbol names
    rail_voltages: dict[str, float] = {}
    for reg in power_regulators:
        out_rail = reg.get("output_rail")
        v_out = reg.get("estimated_vout")
        if out_rail and v_out is not None:
            rail_voltages[_clean_hierarchical_name(out_rail)] = v_out
    # Augment with voltages inferred from power symbol / net names
    for net_name in ctx.nets:
        clean = _clean_hierarchical_name(net_name)
        if clean not in rail_voltages:
            v = _estimate_rail_voltage(clean)
            if v is not None:
                rail_voltages[clean] = v

    protection_devices = detect_protection_devices(ctx)
    bridge_circuits, matched_fets, fet_pins = detect_bridge_circuits(ctx)
    transistor_circuits = detect_transistor_circuits(ctx, matched_fets, fet_pins)

    # Post-processing that needs cross-detector data
    voltage_dividers, feedback_networks = postfilter_vd_and_dedup(
        voltage_dividers, feedback_networks, transistor_circuits, nets=ctx.nets)
    detect_led_drivers(ctx, transistor_circuits)
    buzzer_speaker_circuits = detect_buzzer_speakers(ctx, transistor_circuits)
    key_matrices = detect_key_matrices(ctx)
    isolation_barriers = detect_isolation_barriers(ctx)
    ethernet_interfaces = detect_ethernet_interfaces(ctx)
    hdmi_dvi_interfaces = detect_hdmi_dvi_interfaces(ctx)
    lvds_interfaces = detect_lvds_interfaces(ctx)
    memory_interfaces = detect_memory_interfaces(ctx)
    rf_chains = detect_rf_chains(ctx)
    rf_matching = detect_rf_matching(ctx)
    bms_systems = detect_bms_systems(ctx)
    battery_chargers = detect_battery_chargers(ctx)
    motor_drivers = detect_motor_drivers(ctx)
    addressable_led_chains = detect_addressable_leds(ctx)
    debug_interfaces = detect_debug_interfaces(ctx)
    power_path = detect_power_path(ctx)
    esd_coverage_audit = audit_esd_protection(ctx, protection_devices)
    adc_circuits = detect_adc_circuits(ctx, rc_filters, protection_devices)
    reset_supervisors = detect_reset_supervisors(ctx)
    clock_distribution = detect_clock_distribution(ctx, crystal_circuits)
    display_interfaces = detect_display_interfaces(ctx)
    sensor_interfaces = detect_sensor_interfaces(ctx)
    level_shifters = detect_level_shifters(ctx)
    audio_circuits = detect_audio_circuits(ctx)
    led_driver_ics = detect_led_driver_ics(ctx)
    rtc_circuits = detect_rtc_circuits(ctx, crystal_circuits)
    led_audit = audit_led_circuits(ctx, transistor_circuits)
    thermocouple_rtd = detect_thermocouple_rtd(ctx)
    power_sequencing_validation = validate_power_sequencing(
        ctx, power_regulators, power_path, reset_supervisors)
    connector_ground_audit = audit_connector_ground_distribution(ctx)

    # Validation detectors (rich findings)
    pullup_findings = validate_pullups(ctx)
    voltage_level_findings = validate_voltage_levels(ctx, level_shifters)
    i2c_findings = validate_i2c_bus(ctx)
    spi_findings = validate_spi_bus(ctx)
    can_findings = validate_can_bus(ctx)
    usb_findings = validate_usb_bus(ctx)
    power_seq_dep_findings = validate_power_seq_deps(ctx, power_regulators)
    led_resistor_findings = validate_led_resistors(ctx)
    feedback_stability_findings = validate_feedback_stability(ctx, power_regulators)
    crystal_load_findings = validate_crystal_load_caps(ctx, crystal_circuits)

    # Lookup detectors (Phase 4c) — consume v1.4 datasheet facts via lookup().
    # Soft-skip when get_facts() returns None (no MPN cache). Synonym-resolved
    # rail keys per addendum §A2; per-pin Pin.absolute_max overrides rail-level.
    am_001_findings = detect_absolute_max_violations(ctx, rail_voltages)
    ov_001_findings = detect_vcc_outside_recommended(ctx, rail_voltages)
    ft_001_findings = detect_5v_on_non_tolerant_pin(ctx, rail_voltages)
    pm_001_findings = detect_wrong_signal_type(ctx)
    ex_001_findings = detect_missing_required_components(ctx, power_regulators)

    # New domain detectors (rich format)
    wireless_modules = detect_wireless_modules(ctx)
    transformer_feedback = detect_transformer_feedback(ctx)
    i2c_address_conflicts = detect_i2c_address_conflicts(ctx)
    energy_harvesting = detect_energy_harvesting(ctx)
    pwm_led_dimming = detect_pwm_led_dimming(ctx, transistor_circuits)
    headphone_jacks = detect_headphone_jack(ctx)
    solder_jumpers = detect_solder_jumpers(ctx)
    bridge_facts = build_bridge_facts(
        ctx.components, build_ref_pins(ctx.nets), solder_jumpers)
    shorted_two_pin_components = detect_shorted_two_pin_components(ctx)
    rail_source_audit = audit_rail_sources(
        ctx, power_regulators=power_regulators, solder_jumpers=solder_jumpers,
        bridge_facts=bridge_facts)
    label_aliases = detect_label_aliases(ctx)
    power_pin_dc_paths = audit_power_pin_dc_paths(
        ctx, solder_jumpers=solder_jumpers, bridge_facts=bridge_facts)

    # Remove R/C components that appear in crystal circuits from RC filter
    # results — prevents misclassifying crystal feedback resistors + load caps
    # as RC filters (e.g., "10M + 22pF = 723Hz RC filter").
    if crystal_circuits and rc_filters:
        xtal_refs = set()
        for xc in crystal_circuits:
            for lc in xc.get("load_caps", []):
                xtal_refs.add(lc["ref"])
            if "feedback_resistor" in xc:
                xtal_refs.add(xc["feedback_resistor"])
        if xtal_refs:
            rc_filters = [
                f for f in rc_filters
                if f.get("resistor", {}).get("reference") not in xtal_refs
                and f.get("capacitor", {}).get("reference") not in xtal_refs
            ]

    def _enrich_capacitor_data(results_dict, context):
        """Add package size, ESR, dielectric, and rated voltage to all cap entries.

        Walks through all detection dicts recursively, finds entries with a 'farads'
        key and a 'ref' key, and adds derived fields from the component's footprint
        and value string.
        """
        from kicad_core.passives import (extract_cap_package, estimate_cap_esr,
                                         classify_dielectric)
        from kicad_core.values import parse_rated_voltage

        def _enrich(obj):
            if isinstance(obj, dict):
                if "farads" in obj and "ref" in obj:
                    ref = obj["ref"]
                    comp = context.comp_lookup.get(ref)
                    if comp:
                        # Package and ESR (existing)
                        if "package" not in obj:
                            fp = comp.get("footprint", "")
                            pkg = extract_cap_package(fp)
                            if pkg:
                                obj["package"] = pkg
                                esr = estimate_cap_esr(obj["farads"], pkg)
                                if esr is not None:
                                    obj["esr_ohm"] = esr
                        # Dielectric classification (new)
                        if "dielectric" not in obj:
                            value_str = comp.get("value", "")
                            desc_str = comp.get("description", "")
                            obj["dielectric"] = classify_dielectric(value_str, desc_str)
                        # Rated voltage (new)
                        if "rated_voltage_V" not in obj:
                            value_str = comp.get("value", "")
                            rv = parse_rated_voltage(value_str)
                            if rv is not None:
                                obj["rated_voltage_V"] = rv
                for v in obj.values():
                    _enrich(v)
            elif isinstance(obj, list):
                for item in obj:
                    _enrich(item)

        _enrich(results_dict)

    def _apply_capacitor_derating(results_dict):
        """Apply DC bias derating to capacitor entries where applied voltage is known.

        Cross-references regulator output voltages with output_capacitors and
        decoupling_analysis to compute effective_farads after DC bias derating.
        Only adds derating fields when both package and applied voltage are known.
        """
        from kicad_core.passives import estimate_dc_bias_derating

        # Build rail → voltage map from power regulators
        rail_voltage = {}
        for reg in results_dict.get("power_regulators", []):
            vout = reg.get("vout_estimated") or reg.get("estimated_vout")
            rail = reg.get("output_rail", "")
            if vout and vout > 0 and rail:
                # Use the highest voltage seen for a rail (conservative)
                if rail not in rail_voltage or vout > rail_voltage[rail]:
                    rail_voltage[rail] = vout

        def _derate_cap(cap, applied_v):
            """Add derating fields to a single cap entry."""
            farads = cap.get("farads", 0)
            package = cap.get("package")
            dielectric = cap.get("dielectric")
            if not farads or farads <= 0 or not package or not dielectric:
                return

            # Determine rated voltage: from cap entry, or estimate from rail
            rated_v = cap.get("rated_voltage_V")
            if rated_v is None:
                # Conservative estimate based on typical voltage ratings
                if applied_v <= 1.8:
                    rated_v = 6.3
                elif applied_v <= 3.3:
                    rated_v = 6.3
                elif applied_v <= 5.0:
                    rated_v = 10.0
                elif applied_v <= 12.0:
                    rated_v = 25.0
                else:
                    rated_v = applied_v * 2  # assume 2:1 margin

            voltage_ratio = applied_v / rated_v
            remaining = estimate_dc_bias_derating(dielectric, package, voltage_ratio)

            cap["applied_voltage_V"] = applied_v
            cap["derating_factor"] = round(remaining, 3)
            cap["effective_farads"] = farads * remaining

        # Derate output and input capacitors on power regulators
        for reg in results_dict.get("power_regulators", []):
            vout = reg.get("vout_estimated") or reg.get("estimated_vout")
            if not vout or vout <= 0:
                continue
            for cap in reg.get("output_capacitors", []):
                _derate_cap(cap, vout)

        # Derate decoupling analysis capacitors
        for rail_entry in results_dict.get("decoupling_analysis", []):
            rail_name = rail_entry.get("rail", "")
            v = rail_voltage.get(rail_name)
            if not v:
                continue
            any_derated = False
            for cap in rail_entry.get("capacitors", []):
                _derate_cap(cap, v)
                if "effective_farads" in cap:
                    any_derated = True
            # Add total effective capacitance alongside nominal
            if any_derated:
                total_eff = sum(
                    c.get("effective_farads", c["farads"])
                    for c in rail_entry["capacitors"]
                )
                rail_entry["total_effective_capacitance_uF"] = round(total_eff * 1e6, 3)

        # Derate LC filter capacitors where rail voltage is known
        for filt in results_dict.get("lc_filters", []):
            rail = filt.get("rail", "")
            v = rail_voltage.get(rail)
            if v and "capacitor" in filt:
                cap = filt["capacitor"]
                if isinstance(cap, dict) and "farads" in cap:
                    _derate_cap(cap, v)

    results = {
        "rail_voltages": rail_voltages,
        "voltage_dividers": voltage_dividers,
        "rc_filters": rc_filters,
        "lc_filters": lc_filters,
        "feedback_networks": feedback_networks,
        "crystal_circuits": crystal_circuits,
        "snubbers": [],
        "decoupling_analysis": decoupling_analysis,
        "current_sense": current_sense,
        "power_regulators": power_regulators,
        "protection_devices": protection_devices,
        "opamp_circuits": opamp_circuits,
        "bridge_circuits": bridge_circuits,
        "transistor_circuits": transistor_circuits,
        "buzzer_speaker_circuits": buzzer_speaker_circuits,
        "key_matrices": key_matrices,
        "isolation_barriers": isolation_barriers,
        "ethernet_interfaces": ethernet_interfaces,
        "hdmi_dvi_interfaces": hdmi_dvi_interfaces,
        "lvds_interfaces": lvds_interfaces,
        "memory_interfaces": memory_interfaces,
        "rf_chains": rf_chains,
        "rf_matching": rf_matching,
        "bms_systems": bms_systems,
        "battery_chargers": battery_chargers,
        "motor_drivers": motor_drivers,
        "addressable_led_chains": addressable_led_chains,
        "debug_interfaces": debug_interfaces,
        "power_path": power_path,
        "esd_coverage_audit": esd_coverage_audit,
        "adc_circuits": adc_circuits,
        "reset_supervisors": reset_supervisors,
        "clock_distribution": clock_distribution,
        "display_interfaces": display_interfaces,
        "sensor_interfaces": sensor_interfaces,
        "level_shifters": level_shifters,
        "audio_circuits": audio_circuits,
        "led_driver_ics": led_driver_ics,
        "rtc_circuits": rtc_circuits,
        "led_audit": led_audit,
        "thermocouple_rtd": thermocouple_rtd,
        "power_sequencing_validation": power_sequencing_validation,
        "connector_ground_audit": connector_ground_audit,
        "wireless_modules": wireless_modules,
        "transformer_feedback": transformer_feedback,
        "i2c_address_conflicts": i2c_address_conflicts,
        "energy_harvesting": energy_harvesting,
        "pwm_led_dimming": pwm_led_dimming,
        "headphone_jacks": headphone_jacks,
        "solder_jumpers": solder_jumpers,
        "shorted_two_pin_components": shorted_two_pin_components,
        "rail_source_audit": rail_source_audit,
        "label_aliases": label_aliases,
        "power_pin_dc_paths": power_pin_dc_paths,
        "validation_findings": (
            pullup_findings +
            voltage_level_findings +
            i2c_findings +
            spi_findings +
            can_findings +
            usb_findings +
            power_seq_dep_findings +
            led_resistor_findings +
            feedback_stability_findings +
            crystal_load_findings
        ),
        "lookup_findings": (
            am_001_findings +
            ov_001_findings +
            ft_001_findings +
            pm_001_findings +
            ex_001_findings
        ),
    }

    net_classifications = _build_net_classifications(results)
    if net_classifications:
        results["net_classifications"] = net_classifications

    # Certification suggestions cross-reference all domain detections
    cert_suggestions = suggest_certifications(ctx, results)
    if cert_suggestions:
        results["suggested_certifications"] = cert_suggestions

    results["design_observations"] = detect_design_observations(ctx, results)

    # Post-process: enrich capacitor entries with package size and estimated ESR
    _enrich_capacitor_data(results, ctx)
    _apply_capacitor_derating(results)

    return results


def generate_bom(components: list[dict]) -> list[dict]:
    """Generate grouped BOM from components."""
    groups: dict[tuple, dict] = {}

    # Deduplicate multi-unit symbols — only count each reference once
    seen_refs = set()

    for comp in components:
        if comp["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        if not comp["in_bom"]:
            continue
        if comp["reference"] in seen_refs:
            continue
        seen_refs.add(comp["reference"])

        # Group key: value + footprint + MPN (or just value + footprint if no MPN)
        group_key = (comp["value"], comp["footprint"], comp["mpn"])

        if group_key not in groups:
            groups[group_key] = {
                "value": comp["value"],
                "footprint": comp["footprint"],
                "mpn": comp["mpn"],
                "manufacturer": comp["manufacturer"],
                "digikey": comp["digikey"],
                "mouser": comp["mouser"],
                "lcsc": comp["lcsc"],
                "element14": comp["element14"],
                "datasheet": comp["datasheet"],
                "description": comp["description"],
                "references": [],
                "quantity": 0,
                "dnp": comp["dnp"],
                "type": comp["type"],
            }

        groups[group_key]["references"].append(comp["reference"])
        groups[group_key]["quantity"] += 1

    # Sort by reference
    bom = sorted(groups.values(), key=lambda g: g["references"][0] if g["references"] else "")
    return bom


def compute_statistics(components: list[dict], nets: dict, bom: list[dict],
                       wires: list[dict], no_connects: list[dict]) -> dict:
    """Compute summary statistics."""
    # Deduplicate multi-unit symbols by reference
    seen_refs = set()
    non_power = []
    for c in components:
        if c["type"] in ("power_symbol", "power_flag", "flag"):
            continue
        if c["reference"] in seen_refs:
            continue
        seen_refs.add(c["reference"])
        non_power.append(c)
    bom_items = [b for b in bom if not b["dnp"]]
    dnp_items = [b for b in bom if b["dnp"]]

    type_counts = {}
    for comp in non_power:
        t = comp["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    # Build power rails with estimated voltages
    power_rail_names = sorted(set(
        comp["value"] for comp in components if comp["type"] == "power_symbol"
    ))
    for net_name in nets:
        if _is_power_net_name(net_name):
            clean = _clean_hierarchical_name(net_name)
            if clean not in power_rail_names:
                power_rail_names.append(clean)
    power_rail_names = sorted(set(power_rail_names))

    power_rails = []
    for name in power_rail_names:
        clean = _clean_hierarchical_name(name)
        # Skip PWR_FLAG — it's an ERC directive, not a physical rail.
        if clean == "PWR_FLAG":
            continue
        v = _parse_voltage_from_net_name(clean)
        power_rails.append({"name": clean, "voltage": v})

    # Missing properties
    missing_mpn = [c["reference"] for c in non_power
                   if c["type"] not in ("test_point", "mounting_hole")
                   and not c["mpn"] and not c["dnp"] and c["in_bom"]]
    missing_footprint = [c["reference"] for c in non_power
                         if not c["footprint"] and c["in_bom"] and not c["dnp"]]

    return {
        "total_components": len(non_power),
        "unique_parts": len(bom_items),
        "dnp_parts": sum(b["quantity"] for b in dnp_items),
        "total_nets": len(nets),
        "total_wires": len(wires),
        "total_no_connects": len(no_connects),
        "component_types": type_counts,
        "power_rails": power_rails,
        "missing_mpn": missing_mpn,
        "missing_footprint": missing_footprint,
    }


def parse_legacy_schematic(path: str, analysis_dir: str | Path | None = None) -> dict:
    """Parse a KiCad 5 legacy .sch file and return the same structure as analyze_schematic.

    Legacy format uses line-oriented text with $Comp/$EndComp blocks, coordinates
    in mils (1/1000 inch), and positional field numbering (F0=ref, F1=value, etc.).

    For hierarchical designs, recursively parses all subsheets referenced by
    $Sheet blocks and merges connectivity across sheets.

    Parses .lib files to populate component pin data for pin-to-net mapping
    and signal analysis.
    """
    all_components = []
    all_wires = []
    all_labels = []
    all_junctions = []
    all_no_connects = []
    sheets_parsed = []
    all_sch_lines = {}  # path -> LIBS: lines for lib resolution

    to_parse = [str(Path(path).resolve())]
    parsed = set()

    while to_parse:
        sheet_path = to_parse.pop(0)
        if sheet_path in parsed:
            continue
        parsed.add(sheet_path)

        components, wires, labels, junctions, no_connects, sub_sheets, lib_lines = \
            _parse_legacy_single_sheet(sheet_path)

        all_sch_lines[sheet_path] = lib_lines

        # Tag elements with sheet index to keep coordinate spaces separate
        sheet_idx = len(sheets_parsed)
        for c in components:
            c["_sheet"] = sheet_idx
        for w in wires:
            w["_sheet"] = sheet_idx
        for lbl in labels:
            lbl["_sheet"] = sheet_idx
        for j in junctions:
            j["_sheet"] = sheet_idx
        for nc in no_connects:
            nc["_sheet"] = sheet_idx

        all_components.extend(components)
        all_wires.extend(wires)
        all_labels.extend(labels)
        all_junctions.extend(junctions)
        all_no_connects.extend(no_connects)
        sheets_parsed.append(sheet_path)

        for sub_path in sub_sheets:
            if sub_path not in parsed:
                to_parse.append(sub_path)

    # Resolve .lib files and parse pin data
    root_path = str(Path(path).resolve())
    lib_symbols, legacy_resolution = _resolve_legacy_libs(root_path, all_sch_lines)

    # Build a reverse lookup for cache lib names: bare_symbol -> full cache name.
    # Cache libs store "Library_Symbol" while schematics reference bare "Symbol"
    # or "Library:Symbol".  This handles both forms.
    _cache_suffix_map: dict[str, str] = {}
    for sym_name in lib_symbols:
        if "_" in sym_name:
            bare = sym_name.rsplit("_", 1)[-1]
            # Only map if the bare name is unique (avoid ambiguity)
            if bare not in _cache_suffix_map:
                _cache_suffix_map[bare] = sym_name
            else:
                _cache_suffix_map[bare] = None  # ambiguous — don't use
        # Also try full name after last colon-like underscore
        # e.g., "OLIMEX_IC_BL4054B-42TPRN(SOT23-5)" → "BL4054B-42TPRN(SOT23-5)"
        parts = sym_name.split("_")
        if len(parts) >= 3:
            tail = "_".join(parts[2:])
            if tail and tail not in _cache_suffix_map:
                _cache_suffix_map[tail] = sym_name

    # Populate pin positions for each component using lib symbol data.
    # V2 format uses bare symbol names ("MIC5207-BM5"), V4 uses "Library:Symbol".
    # Cache libs use underscores ("Device_C") instead of colons ("Device:C").
    for comp in all_components:
        lib_id = comp.get("lib_id", "")
        sym_def = lib_symbols.get(lib_id)
        _pin_src = "parsed_lib"
        if not sym_def and ":" in lib_id:
            # V4: try underscore form (cache lib naming) and bare symbol name
            bare_name = lib_id.split(":", 1)[1]
            sym_def = (lib_symbols.get(lib_id.replace(":", "_"))
                       or lib_symbols.get(bare_name))
        else:
            bare_name = lib_id
        if not sym_def:
            # Bare name lookup via cache suffix map (handles cache libs
            # that store "Library_Symbol" while schematic uses bare "Symbol")
            cache_key = _cache_suffix_map.get(bare_name)
            if cache_key:
                sym_def = lib_symbols.get(cache_key)
                _pin_src = "suffix_match"
        if sym_def:
            comp["pins"] = compute_pin_positions(comp, {lib_id: sym_def})
            comp["_pin_source"] = _pin_src
            # KH-216: Store unit-valid pin numbers for pin_nets filtering
            comp["_unit_pins"] = {p["number"] for p in comp["pins"]}
            # Snap pin positions to mil grid — eliminates floating-point drift
            # from trig-based rotation so pins align with wire endpoints.
            for pin in comp["pins"]:
                pin["x"] = _snap_mil(pin["x"])
                pin["y"] = _snap_mil(pin["y"])

    # KH-016 fix: Snap component pins to nearby wire endpoints when the
    # computed pin positions don't match any wire (caused by KiCad version
    # differences in standard library pin offsets).  For each pin, if no wire
    # endpoint is within COORD_EPSILON, find the closest wire endpoint on the
    # same sheet within a generous radius and snap to it.
    _snap_pins_to_wires(all_components, all_wires)

    # Extract power symbols (preserve _sheet so build_net_map keeps coordinate
    # spaces separate — without it, power symbols from sub-sheets all land in
    # sheet 0's coordinate space and fail to connect to their actual wires).
    power_symbols = []
    for comp in all_components:
        if comp["type"] == "power_symbol":
            ps = {
                "net_name": comp["value"],
                "x": comp["x"],
                "y": comp["y"],
                "lib_id": comp["lib_id"],
            }
            if "_sheet" in comp:
                ps["_sheet"] = comp["_sheet"]
            ps["_power_scope"] = comp.get("_power_scope", "global")
            power_symbols.append(ps)

    # Generate BOM
    bom = generate_bom(all_components)

    # Build nets from wires + labels + power symbols + component pins
    nets = build_net_map(all_components, all_wires, all_labels, power_symbols, all_junctions,
                         all_no_connects,
                         sheet_names=[Path(p).stem for p in sheets_parsed])

    stats = compute_statistics(all_components, nets, bom, all_wires, all_no_connects)

    # Subcircuit detection (IC + 1-hop neighbors)
    # Build shared analysis context for legacy path
    _cache_dir = _resolve_lookup_paths(path, analysis_dir)
    ctx = build_analysis_context(
        all_components, nets, lib_symbols,
        no_connects=all_no_connects, source=ANALYZER_SOURCE,
        cache_dir=_cache_dir, project_dir=str(Path(path).parent))

    subcircuits = identify_subcircuits(ctx)

    # Signal path and filter analysis
    signal_analysis = analyze_signal_paths(ctx)

    # Design rule analysis
    design_analysis = analyze_design_rules(ctx, results_in=signal_analysis)

    # Filter to real components (non-power) for annotation check
    real_components = [
        c for c in all_components
        if c["type"] not in ("power_symbol", "power_flag", "flag")
    ]
    annotation_issues = check_annotation_completeness(real_components)

    # Enrich components with pin-to-net mapping (legacy path)
    # KH-211: Include __unnamed_* nets so that connections through unlabelled
    # wires (common in hierarchical sub-sheets) appear in pin_nets.
    _pin_nets_l: dict[str, dict[str, str]] = {}
    for _net_name, _net_info in nets.items():
        if isinstance(_net_info, dict):
            for _p in _net_info.get('pins', []):
                _comp_ref = _p.get('component', '')
                _pin_num = _p.get('pin_number', '')
                if _comp_ref and _pin_num:
                    _pin_nets_l.setdefault(_comp_ref, {})[_pin_num] = _net_name
    for _comp in all_components:
        _all_pn = _pin_nets_l.get(_comp.get('reference', ''), {})
        _valid = _comp.get("_unit_pins")
        if _valid and len(_all_pn) > len(_valid):
            _comp['pin_nets'] = {k: v for k, v in _all_pn.items() if k in _valid}
        else:
            _comp['pin_nets'] = _all_pn
        _comp.pop("_unit_pins", None)

    # Add stable detection IDs for diff matching (legacy path)
    from detection_schema import compute_detection_id as _compute_det_id
    for _det_type, _dets in signal_analysis.items():
        if isinstance(_dets, list):
            for _det in _dets:
                if isinstance(_det, dict):
                    _det["detection_id"] = _compute_det_id(_det, _det_type)

    # Flatten signal_analysis: all list values become findings, dict values move to top level
    findings = []
    top_level_dicts = {}
    for key, value in signal_analysis.items():
        if isinstance(value, list):
            _det_name = f"detect_{key}"
            for _item in value:
                if isinstance(_item, dict) and "detector" not in _item:
                    _item["detector"] = _det_name
            findings.extend(value)
        elif isinstance(value, dict):
            # rail_voltages, net_classifications, etc. — promote to top level
            top_level_dicts[key] = value

    sev_counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info").lower() if isinstance(f, dict) else "info"
        if sev in ("critical", "high"):
            sev_counts["error"] += 1
        elif sev in ("medium", "warning"):
            sev_counts["warning"] += 1
        else:
            sev_counts["info"] += 1

    # Legacy analysis quality summary (KH-271)
    _pin_source_counts = {"parsed_lib": 0, "suffix_match": 0, "snapped_to_wire": 0, "unresolved": 0}
    for c in real_components:
        src = c.get("_pin_source", "unresolved")
        if src in _pin_source_counts:
            _pin_source_counts[src] += 1
        else:
            _pin_source_counts[src] = 1

    # Deterministic order for byte-identical repeated runs (KH-316).
    sort_findings(findings)

    result = {
        "analyzer_type": "schematic",
        "schema_version": "1.4.0",
        "summary": {"total_findings": len(findings), "by_severity": sev_counts},
        "trust_summary": compute_trust_summary(findings),
        "kicad_version": "5 (legacy)",
        "file_version": "4",
        "title_block": {},  # legacy .sch has no (title_block ...) node (TH-043)
        "sheets_parsed": len(sheets_parsed),
        "sheet_files": sheets_parsed,
        "statistics": stats,
        "bom": bom,
        "components": real_components,
        "nets": nets,
        "subcircuits": subcircuits,
        "findings": findings,
        "assessments": [],
        "design_analysis": design_analysis,
        "labels": _labels_for_output(all_labels),
        "no_connects": all_no_connects,
        "power_symbols": power_symbols,
        "annotation_issues": annotation_issues,
        "legacy_analysis_quality": {
            "is_legacy_schematic": True,
            "library_resolution": legacy_resolution,
            "pin_source_coverage": _pin_source_counts,
        },
    }
    # Promote dict values from signal_analysis to top level (rail_voltages, etc.)
    result.update(top_level_dicts)
    return result


# ---------------------------------------------------------------------------
# Tier 3: High-level design analysis functions
# ---------------------------------------------------------------------------


def analyze_schematic(path: str, project_root: str | None = None,
                      no_hierarchy: bool = False,
                      analysis_dir: str | Path | None = None) -> dict:
    """Main analysis function. Returns complete structured data.

    For hierarchical designs (multi-sheet), recursively parses all sub-sheets
    and merges connectivity. Global and hierarchical labels connect nets across
    sheets.

    If *path* is a sub-sheet (not the root), the function auto-discovers the
    root schematic via ``.kicad_pro`` and redirects to a full-project analysis.
    The result includes ``_redirected_from`` with the original filename.  If the
    file is not part of any active sheet tree, ``_stale_file_warning`` is set.

    Args:
        path: Path to .kicad_sch file to analyze.
        project_root: Optional path to root .kicad_sch for hierarchy context.
            Auto-discovered from .kicad_pro if not provided.
        no_hierarchy: If True, skip hierarchy auto-discovery entirely.
            Useful when analysing a sub-sheet in isolation.
    """
    # Detect legacy format
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline().strip()

    if first_line.startswith("EESchema"):
        return parse_legacy_schematic(path, analysis_dir=analysis_dir)

    # Parse root sheet and all sub-sheets recursively via parse_all_sheets().
    root_tree = parse_file(path)

    is_sub = detect_sub_sheet(root_tree, file_path=path)
    hierarchy_warning = None

    if is_sub and not no_hierarchy:
        from kicad_core.project import discover_root_schematic
        root_path = project_root or discover_root_schematic(path)
        if root_path:
            # Redirect: analyze the full project from the root schematic.
            # This gives a complete picture (all sheets, all components)
            # instead of analyzing a sub-sheet in isolation.
            original_basename = os.path.basename(path)
            root_basename = os.path.basename(root_path)
            print(f"Note: {original_basename} is a sub-sheet — analyzing "
                  f"full project from root {root_basename}",
                  file=sys.stderr)
            result = analyze_schematic(root_path, no_hierarchy=True)
            result["_redirected_from"] = original_basename

            # Stale file check: is the original file in the project tree?
            target_abs = str(Path(path).resolve())
            in_project = any(
                str(Path(s).resolve()) == target_abs
                for s in result.get("sheets", []))
            if not in_project:
                result["_stale_file_warning"] = (
                    f"{original_basename} is not referenced by any sheet "
                    f"in the project ({root_basename}). It may be a stale "
                    f"or abandoned child schematic.")
                print(f"Warning: {original_basename} is not part of the "
                      f"active project sheet tree", file=sys.stderr)

            return result
        else:
            hierarchy_warning = (
                "File appears to be a sub-sheet (has hierarchical labels but "
                "no symbol_instances). No root schematic found. Component "
                "references may be incomplete. Use --project-root for full "
                "hierarchy analysis."
            )
    elif is_sub and no_hierarchy:
        hierarchy_warning = (
            "File appears to be a sub-sheet but hierarchy discovery is "
            "disabled (--no-hierarchy). Component references may be incomplete."
        )

    parsed = parse_all_sheets(path, root_tree=root_tree)

    merge_top_level_sheets(parsed, path, root_tree)

    all_components = parsed["components"]
    all_wires = parsed["wires"]
    all_labels = parsed["labels"]
    all_junctions = parsed["junctions"]
    all_no_connects = parsed["no_connects"]
    all_lib_symbols = parsed["lib_symbols"]
    all_text_annotations = parsed["text_annotations"]
    merged_bus = parsed["bus_elements"]
    root_title_block = parsed["title_block"]
    sheets_parsed = parsed["sheets_parsed"]
    power_symbols = parsed["power_symbols"]
    root_symbol_instances = parsed["root_symbol_instances"]
    generator_version = parsed["generator_version"]
    file_version = parsed["file_version"]

    try:
        _v = int(file_version)
    except (TypeError, ValueError):
        _v = None
    format_newer_note = None
    if _v is not None and _v > MAX_TESTED_FORMAT_VERSION:
        format_newer_note = (
            f"file format version {_v} is newer than the max tested "
            f"({MAX_TESTED_FORMAT_VERSION}); analysis is best-effort")

    # Build net map across all sheets
    nets = build_net_map(all_components, all_wires, all_labels, power_symbols, all_junctions,
                         all_no_connects,
                         sheet_names=[Path(p).stem for p in sheets_parsed],
                         bus_elements=merged_bus)

    # Generate BOM
    bom = generate_bom(all_components)

    # Build shared analysis context (pin_net and every index are built once, here)
    _cache_dir = _resolve_lookup_paths(path, analysis_dir)
    ctx = build_analysis_context(
        all_components, nets, all_lib_symbols,
        no_connects=all_no_connects, generator_version=generator_version,
        source=ANALYZER_SOURCE, cache_dir=_cache_dir, project_dir=str(Path(path).parent))
    pin_net = ctx.pin_net

    # Identify subcircuits
    subcircuits = identify_subcircuits(ctx)

    # Detailed IC pinout analysis for datasheet cross-referencing
    ic_analysis = analyze_ic_pinouts(ctx)
    # Parallel transistor pinout analysis (F4) — same code path, different
    # filter. ic_pin_analysis stays IC/connector/crystal/oscillator-only for
    # consumer compatibility; transistors go in their own array.
    transistor_analysis = analyze_ic_pinouts(ctx, target_types={"transistor"})

    # Analyze connectivity for issues
    connectivity_issues = analyze_connectivity(all_components, nets, all_no_connects)

    # Signal path and filter analysis
    signal_analysis = analyze_signal_paths(ctx)

    # Deep EE analysis: power domains, buses, differential pairs, ERC
    design_analysis = analyze_design_rules(ctx, results_in=signal_analysis)

    # ---- New Tier 1 + Tier 2 analyses ----

    # Reuse known_power_rails from context for PWR_FLAG audit
    known_power_rails = ctx.known_power_rails

    annotation_issues = check_annotation_completeness(all_components)
    label_shape_warnings = validate_label_shapes(all_labels, nets)
    pwr_flag_warnings = audit_pwr_flags(all_components, nets, known_power_rails)
    fp_filter_warnings = validate_footprint_filters(all_components, all_lib_symbols)
    sourcing_audit = audit_sourcing_fields(all_components)
    datasheet_coverage_findings = audit_datasheet_coverage(
        all_components, str(Path(path).parent))
    sourcing_gate_findings = audit_sourcing_gate(all_components)
    dnp_rate_findings = audit_dnp_rate(all_components)
    alternate_pins = summarize_alternate_pins(all_lib_symbols)
    ground_domains = classify_ground_domains(nets, all_components)
    bus_topology = analyze_bus_topology(merged_bus, all_labels, nets)
    wire_geometry = analyze_wire_geometry(all_wires)
    sim_readiness = check_simulation_readiness(all_components, all_lib_symbols)
    property_issues = audit_property_patterns(all_components)
    placement = spatial_clustering(all_components)
    pin_coverage = verify_pin_coverage(all_components, all_lib_symbols)
    instance_issues = check_instance_consistency(all_components)
    hier_label_analysis = validate_hierarchical_labels(all_labels, nets, merged_bus)
    generic_sym_warnings = check_generic_transistor_symbols(all_components, str(path))

    # ---- Tier 3: High-level design analyses ----
    pdn_analysis = analyze_pdn_impedance(ctx, signal_analysis)
    # KH-374: power_sequencing must run before sleep_current so the sleep
    # audit can consult real EN connectivity (en_source) instead of just
    # EN-pin-name presence.
    power_sequencing = analyze_power_sequencing(ctx, signal_analysis)
    sleep_current = analyze_sleep_current(ctx, signal_analysis, power_sequencing)
    voltage_derating = analyze_voltage_derating(ctx, signal_analysis,
                                                 project_dir=str(Path(path).parent))
    power_budget = analyze_power_budget(ctx, signal_analysis)
    bom_optimization = analyze_bom_optimization(all_components)
    test_coverage = analyze_test_coverage(ctx)
    assembly_complexity = analyze_assembly_complexity(all_components)
    usb_compliance = analyze_usb_compliance(ctx, signal_analysis)
    inrush_analysis = analyze_inrush_current(ctx, signal_analysis)
    protocol_compliance = analyze_protocol_compliance(all_components, nets, design_analysis, signal_analysis, pin_net)

    # Add parsed numeric values to all passive components and category field
    for comp in all_components:
        comp["category"] = comp.get("type")
        if comp["type"] in ("resistor", "capacitor", "inductor", "ferrite_bead", "crystal"):
            pv = parse_value(comp.get("value", ""), component_type=comp["type"])
            if pv is not None:
                comp["parsed_value"] = pv

    # Statistics
    stats = compute_statistics(all_components, nets, bom, all_wires, all_no_connects)

    # Annotate __unnamed_N nets with a human-readable display_name when
    # exactly one named IC pin is on them. Does NOT rename the net —
    # only adds a display hint consumers can use in reports.
    _IC_TYPES = {"ic", "regulator", "opamp", "microcontroller", "memory",
                 "connector_ic", "analog_ic", "mixed_signal",
                 "power_management", "interface"}
    _comp_by_ref = {c.get("reference"): c for c in all_components}
    for _net_name, _info in nets.items():
        if not _net_name.startswith("__unnamed_"):
            continue
        if _info.get("display_name"):
            continue
        _named_ic_pin = None
        for _p in _info.get("pins", []) or []:
            _pname = (_p.get("pin_name") or "").strip()
            if not _pname or _pname in ("~", "NC"):
                continue
            _ref = _p.get("component") or ""
            _comp = _comp_by_ref.get(_ref)
            if not _comp:
                continue
            _ctype = (_comp.get("type") or _comp.get("category") or "").lower()
            if _ctype not in _IC_TYPES:
                continue
            if _named_ic_pin is None:
                _named_ic_pin = (_ref, _pname)
            else:
                # Multiple named IC pins — ambiguous, skip annotation.
                _named_ic_pin = None
                break
        if _named_ic_pin:
            _info["display_name"] = f"{_named_ic_pin[0]}.{_named_ic_pin[1]}"

    # Load .kicad_pro for project metadata (KiCad 6+)
    pro = load_kicad_pro(str(path))
    project_settings = {}
    if pro:
        text_vars = extract_pro_text_variables(pro)
        if text_vars:
            project_settings['text_variables'] = text_vars
            # Enrich title block with text variables where empty
            if root_title_block:
                for tb_key, var_name in (('title', 'TITLE'),
                                          ('company', 'COMPANY'),
                                          ('revision', 'REVISION')):
                    if not root_title_block.get(tb_key) and var_name in text_vars:
                        root_title_block[tb_key] = text_vars[var_name]

    # Library tables
    lib_tables = load_lib_tables(str(path))
    if lib_tables.get('symbol_libs'):
        project_settings['symbol_libs'] = lib_tables['symbol_libs']

    # Enrich components with pin-to-net mapping for downstream consumers
    # KH-211: Include __unnamed_* nets so that connections through unlabelled
    # wires (common in hierarchical sub-sheets) appear in pin_nets.
    _pin_nets: dict[str, dict[str, str]] = {}
    for _net_name, _net_info in nets.items():
        if isinstance(_net_info, dict):
            for _p in _net_info.get('pins', []):
                _comp_ref = _p.get('component', '')
                _pin_num = _p.get('pin_number', '')
                if _comp_ref and _pin_num:
                    _pin_nets.setdefault(_comp_ref, {})[_pin_num] = _net_name
    for _comp in all_components:
        _all_pn = _pin_nets.get(_comp.get('reference', ''), {})
        _valid = _comp.get("_unit_pins")
        if _valid and len(_all_pn) > len(_valid):
            _comp['pin_nets'] = {k: v for k, v in _all_pn.items() if k in _valid}
        else:
            _comp['pin_nets'] = _all_pn
        _comp.pop("_unit_pins", None)

    # Flatten signal_analysis: all list values become findings, dict values promote to top level
    # KH-388: detect_voltage_dividers' feedback-network path deliberately
    # appends the SAME finding dict to both the `voltage_dividers` and
    # `feedback_networks` signal_analysis lists — see the 8c36212 cascade
    # warning in signal_detectors.py:324-346; that double-emission must
    # stay, it feeds detect_rc_filters' exclusion set. Dedup here instead
    # so the shared object doesn't also duplicate in the flattened
    # findings[] output. id()-based dedup is safe for ANY detector (a
    # dict appearing twice in the SAME analysis output is always the same
    # aliasing quirk noted in finding_schema.py's assign_finding_ids). The
    # (detector, components) key belt is scoped to detect_voltage_dividers
    # only — other detectors (e.g. VM-001) legitimately emit multiple
    # distinct findings for the same component pair on different nets, so
    # a components-only key would wrongly collapse those. Order-preserving
    # (first occurrence wins).
    findings = []
    _flatten_seen_ids = set()
    _flatten_seen_vd_keys = set()
    for _sa_key, _sa_value in signal_analysis.items():
        if isinstance(_sa_value, list):
            _det_name = f"detect_{_sa_key}"
            for _item in _sa_value:
                if isinstance(_item, dict) and "detector" not in _item:
                    _item["detector"] = _det_name
            for _item in _sa_value:
                if isinstance(_item, dict):
                    _iid = id(_item)
                    if _iid in _flatten_seen_ids:
                        continue
                    _flatten_seen_ids.add(_iid)
                    if _item.get("detector") == "detect_voltage_dividers":
                        _vkey = (_item.get("detector"), tuple(_item.get("components") or []))
                        if _vkey in _flatten_seen_vd_keys:
                            continue
                        _flatten_seen_vd_keys.add(_vkey)
                findings.append(_item)

    # Datasheet-coverage audit findings (DS-001 / DS-002 / DS-003) surface
    # up front so reviewers can't miss the "this is a consistency-only
    # check" banner when no manufacturer evidence is available.
    if datasheet_coverage_findings:
        findings.extend(datasheet_coverage_findings)

    if sourcing_gate_findings:
        findings.extend(sourcing_gate_findings)

    if dnp_rate_findings:
        findings.extend(dnp_rate_findings)

    # NT-001 — single-pin nets weighted by pin type (Task 3)
    nt_findings = connectivity_issues.get("single_pin_net_findings", [])
    if nt_findings:
        findings.extend(nt_findings)

    # VD-001..004 — component voltage/power derating (rich findings since v1.4)
    if voltage_derating:
        findings.extend(voltage_derating)

    # UC-001..004 — USB compliance check failures (KH-338)
    if usb_compliance:
        findings.extend(usb_compliance.pop("findings", []))

    if format_newer_note:
        findings.append(make_finding(
            detector="format_version_gate", rule_id="FV-001",
            category="file_format",
            summary=format_newer_note,
            description=format_newer_note,
            severity="info", confidence="deterministic",
            evidence_source="topology",
        ))

    # Build severity summary
    sev_counts = {"error": 0, "warning": 0, "info": 0}
    for _f in findings:
        _sev = _f.get("severity", "info").lower() if isinstance(_f, dict) else "info"
        if _sev in ("critical", "high"):
            sev_counts["error"] += 1
        elif _sev in ("medium", "warning"):
            sev_counts["warning"] += 1
        else:
            sev_counts["info"] += 1

    # Deterministic order so repeated runs produce byte-identical output
    # (KH-316).  Sort key: (rule_id, detector, first_component, first_net, summary).
    sort_findings(findings)

    result = {
        "analyzer_type": "schematic",
        "schema_version": "1.4.0",
        "summary": {"total_findings": len(findings), "by_severity": sev_counts},
        "trust_summary": compute_trust_summary(findings, bom=bom),
        "kicad_version": generator_version,
        "file_version": file_version,
        "title_block": root_title_block,
        "statistics": stats,
        "findings": findings,
        "assessments": [],
        "bom": bom,
        "components": [
            {k: v for k, v in c.items() if k != "pins"}
            for c in all_components
            if c["type"] not in ("power_symbol", "power_flag", "flag")
        ],
        "nets": nets,
        "subcircuits": subcircuits,
        "ic_pin_analysis": ic_analysis,
        "transistor_pin_analysis": transistor_analysis,
        "design_analysis": design_analysis,
        "connectivity_issues": connectivity_issues,
        "labels": _labels_for_output(all_labels),
        "no_connects": all_no_connects,
        "power_symbols": power_symbols,
        "annotation_issues": annotation_issues,
        "label_shape_warnings": label_shape_warnings,
        "pwr_flag_warnings": pwr_flag_warnings,
        "footprint_filter_warnings": fp_filter_warnings,
        "sourcing_audit": sourcing_audit,
        "ground_domains": ground_domains,
        "bus_topology": bus_topology,
        "wire_geometry": wire_geometry,
        "simulation_readiness": sim_readiness,
        "property_issues": property_issues,
        "placement_analysis": placement,
        "hierarchical_labels": hier_label_analysis,
    }

    # Promote dict values from signal_analysis to top level (rail_voltages, net_classifications, etc.)
    for _sa_key, _sa_value in signal_analysis.items():
        if isinstance(_sa_value, dict):
            result[_sa_key] = _sa_value

    # Only include non-empty optional sections
    if all_text_annotations:
        result["text_annotations"] = all_text_annotations
    if alternate_pins:
        result["alternate_pin_summary"] = alternate_pins
    if pin_coverage:
        result["pin_coverage_warnings"] = pin_coverage
    if instance_issues:
        result["instance_consistency_warnings"] = instance_issues
    if generic_sym_warnings:
        result["generic_symbol_warnings"] = generic_sym_warnings
    if pdn_analysis:
        result["pdn_impedance"] = pdn_analysis
    if sleep_current:
        result["sleep_current_audit"] = sleep_current
    if power_budget:
        result["power_budget"] = power_budget
    if power_sequencing:
        result["power_sequencing"] = power_sequencing
    if bom_optimization:
        result["bom_optimization"] = bom_optimization
    if test_coverage:
        result["test_coverage"] = test_coverage
    if assembly_complexity:
        result["assembly_complexity"] = assembly_complexity
    if usb_compliance:
        result["usb_compliance"] = usb_compliance
    if inrush_analysis:
        result["inrush_analysis"] = inrush_analysis
    if protocol_compliance:
        result["protocol_compliance"] = protocol_compliance

    if len(sheets_parsed) > 1:
        result["sheets"] = sheets_parsed
    if project_settings:
        result["project_settings"] = project_settings
    if hierarchy_warning:
        result["hierarchy_warning"] = hierarchy_warning

    # --- Missing information section ---
    # Aggregates data gaps so downstream consumers can separate
    # "missing data" from "actual design issues"
    missing_info = {}
    # Missing MPNs and footprints (from statistics)
    missing_mpn = stats.get("missing_mpn", [])
    if missing_mpn:
        missing_info["missing_mpn"] = missing_mpn
    missing_fp = stats.get("missing_footprint", [])
    if missing_fp:
        missing_info["missing_footprint"] = missing_fp
    # Components with MPN but no datasheet URL
    missing_ds = [c["reference"] for c in all_components
                  if c.get("mpn") and not c.get("datasheet")
                  and c["type"] not in ("power_symbol", "power_flag", "flag")]
    if missing_ds:
        missing_info["missing_datasheet"] = sorted(missing_ds)
    # Regulators with heuristic Vref (no datasheet lookup available)
    sig = signal_analysis or {}
    heuristic_vref = [r["ref"] for r in sig.get("power_regulators", [])
                      if r.get("vref_source") == "heuristic"]
    if heuristic_vref:
        missing_info["heuristic_vref"] = heuristic_vref
    if missing_info:
        result["missing_info"] = missing_info

    # BOM lock verification (production readiness)
    _bom_real = [c for c in all_components
                 if c.get("type") not in ("power_symbol", "power_flag", "flag",
                                           "mounting_hole", "fiducial",
                                           "test_point", "graphic")
                 and not c.get("reference", "").startswith("#")
                 and c.get("in_bom", True) and not c.get("dnp", False)]
    # Deduplicate multi-unit symbols
    _bom_seen = set()
    _bom_dedup = []
    for _bc in _bom_real:
        if _bc["reference"] not in _bom_seen:
            _bom_seen.add(_bc["reference"])
            _bom_dedup.append(_bc)
    _bom_real = _bom_dedup
    _bom_no_mpn = [c["reference"] for c in _bom_real if not c.get("mpn")]
    _bom_generic = [c["reference"] for c in _bom_real
                    if c.get("value", "") in ("", "~", "DNP", "DNF", "NC")
                    or c.get("value", "").startswith("?")]
    _bom_lock_pct = round((1 - len(_bom_no_mpn) / max(len(_bom_real), 1)) * 100)
    result["bom_lock"] = {
        "total_bom_components": len(_bom_real),
        "components_with_mpn": len(_bom_real) - len(_bom_no_mpn),
        "missing_mpn": _bom_no_mpn[:20],
        "missing_mpn_count": len(_bom_no_mpn),
        "generic_values": _bom_generic[:10],
        "lock_pct": _bom_lock_pct,
        "status": "pass" if _bom_lock_pct >= 95 else
                  "warning" if _bom_lock_pct >= 70 else "fail",
    }

    # Add stable detection IDs for diff matching
    from detection_schema import compute_detection_id as _compute_det_id
    for _det_type, _dets in signal_analysis.items():
        if isinstance(_dets, list):
            for _det in _dets:
                if isinstance(_det, dict):
                    _det["detection_id"] = _compute_det_id(_det, _det_type)

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KiCad Schematic Analyzer")
    parser.add_argument("schematic", nargs="?",
                        help="Path to .kicad_sch, .kicad_pro, or project directory")
    parser.add_argument("--output", "-o", help="Output JSON file (default: stdout)")
    parser.add_argument("--compact", action="store_true", help="Compact JSON output")
    parser.add_argument("--schema", action="store_true",
                        help="Print JSON output schema and exit")
    parser.add_argument("--config", default=None,
                        help="Path to .kicad-happy.json project config file")
    parser.add_argument("--project-root", default=None,
                        help="Root .kicad_sch for hierarchy context (auto-discovered if omitted)")
    parser.add_argument("--no-hierarchy", action="store_true",
                        help="Disable hierarchy auto-discovery (treat file as standalone root)")
    parser.add_argument("--lifecycle", action="store_true",
                        help="Run lifecycle/obsolescence audit (requires network + API keys)")
    parser.add_argument("--analysis-dir", default=None,
                        help="Write output to analysis cache directory (timestamped runs)")
    parser.add_argument("--text", action="store_true",
                        help="Print human-readable text report to stdout")
    parser.add_argument('--stage', default=None,
                        choices=['schematic', 'layout', 'pre_fab', 'bring_up'],
                        help='Filter findings by review stage')
    parser.add_argument('--audience', default=None,
                        choices=['designer', 'reviewer', 'manager'],
                        help='Audience level for summaries and --text output')
    parser.add_argument('--only-deterministic', action='store_true',
                        help='Accepted for consistency; analyzers never write llm_* fields. '
                             'Honored by downstream consumers (Phase 4 spec §3.4).')
    args = parser.parse_args()

    if args.schema:
        emit_schema(SchematicEnvelope)

    if not args.schematic:
        parser.error("the following arguments are required: schematic")

    # Resolve .kicad_pro or directory to the root .kicad_sch
    from kicad_core.project import resolve_project_input
    try:
        resolved, note = resolve_project_input(args.schematic, '.kicad_sch')
        if note:
            print(f"Note: {note} → {os.path.basename(resolved)}",
                  file=sys.stderr)
        args.schematic = resolved
    except FileNotFoundError as e:
        parser.error(str(e))

    # Load project config (for project settings — suppressions applied to
    # EMC/thermal findings, not schematic warnings which lack rule_ids)
    try:
        from project_config import load_config_from_path, load_config
        if args.config:
            config = load_config_from_path(args.config)
        else:
            config = load_config(str(Path(args.schematic).parent))
    except ImportError:
        config = {"version": 1, "project": {}, "suppressions": []}

    # Resolve canonical analysis_dir ONCE — used for both AnalysisContext
    # (Phase 4d-active) and capability_mode_ref (Phase 4 §3.3). This must
    # be the same path so `--analysis-dir X` writes outputs AND capability
    # mode to the same X, not to ./analysis (audit Highest-Risk #4).
    if args.analysis_dir:
        _analysis_dir_for_ctx = Path(args.analysis_dir)
    elif args.output:
        _analysis_dir_for_ctx = Path(args.output).parent
    else:
        _analysis_dir_for_ctx = Path("analysis")

    # Resolve capability_mode_ref BEFORE build_inputs so inputs.run_id ==
    # capability_mode_ref.run_id (Phase 4 spec §3.3, audit Highest-Risk #5).
    # First-writer-wins side effect: creates capability_mode.json if absent.
    _capability_mode_ref = get_capability_mode_ref(_analysis_dir_for_ctx)

    # Build inputs provenance block (Track 1.3).
    _sch_path = Path(args.schematic)
    if args.config:
        _cfg_path = Path(args.config) if Path(args.config).is_file() else None
    else:
        _default_cfg = _sch_path.parent / ".kicad-happy.json"
        _cfg_path = _default_cfg if _default_cfg.is_file() else None
    inputs = build_inputs(
        source_files=[_sch_path],
        config_path=_cfg_path,
        run_id=_capability_mode_ref["run_id"],
    )
    compat = build_compat()

    result = analyze_schematic(args.schematic,
                               project_root=args.project_root,
                               no_hierarchy=args.no_hierarchy,
                               analysis_dir=_analysis_dir_for_ctx)
    # Inject provenance and drop the legacy 'file' key (already removed
    # from internal result assembly, but belt-and-suspenders).
    result["inputs"] = inputs
    result["compat"] = compat
    result.pop("file", None)

    # Attach project config summary to output for downstream consumers
    project = config.get("project", {})
    if project:
        result["project_config"] = project

    # Resolve design intent for downstream consumers
    try:
        from project_config import resolve_design_intent
        sch_data_for_intent = {
            'components': result.get('components', []),
            'title_block': result.get('title_block', {}),
        }
        intent = resolve_design_intent(config,
                                        schematic_data=sch_data_for_intent)
        result['design_intent'] = intent

        # Gate CERT-001 blanket certification suggestions on target_market.
        # For hobby projects, "EU EMC compliance required" and the fallback
        # FCC Part 15 Subpart B fire as noise on every board.  Keep specific
        # triggers (RF, wireless, battery, USB, ethernet, HV) — those
        # represent real circuit hazards regardless of market.
        target_market = (intent or {}).get('target_market', 'hobby')
        if target_market == 'hobby':
            _blanket_cert_prefixes = (
                'FCC Part 15 Subpart B',
                'CISPR 32 / CE EMC Directive',
            )
            result['findings'] = [
                f for f in result.get('findings', [])
                if not (isinstance(f, dict)
                        and f.get('rule_id') == 'CERT-001'
                        and any(str(f.get('standard', '')).startswith(p)
                                for p in _blanket_cert_prefixes))
            ]
    except ImportError:
        pass

    # Apply power_rails config (ignore/flag/voltage_overrides)
    try:
        from project_config import apply_power_rails_config
        stats = result.get('statistics', {})
        rv = result.get('rail_voltages', {})
        pr = stats.get('power_rails', [])
        if rv or pr:
            filtered_rv, filtered_pr, flagged = apply_power_rails_config(
                rv, pr, config)
            result['rail_voltages'] = filtered_rv
            stats['power_rails'] = filtered_pr
            if flagged:
                result['flagged_rails'] = flagged
    except (ImportError, Exception):
        pass

    # rc.2 4.3 — LC-007 lifecycle-skipped INFO finding. Emit explicitly so
    # reviewers see "lifecycle audit not run" in the findings list rather
    # than silently missing it. Fires in three cases:
    #   1. --lifecycle flag was not passed (most common — high frequency)
    #   2. --lifecycle passed but no MPNs in BOM
    #   3. --lifecycle passed but the audit raised an exception
    _lifecycle_skip_reason: str | None = None
    if not args.lifecycle:
        _lifecycle_skip_reason = (
            "--lifecycle flag not passed (run with --lifecycle to query "
            "DigiKey / Mouser / LCSC / element14 for obsolescence + "
            "operating-temp coverage; requires network + API keys)"
        )
    else:
        try:
            from lifecycle_audit import audit_bom
            project_dir = str(Path(args.schematic).parent)
            lifecycle = audit_bom(result, project_dir=project_dir)
            if lifecycle and lifecycle.get("components_checked", 0) > 0:
                result["lifecycle_audit"] = lifecycle
                print(f"Lifecycle: {lifecycle.get('lifecycle_summary', {})}", file=sys.stderr)
            else:
                _lifecycle_skip_reason = (
                    "no components with MPNs to check — populate MPN "
                    "fields on BOM parts and re-run with --lifecycle"
                )
                print("Lifecycle: no components with MPNs to check", file=sys.stderr)
        except ImportError:
            _lifecycle_skip_reason = "lifecycle_audit.py not found"
            print("Warning: lifecycle_audit.py not found", file=sys.stderr)
        except (OSError, ValueError, TypeError, KeyError) as e:
            _lifecycle_skip_reason = f"audit raised {type(e).__name__}: {e}"
            print(f"Warning: lifecycle audit failed: {e}", file=sys.stderr)

    if _lifecycle_skip_reason is not None:
        if 'findings' not in result:
            result['findings'] = []
        result['findings'].append({
            "detector": "audit_lifecycle_skipped",
            "rule_id": "LC-007",
            "severity": "info",
            "confidence": "deterministic",
            "evidence_source": "topology",
            "category": "lifecycle",
            "summary": f"Lifecycle audit not run — {_lifecycle_skip_reason.split(' (')[0]}",
            "description": (
                f"Component lifecycle / obsolescence audit was not run "
                f"this session. Reason: {_lifecycle_skip_reason}. The "
                f"review cannot report active / NRND / EOL / obsolete "
                f"status, last-time-buy windows, or operating-temperature "
                f"coverage for any BOM part. Treat the lifecycle section "
                f"of the report as 'not performed'."
            ),
            "components": [],
            "nets": [],
            "pins": [],
            "recommendation": (
                "Run with --lifecycle (requires DIGIKEY_CLIENT_ID / "
                "MOUSER_SEARCH_API_KEY / ELEMENT14_API_KEY env vars; "
                "LCSC needs no auth) to populate this section. If "
                "intentionally skipped, note it explicitly in the report's "
                "'Not Performed' section."
            ),
            "report_context": {
                "section": "Component Lifecycle",
                "impact": "No obsolescence / temperature-grade evidence available.",
                "standard_ref": "",
            },
        })

    # Datasheet verification — cross-check extracted datasheet data against schematic
    try:
        # Import datasheet_verify from the datasheets skill
        import os as _os, sys as _sys
        _ds_scripts = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                    '..', '..', 'datasheets', 'scripts')
        if _os.path.isdir(_ds_scripts):
            _sys.path.insert(0, _os.path.abspath(_ds_scripts))
        from datasheet_verify import run_datasheet_verification
        project_dir = str(Path(args.schematic).parent)
        ds_verify = run_datasheet_verification(result, project_dir=project_dir)
        if ds_verify.get("findings") or ds_verify.get("summary", {}).get("ics_with_extractions", 0) > 0:
            result["datasheet_verification"] = ds_verify
    except ImportError:
        pass
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        # AttributeError added for rc.3 — defense against future None-leaks
        # in datasheet_verify.py (see _load_extraction normalization).
        result["datasheet_verification"] = {
            "findings": [],
            "summary": {"error": f"{type(e).__name__}: {e}"},
        }

    from output_filters import apply_output_filters
    apply_output_filters(result, args.stage, args.audience)

    # Recompute summary + trust_summary from the final findings list — post-
    # filters (CERT-001 hobby gating, power_rails config, lifecycle audit,
    # datasheet verification, output_filters stage filter) can mutate
    # findings[] after the initial summary was built. Keep the envelope
    # consistent with what actually ships in findings[].
    _final_findings = result.get('findings', []) if isinstance(result.get('findings'), list) else []
    _sev_counts = {"error": 0, "warning": 0, "info": 0}
    for _f in _final_findings:
        if not isinstance(_f, dict):
            continue
        _s = str(_f.get('severity', 'info')).lower()
        if _s in _sev_counts:
            _sev_counts[_s] += 1
        else:
            _sev_counts['info'] += 1
    if isinstance(result.get('summary'), dict):
        result['summary']['total_findings'] = len(_final_findings)
        result['summary']['by_severity'] = _sev_counts
    try:
        from finding_schema import compute_trust_summary
        result['trust_summary'] = compute_trust_summary(_final_findings, bom=result.get('bom'))
    except (ImportError, Exception):
        pass

    # Guarantee every finding carries a stable finding_id (Layer 2 merge keys
    # on it). Runs after all filtering/appends; before any output branch.
    assign_finding_ids(result.get('findings', []), 'schematic')

    if args.text:
        from output_filters import format_text
        print(format_text(result.get('findings', []), args.audience or 'designer', args.stage))
        sys.exit(0)

    # Wire capability_mode_ref (Phase 4 spec §3.3). Already resolved early
    # so inputs.run_id and capability_mode_ref.run_id match.
    result["capability_mode_ref"] = _capability_mode_ref

    indent = None if args.compact else 2
    output = json.dumps(result, indent=indent, default=str)

    if args.analysis_dir:
        import tempfile
        from analysis_cache import (hash_source_file,
                                     should_create_new_run, create_run,
                                     overwrite_current, CANONICAL_OUTPUTS,
                                     resolve_analysis_dir)

        project_dir = str(Path(args.schematic).parent)
        analysis_dir = resolve_analysis_dir(args.analysis_dir)

        # Find .kicad_pro for manifest
        pro_file = ""
        try:
            for f in os.listdir(project_dir):
                if f.endswith(".kicad_pro"):
                    pro_file = f
                    break
        except OSError:
            pass

        # Ensure the target directory exists with manifest
        os.makedirs(analysis_dir, exist_ok=True)
        from analysis_cache import MANIFEST_FILENAME, save_manifest, _empty_manifest, GITIGNORE_CONTENT
        manifest_path = os.path.join(analysis_dir, MANIFEST_FILENAME)
        if not os.path.isfile(manifest_path):
            manifest = _empty_manifest()
            manifest['project'] = pro_file
            save_manifest(analysis_dir, manifest)
        # Respect track_in_git config — skip .gitignore if user wants git tracking
        _track_in_git = False
        try:
            _track_in_git = config.get('analysis', {}).get('track_in_git', False)
        except (NameError, AttributeError):
            pass
        gitignore_path = os.path.join(analysis_dir, '.gitignore')
        if not _track_in_git and not os.path.isfile(gitignore_path):
            with open(gitignore_path, 'w') as f:
                f.write(GITIGNORE_CONTENT)

        source_hashes = {os.path.basename(args.schematic): hash_source_file(args.schematic)}

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, CANONICAL_OUTPUTS.get("schematic", "schematic.json"))
            Path(out_file).write_text(output)

            if should_create_new_run(analysis_dir, tmp_dir):
                run_id = create_run(
                    analysis_dir=analysis_dir,
                    outputs_dir=tmp_dir,
                    source_hashes=source_hashes,
                    scripts={"schematic": f"analyze_schematic.py {os.path.basename(args.schematic)}"},
                )
                print(f"Analysis cached: {os.path.join(analysis_dir, run_id, 'schematic.json')}", file=sys.stderr)
            else:
                overwrite_current(analysis_dir, tmp_dir, source_hashes=source_hashes)
                print(f"Analysis cache updated (current run)", file=sys.stderr)

    elif args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()

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
import os
import sys
from pathlib import Path

# Add scripts dir to path for kicad_core
sys.path.insert(0, str(Path(__file__).parent))
from schematic.pipeline import (
    analyze_schematic,
    analyze_signal_paths,
    parse_legacy_schematic,
    analyze_legacy_schematic,
    finalize_for_cli,
    ANALYZER_SOURCE,
    MAX_TESTED_FORMAT_VERSION,
    _resolve_lookup_paths,
    _build_net_classifications,
)
from kicad_core.netnames import _clean_hierarchical_name, _UUID_RE
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
    classify_ic_pinout_role as _classify_ic_function,
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
from schematic.bom_stats import (
    generate_bom,
    compute_statistics,
)
from envelopes.schematic import SchematicEnvelope
from schema_codec import emit_schema
from inputs_builder import build_inputs, build_compat
from capability_mode import get_capability_mode_ref
from kicad_core.cli import (add_compact_arg, add_config_arg, add_only_deterministic_arg,
                            add_output_arg, add_schema_arg, add_stage_audience_args, add_text_arg)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="KiCad Schematic Analyzer")
    parser.add_argument("schematic", nargs="?",
                        help="Path to .kicad_sch, .kicad_pro, or project directory")
    add_output_arg(parser)
    add_compact_arg(parser)
    add_schema_arg(parser)
    add_config_arg(parser)
    parser.add_argument("--project-root", default=None,
                        help="Root .kicad_sch for hierarchy context (auto-discovered if omitted)")
    parser.add_argument("--no-hierarchy", action="store_true",
                        help="Disable hierarchy auto-discovery (treat file as standalone root)")
    parser.add_argument("--lifecycle", action="store_true",
                        help="Run lifecycle/obsolescence audit (requires network + API keys)")
    parser.add_argument("--analysis-dir", default=None,
                        help="Write output to analysis cache directory (timestamped runs)")
    add_text_arg(parser, help="Print human-readable text report to stdout")
    add_stage_audience_args(parser)
    add_only_deterministic_arg(parser)
    args = parser.parse_args(argv)

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
    from project_config import resolve_config
    resolved_cfg = resolve_config(args.config, str(Path(args.schematic).parent))
    config = resolved_cfg.effective
    _acfg = config.get("analysis")
    analysis_cfg = _acfg if isinstance(_acfg, dict) else {}

    # Resolve canonical analysis_dir ONCE — used for both AnalysisContext
    # (Phase 4d-active) and capability_mode_ref (Phase 4 §3.3). This must
    # be the same path so `--analysis-dir X` writes outputs AND capability
    # mode to the same X, not to ./analysis (audit Highest-Risk #4).
    if args.analysis_dir:
        _analysis_dir_for_ctx = Path(args.analysis_dir)
    elif args.output:
        _analysis_dir_for_ctx = Path(args.output).parent
    else:
        _analysis_dir_for_ctx = Path(analysis_cfg.get("output_dir") or "analysis")

    # Resolve capability_mode_ref BEFORE build_inputs so inputs.run_id ==
    # capability_mode_ref.run_id (Phase 4 spec §3.3, audit Highest-Risk #5).
    # First-writer-wins side effect: creates capability_mode.json if absent.
    _capability_mode_ref = get_capability_mode_ref(_analysis_dir_for_ctx)

    # Build inputs provenance block (Track 1.3).
    _sch_path = Path(args.schematic)
    _cfg_path = Path(resolved_cfg.hash_input) if resolved_cfg.hash_input else None
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

    finalize_for_cli(result, config, schematic_path=args.schematic, lifecycle=args.lifecycle,
                     stage=args.stage, audience=args.audience)

    if args.text:
        from output_filters import format_text
        print(format_text(result.get('findings', []), args.audience or 'designer', args.stage))
        return 0

    # Wire capability_mode_ref (Phase 4 spec §3.3). Already resolved early
    # so inputs.run_id and capability_mode_ref.run_id match.
    result["capability_mode_ref"] = _capability_mode_ref

    indent = None if args.compact else 2
    output = json.dumps(result, indent=indent, default=str)

    if args.analysis_dir:
        from output_io import write_primary_run
        write_primary_run(args.analysis_dir, output, analyzer="schematic", source_path=args.schematic,
                          script_name="analyze_schematic.py",
                          track_in_git=bool(analysis_cfg.get("track_in_git", False)),
                          diff_threshold=analysis_cfg.get("diff_threshold", "major"),
                          retention=int(analysis_cfg.get("retention", 0) or 0))
    elif args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

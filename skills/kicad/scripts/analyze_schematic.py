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
from schematic.bom_stats import (
    generate_bom,
    compute_statistics,
)
from finding_schema import assign_finding_ids
from envelopes.schematic import SchematicEnvelope
from schema_codec import emit_schema
from inputs_builder import build_inputs, build_compat
from capability_mode import get_capability_mode_ref


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

#!/usr/bin/env python3
"""Markdown scaffold generator for engineering documentation.

Reads analysis JSONs and .kicad-happy.json config to produce a structured
markdown document with `<!-- GENERATED: section_id -->` markers for
regeneratable content and narrative placeholders for Claude/user prose.

Usage:
    python3 kidoc_scaffold.py --project-dir . --type hdd --output reports/HDD.md
    python3 kidoc_scaffold.py --project-dir . --type design_review --output reports/DR.md
    python3 kidoc_scaffold.py --project-dir . --config .kicad-happy.json --output reports/

Explicit analyzer JSON inputs (bypass the analysis cache lookup — useful
for harness batch runs and any caller that already has analyzer outputs
on disk but not organised under an analysis/manifest.json convention):

    python3 kidoc_scaffold.py --schematic-json sch.json --pcb-json pcb.json \\
        --emc-json emc.json --thermal-json thermal.json --type hdd \\
        --output reports/HDD.md

Zero external dependencies — Python 3.8+ stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_kicad_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', '..', 'kicad', 'scripts')
if os.path.isdir(_kicad_scripts):
    sys.path.insert(0, os.path.abspath(_kicad_scripts))

from kidoc_sections import (
    section_front_matter, section_executive_summary,
    section_system_overview, section_power_design,
    section_signal_interfaces, section_analog_design, section_thermal,
    section_emc, section_pcb_design, section_bom_summary,
    section_test_debug, section_compliance, section_appendix_schematics,
    section_mechanical_environmental,
    # CE Technical File
    section_ce_product_identification, section_ce_essential_requirements,
    section_ce_harmonized_standards, section_ce_risk_assessment,
    section_ce_declaration_of_conformity,
    # Design Review
    section_review_summary, section_review_action_items,
    # ICD
    section_icd_interface_list, section_icd_connector_details,
    section_icd_electrical_characteristics,
    # Manufacturing
    section_mfg_assembly_overview, section_mfg_pcb_fab_notes,
    section_mfg_assembly_instructions, section_mfg_test_procedures,
)
from kidoc_templates import get_section_list, get_document_title

# Try to import project_config for cascading config loading
try:
    from project_config import load_config, load_config_from_path
except ImportError:
    def load_config(search_dir):
        return {'version': 1, 'project': {}, 'suppressions': []}
    def load_config_from_path(path):
        return {'version': 1, 'project': {}, 'suppressions': []}


# ======================================================================
# Analysis cache loading
# ======================================================================

def load_analysis_cache(project_dir: str,
                        cache_dir: str | None = None) -> dict:
    """Load all analysis JSONs from the analysis/ manifest.

    Uses the manifest.json in the analysis directory to find the current
    run folder and load all output JSONs from it.

    Falls back to direct file search in cache_dir or project_dir if
    no manifest exists (for backwards compat during transition).

    Args:
        project_dir: Root directory of the KiCad project.
        cache_dir: Override analysis directory path.

    Returns dict with keys: schematic, pcb, emc, thermal, spice, gate.
    """
    cache = {}

    # Determine analysis directory
    analysis_dir = cache_dir
    if not analysis_dir:
        # Read output_dir from config
        try:
            from project_config import load_config
            config = load_config(project_dir)
            analysis_dir = os.path.join(
                project_dir,
                config.get('analysis', {}).get('output_dir', 'analysis'))
        except ImportError:
            analysis_dir = os.path.join(project_dir, 'analysis')

    # Try manifest-based loading
    manifest_path = os.path.join(analysis_dir, 'manifest.json')
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            current_id = manifest.get('current')
            if current_id and current_id in manifest.get('runs', {}):
                run_dir = os.path.join(analysis_dir, current_id)
                run_meta = manifest['runs'][current_id]
                for analysis_type, filename in run_meta.get('outputs', {}).items():
                    filepath = os.path.join(run_dir, filename)
                    if os.path.isfile(filepath):
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                cache[analysis_type] = json.load(f)
                        except json.JSONDecodeError:
                            pass
                return cache
        except (json.JSONDecodeError, OSError):
            pass  # Fall through to empty return

    # No manifest -- return empty cache
    return cache


def _load_explicit_jsons(paths: dict) -> dict:
    """Load analyzer JSONs from explicit CLI-provided paths.

    Bypasses the manifest-based analysis cache lookup entirely. Used
    when a caller (e.g., a batch harness runner) already has analyzer
    outputs on disk and doesn't want kidoc to run its own discovery.

    Args:
        paths: dict mapping analysis type key ('schematic', 'pcb', 'emc',
            'thermal') to file path, or None for unprovided types.

    Returns:
        dict mapping analysis type to loaded JSON dict, for paths that
        were provided and loaded successfully. Types with a None path
        are skipped. Types with an unreadable or malformed file cause
        an error and sys.exit(1) — this function assumes explicit paths
        are authoritative and should fail loudly rather than silently
        skip.
    """
    cache = {}
    for analysis_type, path in paths.items():
        if path is None:
            continue
        if not os.path.isfile(path):
            print(f"Error: {analysis_type} JSON not found: {path}",
                  file=sys.stderr)
            sys.exit(1)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error: cannot load {analysis_type} JSON {path}: {e}",
                  file=sys.stderr)
            sys.exit(1)
        if ('signal_analysis' in data and 'findings' not in data
                and analysis_type == 'schematic'):
            print(f"Error: {path} uses the pre-v1.3 signal_analysis "
                  f"wrapper format.\nRe-run analyze_schematic.py to "
                  f"produce the current findings[] format.",
                  file=sys.stderr)
            sys.exit(1)
        cache[analysis_type] = data
    return cache


# ======================================================================
# Template variable resolution
# ======================================================================

def resolve_template_vars(text: str, config: dict) -> str:
    """Replace {project}, {rev}, etc. placeholders."""
    project = config.get('project', {})
    replacements = {
        '{project}': project.get('name', ''),
        '{rev}': project.get('revision', ''),
        '{company}': project.get('company', ''),
        '{number}': project.get('number', ''),
        '{classification}': config.get('reports', {}).get('classification', ''),
        '{author}': project.get('author', ''),
    }
    for key, val in replacements.items():
        text = text.replace(key, val)
    return text


# ======================================================================
# Scaffold generation
# ======================================================================

def scaffold_document(project_dir: str, doc_type: str, output_path: str,
                      config: dict,
                      analysis_cache: dict | None = None,
                      analysis_dir: str | None = None,
                      spec: dict | None = None) -> str:
    """Generate a markdown scaffold for the specified document type.

    Returns the markdown content (also writes to output_path).
    """
    if analysis_cache is None:
        analysis_cache = load_analysis_cache(project_dir)

    analysis = analysis_cache.get('schematic', {})
    pcb_data = analysis_cache.get('pcb')
    emc_data = analysis_cache.get('emc')
    thermal_data = analysis_cache.get('thermal')

    # Determine paths for diagrams and schematic SVGs.
    # Figures live under reports/figures/ (git-tracked), separate from
    # analysis/ (gitignored, managed by analysis_cache.py) which holds JSON data.
    output_abs = os.path.abspath(output_path)
    reports_root = os.path.dirname(output_abs)
    figures_base = os.path.join(reports_root, 'figures')
    diagrams_dir = os.path.join(figures_base, 'diagrams')
    sch_cache_dir = os.path.join(figures_base, 'schematics')

    # Use relative paths from the output file's directory
    output_dir = os.path.dirname(os.path.abspath(output_path))
    try:
        diagrams_rel = os.path.relpath(diagrams_dir, output_dir)
        sch_cache_rel = os.path.relpath(sch_cache_dir, output_dir)
    except ValueError:
        diagrams_rel = diagrams_dir
        sch_cache_rel = sch_cache_dir

    # Get sections for this document type (spec overrides config overrides)
    if spec:
        from kidoc_spec import get_section_types
        sections = get_section_types(spec)
    else:
        sections = get_section_list(doc_type, config)

    gate_data = analysis_cache.get('gate')

    # Build markdown
    parts = []

    section_map = {
        # Core sections (HDD)
        'front_matter': lambda: section_front_matter(config, doc_type),
        'executive_summary': lambda: section_executive_summary(analysis, emc_data, thermal_data, pcb_data),
        'system_overview': lambda: section_system_overview(analysis, diagrams_rel),
        'power_design': lambda: section_power_design(analysis, diagrams_rel),
        'signal_interfaces': lambda: section_signal_interfaces(analysis),
        'analog_design': lambda: section_analog_design(analysis, diagrams_rel),
        'thermal_analysis': lambda: section_thermal(thermal_data),
        'emc_analysis': lambda: section_emc(emc_data),
        'pcb_design': lambda: section_pcb_design(pcb_data),
        'mechanical_environmental': lambda: section_mechanical_environmental(analysis, pcb_data),
        'bom_summary': lambda: section_bom_summary(analysis),
        'test_debug': lambda: section_test_debug(analysis),
        'compliance': lambda: section_compliance(analysis, emc_data, config),
        'appendix_schematics': lambda: section_appendix_schematics(sch_cache_rel, analysis, sch_cache_dir),
        # CE Technical File
        'ce_product_identification': lambda: section_ce_product_identification(analysis, config),
        'ce_essential_requirements': lambda: section_ce_essential_requirements(analysis, config),
        'ce_harmonized_standards': lambda: section_ce_harmonized_standards(config),
        'ce_risk_assessment': lambda: section_ce_risk_assessment(analysis, emc_data, thermal_data),
        'ce_declaration_of_conformity': lambda: section_ce_declaration_of_conformity(config),
        # Design Review
        'review_summary': lambda: section_review_summary(analysis, emc_data, thermal_data, gate_data),
        'review_action_items': lambda: section_review_action_items(config),
        # ICD
        'icd_interface_list': lambda: section_icd_interface_list(analysis),
        'icd_connector_details': lambda: section_icd_connector_details(analysis, config),
        'icd_electrical_characteristics': lambda: section_icd_electrical_characteristics(analysis),
        # Manufacturing
        'mfg_assembly_overview': lambda: section_mfg_assembly_overview(analysis),
        'mfg_pcb_fab_notes': lambda: section_mfg_pcb_fab_notes(pcb_data),
        'mfg_assembly_instructions': lambda: section_mfg_assembly_instructions(analysis),
        'mfg_test_procedures': lambda: section_mfg_test_procedures(analysis),
    }

    for section_name in sections:
        generator = section_map.get(section_name)
        if generator:
            content = generator()
            if content is not None:
                parts.append(content)

    markdown = "\n".join(parts)

    # Resolve template variables
    markdown = resolve_template_vars(markdown, config)

    # Write output (overwrites — use git to track/merge user edits)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(markdown)

    return markdown


# ======================================================================
# Auto-run analyses
# ======================================================================

def _auto_run_analyses(project_dir: str, analysis_dir: str,
                       figures_dir: str | None = None,
                       sch_path: str | None = None,
                       pcb_path: str | None = None) -> dict[str, bool]:
    """Auto-run available analyses that haven't been generated yet.

    Args:
        figures_dir: Base directory for generated figures (diagrams, schematics).
            Defaults to ``analysis_dir`` parent's ``figures/`` sibling when None.

    Returns dict of {analysis_name: was_run_successfully} for reporting.
    """
    if figures_dir is None:
        # Default: reports/figures/ (sibling of analysis output)
        figures_dir = os.path.join(os.path.dirname(os.path.normpath(analysis_dir)),
                                   '..', 'figures')
    results = {}
    scripts_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', '..', 'kicad', 'scripts'))

    os.makedirs(analysis_dir, exist_ok=True)

    # Auto-detect schematic and PCB files if not specified
    if not sch_path:
        for f in Path(project_dir).rglob('*.kicad_sch'):
            sch_path = str(f)
            break
    if not pcb_path:
        for f in Path(project_dir).rglob('*.kicad_pcb'):
            pcb_path = str(f)
            break

    def _run_analysis(name: str, cmd: list[str]) -> None:
        """Run an analysis subprocess with timeout, recording result."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120)
            results[name] = result.returncode == 0
        except subprocess.TimeoutExpired:
            results[name] = False

    # Schematic analysis
    sch_json = os.path.join(analysis_dir, 'schematic.json')
    if sch_path and not os.path.isfile(sch_json):
        analyzer = os.path.join(scripts_dir, 'analyze_schematic.py')
        if os.path.isfile(analyzer):
            _run_analysis('schematic',
                          [sys.executable, analyzer, sch_path,
                           '--output', sch_json])

    # PCB analysis
    pcb_json = os.path.join(analysis_dir, 'pcb.json')
    if pcb_path and not os.path.isfile(pcb_json):
        analyzer = os.path.join(scripts_dir, 'analyze_pcb.py')
        if os.path.isfile(analyzer):
            _run_analysis('pcb',
                          [sys.executable, analyzer, pcb_path,
                           '--output', pcb_json])

    # EMC analysis (requires both schematic + PCB JSONs)
    emc_json = os.path.join(analysis_dir, 'emc.json')
    if (os.path.isfile(sch_json) and os.path.isfile(pcb_json)
            and not os.path.isfile(emc_json)):
        emc_scripts = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', '..', 'emc', 'scripts'))
        analyzer = os.path.join(emc_scripts, 'analyze_emc.py')
        if os.path.isfile(analyzer):
            _run_analysis('emc',
                          [sys.executable, analyzer,
                           '--schematic', sch_json, '--pcb', pcb_json,
                           '--output', emc_json])

    # Thermal analysis (requires both schematic + PCB JSONs)
    thermal_json = os.path.join(analysis_dir, 'thermal.json')
    if (os.path.isfile(sch_json) and os.path.isfile(pcb_json)
            and not os.path.isfile(thermal_json)):
        analyzer = os.path.join(scripts_dir, 'analyze_thermal.py')
        if os.path.isfile(analyzer):
            _run_analysis('thermal',
                          [sys.executable, analyzer,
                           '--schematic', sch_json, '--pcb', pcb_json,
                           '--output', thermal_json])

    # Figures (diagrams + charts from schematic analysis JSON)
    # Run via venv so matplotlib generators can render
    diagrams_dir = os.path.join(os.path.normpath(figures_dir), 'diagrams')
    if os.path.isfile(sch_json):
        try:
            from kidoc_venv import ensure_venv
            venv_py = ensure_venv(project_dir)
        except Exception as exc:
            print(f"  Warning: venv setup failed ({exc}), "
                  f"matplotlib figures will be skipped",
                  file=sys.stderr)
            venv_py = sys.executable

        diagrams_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'kidoc_diagrams.py')
        cmd = [venv_py, diagrams_script,
               '--analysis', sch_json,
               '--output', diagrams_dir]
        if os.path.isfile(emc_json):
            cmd.extend(['--emc', emc_json])
        if os.path.isfile(thermal_json):
            cmd.extend(['--thermal', thermal_json])
        spice_json = os.path.join(analysis_dir, 'spice.json')
        if os.path.isfile(spice_json):
            cmd.extend(['--spice', spice_json])
        _run_analysis('diagrams', cmd)

    # Schematic SVG renders (requires .kicad_sch)
    sch_cache_dir = os.path.join(os.path.normpath(figures_dir), 'schematics')
    if sch_path and not os.path.isdir(sch_cache_dir):
        try:
            from figures.renderers import render_schematic
            os.makedirs(sch_cache_dir, exist_ok=True)
            paths = render_schematic(sch_path, sch_cache_dir)
            results['renders'] = bool(paths)
        except (OSError, ValueError) as exc:
            print(f"  Warning: schematic render failed: {exc}",
                  file=sys.stderr)
            results['renders'] = False

    return results


def _print_analysis_summary(results: dict, analysis_dir: str,
                            figures_dir: str | None = None) -> None:
    """Print what analyses are available and what's missing."""
    available = []
    missing = []

    checks = {
        'schematic': 'schematic.json',
        'pcb': 'pcb.json',
        'emc': 'emc.json',
        'thermal': 'thermal.json',
        'spice': 'spice.json',
    }

    for name, filename in checks.items():
        path = os.path.join(analysis_dir, filename)
        if os.path.isfile(path):
            if name in results:
                available.append(f"  {name}: auto-generated")
            else:
                available.append(f"  {name}: found")
        else:
            if name in results:
                missing.append(f"  {name}: auto-run failed")
            elif name == 'spice':
                missing.append(f"  {name}: requires manual SPICE simulation")
            else:
                missing.append(f"  {name}: not available (no source data)")

    # Check diagrams and renders (under figures/ directory)
    fig_base = figures_dir or os.path.join(
        os.path.dirname(os.path.normpath(analysis_dir)), '..', 'figures')
    diagrams_dir = os.path.join(os.path.normpath(fig_base), 'diagrams')
    if os.path.isdir(diagrams_dir):
        if 'diagrams' in results:
            available.append("  diagrams: auto-generated")
        else:
            available.append("  diagrams: found")
    else:
        missing.append("  diagrams: not generated")

    sch_fig_dir = os.path.join(os.path.normpath(fig_base), 'schematics')
    if os.path.isdir(sch_fig_dir):
        if 'renders' in results:
            available.append("  renders: auto-generated")
        else:
            available.append("  renders: found")
    else:
        missing.append("  renders: not generated (needs kicad-cli)")

    if available:
        print("Analysis data:", file=sys.stderr)
        for a in available:
            print(a, file=sys.stderr)
    if missing:
        print("Not included (run separately to add):", file=sys.stderr)
        for m in missing:
            print(m, file=sys.stderr)


# ======================================================================
# Main
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate markdown scaffold for engineering documentation')
    parser.add_argument('--project-dir', '-p', default='.',
                        help='Path to KiCad project directory')
    parser.add_argument('--type', '-t', default='hdd',
                        choices=['hdd', 'ce_technical_file', 'design_review',
                                 'icd', 'manufacturing',
                                 'schematic_review', 'power_analysis',
                                 'emc_report'],
                        help='Document type (default: hdd)')
    parser.add_argument('--spec', default=None,
                        help='Path to document spec JSON (overrides --type)')
    parser.add_argument('--output', '-o', required=True,
                        help='Output markdown file path')
    parser.add_argument('--config', default=None,
                        help='Path to .kicad-happy.json config')
    parser.add_argument('--analysis-dir', default=None,
                        help='Directory containing analysis JSONs')
    parser.add_argument('--analyze', action='store_true',
                        help='Run KiCad analysis scripts if no analysis data '
                             'exists. Without this flag, errors when analysis '
                             'is missing.')
    parser.add_argument('--schematic-json', default=None,
                        help='Explicit path to schematic analyzer JSON. '
                             'When any of --schematic-json/--pcb-json/'
                             '--emc-json/--thermal-json is provided, the '
                             'manifest-based analysis cache lookup is '
                             'bypassed entirely.')
    parser.add_argument('--pcb-json', default=None,
                        help='Explicit path to PCB analyzer JSON. See '
                             '--schematic-json for mode notes.')
    parser.add_argument('--emc-json', default=None,
                        help='Explicit path to EMC analyzer JSON. See '
                             '--schematic-json for mode notes.')
    parser.add_argument('--thermal-json', default=None,
                        help='Explicit path to thermal analyzer JSON. See '
                             '--schematic-json for mode notes.')
    args = parser.parse_args()

    # Load spec (--spec overrides --type)
    if args.spec:
        from kidoc_spec import load_spec
        spec = load_spec(args.spec)
        doc_type = spec.get('type', 'custom')
    else:
        from kidoc_spec import load_builtin_spec
        spec = load_builtin_spec(args.type)
        doc_type = args.type

    # Load config
    if args.config:
        config = load_config_from_path(args.config)
    else:
        config = load_config(args.project_dir)

    # Determine analysis directory from config or CLI
    if args.analysis_dir:
        analysis_dir = args.analysis_dir
    else:
        analysis_dir = os.path.join(
            args.project_dir,
            config.get('analysis', {}).get('output_dir', 'analysis'))

    # Figures (diagrams, schematics) go under reports/figures/ (git-tracked),
    # separate from analysis/ which holds analysis JSONs.
    output_dir = os.path.dirname(os.path.abspath(args.output))
    figures_dir = os.path.join(output_dir, 'figures')

    # Explicit JSON inputs bypass the manifest-based cache entirely.
    # If any of --schematic-json/--pcb-json/--emc-json/--thermal-json
    # is provided, _load_explicit_jsons is authoritative and we skip
    # both the cache lookup and --analyze auto-run.
    explicit_jsons = {
        'schematic': args.schematic_json,
        'pcb': args.pcb_json,
        'emc': args.emc_json,
        'thermal': args.thermal_json,
    }
    has_explicit = any(p is not None for p in explicit_jsons.values())

    if has_explicit:
        if args.analyze:
            print('Error: --analyze cannot be combined with explicit '
                  '--schematic-json/--pcb-json/--emc-json/--thermal-json '
                  'flags. Explicit JSONs bypass the analysis pipeline; '
                  'drop --analyze or drop the explicit flags.',
                  file=sys.stderr)
            sys.exit(1)
        cache = _load_explicit_jsons(explicit_jsons)
    else:
        # Load analysis cache from manifest
        cache = load_analysis_cache(args.project_dir, analysis_dir)

        if not cache:
            if args.analyze:
                # Run analyses using existing _auto_run_analyses
                auto_results = _auto_run_analyses(args.project_dir, analysis_dir,
                                                   figures_dir=figures_dir)
                cache = load_analysis_cache(args.project_dir, analysis_dir)
                _print_analysis_summary(auto_results, analysis_dir,
                                        figures_dir=figures_dir)
                if not cache:
                    print('Error: Analysis scripts ran but produced no output.',
                          file=sys.stderr)
                    sys.exit(1)
            else:
                print(f'Error: No analysis data found in '
                      f'{analysis_dir}.\n'
                      'Run with --analyze to generate it, or run the '
                      'KiCad analysis skill first.',
                      file=sys.stderr)
                sys.exit(1)

    # Generate scaffold
    scaffold_document(
        project_dir=args.project_dir,
        doc_type=doc_type,
        output_path=args.output,
        config=config,
        analysis_cache=cache,
        analysis_dir=analysis_dir,
        spec=spec,
    )

    print(args.output, file=sys.stderr)


if __name__ == '__main__':
    main()

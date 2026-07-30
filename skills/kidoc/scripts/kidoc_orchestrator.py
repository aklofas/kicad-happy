#!/usr/bin/env python3
"""Render orchestrator for kidoc document generation.

Coordinates all figure generation for a report based on the document
spec.  All figures — schematic overviews, subsystem crops, PCB views,
block diagrams, pinouts, and analysis charts — go through the
registered generator framework with tracked JSON inputs.

Usage:
    python3 kidoc_orchestrator.py --spec spec.json --project-dir . --output reports/figures/
    python3 kidoc_orchestrator.py --analysis schematic.json --project-dir . --output reports/figures/

Zero external dependencies -- Python 3.8+ stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure this script's directory is on sys.path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kidoc_spec import load_spec, expand_type_to_spec
from figures import run_all, FigureTheme


# ======================================================================
# File auto-detection
# ======================================================================

def _find_file(project_dir: str, suffix: str) -> Optional[str]:
    """Find the first file with *suffix* under *project_dir*."""
    for f in Path(project_dir).rglob(f'*{suffix}'):
        return str(f)
    return None


# ======================================================================
# Main orchestrator
# ======================================================================

def orchestrate_renders(spec: dict, project_dir: str,
                        analysis: dict,
                        figures_dir: str,
                        sch_path: Optional[str] = None,
                        pcb_path: Optional[str] = None,
                        config: Optional[dict] = None
                        ) -> Dict[str, List[str]]:
    """Generate all figures for a report based on the document spec.

    All figure generation goes through the registered generator framework.
    The analysis dict is augmented with ``_sch_path``, ``_pcb_path``, and
    ``_spec_sections`` so generators can access project files and spec data.

    Args:
        spec: document spec dict (from kidoc_spec.py)
        project_dir: KiCad project directory
        analysis: loaded schematic analysis JSON
        figures_dir: base output directory (e.g., reports/figures/)
        sch_path: path to .kicad_sch (auto-detected if None)
        pcb_path: path to .kicad_pcb (auto-detected if None)
        config: project config from .kicad-happy.json

    Returns:
        dict mapping category -> list of generated figure paths
    """
    config = config or {}

    # Auto-detect project files
    if not sch_path:
        sch_path = _find_file(project_dir, '.kicad_sch')
    if not pcb_path:
        pcb_path = _find_file(project_dir, '.kicad_pcb')

    # Augment analysis with paths and spec sections so generators
    # can access them via the standard prepare(analysis, config) interface
    augmented = dict(analysis) if analysis else {}
    if sch_path:
        augmented['_sch_path'] = sch_path
    if pcb_path:
        augmented['_pcb_path'] = pcb_path
    augmented['_spec_sections'] = spec.get('sections', [])

    # Run all generators through the framework
    print(f"  Generating figures into {figures_dir}", file=sys.stderr)
    paths = run_all(augmented, config, figures_dir)

    result: Dict[str, List[str]] = {}
    if paths:
        result['_figures'] = paths

    return result


# ======================================================================
# CLI
# ======================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Render orchestrator for kidoc document generation')
    parser.add_argument('--spec', '-s', default=None,
                        help='Path to document spec JSON '
                             '(default: auto-generate from analysis)')
    parser.add_argument('--analysis', '-a', default=None,
                        help='Path to schematic analysis JSON')
    parser.add_argument('--project-dir', '-p', required=True,
                        help='KiCad project directory')
    parser.add_argument('--output', '-o', required=True,
                        help='Output directory for figures')
    parser.add_argument('--sch', default=None,
                        help='Path to .kicad_sch (auto-detected if omitted)')
    parser.add_argument('--pcb', default=None,
                        help='Path to .kicad_pcb (auto-detected if omitted)')
    parser.add_argument('--config', default=None,
                        help='Path to .kicad-happy.json config '
                             '(for branding/theme)')
    parser.add_argument('--emc', default=None,
                        help='Path to EMC analysis JSON')
    parser.add_argument('--thermal', default=None,
                        help='Path to thermal analysis JSON')
    parser.add_argument('--spice', default=None,
                        help='Path to SPICE results JSON')
    parser.add_argument('--analyze', action='store_true',
                        help='Run KiCad analysis scripts if no analysis data '
                             'exists.')
    args = parser.parse_args()

    # Load or generate spec
    if args.spec:
        spec = load_spec(args.spec)
    else:
        spec = expand_type_to_spec('hdd')

    # Load analysis and merge supplemental data
    analysis = {}
    if args.analysis:
        with open(args.analysis) as f:
            analysis = json.load(f)

    # If no explicit analysis path, try manifest
    if not args.analysis:
        try:
            _kicad_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          '..', '..', 'kicad', 'scripts')
            if os.path.isdir(_kicad_scripts):
                import sys as _sys
                _sys.path.insert(0, os.path.abspath(_kicad_scripts))
            from project_config import load_config
            _config = load_config(args.project_dir)
            _analysis_dir = os.path.join(
                args.project_dir,
                _config.get('analysis', {}).get('output_dir', 'analysis'))
            _manifest_path = os.path.join(_analysis_dir, 'manifest.json')
            if os.path.isfile(_manifest_path):
                with open(_manifest_path) as f:
                    _manifest = json.load(f)
                _current_id = _manifest.get('current')
                if _current_id:
                    _sch_path = os.path.join(_analysis_dir, _current_id,
                                             'schematic.json')
                    if os.path.isfile(_sch_path):
                        args.analysis = _sch_path
                        with open(_sch_path) as f:
                            analysis = json.load(f)
        except (ImportError, json.JSONDecodeError, OSError):
            pass

    for path in (args.emc, args.thermal, args.spice):
        if path:
            with open(path) as f:
                analysis.update(json.load(f))

    # Load config
    config = None
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    figures_dir = os.path.abspath(args.output)
    project_dir = os.path.abspath(args.project_dir)

    print(f"Orchestrating renders into {figures_dir}", file=sys.stderr)
    result = orchestrate_renders(
        spec, project_dir, analysis, figures_dir,
        sch_path=args.sch, pcb_path=args.pcb, config=config,
    )

    # Report
    total = sum(len(v) for v in result.values())
    print(f"\nGenerated {total} figure(s):", file=sys.stderr)
    for category, paths in sorted(result.items()):
        print(f"  {category}:", file=sys.stderr)
        for p in paths:
            print(f"    {p}", file=sys.stderr)

    # Output JSON manifest to stdout
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()

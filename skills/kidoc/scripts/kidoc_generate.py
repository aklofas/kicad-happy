#!/usr/bin/env python3
"""Orchestrator for kidoc document generation.

Manages the full pipeline: analysis → render → scaffold → PDF/DOCX.
Runs analysis and rendering with system Python (zero-dep), then
dispatches PDF/DOCX generation to the project-local venv.

Usage:
    python3 kidoc_generate.py --project-dir . --format pdf
    python3 kidoc_generate.py --project-dir . --format docx
    python3 kidoc_generate.py --project-dir . --format all
    python3 kidoc_generate.py --project-dir . --doc HDD.md --format pdf

Zero external dependencies — Python stdlib only (dispatches to venv for PDF/DOCX).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kidoc_venv import ensure_venv, venv_python

_kicad_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', '..', 'kicad', 'scripts')
if os.path.isdir(_kicad_scripts):
    sys.path.insert(0, os.path.abspath(_kicad_scripts))

try:
    from project_config import load_config, load_config_from_path
except ImportError:
    def load_config(search_dir):
        return {'version': 1, 'project': {}, 'suppressions': []}
    def load_config_from_path(path):
        return {'version': 1, 'project': {}, 'suppressions': []}


SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Map markdown stem → human-readable document type name
_DOC_TYPE_NAMES = {
    'hdd': 'Hardware Design Description',
    'ce_technical_file': 'CE Technical File',
    'design_review': 'Design Review',
    'icd': 'Interface Control Document',
    'manufacturing': 'Manufacturing Transfer Package',
}


def _build_filename(stem: str, project_name: str, revision: str) -> str:
    """Build a human-readable filename from project info.

    Examples:
        "SacMap Rev2 - Hardware Design Description Rev 2.0"
        "Widget Board - Design Review Rev 1.1"
        "HDD" (fallback if no project name)
    """
    # Try to match stem to a known doc type
    doc_type_name = ''
    stem_lower = stem.lower().replace('-', '_').replace(' ', '_')
    for key, name in _DOC_TYPE_NAMES.items():
        if key in stem_lower or stem_lower in key:
            doc_type_name = name
            break
    if not doc_type_name:
        doc_type_name = stem.replace('_', ' ').replace('-', ' ').title()

    parts = []
    if project_name:
        parts.append(project_name)
    parts.append(doc_type_name)
    name = ' - '.join(parts)

    if revision:
        name += f' Rev {revision}'

    # Sanitize for filesystem
    name = name.replace('/', '-').replace('\\', '-').replace(':', '-')
    return name


def _find_markdown_files(project_dir: str) -> list[str]:
    """Find markdown scaffolds in the reports/ directory."""
    reports_dir = os.path.join(project_dir, 'reports')
    if not os.path.isdir(reports_dir):
        return []
    return sorted(
        os.path.join(reports_dir, f)
        for f in os.listdir(reports_dir)
        if f.endswith('.md') and not f.startswith('.')
    )


def _run_format_generator(format_name: str, python: str, script: str,
                          md_path: str, output_path: str,
                          config: dict) -> bool:
    """Run a document format generator as a subprocess.

    Args:
        format_name: Human label for error messages (e.g. "PDF").
        python: Python interpreter (system or venv).
        script: Generator script name (e.g. 'kidoc_pdf.py').
        md_path: Input markdown path.
        output_path: Output file path.
        config: Project config dict (serialized as JSON arg).

    Returns True on success.
    """
    cmd = [
        python,
        os.path.join(SCRIPTS_DIR, script),
        '--input', md_path,
        '--output', output_path,
        '--config', json.dumps(config),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"{format_name} generation failed: {result.stderr}",
              file=sys.stderr)
        return False
    return True




def generate_documents(project_dir: str, formats: list[str],
                       doc_name: str | None = None,
                       config: dict | None = None) -> list[str]:
    """Generate PDF/DOCX from markdown scaffolds.

    Returns list of output file paths.
    """
    if config is None:
        config = load_config(project_dir)

    # Find markdown files
    if doc_name:
        md_path = doc_name
        if not os.path.isabs(md_path):
            md_path = os.path.join(project_dir, 'reports', md_path)
        md_files = [md_path] if os.path.isfile(md_path) else []
    else:
        md_files = _find_markdown_files(project_dir)

    if not md_files:
        print("No markdown files found in reports/. Run kidoc_scaffold.py first.",
              file=sys.stderr)
        return []

    # Ensure venv for PDF/DOCX/ODT (not needed for HTML)
    needs_venv = any(f in formats for f in ('pdf', 'docx', 'odt', 'all'))
    venv_py = None
    if needs_venv:
        print("Checking report generation environment...", file=sys.stderr)
        venv_py = ensure_venv(project_dir)

    output_dir = os.path.join(project_dir, 'reports', 'output')
    os.makedirs(output_dir, exist_ok=True)

    outputs = []
    for md_path in md_files:
        stem = Path(md_path).stem
        project = config.get('project', {})
        rev = project.get('revision', '')
        proj_name = project.get('name', '')

        # Build human-readable filename a manager can understand
        # e.g. "SacMap Rev2 - Hardware Design Description Rev 2.0.pdf"
        base_name = _build_filename(stem, proj_name, rev)

        # Format → (label, script, needs_venv)
        _FORMAT_SCRIPTS = {
            'html': ('HTML', 'kidoc_html.py', False),
            'pdf':  ('PDF',  'kidoc_pdf.py',  True),
            'docx': ('DOCX', 'kidoc_docx.py', True),
            'odt':  ('ODT',  'kidoc_odt.py',  True),
        }

        for fmt, (label, script, needs) in _FORMAT_SCRIPTS.items():
            if fmt not in formats and 'all' not in formats:
                continue
            out_path = os.path.join(output_dir, f"{base_name}.{fmt}")
            print(f"Generating {label}: {out_path}", file=sys.stderr)
            py = sys.executable
            if needs:
                if venv_py is None:
                    venv_py = ensure_venv(project_dir)
                py = venv_py
            if _run_format_generator(label, py, script,
                                     md_path, out_path, config):
                outputs.append(out_path)
                print(f"  -> {out_path}", file=sys.stderr)

    return outputs


def main():
    parser = argparse.ArgumentParser(
        description='Generate PDF/DOCX from kidoc markdown scaffolds')
    parser.add_argument('--project-dir', '-p', default='.',
                        help='Path to KiCad project directory')
    parser.add_argument('--format', '-f', default='pdf',
                        choices=['pdf', 'html', 'docx', 'odt', 'all'],
                        help='Output format (default: pdf)')
    parser.add_argument('--doc', default=None,
                        help='Specific markdown file to process')
    parser.add_argument('--config', default=None,
                        help='Path to .kicad-happy.json config')
    parser.add_argument('--spec', default=None,
                        help='Path to document spec JSON')
    args = parser.parse_args()

    if args.config:
        config = load_config_from_path(args.config)
    else:
        config = load_config(args.project_dir)

    # When --spec is provided, use its title as fallback project name
    if args.spec:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from kidoc_spec import load_spec
        spec = load_spec(args.spec)
        if not config.get('project', {}).get('name'):
            config.setdefault('project', {})['name'] = spec.get('title', '')

    formats = [args.format] if args.format != 'all' else ['html', 'pdf', 'docx', 'odt']

    outputs = generate_documents(
        project_dir=args.project_dir,
        formats=formats,
        doc_name=args.doc,
        config=config,
    )

    if outputs:
        print(f"\nGenerated {len(outputs)} document(s):", file=sys.stderr)
        for o in outputs:
            print(f"  {o}", file=sys.stderr)
    else:
        print("No documents generated.", file=sys.stderr)


if __name__ == '__main__':
    main()

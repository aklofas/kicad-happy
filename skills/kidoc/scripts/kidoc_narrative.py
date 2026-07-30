#!/usr/bin/env python3
"""Narrative context builder for kidoc engineering documentation.

Assembles focused context packages for each narrative section in a report.
The LLM reads this context and writes
engineering prose.  This module does NOT generate prose — it prepares the
data the LLM needs.

Usage:
    # Context for one section
    python3 kidoc_narrative.py --analysis schematic.json --section power_design

    # Contexts for all NARRATIVE sections in a report
    python3 kidoc_narrative.py --analysis schematic.json --report reports/HDD.md

    # With additional data sources
    python3 kidoc_narrative.py --analysis schematic.json --section power_design \
        --spec spec.json --emc emc.json --thermal thermal.json --pcb pcb.json

Zero external dependencies — Python 3.8+ stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from kidoc_narrative_config import (
    SECTION_TITLES,
    WRITING_GUIDANCE,
    SECTION_QUESTIONS,
)
from kidoc_narrative_extractors import SECTION_DATA_EXTRACTORS
from kidoc_narrative_augment import (
    build_datasheet_notes,
    build_spice_notes,
    build_cross_references,
)


# ======================================================================
# Main context builder
# ======================================================================

def build_narrative_context(section_id: str, section_type: str,
                            analysis: dict,
                            spec: dict | None = None,
                            extractions: dict | None = None,
                            spice_data: dict | None = None,
                            existing_narrative: str | None = None,
                            emc_data: dict | None = None,
                            thermal_data: dict | None = None,
                            pcb_data: dict | None = None) -> dict:
    """Build focused context for LLM narrative generation.

    Returns a dict with all the data the LLM needs to write prose for
    one section.  The LLM should NOT see the full analysis JSON — only
    this focused slice.
    """
    # Audience/tone from spec
    audience = ''
    tone = 'technical'
    questions = []
    if spec:
        audience = spec.get('audience', '')
        tone = spec.get('tone', 'technical')
        # Per-section questions from spec override defaults
        for s in spec.get('sections', []):
            if s.get('id') == section_id or s.get('type') == section_type:
                questions = s.get('questions', [])
                break

    if not questions:
        questions = list(SECTION_QUESTIONS.get(section_type, []))

    # Extract focused data
    extractor = SECTION_DATA_EXTRACTORS.get(section_type)
    if extractor:
        data_summary = extractor(
            analysis,
            emc_data=emc_data,
            thermal_data=thermal_data,
            pcb_data=pcb_data,
        )
    else:
        data_summary = 'No data extractor available for this section type.'

    # Datasheet notes
    datasheet_notes = build_datasheet_notes(section_type, analysis, extractions)

    # SPICE notes
    spice_notes = build_spice_notes(section_type, analysis, spice_data)

    # Cross-references
    cross_refs = build_cross_references(
        section_type, analysis,
        emc_data=emc_data,
        thermal_data=thermal_data,
        pcb_data=pcb_data,
    )

    # Writing guidance
    guidance = WRITING_GUIDANCE.get(section_type, '')

    return {
        'section_id': section_id,
        'section_type': section_type,
        'section_title': SECTION_TITLES.get(section_type, section_type),
        'audience': audience,
        'tone': tone,
        'questions': questions,
        'data_summary': data_summary,
        'datasheet_notes': datasheet_notes,
        'spice_notes': spice_notes,
        'existing_text': existing_narrative or '',
        'cross_references': cross_refs,
        'writing_guidance': guidance,
    }


# ======================================================================
# Batch context builder
# ======================================================================

# Pattern matching narrative placeholders in scaffold output.
# The scaffold emits italic placeholder text: *[hint text]*
# Nearby headings identify the section.
_NARRATIVE_PLACEHOLDER_RE = re.compile(r'^\*\[.+?\]\*$')

# Map heading text to section types
_HEADING_TO_SECTION = {
    'executive summary': 'executive_summary',
    'system overview': 'system_overview',
    'power system design': 'power_design',
    'signal interfaces': 'signal_interfaces',
    'analog design': 'analog_design',
    'thermal analysis': 'thermal_analysis',
    'emc considerations': 'emc_analysis',
    'pcb design details': 'pcb_design',
    'mechanical / environmental': 'mechanical_environmental',
    'bom summary': 'bom_summary',
    'test and debug': 'test_debug',
    'compliance and standards': 'compliance',
    # CE
    'product identification': 'ce_product_identification',
    'essential requirements': 'ce_essential_requirements',
    'risk assessment': 'ce_risk_assessment',
    # Design Review
    'review summary': 'review_summary',
    'action items': 'review_action_items',
    # ICD
    'interface list': 'icd_interface_list',
    'connector details': 'icd_connector_details',
    'electrical characteristics': 'icd_electrical_characteristics',
    # Manufacturing
    'assembly overview': 'mfg_assembly_overview',
    'pcb fabrication notes': 'mfg_pcb_fab_notes',
    'assembly instructions': 'mfg_assembly_instructions',
    'production test procedures': 'mfg_test_procedures',
}


def _detect_sections_from_markdown(md_text: str) -> list[dict]:
    """Detect narrative sections from markdown scaffold.

    Returns list of {'section_type': str, 'existing_text': str|None}
    for each section that has a narrative placeholder or where the user
    has already written content.
    """
    lines = md_text.split('\n')
    sections = []
    current_section = None

    for line in lines:
        stripped = line.strip()

        # Track headings to determine current section
        if stripped.startswith('#'):
            heading_text = stripped.lstrip('#').strip()
            # Remove numbering like "2. " or "## 3. "
            heading_clean = re.sub(r'^\d+\.\s*', '', heading_text).lower()
            section_type = _HEADING_TO_SECTION.get(heading_clean)
            if section_type:
                current_section = section_type

        # Detect narrative placeholder
        if current_section and _NARRATIVE_PLACEHOLDER_RE.match(stripped):
            sections.append({
                'section_type': current_section,
                'existing_text': None,
            })

    return sections


def build_all_narrative_contexts(report_md_path: str,
                                 analysis: dict,
                                 spec: dict | None = None,
                                 extractions: dict | None = None,
                                 spice_data: dict | None = None,
                                 emc_data: dict | None = None,
                                 thermal_data: dict | None = None,
                                 pcb_data: dict | None = None) -> list[dict]:
    """Build contexts for all narrative sections in a report.

    Reads the markdown file, finds all narrative placeholder sections,
    and builds context for each.
    """
    with open(report_md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    detected = _detect_sections_from_markdown(md_text)

    contexts = []
    for det in detected:
        section_type = det['section_type']
        ctx = build_narrative_context(
            section_id=section_type,
            section_type=section_type,
            analysis=analysis,
            spec=spec,
            extractions=extractions,
            spice_data=spice_data,
            existing_narrative=det.get('existing_text'),
            emc_data=emc_data,
            thermal_data=thermal_data,
            pcb_data=pcb_data,
        )
        contexts.append(ctx)

    return contexts


# ======================================================================
# Output formatting
# ======================================================================

def format_context(ctx: dict) -> str:
    """Format a narrative context dict as readable text for the LLM."""
    lines = []
    lines.append(f"=== NARRATIVE CONTEXT: {ctx['section_title']} ===")
    lines.append(f"Section: {ctx['section_id']} (type: {ctx['section_type']})")

    if ctx.get('audience'):
        lines.append(f"Audience: {ctx['audience']}")
    if ctx.get('tone'):
        lines.append(f"Tone: {ctx['tone']}")

    lines.append("")
    lines.append("--- DATA SUMMARY ---")
    lines.append(ctx.get('data_summary', '(none)'))

    if ctx.get('datasheet_notes'):
        lines.append("")
        lines.append("--- DATASHEET NOTES ---")
        lines.append(ctx['datasheet_notes'])

    if ctx.get('spice_notes'):
        lines.append("")
        lines.append("--- SPICE VALIDATION ---")
        lines.append(ctx['spice_notes'])

    if ctx.get('cross_references'):
        lines.append("")
        lines.append("--- CROSS-REFERENCES ---")
        lines.append(ctx['cross_references'])

    if ctx.get('existing_text'):
        lines.append("")
        lines.append("--- EXISTING NARRATIVE (rewrite if stale) ---")
        lines.append(ctx['existing_text'])

    if ctx.get('questions'):
        lines.append("")
        lines.append("--- QUESTIONS TO ADDRESS ---")
        for q in ctx['questions']:
            lines.append(f"  - {q}")

    if ctx.get('writing_guidance'):
        lines.append("")
        lines.append("--- WRITING GUIDANCE ---")
        lines.append(ctx['writing_guidance'])

    lines.append("")
    return '\n'.join(lines)


# ======================================================================
# CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Build narrative context for kidoc report sections')
    parser.add_argument('--analysis', required=True,
                        help='Path to schematic analysis JSON')
    parser.add_argument('--section',
                        help='Build context for one section type')
    parser.add_argument('--report',
                        help='Build contexts for all narrative sections in a markdown file')
    parser.add_argument('--spec',
                        help='Document spec JSON (for audience/tone/questions)')
    parser.add_argument('--emc',
                        help='Path to EMC analysis JSON')
    parser.add_argument('--thermal',
                        help='Path to thermal analysis JSON')
    parser.add_argument('--pcb',
                        help='Path to PCB analysis JSON')
    parser.add_argument('--extractions',
                        help='Path to datasheet extractions directory or JSON')
    parser.add_argument('--spice',
                        help='Path to SPICE results JSON')
    args = parser.parse_args()

    # Load analysis
    with open(args.analysis, 'r', encoding='utf-8') as f:
        analysis = json.load(f)

    # Load optional data sources
    spec = None
    if args.spec:
        with open(args.spec, 'r', encoding='utf-8') as f:
            spec = json.load(f)

    emc_data = None
    if args.emc:
        with open(args.emc, 'r', encoding='utf-8') as f:
            emc_data = json.load(f)
    else:
        # Try to find emc.json alongside the analysis
        emc_path = os.path.join(os.path.dirname(args.analysis), 'emc.json')
        if os.path.isfile(emc_path):
            with open(emc_path, 'r', encoding='utf-8') as f:
                emc_data = json.load(f)

    thermal_data = None
    if args.thermal:
        with open(args.thermal, 'r', encoding='utf-8') as f:
            thermal_data = json.load(f)
    else:
        thermal_path = os.path.join(os.path.dirname(args.analysis), 'thermal.json')
        if os.path.isfile(thermal_path):
            with open(thermal_path, 'r', encoding='utf-8') as f:
                thermal_data = json.load(f)

    pcb_data = None
    if args.pcb:
        with open(args.pcb, 'r', encoding='utf-8') as f:
            pcb_data = json.load(f)
    else:
        pcb_path = os.path.join(os.path.dirname(args.analysis), 'pcb.json')
        if os.path.isfile(pcb_path):
            with open(pcb_path, 'r', encoding='utf-8') as f:
                pcb_data = json.load(f)

    spice_data = None
    if args.spice:
        with open(args.spice, 'r', encoding='utf-8') as f:
            spice_data = json.load(f)

    extractions = None
    if args.extractions:
        ext_path = args.extractions
        if os.path.isfile(ext_path):
            with open(ext_path, 'r', encoding='utf-8') as f:
                extractions = json.load(f)
        elif os.path.isdir(ext_path):
            # Load all JSONs from directory keyed by filename stem
            extractions = {}
            for fname in os.listdir(ext_path):
                if fname.endswith('.json'):
                    fpath = os.path.join(ext_path, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            extractions[fname.replace('.json', '')] = json.load(f)
                    except (json.JSONDecodeError, OSError):
                        pass

    # Build and output context
    if args.section:
        ctx = build_narrative_context(
            section_id=args.section,
            section_type=args.section,
            analysis=analysis,
            spec=spec,
            extractions=extractions,
            spice_data=spice_data,
            emc_data=emc_data,
            thermal_data=thermal_data,
            pcb_data=pcb_data,
        )
        print(format_context(ctx))

    elif args.report:
        if not os.path.isfile(args.report):
            print(f"Error: report file not found: {args.report}", file=sys.stderr)
            sys.exit(1)
        contexts = build_all_narrative_contexts(
            report_md_path=args.report,
            analysis=analysis,
            spec=spec,
            extractions=extractions,
            spice_data=spice_data,
            emc_data=emc_data,
            thermal_data=thermal_data,
            pcb_data=pcb_data,
        )
        if not contexts:
            print("No narrative sections found in report.", file=sys.stderr)
            sys.exit(0)
        for ctx in contexts:
            print(format_context(ctx))

    else:
        # No --section or --report: list available section types
        print("Available section types:")
        for stype in sorted(SECTION_DATA_EXTRACTORS.keys()):
            title = SECTION_TITLES.get(stype, stype)
            print(f"  {stype:30s} {title}")
        print(f"\n{len(SECTION_DATA_EXTRACTORS)} extractors available.")
        print("\nUse --section <type> or --report <file.md> to generate context.")


if __name__ == '__main__':
    main()

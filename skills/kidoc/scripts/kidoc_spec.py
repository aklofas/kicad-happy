#!/usr/bin/env python3
"""Document spec parser, validator, and expander for kidoc.

A spec is a JSON dict describing a complete document: its type, title,
audience, tone, input files, output formats, and an ordered list of
section definitions.  Specs can be created from built-in templates
(expanded with defaults) or loaded from user-authored JSON files.

Usage:
    python3 kidoc_spec.py --list                   # list built-in types
    python3 kidoc_spec.py --expand hdd             # expand type to full spec JSON
    python3 kidoc_spec.py --validate spec.json     # validate a spec file

Zero external dependencies -- Python 3.8+ stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kidoc_templates import DOCUMENT_TEMPLATES, get_document_title


# ======================================================================
# Constants
# ======================================================================

DEFAULT_SPECS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'default_specs')

VALID_RENDER_MODES = ('auto', 'kicad-cli', 'crop', 'annotated')
VALID_NARRATIVE_MODES = ('auto', 'none')
VALID_TONES = ('technical', 'executive', 'conversational')

# Default section spec values
SECTION_DEFAULTS = {
    'render': 'auto',
    'narrative': 'auto',
    'focus_refs': [],
    'highlight_nets': [],
    'include': [],
    'questions': [],
}


# ======================================================================
# Spec loading
# ======================================================================

def load_spec(spec_path: str) -> dict:
    """Load a JSON spec file, validate, and return the spec dict.

    Raises ValueError on invalid JSON or missing required fields.
    """
    path = Path(spec_path)
    if not path.exists():
        raise FileNotFoundError(f'Spec file not found: {spec_path}')

    with open(path, 'r', encoding='utf-8') as f:
        try:
            spec = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Invalid JSON in {spec_path}: {exc}') from exc

    return validate_spec(spec)


def load_builtin_spec(doc_type: str) -> dict:
    """Load a built-in spec from default_specs/ or generate from template.

    Checks for a pre-generated JSON file first; falls back to
    expand_type_to_spec() if no file exists.
    """
    json_path = os.path.join(DEFAULT_SPECS_DIR, f'{doc_type}.json')
    if os.path.isfile(json_path):
        return load_spec(json_path)
    return expand_type_to_spec(doc_type)


def expand_type_to_spec(doc_type: str) -> dict:
    """Expand a type name into a full spec dict with sections.

    Uses DOCUMENT_TEMPLATES to populate the section list with defaults.
    Raises ValueError if the type is unknown.
    """
    if doc_type not in DOCUMENT_TEMPLATES:
        available = ', '.join(sorted(DOCUMENT_TEMPLATES))
        raise ValueError(
            f'Unknown document type: {doc_type!r}. '
            f'Available types: {available}'
        )

    template = DOCUMENT_TEMPLATES[doc_type]

    sections = []
    for section_name in template['sections']:
        section = {
            'id': section_name,
            'type': section_name,
        }
        section.update({k: _deep_copy_default(v)
                        for k, v in SECTION_DEFAULTS.items()})
        sections.append(section)

    spec = {
        'type': doc_type,
        'title': template['name'],
        'audience': '',
        'tone': 'technical',
        'schematic': '',
        'pcb': '',
        'default_formats': list(template.get('default_formats', ['pdf'])),
        'sections': sections,
    }

    return spec


# ======================================================================
# Validation
# ======================================================================

def validate_spec(spec: dict) -> dict:
    """Fill defaults for missing fields and validate required fields.

    Returns the (possibly modified) spec dict.
    Raises ValueError on invalid data.
    """
    if not isinstance(spec, dict):
        raise ValueError('Spec must be a JSON object (dict)')

    # Top-level defaults
    spec.setdefault('type', 'custom')
    spec.setdefault('title', get_document_title(spec['type'])
                    if spec['type'] in DOCUMENT_TEMPLATES
                    else 'Custom Document')
    spec.setdefault('audience', '')
    spec.setdefault('tone', 'technical')
    spec.setdefault('schematic', '')
    spec.setdefault('pcb', '')
    spec.setdefault('default_formats', ['pdf'])

    # Validate tone
    if spec['tone'] not in VALID_TONES:
        raise ValueError(
            f'Invalid tone: {spec["tone"]!r}. '
            f'Must be one of: {", ".join(VALID_TONES)}'
        )

    # Validate default_formats
    if not isinstance(spec['default_formats'], list):
        raise ValueError('default_formats must be a list')

    # Sections
    if 'sections' not in spec:
        raise ValueError('Spec must contain a "sections" list')

    if not isinstance(spec['sections'], list):
        raise ValueError('"sections" must be a list')

    seen_ids = set()
    for i, section in enumerate(spec['sections']):
        if not isinstance(section, dict):
            raise ValueError(f'Section {i} must be a dict')

        # Required: id and type
        if 'id' not in section:
            raise ValueError(f'Section {i} missing required field "id"')
        if 'type' not in section:
            section['type'] = section['id']

        sid = section['id']
        if sid in seen_ids:
            raise ValueError(f'Duplicate section id: {sid!r}')
        seen_ids.add(sid)

        # Fill section defaults
        for key, default_val in SECTION_DEFAULTS.items():
            section.setdefault(key, _deep_copy_default(default_val))

        # Validate render mode
        if section['render'] not in VALID_RENDER_MODES:
            raise ValueError(
                f'Section {sid!r}: invalid render mode {section["render"]!r}. '
                f'Must be one of: {", ".join(VALID_RENDER_MODES)}'
            )

        # Validate narrative mode
        if section['narrative'] not in VALID_NARRATIVE_MODES:
            raise ValueError(
                f'Section {sid!r}: invalid narrative mode '
                f'{section["narrative"]!r}. '
                f'Must be one of: {", ".join(VALID_NARRATIVE_MODES)}'
            )

        # Validate list fields
        for list_field in ('focus_refs', 'highlight_nets',
                           'include', 'questions'):
            if not isinstance(section.get(list_field, []), list):
                raise ValueError(
                    f'Section {sid!r}: {list_field!r} must be a list'
                )

    return spec


# ======================================================================
# Accessors
# ======================================================================

def get_section_types(spec: dict) -> list[str]:
    """Extract the ordered list of section type names from a spec."""
    return [s['type'] for s in spec.get('sections', [])]


def get_section_spec(spec: dict, section_id: str) -> dict | None:
    """Get the spec dict for a single section by id.

    Returns None if no section with the given id exists.
    """
    for section in spec.get('sections', []):
        if section['id'] == section_id:
            return section
    return None


def list_builtin_types() -> list[str]:
    """List available built-in document types (sorted)."""
    return sorted(DOCUMENT_TEMPLATES.keys())


# ======================================================================
# Output
# ======================================================================

def save_spec(spec: dict, output_path: str) -> None:
    """Write a spec dict to a JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(spec, f, indent=2)
        f.write('\n')


# ======================================================================
# Helpers
# ======================================================================

def _deep_copy_default(val):
    """Return a copy of a default value (handles lists, dicts, scalars)."""
    if isinstance(val, list):
        return list(val)
    if isinstance(val, dict):
        return dict(val)
    return val


# ======================================================================
# CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description='kidoc spec tool -- parse, validate, and expand '
                    'document specs'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--list', action='store_true',
                       help='List available built-in document types')
    group.add_argument('--expand', metavar='TYPE',
                       help='Expand a type name to a full spec JSON')
    group.add_argument('--validate', metavar='FILE',
                       help='Validate a spec JSON file')

    args = parser.parse_args()

    if args.list:
        types = list_builtin_types()
        for t in types:
            title = get_document_title(t)
            print(f'  {t:24s} {title}')
        print(f'\n{len(types)} types available.')
        return

    if args.expand:
        try:
            spec = expand_type_to_spec(args.expand)
        except ValueError as exc:
            print(f'Error: {exc}', file=sys.stderr)
            sys.exit(1)
        json.dump(spec, sys.stdout, indent=2)
        sys.stdout.write('\n')
        return

    if args.validate:
        try:
            spec = load_spec(args.validate)
            n_sections = len(spec.get('sections', []))
            print(f'OK: {args.validate} -- type={spec["type"]!r}, '
                  f'{n_sections} sections')
        except (FileNotFoundError, ValueError) as exc:
            print(f'FAIL: {args.validate} -- {exc}', file=sys.stderr)
            sys.exit(1)
        return


if __name__ == '__main__':
    main()

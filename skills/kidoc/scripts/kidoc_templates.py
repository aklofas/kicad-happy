"""Document type template definitions for kidoc.

Each document type defines its section list, default output formats,
and type-specific options.  Used by kidoc_scaffold.py to determine
which sections to generate.

Zero external dependencies — constants only.
"""

from __future__ import annotations


DOCUMENT_TEMPLATES = {
    "hdd": {
        "name": "Hardware Design Description",
        "sections": [
            "front_matter", "executive_summary", "system_overview", "power_design",
            "signal_interfaces", "analog_design", "thermal_analysis",
            "emc_analysis", "pcb_design", "mechanical_environmental",
            "bom_summary", "test_debug", "compliance",
            "appendix_schematics",
        ],
        "default_formats": ["pdf", "docx"],
    },
    "ce_technical_file": {
        "name": "CE Technical File",
        "sections": [
            "front_matter", "ce_product_identification",
            "ce_essential_requirements", "ce_harmonized_standards",
            "ce_risk_assessment", "emc_analysis", "thermal_analysis",
            "ce_declaration_of_conformity",
            "bom_summary", "appendix_schematics",
        ],
        "default_formats": ["pdf"],
        "pdfa": True,
    },
    "design_review": {
        "name": "Design Review Package",
        "sections": [
            "front_matter", "executive_summary", "review_summary",
            "system_overview", "power_design",
            "emc_analysis", "thermal_analysis",
            "bom_summary", "review_action_items",
        ],
        "default_formats": ["pdf"],
    },
    "icd": {
        "name": "Interface Control Document",
        "sections": [
            "front_matter", "system_overview",
            "icd_interface_list", "icd_connector_details",
            "signal_interfaces", "icd_electrical_characteristics",
        ],
        "default_formats": ["pdf", "docx"],
    },
    "manufacturing": {
        "name": "Manufacturing Transfer Package",
        "sections": [
            "front_matter", "mfg_assembly_overview",
            "bom_summary", "mfg_pcb_fab_notes",
            "mfg_assembly_instructions", "mfg_test_procedures",
            "appendix_schematics",
        ],
        "default_formats": ["pdf"],
    },
    "schematic_review": {
        "name": "Schematic Review Report",
        "sections": [
            "front_matter", "executive_summary", "system_overview",
            "power_design", "signal_interfaces", "analog_design",
            "bom_summary", "appendix_schematics",
        ],
        "default_formats": ["pdf"],
    },
    "power_analysis": {
        "name": "Power Analysis Report",
        "sections": [
            "front_matter", "executive_summary", "power_design",
            "thermal_analysis", "emc_analysis", "bom_summary",
            "appendix_schematics",
        ],
        "default_formats": ["pdf"],
    },
    "emc_report": {
        "name": "EMC Pre-Compliance Report",
        "sections": [
            "front_matter", "executive_summary",
            "emc_analysis", "compliance",
            "appendix_schematics",
        ],
        "default_formats": ["pdf"],
    },
}


def get_template(doc_type: str) -> dict:
    """Get the template for a document type, with defaults fallback."""
    return DOCUMENT_TEMPLATES.get(doc_type, DOCUMENT_TEMPLATES['hdd'])


def get_section_list(doc_type: str, config: dict | None = None) -> list[str]:
    """Get the section list for a document type, allowing config overrides."""
    template = get_template(doc_type)
    sections = list(template['sections'])

    # Allow config to override sections
    if config:
        reports = config.get('reports', {})
        for doc_def in reports.get('documents', []):
            if doc_def.get('type') == doc_type and 'sections' in doc_def:
                sections = doc_def['sections']
                break

    return sections


def get_document_title(doc_type: str) -> str:
    """Get the display name for a document type."""
    template = get_template(doc_type)
    return template['name']

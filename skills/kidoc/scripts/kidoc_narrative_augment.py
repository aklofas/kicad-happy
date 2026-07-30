"""Narrative augmentation — datasheet, SPICE, and cross-reference builders.

These functions enrich narrative context with supplemental data sources
beyond the primary schematic analysis JSON.

Zero external dependencies — Python 3.8+ stdlib only.
"""

from __future__ import annotations


# ======================================================================
# Datasheet notes
# ======================================================================

def build_datasheet_notes(section_type: str, analysis: dict,
                          extractions: dict | None) -> str:
    """Build datasheet notes relevant to a section."""
    if not extractions:
        return ''

    parts = []

    if section_type == 'power_design':
        regs = [f for f in analysis.get('findings', [])
                if f.get('detector') == 'detect_power_regulators']
        for r in regs:
            value = r.get('value', '')
            ref = r.get('ref', '')
            # Look for extraction by MPN or value
            for key in (r.get('mpn', ''), value):
                if key and key in extractions:
                    ext = extractions[key]
                    parts.append(f"{ref} ({value}): {_summarize_extraction(ext)}")

    elif section_type == 'analog_design':
        opamps = [f for f in analysis.get('findings', [])
                  if f.get('detector') == 'detect_opamp_circuits']
        for o in opamps:
            value = o.get('value', '')
            ref = o.get('ref', '')
            for key in (o.get('mpn', ''), value):
                if key and key in extractions:
                    ext = extractions[key]
                    parts.append(f"{ref} ({value}): {_summarize_extraction(ext)}")

    return '\n'.join(parts)


def _summarize_extraction(ext: dict) -> str:
    """One-line summary of a datasheet extraction."""
    parts = []
    if ext.get('voltage_ratings'):
        parts.append(f"Vmax={ext['voltage_ratings']}")
    if ext.get('operating_temp'):
        parts.append(f"Temp={ext['operating_temp']}")
    if ext.get('package'):
        parts.append(f"Package={ext['package']}")
    return '; '.join(parts) if parts else '(extraction available)'


# ======================================================================
# SPICE notes
# ======================================================================

def build_spice_notes(section_type: str, analysis: dict,
                      spice_data: dict | None) -> str:
    """Build SPICE simulation notes relevant to a section."""
    if not spice_data:
        return ''

    results = spice_data.get('simulation_results', [])
    if not results:
        return ''

    parts = []
    for r in results:
        subcircuit_type = r.get('subcircuit_type', '')
        # Match SPICE results to section type
        relevant = False
        if section_type == 'analog_design' and subcircuit_type in ('filter', 'divider', 'opamp'):
            relevant = True
        elif section_type == 'power_design' and subcircuit_type in ('regulator', 'lc_filter'):
            relevant = True

        if relevant:
            parts.append(
                f"SPICE {r.get('name', '?')}: "
                f"measured={r.get('measured_value', '?')}, "
                f"expected={r.get('expected_value', '?')}, "
                f"{'PASS' if r.get('pass') else 'FAIL'}"
            )

    return '\n'.join(parts)


# ======================================================================
# Cross-references
# ======================================================================

def build_cross_references(section_type: str, analysis: dict,
                           emc_data: dict | None = None,
                           thermal_data: dict | None = None,
                           pcb_data: dict | None = None) -> str:
    """Brief references to related sections."""
    parts = []

    if section_type == 'power_design':
        if thermal_data:
            s = thermal_data.get('summary', {})
            parts.append(f"See Thermal: score {s.get('thermal_score', '?')}/100, "
                         f"{s.get('components_above_85c', 0)} above 85C")
        if emc_data:
            dc_findings = [f for f in emc_data.get('findings', [])
                           if f.get('category') == 'decoupling' and not f.get('suppressed')]
            if dc_findings:
                parts.append(f"See EMC: {len(dc_findings)} decoupling finding(s)")

    elif section_type == 'emc_analysis':
        regs = [f for f in analysis.get('findings', [])
                if f.get('detector') == 'detect_power_regulators']
        if regs:
            parts.append(f"See Power: {len(regs)} regulator(s)")
        if pcb_data:
            parts.append(f"See PCB: {pcb_data.get('statistics', {}).get('copper_layers_used', '?')} layers")

    elif section_type == 'thermal_analysis':
        regs = [f for f in analysis.get('findings', [])
                if f.get('detector') == 'detect_power_regulators']
        pdiss_regs = [r for r in regs if r.get('power_dissipation')]
        if pdiss_regs:
            parts.append(f"See Power: {len(pdiss_regs)} regulator(s) with dissipation data")

    elif section_type == 'executive_summary':
        if emc_data:
            s = emc_data.get('summary', {})
            parts.append(f"EMC: {s.get('emc_risk_score', '?')}/100")
        if thermal_data:
            s = thermal_data.get('summary', {})
            parts.append(f"Thermal: {s.get('thermal_score', '?')}/100")

    return '\n'.join(parts)

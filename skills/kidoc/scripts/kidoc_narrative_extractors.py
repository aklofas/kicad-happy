"""Narrative data extractors — pull focused data from analysis JSON.

Each extractor takes the analysis dict (plus optional keyword args for
supplemental data sources) and returns a concise text summary for one
report section type.

Zero external dependencies — Python 3.8+ stdlib only.
"""

from __future__ import annotations

from finding_schema import Det, group_findings


# ======================================================================
# Utility
# ======================================================================

def _format_freq(hz) -> str:
    """Format frequency value for display."""
    if hz is None:
        return '?'
    try:
        hz = float(hz)
    except (TypeError, ValueError):
        return str(hz)
    if hz >= 1e9:
        return f"{hz/1e9:.2f}GHz"
    if hz >= 1e6:
        return f"{hz/1e6:.2f}MHz"
    if hz >= 1e3:
        return f"{hz/1e3:.2f}kHz"
    return f"{hz:.2f}Hz"


# ======================================================================
# Section data extractors
# ======================================================================

def _extract_overview_data(analysis: dict, **kwargs) -> str:
    """Extract system overview data as concise text summary."""
    parts = []
    stats = analysis.get('statistics', {})
    if stats:
        parts.append(
            f"Components: {stats.get('total_components', 0)} total, "
            f"{stats.get('unique_parts', 0)} unique"
        )
        parts.append(f"Nets: {stats.get('total_nets', 0)}")
        parts.append(f"Sheets: {stats.get('sheets', 1)}")

        types = stats.get('component_types', {})
        if types:
            type_str = ', '.join(f"{v} {k}" for k, v in
                                 sorted(types.items(), key=lambda x: -x[1]))
            parts.append(f"Component types: {type_str}")

        missing = stats.get('missing_mpn', [])
        if missing:
            parts.append(f"Missing MPNs: {len(missing)} components ({', '.join(missing[:5])}"
                         + (f" +{len(missing)-5}" if len(missing) > 5 else "") + ")")

    # Key ICs
    components = analysis.get('components', [])
    ics = [c for c in components if c.get('type') == 'ic']
    if ics:
        ic_list = [f"{c.get('reference', '?')} ({c.get('value', '?')})" for c in ics[:8]]
        parts.append(f"Key ICs: {', '.join(ic_list)}")

    # Power rails
    rails = stats.get('power_rails', [])
    if rails:
        rail_names = [r.get('name', '?') for r in rails if r.get('name')]
        parts.append(f"Power rails: {', '.join(rail_names)}")

    # Title block
    tb = analysis.get('title_block', {})
    if tb.get('title'):
        parts.insert(0, f"Project: {tb['title']}")

    return '\n'.join(parts) if parts else 'No system overview data available.'




def _extract_power_data(analysis: dict, **kwargs) -> str:
    """Extract power design data as concise text summary."""
    parts = []
    _sa = group_findings(analysis)
    regs = _sa.get(Det.POWER_REGULATORS, [])
    if regs:
        parts.append(f"{len(regs)} voltage regulator(s):")
        for r in regs:
            line = f"  - {r.get('ref', '?')}: {r.get('value', '?')}"
            line += f", topology={r.get('topology', '?')}"
            if r.get('estimated_vout'):
                line += f", Vout={r['estimated_vout']:.3f}V"
            line += f", input={r.get('input_rail', '?')}"
            line += f", output={r.get('output_rail', '?')}"

            # Feedback divider
            fb = r.get('feedback_divider')
            if fb:
                line += (f", feedback R_top={fb.get('r_top', {}).get('ref', '?')}"
                         f"({fb.get('r_top', {}).get('value', '?')})"
                         f" R_bot={fb.get('r_bottom', {}).get('ref', '?')}"
                         f"({fb.get('r_bottom', {}).get('value', '?')})")

            # Input/output caps
            in_caps = r.get('input_capacitors', [])
            out_caps = r.get('output_capacitors', [])
            if in_caps:
                cap_str = ', '.join(f"{c.get('ref','?')}={c.get('value','?')}" for c in in_caps)
                line += f", input_caps=[{cap_str}]"
            if out_caps:
                cap_str = ', '.join(f"{c.get('ref','?')}={c.get('value','?')}" for c in out_caps)
                line += f", output_caps=[{cap_str}]"

            # Power dissipation
            pdiss = r.get('power_dissipation', {})
            if pdiss:
                line += (f", Pdiss={pdiss.get('estimated_pdiss_W', '?')}W"
                         f" (Vin={pdiss.get('vin_estimated_V', '?')}V"
                         f" dropout={pdiss.get('dropout_V', '?')}V)")

            parts.append(line)

    decoupling = _sa.get(Det.DECOUPLING, [])
    if decoupling:
        if isinstance(decoupling, list) and decoupling:
            total_caps = sum(len(d.get('capacitors', [])) for d in decoupling
                             if isinstance(d, dict))
            parts.append(f"Decoupling: {len(decoupling)} group(s), {total_caps} capacitor(s)")
            for d in decoupling:
                if isinstance(d, dict):
                    ic = d.get('ic_ref') or d.get('ic') or d.get('rail', '?')
                    caps = d.get('capacitors', [])
                    cap_str = ', '.join(f"{c.get('ref','?')}={c.get('value','?')}"
                                        for c in caps if isinstance(c, dict))
                    parts.append(f"  - {ic}: [{cap_str}]")
        elif isinstance(decoupling, dict):
            parts.append(f"Decoupling: {decoupling.get('total_caps', 0)} capacitor(s)")

    # Protection devices
    protection = _sa.get(Det.PROTECTION_DEVICES, [])
    if protection:
        parts.append(f"Protection devices: {len(protection)}")
        for p in protection[:5]:
            parts.append(f"  - {p.get('ref', '?')}: {p.get('value', '?')} ({p.get('type', '?')})")

    return '\n'.join(parts) if parts else 'No power design data available.'


def _extract_signal_data(analysis: dict, **kwargs) -> str:
    """Extract signal interface data as concise text summary."""
    parts = []

    bus_analysis = analysis.get('design_analysis', {}).get('bus_analysis', {})
    for bus_type in ('i2c', 'spi', 'uart', 'can'):
        buses = bus_analysis.get(bus_type, [])
        for bus in buses:
            signals = bus.get('signals', [])
            sig_names = [s.get('name', str(s)) if isinstance(s, dict) else str(s)
                         for s in signals]
            if sig_names and any(s for s in sig_names):
                bus_id = bus.get('bus_id', bus_type)
                parts.append(f"{bus_type.upper()} {bus_id}: {', '.join(sig_names[:10])}")

    # Level shifters
    _sa = group_findings(analysis)
    shifters = _sa.get(Det.LEVEL_SHIFTERS, [])
    if shifters:
        parts.append(f"Level shifters: {len(shifters)}")
        for s in shifters:
            parts.append(f"  - {s.get('ref', '?')}: {s.get('value', '')} "
                         f"({s.get('low_side_rail', '?')} <-> {s.get('high_side_rail', '?')})")

    # ESD coverage
    esd = _sa.get(Det.ESD_AUDIT, [])
    if esd:
        unprotected = [e for e in esd if isinstance(e, dict) and e.get('coverage') == 'none']
        if unprotected:
            refs = [e.get('connector_ref', '?') for e in unprotected]
            parts.append(f"ESD gaps: {len(unprotected)} connector(s) with no protection "
                         f"({', '.join(refs[:5])})")

    # Differential pairs
    diff_pairs = analysis.get('design_analysis', {}).get('differential_pairs', [])
    if diff_pairs:
        parts.append(f"Differential pairs: {len(diff_pairs)}")
        for dp in diff_pairs[:5]:
            parts.append(f"  - {dp.get('name', '?')}: "
                         f"{dp.get('positive_net', '?')} / {dp.get('negative_net', '?')}")

    if not parts:
        parts.append('No formal buses or interfaces detected.')

    return '\n'.join(parts)


def _extract_analog_data(analysis: dict, **kwargs) -> str:
    """Extract analog design data as concise text summary."""
    parts = []
    sa = group_findings(analysis)

    # Voltage dividers
    dividers = sa.get(Det.VOLTAGE_DIVIDERS, [])
    if dividers:
        parts.append(f"{len(dividers)} voltage divider(s):")
        for d in dividers:
            r_top = d.get('r_top', {})
            r_bot = d.get('r_bottom', {})
            parts.append(
                f"  - {r_top.get('ref', '?')}({r_top.get('value', '?')}) / "
                f"{r_bot.get('ref', '?')}({r_bot.get('value', '?')}), "
                f"ratio={d.get('ratio', '?'):.4f}, "
                f"top_net={d.get('top_net', '?')}, "
                f"mid_net={d.get('mid_net', '?')}, "
                f"bottom_net={d.get('bottom_net', '?')}"
            )
            connections = d.get('mid_point_connections', [])
            if connections:
                conn_str = ', '.join(
                    f"{c.get('component', '?')}.{c.get('pin_name', '?')}"
                    for c in connections if isinstance(c, dict)
                )
                parts.append(f"    connects to: {conn_str}")

    # Filters
    for ftype, label in [(Det.RC_FILTERS, 'RC filter'), (Det.LC_FILTERS, 'LC filter')]:
        filters = sa.get(ftype, [])
        if filters:
            parts.append(f"{len(filters)} {label}(s):")
            for f in filters:
                r = f.get('resistor', {})
                c = f.get('capacitor', {})
                r_ref = r.get('ref', '?') if isinstance(r, dict) else str(r)
                c_ref = c.get('ref', '?') if isinstance(c, dict) else str(c)
                fc = f.get('cutoff_hz')
                fc_str = _format_freq(fc) if fc else '?'
                parts.append(
                    f"  - {f.get('type', '?')}: {r_ref} + {c_ref}, "
                    f"fc={fc_str}, "
                    f"input={f.get('input_net', '?')}, output={f.get('output_net', '?')}"
                )

    # Opamp circuits
    opamps = sa.get(Det.OPAMP_CIRCUITS, [])
    if opamps:
        parts.append(f"{len(opamps)} opamp circuit(s):")
        for o in opamps:
            parts.append(
                f"  - {o.get('ref', '?')} ({o.get('value', '?')}): "
                f"topology={o.get('topology', '?')}, gain={o.get('gain', '?')}"
            )

    # Crystal circuits
    crystals = sa.get(Det.CRYSTAL_CIRCUITS, [])
    if crystals:
        parts.append(f"{len(crystals)} crystal circuit(s):")
        for c in crystals:
            freq = c.get('frequency_hz')
            parts.append(f"  - {c.get('ref', '?')}: {_format_freq(freq) if freq else '?'}")

    if not parts:
        parts.append('No analog subcircuits detected.')

    return '\n'.join(parts)


def _extract_thermal_data(analysis: dict, **kwargs) -> str:
    """Extract thermal analysis data as concise text summary."""
    thermal_data = kwargs.get('thermal_data')
    if not thermal_data:
        return 'No thermal analysis data available.'

    parts = []
    summary = thermal_data.get('summary', {})
    parts.append(f"Thermal score: {summary.get('thermal_score', '?')}/100")
    parts.append(f"Total board dissipation: {summary.get('total_board_dissipation_w', '?')}W")
    parts.append(f"Ambient: {summary.get('ambient_c', 25.0)}C")

    hottest = summary.get('hottest_component', {})
    if isinstance(hottest, dict):
        parts.append(f"Hottest: {hottest.get('ref', '?')} at {hottest.get('tj_estimated_c', '?')}C")
    elif hottest:
        parts.append(f"Hottest: {hottest}")

    above_85 = summary.get('components_above_85c', 0)
    parts.append(f"Components above 85C: {above_85}")

    assessments = thermal_data.get('thermal_assessments', [])
    if assessments:
        parts.append(f"\n{len(assessments)} thermal assessment(s):")
        for a in assessments:
            parts.append(
                f"  - {a.get('ref', '?')} ({a.get('value', '?')}): "
                f"Pdiss={a.get('pdiss_w', 0):.2f}W, "
                f"package={a.get('package', '?')}, "
                f"Rth_JA={a.get('rtheta_ja_effective', '?')}C/W, "
                f"Tj={a.get('tj_estimated_c', 0):.1f}C, "
                f"Tj_max={a.get('tj_max_c', '?')}C, "
                f"margin={a.get('margin_c', 0):.1f}C"
            )

    findings = thermal_data.get('findings', [])
    if findings:
        parts.append(f"\n{len(findings)} thermal finding(s):")
        for f in findings[:5]:
            parts.append(f"  - [{f.get('severity', '?')}] {f.get('title', '?')}")

    return '\n'.join(parts)


def _extract_emc_data(analysis: dict, **kwargs) -> str:
    """Extract EMC analysis data as concise text summary."""
    emc_data = kwargs.get('emc_data')
    if not emc_data:
        return 'No EMC analysis data available.'

    parts = []
    summary = emc_data.get('summary', {})
    parts.append(f"EMC risk score: {summary.get('emc_risk_score', '?')}/100")
    parts.append(
        f"Findings: {summary.get('critical', 0)} critical, "
        f"{summary.get('high', 0)} high, "
        f"{summary.get('medium', 0)} medium, "
        f"{summary.get('low', 0)} low"
    )
    parts.append(f"Target standard: {emc_data.get('target_standard', '?')}")

    findings = emc_data.get('findings', [])
    active = [f for f in findings if not f.get('suppressed')]
    if active:
        sev_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
        active.sort(key=lambda x: sev_order.get(x.get('severity', 'INFO'), 5))

        # Group by category
        by_cat: dict[str, int] = {}
        for f in active:
            cat = f.get('category', 'other')
            by_cat[cat] = by_cat.get(cat, 0) + 1
        parts.append(f"\nCategories: {', '.join(f'{c}({n})' for c, n in sorted(by_cat.items()))}")

        # Top findings
        top = [f for f in active if f.get('severity') in ('CRITICAL', 'HIGH')]
        if top:
            parts.append(f"\n{len(top)} critical/high finding(s):")
            for f in top[:10]:
                parts.append(
                    f"  - [{f.get('severity')}] {f.get('rule_id', '?')}: "
                    f"{f.get('title', '?')}"
                )
                if f.get('recommendation'):
                    parts.append(f"    Recommendation: {f['recommendation'][:120]}")

    return '\n'.join(parts)


def _extract_pcb_data(analysis: dict, **kwargs) -> str:
    """Extract PCB design data as concise text summary."""
    pcb_data = kwargs.get('pcb_data')
    if not pcb_data:
        return 'No PCB analysis data available.'

    parts = []
    stats = pcb_data.get('statistics', {})
    if stats:
        parts.append(f"Copper layers: {stats.get('copper_layers_used', '?')}")
        parts.append(f"Footprints: {stats.get('footprint_count', '?')} "
                     f"(front={stats.get('front_side', '?')}, back={stats.get('back_side', '?')})")
        parts.append(f"SMD: {stats.get('smd_count', '?')}, THT: {stats.get('tht_count', '?')}")
        parts.append(f"Tracks: {stats.get('track_segments', '?')} segments, "
                     f"{stats.get('total_track_length_mm', '?')}mm total")
        parts.append(f"Vias: {stats.get('via_count', '?')}")
        parts.append(f"Zones: {stats.get('zone_count', '?')}")
        parts.append(f"Board area: {stats.get('board_width_mm', '?')}mm x "
                     f"{stats.get('board_height_mm', '?')}mm "
                     f"({stats.get('board_area_mm2', '?')}mm2)")
        if stats.get('routing_complete') is not None:
            parts.append(f"Routing: {'complete' if stats['routing_complete'] else 'incomplete'}")

    layers = pcb_data.get('layers', [])
    copper_layers = [l for l in layers if l.get('type') == 'signal']
    if copper_layers:
        parts.append(f"Layer names: {', '.join(l.get('name', '?') for l in copper_layers)}")

    # DFM — violations are now in findings[], summary in dfm_summary
    dfm_summary = pcb_data.get('dfm_summary', {})
    dfm_violations = [f for f in pcb_data.get('findings', [])
                      if isinstance(f, dict) and f.get('category') == 'dfm']
    if dfm_violations:
        parts.append(f"\nDFM violations: {len(dfm_violations)}")
        for v in dfm_violations[:5]:
            parts.append(f"  - {v.get('rule_id', '?')}: {v.get('summary', v.get('message', '?'))}")
    elif dfm_summary.get('violation_count', 0) > 0:
        parts.append(f"\nDFM violations: {dfm_summary['violation_count']}")

    return '\n'.join(parts)


def _extract_bom_data(analysis: dict, **kwargs) -> str:
    """Extract BOM data as concise text summary."""
    parts = []

    stats = analysis.get('statistics', {})
    parts.append(f"Total components: {stats.get('total_components', '?')}")
    parts.append(f"Unique parts: {stats.get('unique_parts', '?')}")

    types = stats.get('component_types', {})
    if types:
        type_str = ', '.join(f"{k}: {v}" for k, v in
                             sorted(types.items(), key=lambda x: -x[1]))
        parts.append(f"By type: {type_str}")

    missing_mpn = stats.get('missing_mpn', [])
    if missing_mpn:
        parts.append(f"Missing MPNs: {len(missing_mpn)} ({', '.join(missing_mpn[:8])}"
                     + (f" +{len(missing_mpn)-8}" if len(missing_mpn) > 8 else "") + ")")

    dnp = stats.get('dnp_parts', 0)
    if dnp:
        parts.append(f"DNP parts: {dnp}")

    bom = analysis.get('bom', [])
    if bom:
        # Count parts with/without MPN
        with_mpn = sum(1 for b in bom if b.get('mpn'))
        parts.append(f"BOM lines: {len(bom)} ({with_mpn} with MPN)")

    return '\n'.join(parts) if parts else 'No BOM data available.'


def _extract_test_data(analysis: dict, **kwargs) -> str:
    """Extract test and debug data as concise text summary."""
    parts = []
    sa = group_findings(analysis)

    debug = sa.get(Det.DEBUG_INTERFACES, [])
    if debug:
        parts.append(f"{len(debug)} debug interface(s):")
        for d in debug:
            parts.append(f"  - {d.get('ref', '?')}: {d.get('type', '?')} ({d.get('protocol', '?')})")

    # LED indicators
    leds = sa.get(Det.LED_AUDIT, [])
    if leds:
        parts.append(f"{len(leds)} LED indicator(s)")

    if not parts:
        parts.append('No debug interfaces detected.')

    return '\n'.join(parts)


def _extract_executive_data(analysis: dict, **kwargs) -> str:
    """Extract executive summary data combining all sources."""
    parts = []

    # Core stats
    stats = analysis.get('statistics', {})
    tb = analysis.get('title_block', {})
    if tb.get('title'):
        parts.append(f"Project: {tb['title']}")
    parts.append(
        f"Design: {stats.get('total_components', '?')} components, "
        f"{stats.get('unique_parts', '?')} unique, "
        f"{stats.get('total_nets', '?')} nets"
    )

    # Key ICs
    components = analysis.get('components', [])
    ics = [c for c in components if c.get('type') == 'ic']
    if ics:
        parts.append(f"Key ICs: {', '.join(c.get('value', '?') for c in ics[:5])}")

    # Power summary
    regs = group_findings(analysis).get(Det.POWER_REGULATORS, [])
    if regs:
        rails = []
        for r in regs:
            vout = r.get('estimated_vout')
            rail = r.get('output_rail') or '?'
            if vout:
                rails.append(f"{rail} ({vout:.1f}V)")
            else:
                rails.append(rail)
        parts.append(f"Power rails: {', '.join(rails)}")

    # EMC
    emc_data = kwargs.get('emc_data')
    if emc_data:
        emc_sum = emc_data.get('summary', {})
        parts.append(
            f"EMC risk: {emc_sum.get('emc_risk_score', '?')}/100 "
            f"({emc_sum.get('critical', 0)}C/{emc_sum.get('high', 0)}H/"
            f"{emc_sum.get('medium', 0)}M)"
        )

    # Thermal
    thermal_data = kwargs.get('thermal_data')
    if thermal_data:
        t_sum = thermal_data.get('summary', {})
        parts.append(f"Thermal score: {t_sum.get('thermal_score', '?')}/100")

    # PCB
    pcb_data = kwargs.get('pcb_data')
    if pcb_data:
        pcb_stats = pcb_data.get('statistics', {})
        parts.append(
            f"PCB: {pcb_stats.get('copper_layers_used', '?')} layers, "
            f"{pcb_stats.get('board_width_mm', '?')}x{pcb_stats.get('board_height_mm', '?')}mm"
        )

    # Missing MPNs
    missing = stats.get('missing_mpn', [])
    if missing:
        parts.append(f"Missing MPNs: {len(missing)}")

    return '\n'.join(parts)


def _extract_compliance_data(analysis: dict, **kwargs) -> str:
    """Extract compliance-relevant data."""
    parts = []

    emc_data = kwargs.get('emc_data')
    if emc_data:
        parts.append(f"Target standard: {emc_data.get('target_standard', '?')}")
        summary = emc_data.get('summary', {})
        parts.append(f"EMC risk score: {summary.get('emc_risk_score', '?')}/100")
        parts.append(
            f"Critical: {summary.get('critical', 0)}, High: {summary.get('high', 0)}"
        )

    esd = group_findings(analysis).get(Det.ESD_AUDIT, [])
    if esd:
        unprotected = [e for e in esd if isinstance(e, dict) and e.get('coverage') == 'none']
        parts.append(f"ESD: {len(esd)} connectors audited, {len(unprotected)} unprotected")

    if not parts:
        parts.append('No compliance data available.')

    return '\n'.join(parts)


def _extract_mechanical_data(analysis: dict, **kwargs) -> str:
    """Extract mechanical/environmental data."""
    parts = []
    pcb_data = kwargs.get('pcb_data')
    if pcb_data:
        outline = pcb_data.get('board_outline', {})
        if outline:
            parts.append(f"Board: {outline.get('width_mm', '?')}mm x "
                         f"{outline.get('height_mm', '?')}mm")
        stats = pcb_data.get('statistics', {})
        parts.append(f"Footprints: front={stats.get('front_side', '?')}, "
                     f"back={stats.get('back_side', '?')}")

    if not parts:
        parts.append('No mechanical data available.')

    return '\n'.join(parts)


# ======================================================================
# Extractor registry
# ======================================================================

SECTION_DATA_EXTRACTORS = {
    'system_overview': _extract_overview_data,
    'power_design': _extract_power_data,
    'signal_interfaces': _extract_signal_data,
    'analog_design': _extract_analog_data,
    'thermal_analysis': _extract_thermal_data,
    'emc_analysis': _extract_emc_data,
    'pcb_design': _extract_pcb_data,
    'bom_summary': _extract_bom_data,
    'test_debug': _extract_test_data,
    'executive_summary': _extract_executive_data,
    'compliance': _extract_compliance_data,
    'mechanical_environmental': _extract_mechanical_data,
}

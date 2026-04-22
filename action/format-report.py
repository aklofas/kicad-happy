#!/usr/bin/env python3
"""Format kicad-happy analyzer JSON outputs into markdown reports.

Produces two outputs:
1. A PR comment (concise, human-readable, no JSON dumps)
2. A full step summary (detailed, follows report-generation.md structure)
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add kicad scripts to path for project_config
_kicad_scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'skills', 'kicad', 'scripts')
if os.path.isdir(_kicad_scripts):
    sys.path.insert(0, os.path.abspath(_kicad_scripts))

from finding_schema import Det, group_findings


def _load_json(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _group_findings(analysis):
    """Group findings by detector name, returning empty dict for falsy input."""
    if not analysis:
        return {}
    return group_findings(analysis)


def _safe_float(val, fmt=".1f"):
    """Format a value as float, handling strings gracefully."""
    if isinstance(val, (int, float)):
        return f"{val:{fmt}}"
    return str(val) if val else "—"

def _extract_rail_names(rails):
    """Extract rail names from list that may contain strings or dicts."""
    names = []
    for rail in rails:
        if isinstance(rail, dict):
            names.append(rail.get('name', str(rail)))
        else:
            names.append(str(rail))
    return names

# ---------------------------------------------------------------------------
# Top-Risk Summary
# ---------------------------------------------------------------------------

def _render_top_risks(emc, thermal):
    """Render top-risk summary from EMC and thermal findings."""
    try:
        from project_config import compute_top_risks
    except ImportError:
        return []

    all_findings = []
    if emc:
        for f in emc.get("findings", []):
            f.setdefault("source", "EMC")
            all_findings.append(f)
    if thermal:
        for f in thermal.get("findings", []):
            f.setdefault("source", "Thermal")
            all_findings.append(f)

    if not all_findings:
        return []

    risks = compute_top_risks(all_findings)
    L = []

    bucket_labels = {
        "respin": ("PCB Respin Risks", "Issues that may require a board re-order"),
        "bringup": ("Bring-Up Blockers", "Issues that may cause failure on first power-up"),
        "manufacturing": ("Manufacturing Risks", "Issues that may delay production"),
    }

    has_content = False
    for bucket in ("respin", "bringup", "manufacturing"):
        items = risks.get(bucket, [])
        if not items:
            continue
        if not has_content:
            L.append("### Top Risks")
            L.append("")
            has_content = True
        label, desc = bucket_labels[bucket]
        L.append(f"**{label}** — {desc}")
        L.append("")
        for f in items:
            sev = f.get("severity", "?")
            icon = "\U0001f534" if sev == "CRITICAL" else "\u26a0\ufe0f" if sev == "HIGH" else "\U0001f7e1"
            conf = f.get("confidence", "")
            conf_badge = f" `{conf}`" if conf else ""
            source = f.get("source", "")
            L.append(f"- {icon} **{f.get('rule_id', '')}**: "
                     f"{f.get('title', '')}{conf_badge} ({source})")
        L.append("")

    return L


# ---------------------------------------------------------------------------
# Missing Information Section
# ---------------------------------------------------------------------------

def _render_missing_info(sch, thermal):
    """Render missing information section from analyzer outputs."""
    items = []

    if sch:
        mi = sch.get("missing_info", {})
        mpn = mi.get("missing_mpn", [])
        if mpn:
            items.append(f"**Missing MPNs** ({len(mpn)}): {', '.join(mpn[:8])}"
                         + (f" +{len(mpn)-8} more" if len(mpn) > 8 else ""))
        ds = mi.get("missing_datasheet", [])
        if ds:
            items.append(f"**Missing datasheets** ({len(ds)}): {', '.join(ds[:8])}"
                         + (f" +{len(ds)-8} more" if len(ds) > 8 else ""))
        fp = mi.get("missing_footprint", [])
        if fp:
            items.append(f"**Missing footprints** ({len(fp)}): {', '.join(fp[:8])}"
                         + (f" +{len(fp)-8} more" if len(fp) > 8 else ""))
        vref = mi.get("heuristic_vref", [])
        if vref:
            items.append(f"**Heuristic Vref** ({len(vref)}): {', '.join(vref)} "
                         "— output voltage estimated from part number, not datasheet")

    if thermal:
        mi = thermal.get("missing_info", {})
        rtheta = mi.get("default_rtheta_ja", [])
        if rtheta:
            items.append(f"**Default thermal resistance** ({len(rtheta)}): "
                         f"{', '.join(rtheta[:6])}"
                         + (f" +{len(rtheta)-6} more" if len(rtheta) > 6 else "")
                         + " — using conservative fallback, not datasheet value")

    if not items:
        return []

    L = []
    L.append(f"<details><summary>Missing Information ({len(items)} gaps)</summary>")
    L.append("")
    for item in items:
        L.append(f"- {item}")
    L.append("")
    L.append("</details>")
    L.append("")
    return L


# ---------------------------------------------------------------------------
# Trust / Evidence Section
# ---------------------------------------------------------------------------

def _render_trust_evidence(sch, pcb, emc, thermal):
    """Render trust/evidence summary from analyzer trust_summary blocks."""
    sections = []
    if sch:
        sections.append(('Schematic', sch.get('trust_summary')))
    if pcb:
        sections.append(('PCB', pcb.get('trust_summary')))
    if emc:
        sections.append(('EMC', emc.get('trust_summary')))
    if thermal:
        sections.append(('Thermal', thermal.get('trust_summary')))

    # Filter to sections that have trust_summary
    sections = [(name, ts) for name, ts in sections if ts]
    if not sections:
        return []

    L = []

    # Compute aggregate counts across all analyzers
    total_findings = 0
    total_deterministic = 0
    total_heuristic = 0
    total_datasheet = 0
    total_unknown = 0
    for _, ts in sections:
        total_findings += ts.get('total_findings', 0)
        bc = ts.get('by_confidence', {})
        total_deterministic += bc.get('deterministic', 0)
        total_heuristic += bc.get('heuristic', 0)
        total_datasheet += bc.get('datasheet-backed', 0)
        total_unknown += ts.get('unknown_confidence', 0)

    if total_findings == 0:
        return []

    # Determine overall trust level (worst of all analyzers)
    levels = [ts.get('trust_level', 'high') for _, ts in sections]
    if 'low' in levels:
        overall = 'low'
    elif 'mixed' in levels:
        overall = 'mixed'
    else:
        overall = 'high'

    trust_icon = {'high': '\u2705', 'mixed': '\u26a0\ufe0f', 'low': '\u274c'}
    level_icon = trust_icon.get(overall, '')

    det_pct = round(100 * total_deterministic / total_findings)
    heur_pct = round(100 * total_heuristic / total_findings)

    header = (f"Trust / Evidence {level_icon} — "
              f"{det_pct}% deterministic, {heur_pct}% heuristic"
              f" ({total_findings} findings)")

    L.append(f"<details><summary>{header}</summary>")
    L.append("")

    # Per-analyzer breakdown
    L.append("| Analyzer | Findings | Deterministic | Heuristic | Datasheet | Trust |")
    L.append("|----------|----------|---------------|-----------|-----------|-------|")
    for name, ts in sections:
        n = ts.get('total_findings', 0)
        if n == 0:
            continue
        bc = ts.get('by_confidence', {})
        d = bc.get('deterministic', 0)
        h = bc.get('heuristic', 0)
        ds = bc.get('datasheet-backed', 0)
        level = ts.get('trust_level', '?')
        icon = trust_icon.get(level, '')
        L.append(f"| {name} | {n} | {d} ({round(100*d/n)}%) | "
                 f"{h} ({round(100*h/n)}%) | {ds} | {icon} {level} |")
    L.append("")

    # BOM coverage (schematic only)
    if sch:
        ts = sch.get('trust_summary', {})
        bom_cov = ts.get('bom_coverage')
        if bom_cov:
            mpn_pct = bom_cov.get('mpn_pct', 0)
            ds_pct = bom_cov.get('datasheet_pct', 0)
            total_comp = bom_cov.get('total_components', 0)
            L.append(f"**BOM evidence** ({total_comp} components): "
                     f"{mpn_pct:.0f}% have MPNs, {ds_pct:.0f}% have datasheets")
            L.append("")

    # Provenance coverage
    prov_values = [ts.get('provenance_coverage_pct', 0) for _, ts in sections
                   if ts.get('total_findings', 0) > 0]
    if prov_values:
        avg_prov = round(sum(prov_values) / len(prov_values), 1)
        L.append(f"**Provenance coverage**: {avg_prov}% of findings carry detector provenance")
        L.append("")

    # Evidence blockers
    blockers = []
    if total_unknown > 0:
        blockers.append(f"{total_unknown} findings with unknown confidence")
    if sch:
        ts = sch.get('trust_summary', {})
        bom_cov = ts.get('bom_coverage')
        if bom_cov and bom_cov.get('mpn_pct', 100) < 50:
            blockers.append(f"Low MPN coverage ({bom_cov['mpn_pct']:.0f}%) "
                            "limits datasheet-backed verification")
    if blockers:
        L.append("**Evidence blockers:**")
        for b in blockers:
            L.append(f"- {b}")
        L.append("")

    L.append("</details>")
    L.append("")
    return L


# ---------------------------------------------------------------------------
# Tier 1: PR Comment
# ---------------------------------------------------------------------------

def format_report(schematic_path, pcb_path, spice_path, emc_path,
                  severity, derating_profile, run_url=None, diff_path=None,
                  thermal_path=None):
    sch = _load_json(schematic_path)
    pcb = _load_json(pcb_path)
    spice = _load_json(spice_path)
    emc = _load_json(emc_path)
    diff_data = _load_json(diff_path)
    thermal = _load_json(thermal_path)

    L = []
    findings = []     # (severity, detail, source)
    verified = []     # things confirmed working

    # === Header ===
    L.append("## KiCad Design Review")
    L.append("")

    if sch:
        stats = sch.get("statistics", {})
        filename = Path(sch.get("file", "unknown")).name
        rails = stats.get("power_rails", [])
        rail_str = f", {len(rails)} power rails" if rails else ""
        L.append(f"**{filename}** — {stats.get('total_components', 0)} components, "
                 f"{stats.get('unique_parts', 0)} unique, "
                 f"{stats.get('total_nets', 0)} nets{rail_str}")
        L.append("")

    # === Changes from Base (diff section) ===
    if diff_data and diff_data.get("has_changes"):
        s = diff_data.get("summary", {})
        L.append("### Changes from Base")
        L.append("")
        L.append(f"> {s.get('total_changes', 0)} changes: "
                 f"+{s.get('added', 0)} added, "
                 f"-{s.get('removed', 0)} removed, "
                 f"~{s.get('modified', 0)} modified "
                 f"({s.get('severity', 'unknown')})")
        L.append("")
        diff_detail = diff_data.get("diff", {})
        rows = []
        # Component changes
        for c in diff_detail.get("components", {}).get("added", [])[:5]:
            rows.append(f"| + {c.get('reference', '?')} | New: {c.get('value', '')} {c.get('footprint', '')} |")
        for c in diff_detail.get("components", {}).get("removed", [])[:5]:
            rows.append(f"| - {c.get('reference', '?')} | Removed: {c.get('value', '')} |")
        for c in diff_detail.get("components", {}).get("modified", [])[:5]:
            for ch in c.get("changes", []):
                rows.append(f"| ~ {c.get('reference', '?')} {ch.get('field', '')} | {ch.get('base', '?')} → {ch.get('head', '?')} |")
        # Signal analysis changes (diff output may still use signal_analysis key)
        for det_type, det_diff in diff_detail.get("signal_analysis", {}).items():
            label = det_type.replace("_", " ").title()
            for m in det_diff.get("modified", [])[:3]:
                for ch in m.get("changes", []):
                    base_v = ch.get("base", "?")
                    head_v = ch.get("head", "?")
                    pct = ch.get("delta_pct")
                    pct_str = f" ({pct:+.1f}%)" if pct is not None else ""
                    rows.append(f"| ~ {label} {m.get('identity', '?')} | {ch.get('field', '')}: {base_v} → {head_v}{pct_str} |")
        # EMC finding changes
        for f in diff_detail.get("findings", {}).get("new", [])[:3]:
            rows.append(f"| NEW {f.get('severity', '?')} | {f.get('rule_id', '?')}: {f.get('title', '')} |")
        for f in diff_detail.get("findings", {}).get("resolved", [])[:3]:
            rows.append(f"| RESOLVED | {f.get('rule_id', '?')}: {f.get('title', '')} |")
        # SPICE status changes
        for sc in diff_detail.get("status_changes", [])[:3]:
            comps = ", ".join(sc.get("components", []))
            rows.append(f"| ~ {sc.get('subcircuit_type', '?')} {comps} | {sc.get('base_status', '?')} → {sc.get('head_status', '?')} |")
        if rows:
            L.append("| Change | Detail |")
            L.append("|--------|--------|")
            L.extend(rows[:10])
            remaining = s.get("total_changes", 0) - min(len(rows), 10)
            if remaining > 0:
                L.append(f"| | *...and {remaining} more* |")
            L.append("")

    # === Top-Risk Summary ===
    risk_lines = _render_top_risks(emc, thermal)
    if risk_lines:
        L.extend(risk_lines)

    # === Collect all findings ===
    sig = _group_findings(sch)
    vd = sch.get("voltage_derating", {}) if sch else {}
    pc = sch.get("protocol_compliance", {}) if sch else {}

    # Voltage derating issues
    for issue in vd.get("issues", []):
        ref = issue.get("ref", "?")
        ctype = issue.get("component_type", "")
        rule = issue.get("derating_rule", "")
        rail = issue.get("rail", "")
        if ctype == "capacitor":
            detail = (f"{ref} ({issue.get('value','')}) on {rail}: "
                      f"{_safe_float(issue.get('rated_voltage'), '.0f')}V rated, "
                      f"{_safe_float(issue.get('rail_voltage'), '.1f')}V applied — {rule}")
        elif ctype == "ic":
            detail = (f"{ref} ({issue.get('value','')}) on {rail}: "
                      f"abs max {_safe_float(issue.get('abs_max_vin'), '.1f')}V, "
                      f"applied {_safe_float(issue.get('rail_voltage'), '.1f')}V")
        elif ctype == "resistor":
            est = issue.get('estimated_power_w', 0)
            rat = issue.get('rated_power_w', 0)
            detail = (f"{ref} ({issue.get('value','')}) {issue.get('package','')}: "
                      f"{_safe_float(est*1000 if isinstance(est,(int,float)) else est, '.0f')}mW / "
                      f"{_safe_float(rat*1000 if isinstance(rat,(int,float)) else rat, '.0f')}mW rated")
        else:
            detail = f"{ref}: {rule}"
        findings.append((issue.get("severity", "warning"), detail, "Derating"))

    # Protocol compliance issues (deduplicated)
    seen_pc = set()
    for finding in pc.get("findings", []):
        for issue_text in finding.get("issues", []) or []:
            key = f"{finding['protocol']}:{issue_text}"
            if key not in seen_pc:
                seen_pc.add(key)
                findings.append(("warning", issue_text, finding["protocol"].upper()))

    # Connectivity issues
    conn = sch.get("connectivity_issues", {}) if sch else {}
    for net in conn.get("single_pin_nets", [])[:3]:
        findings.append(("warning", f"Single-pin net: {net}", "Connectivity"))

    # Filter by severity
    if severity == "critical":
        findings = [f for f in findings if f[0] == "critical"]
    elif severity == "warning":
        findings = [f for f in findings if f[0] in ("critical", "warning")]

    critical_count = sum(1 for s, _, _ in findings if s == "critical")
    warning_count = sum(1 for s, _, _ in findings if s == "warning")

    # === Collect verified items ===
    for reg in sig.get(Det.POWER_REGULATORS, []):
        vout = reg.get("estimated_vout")
        if vout and isinstance(vout, (int, float)):
            verified.append(f"{reg['ref']} → {reg.get('output_rail','')} at {vout:.2f}V")

    for finding in pc.get("findings", []):
        checks = finding.get("checks", {})
        if finding.get("protocol") == "i2c":
            pu = checks.get("pull_ups_present", {})
            if pu.get("status") == "pass":
                verified.append("I2C pull-ups present")
            rt = checks.get("rise_time", {})
            for ln in ("sda", "scl"):
                if ln in rt and rt[ln].get("valid_400khz"):
                    verified.append(f"I2C {ln.upper()} rise time {rt[ln]['rise_time_ns']}ns (fast mode OK)")

    caps_ok = vd.get("caps_checked", 0) - len([i for i in vd.get("issues", []) if i.get("component_type") == "capacitor"])
    if caps_ok > 0:
        verified.append(f"{caps_ok} cap(s) pass voltage derating")

    if pcb:
        pcb_conn = pcb.get("connectivity", {})
        if pcb_conn.get("routing_complete"):
            verified.append("PCB routing 100% complete")

    if spice:
        spice_pass = spice.get("summary", {}).get("pass", 0)
        if spice_pass > 0:
            verified.append(f"{spice_pass} SPICE subcircuit(s) confirmed")

    if emc:
        emc_summary = emc.get("summary", {})
        emc_score = emc_summary.get("emc_risk_score", 0)
        emc_crit = emc_summary.get("critical", 0)
        emc_high = emc_summary.get("high", 0)
        emc_checks = emc_summary.get("total_checks", 0)
        if emc_crit > 0:
            findings.append(("CRITICAL", f"EMC: {emc_crit} critical finding(s) — score {emc_score}/100", "emc"))
        if emc_high > 0:
            findings.append(("WARNING", f"EMC: {emc_high} high-risk finding(s)", "emc"))
        if emc_checks > 0 and emc_crit == 0 and emc_high == 0:
            verified.append(f"EMC risk score {emc_score}/100 — no critical/high findings")

    # === Summary bar ===
    parts = []
    if critical_count:
        parts.append(f"{critical_count} critical")
    if warning_count:
        parts.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
    parts.append(f"{len(verified)} verified")
    if run_url:
        parts.append(f"[**Full report →**]({run_url})")
    L.append(f"> {' · '.join(parts)}")
    L.append("")

    # === Findings ===
    if findings:
        L.append("### Findings")
        L.append("")
        L.append("| | Issue | Source |")
        L.append("|---|---|---|")
        for sev, detail, source in sorted(findings, key=lambda x: (0 if x[0] == "critical" else 1)):
            icon = "🔴" if sev == "critical" else "⚠️"
            L.append(f"| {icon} | {detail} | {source} |")
        L.append("")

    # === Power ===
    regs = sig.get(Det.POWER_REGULATORS, [])
    sleep = sch.get("sleep_current_audit") if sch else None
    if regs:
        L.append("### Power")
        L.append("")
        for reg in regs:
            vout = reg.get("estimated_vout")
            vout_str = f"→ {vout:.2f}V" if isinstance(vout, (int, float)) else ""
            topo = reg.get("topology", "")
            L.append(f"- **{reg['ref']}** ({reg.get('value','')}) {topo} "
                     f"{reg.get('input_rail','')} {vout_str} on {reg.get('output_rail','')}")
            # Output caps
            out_caps = reg.get("output_capacitors", [])
            if out_caps:
                total_uf = sum(c.get("farads", 0) for c in out_caps) * 1e6
                L.append(f"  - Output caps: {total_uf:.1f}µF ({len(out_caps)} caps)")
        if sleep:
            total_ua = sleep.get("total_estimated_sleep_uA")
            if isinstance(total_ua, (int, float)):
                L.append(f"- Sleep current: {total_ua:.0f}µA estimated")
        L.append("")

    # === Buses & Protocols ===
    buses = sch.get("design_analysis", {}).get("bus_analysis", {}) if sch else {}
    has_bus_content = any(buses.get(k) for k in ("i2c", "spi", "uart", "can")) or pc.get("findings")
    if has_bus_content:
        L.append("### Buses & Protocols")
        L.append("")
        seen_proto = set()
        for finding in pc.get("findings", []):
            proto = finding["protocol"].upper()
            issues = finding.get("issues", []) or []
            checks = finding.get("checks", {})
            devices = finding.get("devices", [])
            dev_names = [d.get('reference', d.get('ref', str(d))) if isinstance(d, dict) else str(d)
                         for d in devices[:4]]
            dev_str = f" ({', '.join(dev_names)})" if dev_names else ""

            if proto == "I2C" and checks:
                detail_key = f"I2C:{finding.get('sda_net','')}"
                if detail_key in seen_proto:
                    continue
                seen_proto.add(detail_key)
                pu = checks.get("pull_ups_present", {})
                rt = checks.get("rise_time", {})
                parts = []
                if pu.get("status") == "fail":
                    parts.append("pull-ups missing")
                elif pu.get("status") == "pass":
                    # Show pull-up value if available
                    pv = checks.get("pull_up_value", {})
                    for ln in ("sda", "scl"):
                        if ln in pv:
                            parts.append(f"{pv[ln].get('ref','')}={pv[ln].get('ohms','')}Ω")
                for ln in ("sda", "scl"):
                    if ln in rt:
                        tr = rt[ln]
                        parts.append(f"{ln.upper()} t_r={tr['rise_time_ns']}ns")
                L.append(f"- **I2C**{dev_str}: {', '.join(parts)}")
            else:
                issue_key = f"{proto}:{';'.join(sorted(issues))}"
                if issue_key in seen_proto:
                    continue
                seen_proto.add(issue_key)
                if issues:
                    L.append(f"- **{proto}**{dev_str}: {issues[0]}")
                else:
                    L.append(f"- **{proto}**{dev_str}: OK")

        # Add buses that had no protocol compliance findings
        for bus_type in ("spi", "can"):
            if buses.get(bus_type) and bus_type.upper() not in [f["protocol"].upper() for f in pc.get("findings", [])]:
                count = len(buses[bus_type])
                L.append(f"- **{bus_type.upper()}**: {count} signal(s) detected")
        L.append("")

    # === Component Health ===
    if vd or (sch and sch.get("statistics", {}).get("missing_mpn")):
        L.append("### Component Health")
        L.append("")
        if vd:
            profile = vd.get("derating_profile", derating_profile)
            caps = vd.get("caps_checked", 0)
            ics = vd.get("ics_checked", 0)
            res = vd.get("resistors_checked", 0)
            issue_count = len(vd.get("issues", []))
            parts = []
            if caps: parts.append(f"{caps} caps")
            if ics: parts.append(f"{ics} ICs")
            if res: parts.append(f"{res} resistors")
            status = f"{issue_count} issue(s)" if issue_count else "all pass"
            L.append(f"- Derating: {', '.join(parts)} checked ({profile}) — {status}")

            od = vd.get("over_designed", [])
            if od:
                for item in od[:2]:
                    L.append(f"- Over-designed: {item.get('ref','')} ({item.get('value','')}) — "
                             f"{item.get('suggestion','')}" if item.get('suggestion') else
                             f"- Over-designed: {item.get('ref','')} ({item.get('value','')}) — "
                             f"margin {_safe_float(item.get('margin_pct'), '.0f')}%")

        if sch:
            stats = sch.get("statistics", {})
            missing = stats.get("missing_mpn", [])
            total = stats.get("total_components", 0)
            if total > 0:
                with_mpn = total - len(missing)
                pct = with_mpn / total * 100
                L.append(f"- MPN coverage: {with_mpn}/{total} ({pct:.0f}%)")
        L.append("")

    # === Signal Analysis (compact) ===
    sig_items = []
    for key, label in [(Det.VOLTAGE_DIVIDERS, "divider"), (Det.RC_FILTERS, "RC filter"),
                       (Det.LC_FILTERS, "LC filter"), (Det.OPAMP_CIRCUITS, "opamp"),
                       (Det.TRANSISTOR_CIRCUITS, "transistor"), (Det.PROTECTION_DEVICES, "protection"),
                       (Det.CRYSTAL_CIRCUITS, "crystal"), (Det.CURRENT_SENSE, "current sense")]:
        items = sig.get(key, [])
        if items:
            sig_items.append(f"{len(items)} {label}{'s' if len(items) > 1 else ''}")
    if sig_items and not regs:  # Don't repeat if power section already shown
        L.append("### Signal Analysis")
        L.append("")
        L.append(f"{', '.join(sig_items)}")
        L.append("")
    elif sig_items:
        # Add non-power detections as a compact line
        non_power = [s for s in sig_items]
        if non_power:
            L.append(f"**Detected:** {', '.join(non_power)}")
            L.append("")

    # === Opamp warnings (if any) ===
    opamps = sig.get(Det.OPAMP_CIRCUITS, [])
    opamp_warnings = [(oa["reference"], w) for oa in opamps for w in oa.get("warnings", [])]
    unused_channels = [(oa["reference"], oa["unused_channels"]) for oa in opamps if oa.get("unused_channels")]
    if opamp_warnings or unused_channels:
        L.append("### Op-Amp Checks")
        L.append("")
        for ref, warning in opamp_warnings:
            L.append(f"- {ref}: {warning}")
        for ref, channels in unused_channels:
            L.append(f"- {ref}: unused channel(s) {channels}")
        L.append("")

    # === PCB (dense one-liner) ===
    if pcb:
        dfm = pcb.get("dfm", {})
        metrics = dfm.get("metrics", {})
        w = metrics.get("board_width_mm", "?")
        h = metrics.get("board_height_mm", "?")
        all_layers = pcb.get("layers", [])
        signal_layers = sum(1 for l in all_layers if l.get("type") == "signal")
        fp_count = len(pcb.get("footprints", []))
        track_count = pcb.get("tracks", {}).get("segment_count", 0)
        via_count = pcb.get("vias", {}).get("count", 0)
        tier = dfm.get("dfm_tier", "?")
        pcb_conn = pcb.get("connectivity", {})
        routing = "100%" if pcb_conn.get("routing_complete") else f"{pcb_conn.get('unrouted_count', '?')} unrouted"

        L.append("### PCB")
        L.append("")
        L.append(f"{w} × {h}mm · {signal_layers} layers · {fp_count} footprints · "
                 f"{track_count} tracks · {via_count} vias · DFM: {tier} · Routing: {routing}")
        L.append("")

        # Thermal pad warnings
        tpv = pcb.get("thermal_pad_vias", [])
        insufficient = [t for t in tpv if t.get("adequacy") == "insufficient"]
        if insufficient:
            for t in insufficient[:3]:
                L.append(f"- ⚠️ {t.get('reference','')} ({t.get('value','')}) thermal vias: "
                         f"{t.get('via_count',0)} — insufficient")
            L.append("")

    # === SPICE (one-liner unless failures) ===
    if spice:
        summary = spice.get("summary", {})
        total = summary.get("total", 0)
        passed = summary.get("pass", 0)
        warn = summary.get("warn", 0)
        fail = summary.get("fail", 0)

        L.append("### SPICE")
        L.append("")
        L.append(f"{total} subcircuits — **{passed} pass**, {warn} warn, {fail} fail")

        # Show failures and warnings
        for r in spice.get("simulation_results", []):
            if r.get("status") == "fail":
                comps = ", ".join(r.get("components", []))
                L.append(f"- 🔴 FAIL: {r.get('subcircuit_type','')} ({comps})")
            elif r.get("status") == "warn":
                comps = ", ".join(r.get("components", []))
                note = r.get("note", "")
                L.append(f"- ⚠️ {r.get('subcircuit_type','')} ({comps}): {note}")
        L.append("")

    # === EMC (one-liner summary + critical/high findings) ===
    if emc:
        emc_s = emc.get("summary", {})
        emc_total = emc_s.get("total_checks", 0)
        emc_score = emc_s.get("emc_risk_score", 0)
        emc_crit = emc_s.get("critical", 0)
        emc_high = emc_s.get("high", 0)

        L.append("### EMC")
        L.append("")
        emc_suppressed = emc_s.get("suppressed", 0)
        sup_str = f", {emc_suppressed} suppressed" if emc_suppressed else ""
        L.append(f"Risk score **{emc_score}/100** — {emc_total} checks: "
                 f"{emc_crit} critical, {emc_high} high{sup_str}")

        for f in emc.get("findings", []):
            if f.get("suppressed"):
                continue
            sev = f.get("severity", "")
            if sev in ("CRITICAL", "HIGH"):
                rule = f.get("rule_id", "")
                title = f.get("title", "")
                icon = "\U0001f534" if sev == "CRITICAL" else "\u26a0\ufe0f"
                L.append(f"- {icon} {rule}: {title}")
        L.append("")

    # === Thermal Analysis ===
    if thermal:
        ts = thermal.get("summary", {})
        th_score = ts.get("thermal_score", 0)
        th_crit = ts.get("critical", 0)
        th_high = ts.get("high", 0)
        th_total = ts.get("total_checks", 0)
        th_pdiss = ts.get("total_board_dissipation_w", 0)

        if th_total > 0:
            L.append("### Thermal Analysis")
            L.append("")
            th_suppressed = ts.get("suppressed", 0)
            th_sup_str = f", {th_suppressed} suppressed" if th_suppressed else ""
            L.append(f"Score **{th_score}/100** — {th_total} checks, "
                     f"total dissipation {th_pdiss:.2f}W{th_sup_str}")

            for f in thermal.get("findings", []):
                if f.get("suppressed"):
                    continue
                sev = f.get("severity", "")
                if sev in ("CRITICAL", "HIGH", "MEDIUM"):
                    rule = f.get("rule_id", "")
                    title = f.get("title", "")
                    icon = "\U0001f534" if sev == "CRITICAL" else "\u26a0\ufe0f" if sev == "HIGH" else "\U0001f7e1"
                    L.append(f"- {icon} {rule}: {title}")
            L.append("")

        if th_crit == 0 and th_high == 0 and th_total > 0:
            verified.append(f"Thermal score {th_score}/100 — no critical/high findings")

    # === Missing Information ===
    mi_lines = _render_missing_info(sch, thermal)
    if mi_lines:
        L.extend(mi_lines)

    # === Trust / Evidence ===
    trust_lines = _render_trust_evidence(sch, pcb, emc, thermal)
    if trust_lines:
        L.extend(trust_lines)

    # === Verified (collapsible, at bottom) ===
    if verified:
        L.append(f"<details><summary>Verified ({len(verified)} checks passed)</summary>")
        L.append("")
        for v in verified:
            L.append(f"- {v}")
        L.append("")
        L.append("</details>")
        L.append("")

    # === Footer ===
    L.append("---")
    if run_url:
        L.append(f"*[kicad-happy](https://github.com/aklofas/kicad-happy)* · **[Full report →]({run_url})**")
    else:
        L.append("*Generated by [kicad-happy](https://github.com/aklofas/kicad-happy)*")
    L.append("<!-- kicad-happy-review -->")

    report = "\n".join(L)
    summary_data = {
        "findings_count": critical_count + warning_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "verified_count": len(verified),
        "has_critical": critical_count > 0,
        "has_schematic": sch is not None,
        "has_pcb": pcb is not None,
        "has_spice": spice is not None,
        "has_emc": emc is not None,
    }

    return report, summary_data


# ---------------------------------------------------------------------------
# Full Report (Step Summary)
# ---------------------------------------------------------------------------

def format_full_report(schematic_path, pcb_path, spice_path, emc_path, derating_profile):
    """Generate the full step summary — no JSON dumps, all human-readable."""
    sch = _load_json(schematic_path)
    pcb = _load_json(pcb_path)
    spice = _load_json(spice_path)
    emc = _load_json(emc_path)

    L = []
    a = L.append

    stats = sch.get("statistics", {}) if sch else {}
    sig = _group_findings(sch)

    # === Header ===
    a("# Design Review — Full Report")
    a("")
    if sch:
        filename = Path(sch.get("file", "unknown")).name
        rails = stats.get("power_rails", [])
        a(f"**{filename}** — {stats.get('total_components', 0)} components "
          f"({stats.get('unique_parts', 0)} unique), {stats.get('total_nets', 0)} nets, "
          f"{stats.get('total_no_connects', 0)} no-connects")
        if rails:
            a(f"")
            a(f"Power rails: {', '.join(_extract_rail_names(rails))}")
        a("")

    # === Critical Findings ===
    all_issues = []
    vd = sch.get("voltage_derating", {}) if sch else {}
    pc = sch.get("protocol_compliance", {}) if sch else {}

    for issue in vd.get("issues", []):
        ref = issue.get("ref", "?")
        ctype = issue.get("component_type", "")
        rule = issue.get("derating_rule", "")
        detail = f"{ref} ({issue.get('value','')}) — {rule}" if ctype != "ic" else \
                 f"{ref} ({issue.get('value','')}) — abs max {_safe_float(issue.get('abs_max_vin'),'.1f')}V"
        all_issues.append((issue.get("severity", "warning"), detail, "Voltage Derating"))

    seen_pc = set()
    for finding in pc.get("findings", []):
        for issue_text in finding.get("issues", []) or []:
            key = f"{finding['protocol']}:{issue_text}"
            if key not in seen_pc:
                seen_pc.add(key)
                all_issues.append(("warning", issue_text, "Protocol Compliance"))

    a("## Critical Findings")
    a("")
    if all_issues:
        a("| Severity | Issue | Section |")
        a("|----------|-------|---------|")
        for sev, detail, section in sorted(all_issues, key=lambda x: (0 if x[0] == "critical" else 1)):
            a(f"| {sev.upper()} | {detail} | {section} |")
    else:
        a("No critical or warning-level issues found.")
    a("")

    # === Component Summary ===
    a("## Component Summary")
    a("")
    type_counts = stats.get("component_types", {})
    if type_counts:
        a("| Type | Count |")
        a("|------|-------|")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            a(f"| {t} | {c} |")
        a("")
    missing = stats.get("missing_mpn", [])
    total = stats.get("total_components", 0)
    if total > 0:
        with_mpn = total - len(missing)
        a(f"**Sourcing:** {with_mpn}/{total} components have MPNs ({with_mpn/total*100:.0f}%)")
        if missing:
            a("")
            a(f"<details><summary>Missing MPNs ({len(missing)})</summary>")
            a("")
            a(", ".join(missing))
            a("")
            a("</details>")
    a("")

    # === Signal Analysis Review ===
    if sig:
        a("## Signal Analysis Review")
        a("")

        # Power Regulators
        regs = sig.get(Det.POWER_REGULATORS, [])
        if regs:
            a("### Power Regulators")
            a("")
            a("| Ref | Value | Topology | Input | Output | Vout | Vref Source |")
            a("|-----|-------|----------|-------|--------|------|-------------|")
            for r in regs:
                vout = r.get("estimated_vout")
                vout_str = f"{float(vout):.2f}V" if isinstance(vout, (int, float)) else "—"
                a(f"| {r.get('ref','')} | {r.get('value','')} | {r.get('topology','')} "
                  f"| {r.get('input_rail','')} | {r.get('output_rail','')} "
                  f"| {vout_str} | {r.get('vref_source','')} |")
            a("")

        # Voltage Dividers
        dividers = sig.get(Det.VOLTAGE_DIVIDERS, [])
        if dividers:
            a("### Voltage Dividers")
            a("")
            for d in dividers:
                ratio = d.get('ratio')
                vout = d.get('vout_estimated')
                ratio_str = f"{float(ratio):.3f}" if isinstance(ratio, (int, float)) else str(ratio)
                vout_str = f"{float(vout):.2f}V" if isinstance(vout, (int, float)) else str(vout)
                a(f"- {d.get('top_ref','')} / {d.get('bottom_ref','')}: "
                  f"ratio={ratio_str}, Vout={vout_str}")
            a("")

        # Filters
        for ftype, fname in [(Det.RC_FILTERS, "RC Filters"), (Det.LC_FILTERS, "LC Filters")]:
            filters = sig.get(ftype, [])
            if filters:
                a(f"### {fname}")
                a("")
                for f in filters:
                    if ftype == Det.RC_FILTERS:
                        comps = f"{f.get('resistor','')} + {f.get('capacitor','')}"
                    else:
                        comps = f"{f.get('inductor','')} + {', '.join(str(c) for c in f.get('capacitors', []))}"
                    fc = f.get("cutoff_frequency_hz") or f.get("resonant_frequency_hz")
                    if isinstance(fc, (int, float)) and fc:
                        fc_str = f"{fc:.0f} Hz" if fc < 1000 else f"{fc/1000:.1f} kHz"
                    else:
                        fc_str = "—"
                    a(f"- {comps}: fc = {fc_str} ({f.get('type', '')})")
                a("")

        # Opamps
        opamps = sig.get(Det.OPAMP_CIRCUITS, [])
        if opamps:
            a("### Op-Amp Circuits")
            a("")
            for oa in opamps:
                gain = oa.get("gain")
                gain_db = oa.get("gain_dB")
                if isinstance(gain, (int, float)) and isinstance(gain_db, (int, float)):
                    gain_str = f"gain={float(gain):.1f} ({float(gain_db):.1f}dB)"
                elif gain:
                    gain_str = f"gain={gain}"
                else:
                    gain_str = ""
                a(f"- **{oa['reference']}** ({oa.get('value','')}) — {oa['configuration']} {gain_str}")
                for w in oa.get("warnings", []):
                    a(f"  - {w}")
                if oa.get("unused_channels"):
                    a(f"  - Unused channels: {oa['unused_channels']} ({oa.get('unused_channel_status','')})")
            a("")

        # Protection
        protection = sig.get(Det.PROTECTION_DEVICES, [])
        if protection:
            a("### Protection Devices")
            a("")
            a("| Ref | Value | Type | Protected Net |")
            a("|-----|-------|------|---------------|")
            for p in protection:
                a(f"| {p.get('ref','')} | {p.get('value','')} | {p.get('type','')} | {p.get('protected_net','')} |")
            a("")

        # Transistors
        transistors = sig.get(Det.TRANSISTOR_CIRCUITS, [])
        if transistors:
            a("### Transistor Circuits")
            a("")
            for t in transistors:
                a(f"- **{t.get('reference','')}** ({t.get('value','')}) — {t.get('type','')}, "
                  f"load: {t.get('load_classification', t.get('load_type', ''))}")
            a("")

        # Crystals
        crystals = sig.get(Det.CRYSTAL_CIRCUITS, [])
        if crystals:
            a("### Crystal Circuits")
            a("")
            for c in crystals:
                caps = c.get("load_caps", [])
                cap_str = ", ".join(f"{lc.get('ref','')}={lc.get('value','')}" for lc in caps) if caps else "none detected"
                a(f"- {c.get('reference','')} ({c.get('value','')}) — load caps: {cap_str}")
            a("")

        # Decoupling
        decoupling = sig.get(Det.DECOUPLING, [])
        if decoupling:
            a("### Decoupling Analysis")
            a("")
            a("| Rail | Caps | Total µF |")
            a("|------|------|----------|")
            for d in decoupling:
                total_uf = d.get('total_capacitance_uF', 0)
                uf_str = f"{float(total_uf):.1f}" if isinstance(total_uf, (int, float)) else str(total_uf)
                a(f"| {d.get('rail','')} | {d.get('cap_count',0)} | {uf_str} |")
            a("")

        # SPICE
        if spice:
            a("### Simulation Verification")
            a("")
            summary = spice.get("summary", {})
            a(f"{summary.get('total',0)} subcircuits verified: "
              f"{summary.get('pass',0)} pass, {summary.get('warn',0)} warn, "
              f"{summary.get('fail',0)} fail, {summary.get('skip',0)} skip")
            a("")
            results = spice.get("simulation_results", [])
            if results:
                a("| Type | Components | Status |")
                a("|------|-----------|--------|")
                for r in results:
                    comps = ", ".join(r.get("components", []))
                    a(f"| {r.get('subcircuit_type','')} | {comps} | {r.get('status','')} |")
                a("")

        # EMC
        if emc:
            emc_s = emc.get("summary", {})
            a("### EMC Pre-Compliance")
            a("")
            a(f"Risk score **{emc_s.get('emc_risk_score', 0)}/100** — "
              f"{emc_s.get('total_checks', 0)} checks: "
              f"{emc_s.get('critical', 0)} critical, "
              f"{emc_s.get('high', 0)} high, "
              f"{emc_s.get('medium', 0)} medium")
            a("")
            emc_findings = emc.get("findings", [])
            actionable = [f for f in emc_findings if f.get("severity") in ("CRITICAL", "HIGH", "MEDIUM")]
            if actionable:
                a("| Severity | Rule | Finding |")
                a("|----------|------|---------|")
                for f in actionable[:15]:
                    a(f"| {f.get('severity','')} | {f.get('rule_id','')} | {f.get('title','')} |")
                a("")

            # Test plan highlights
            tp = emc.get("test_plan", {})
            bands = tp.get("frequency_bands", [])
            high_risk = [b for b in bands if b.get("risk_level") in ("high", "medium") and b.get("source_count", 0) > 0]
            if high_risk:
                a("**Pre-compliance focus bands:**")
                for b in high_risk[:3]:
                    a(f"- {b['band']}: {b['source_count']} emission source(s) ({b['risk_level']} risk)")
                a("")

    # === Power Analysis ===
    has_power = False

    if vd:
        a("## Power Analysis")
        a("")
        has_power = True
        a("### Voltage Derating")
        a("")
        profile = vd.get("derating_profile", derating_profile)
        a(f"Profile: **{profile}**. Checked: {vd.get('caps_checked',0)} caps, "
          f"{vd.get('ics_checked',0)} ICs, {vd.get('resistors_checked',0)} resistors.")
        a("")
        if vd.get("issues"):
            a("| Ref | Value | Type | Rail | Applied | Rated | Margin | Severity |")
            a("|-----|-------|------|------|---------|-------|--------|----------|")
            for i in vd["issues"]:
                rated = i.get("rated_voltage", i.get("rated_power_w", ""))
                applied = i.get("rail_voltage", i.get("voltage_across", ""))
                a(f"| {i.get('ref','')} | {i.get('value','')} | {i.get('component_type','')} "
                  f"| {i.get('rail','')} | {_safe_float(applied)} | {_safe_float(rated)} "
                  f"| {_safe_float(i.get('margin_pct'),'.0f')}% | {i.get('severity','')} |")
            a("")
        if vd.get("over_designed"):
            a("**Over-designed:**")
            a("")
            for od in vd["over_designed"]:
                a(f"- {od.get('ref','')} ({od.get('value','')}) — margin {_safe_float(od.get('margin_pct'),'.0f')}%. "
                  f"{od.get('suggestion','')}")
            a("")
        if not vd.get("issues") and not vd.get("over_designed"):
            a("All components within derating limits.")
            a("")

    # Sleep current
    sleep = sch.get("sleep_current_audit") if sch else None
    if sleep and sleep.get("rails"):
        if not has_power:
            a("## Power Analysis")
            a("")
            has_power = True
        a("### Sleep Current")
        a("")
        a("| Rail | Component | Type | Current (µA) | Notes |")
        a("|------|-----------|------|-------------|-------|")
        for rail_name, rail_data in sleep.get("rails", {}).items():
            for path in rail_data.get("current_paths", []):
                a(f"| {rail_name} | {path.get('ref','')} ({path.get('value','')}) "
                  f"| {path.get('type','')} | {path.get('current_uA','')} | {path.get('note','')} |")
        total = sleep.get("total_estimated_sleep_uA")
        if isinstance(total, (int, float)):
            a(f"")
            a(f"**Total estimated sleep current: {total:.0f}µA**")
        a("")

    # Inrush
    inrush = sch.get("inrush_analysis") if sch else None
    if inrush and inrush.get("rails"):
        if not has_power:
            a("## Power Analysis")
            a("")
            has_power = True
        a("### Inrush Analysis")
        a("")
        a("| Regulator | Output Rail | Output Caps (µF) | Est. Inrush (A) | Soft-start (ms) |")
        a("|-----------|------------|-------------------|-----------------|-----------------|")
        for rail in inrush["rails"]:
            total_uf = rail.get("total_output_capacitance_uF", 0)
            inrush_a = rail.get("estimated_inrush_A", 0)
            ss = rail.get("assumed_soft_start_ms", "")
            a(f"| {rail.get('regulator','')} | {rail.get('output_rail','')} "
              f"| {_safe_float(total_uf)} | {_safe_float(inrush_a, '.3f')} | {ss} |")
        a("")

    # === Design Analysis ===
    if sch:
        da = sch.get("design_analysis", {})
        has_da = False

        # Bus Topology
        buses = da.get("bus_analysis", {})
        if any(buses.get(k) for k in ("i2c", "spi", "uart", "can")):
            a("## Design Analysis")
            a("")
            has_da = True
            a("### Bus Topology")
            a("")
            for bus_type in ("i2c", "spi", "uart", "can"):
                entries = buses.get(bus_type, [])
                if entries:
                    a(f"- **{bus_type.upper()}**: {len(entries)} signal(s)")
            a("")

        # Protocol Compliance
        if pc.get("findings"):
            if not has_da:
                a("## Design Analysis")
                a("")
                has_da = True
            a("### Protocol Compliance")
            a("")
            for finding in pc["findings"]:
                proto = finding["protocol"].upper()
                issues = finding.get("issues", []) or []
                checks = finding.get("checks", {})
                devices = finding.get("devices", [])
                dev_str = f" ({', '.join(devices)})" if devices else ""
                a(f"**{proto}**{dev_str}")
                for check_name, check_data in checks.items():
                    if isinstance(check_data, dict) and "status" in check_data:
                        a(f"- {check_name}: **{check_data['status']}**")
                for issue in issues:
                    a(f"- {issue}")
                a("")

        # Cross-domain
        xd = da.get("cross_domain_signals", [])
        if xd:
            if not has_da:
                a("## Design Analysis")
                a("")
                has_da = True
            a("### Cross-Domain Signals")
            a("")
            for s in xd[:10]:
                a(f"- {s.get('net','')} crosses {', '.join(s.get('power_domains', []))}")
            if len(xd) > 10:
                a(f"- ... and {len(xd) - 10} more")
            a("")

    # === IC Pin Analysis ===
    if sch:
        ic_pins = sch.get("ic_pin_analysis", [])
        if ic_pins:
            a("## Analyzer Verification")
            a("")
            a("### IC Pin Analysis")
            a("")
            a("| Ref | Value | Pins | Unconnected | Decoupling |")
            a("|-----|-------|------|-------------|------------|")
            for ic in ic_pins:
                decaps = ic.get("decoupling_caps_by_rail", {})
                decap_str = ", ".join(f"{rail}: {len(caps)}" for rail, caps in decaps.items()) if decaps else "—"
                a(f"| {ic.get('reference','')} | {ic.get('value','')} "
                  f"| {ic.get('total_pins',0)} | {ic.get('unconnected_pins',0)} | {decap_str} |")
            a("")

    # === PCB Layout ===
    if pcb:
        a("## PCB Layout Analysis")
        a("")
        dfm = pcb.get("dfm", {})
        metrics = dfm.get("metrics", {})
        all_layers = pcb.get("layers", [])
        signal_layers = sum(1 for l in all_layers if l.get("type") == "signal")
        pcb_conn = pcb.get("connectivity", {})

        a("### Board Overview")
        a("")
        a(f"| Metric | Value |")
        a(f"|--------|-------|")
        a(f"| Dimensions | {metrics.get('board_width_mm','?')} × {metrics.get('board_height_mm','?')} mm |")
        a(f"| Layers | {signal_layers} |")
        a(f"| Footprints | {len(pcb.get('footprints', []))} |")
        a(f"| Tracks | {pcb.get('tracks',{}).get('segment_count',0)} |")
        a(f"| Vias | {pcb.get('vias',{}).get('count',0)} |")
        a(f"| DFM tier | {dfm.get('dfm_tier','?')} |")
        if pcb_conn.get("routing_complete"):
            a(f"| Routing | 100% complete |")
        elif pcb_conn.get("unrouted_count", 0) > 0:
            a(f"| Routing | **{pcb_conn['unrouted_count']} unrouted** |")
        a(f"| Min track | {metrics.get('min_track_width_mm','?')} mm |")
        a(f"| Min spacing | {metrics.get('approx_min_spacing_mm','?')} mm |")
        a(f"| Min drill | {metrics.get('min_drill_mm','?')} mm |")
        a(f"| Min annular ring | {metrics.get('min_annular_ring_mm','?')} mm |")
        a(f"| DFM violations | {dfm.get('violation_count',0)} |")
        a("")

        # Thermal pad vias
        tpv = pcb.get("thermal_pad_vias", [])
        if tpv:
            a("### Thermal Pad Vias")
            a("")
            a("| Component | Value | Via Count | Adequacy |")
            a("|-----------|-------|-----------|----------|")
            for t in tpv:
                a(f"| {t.get('reference','')} | {t.get('value','')} "
                  f"| {t.get('via_count',0)} | {t.get('adequacy','')} |")
            a("")

    a("---")
    a("*Generated by [kicad-happy](https://github.com/aklofas/kicad-happy)*")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Format kicad-happy analysis as markdown")
    parser.add_argument("--schematic", help="Path to schematic analysis JSON")
    parser.add_argument("--pcb", help="Path to PCB analysis JSON")
    parser.add_argument("--spice", help="Path to SPICE simulation JSON")
    parser.add_argument("--emc", help="Path to EMC analysis JSON")
    parser.add_argument("--diff", help="Path to diff analysis JSON (from diff_analysis.py)")
    parser.add_argument("--thermal", help="Path to thermal analysis JSON (from analyze_thermal.py)")
    parser.add_argument("--severity", default="all", help="Filter: all, warning, critical")
    parser.add_argument("--derating-profile", default="commercial")
    parser.add_argument("--run-url", help="GitHub Actions run URL for 'Full report' link")
    parser.add_argument("--output", required=True, help="Output markdown file path (PR comment)")
    parser.add_argument("--output-full", help="Output full report markdown (step summary)")
    parser.add_argument("--output-summary", help="Output summary JSON file path")
    args = parser.parse_args()

    report, summary = format_report(
        args.schematic, args.pcb, args.spice, args.emc,
        args.severity, args.derating_profile,
        run_url=args.run_url,
        diff_path=args.diff,
        thermal_path=args.thermal,
    )

    with open(args.output, "w") as f:
        f.write(report)

    if args.output_full:
        full = format_full_report(args.schematic, args.pcb, args.spice, args.emc, args.derating_profile)
        with open(args.output_full, "w") as f:
            f.write(full)
        print(f"Full report: {args.output_full} ({len(full)} chars)", file=sys.stderr)

    if args.output_summary:
        with open(args.output_summary, "w") as f:
            json.dump(summary, f, indent=2)

    print(f"Report: {args.output} ({len(report)} chars)", file=sys.stderr)
    print(f"Findings: {summary['critical_count']} critical, "
          f"{summary['warning_count']} warning, "
          f"{summary['verified_count']} verified", file=sys.stderr)


if __name__ == "__main__":
    main()

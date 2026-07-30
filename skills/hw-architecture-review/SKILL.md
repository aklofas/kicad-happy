---
name: hw-architecture-review
description: >-
  Review board-level hardware architecture: functional blocks, hierarchy,
  interface ownership, dual schematic SoT, commercial reference pattern match,
  and freeze decisions. Use when the user asks for architecture review, system
  block diagram critique, hierarchy decisions, PCIe/backplane ownership,
  "is this the right topology", commercial riser comparison, dual-SoT policy,
  or Phase 1–2 knowledge/architecture gates before layout polish.
---

# Hardware Architecture Review

Methodology skill for **system-level** hardware architecture. Complements `kicad`
(which parses CAD) — this skill decides whether the topology and ownership model
are correct before spending cycles on cosmetics or copper.

## Related Skills

| Skill | Handoff |
|-------|---------|
| `kicad` | Extract nets, symbols, hierarchy sheets, power/clock detectors |
| `power-tree` | Deep rail ownership / sequencing |
| `clock-tree` | REFCLK / oscillator / distribution |
| `constraint-management` | Freeze, SoT, UUID affinity after architecture lock |
| `design-review` | Score architecture into EQ / charter |
| `product-docs` | Capture accepted architecture in customer-facing docs |
| `kidoc` | Generate HDD / ICD scaffolds from CAD |

**Do not** re-implement schematic parsing here — call `kicad` analyzers first.

## Purpose

Produce an evidence-backed architecture verdict: Accept / Accept-with-notes /
Revise / Freeze-copper-and-defer. Map every critical interface to an owner
(RC, EP, adapter, external PSU) and a verification gate.

## When to invoke

- New product intake or Phase 1–2 of a multi-phase PCB campaign
- Hierarchy vs flat schematic decisions
- Passive duct vs switch/retimer vs active redriver debates
- Commercial reference mapping (e.g. powered riser patterns)
- Before any copper ECO that changes topology

## Inputs

- Design intent / requirements (rails, lane count, Gen, form factor)
- Schematic SoT paths (hierarchical root + flat archival if dual-SoT)
- PCB SoT path and fab GO status
- Prior decision log / risk register
- Optional: commercial reference notes or competitor tear-downs
- Analyzer JSON from `analyze_schematic.py` (block inventory)

## Outputs

1. **Architecture review memo** (markdown) with:
   - Block diagram (text/mermaid) of functional partitions
   - Interface ownership table (signal, source, sink, direction, domain)
   - Hierarchy / SoT recommendation
   - Commercial pattern match score (if reference given)
   - Open risks → verification plan IDs
2. **Decision records** for any Accept/Revise calls
3. Explicit **non-claims** (e.g. Gen3 not Gen4; no PCI-SIG compliance)

## Decision process

1. **Inventory blocks** from schematic + docs (MCU/FPGA, connectors, power, clocks, sidebands).
2. **Classify each interface:** power / high-speed / sideband / debug / future.
3. **Assign ownership** — who drives, who terminates, who injects power.
4. **Check topology class:**
   - Passive copper duct (no switch) vs active retime/switch
   - External power injection vs host-only power
   - Common clock vs HCSL from host
5. **Hierarchy policy:** customer PDF SoT vs netlist/fab SoT — allow dual-SoT only with written policy (see MatriQ `DUAL_SOT_POLICY` pattern).
6. **Reference match** (optional): score 8–10 industrial patterns; gaps → measure plan, not impulsive ECO.
7. **Gate:** architecture Accept before layout beauty or copper ECO.

### Correct vs anti-pattern

| Practice | Correct | Anti-pattern |
|----------|---------|--------------|
| Dual-SoT | Named roles + honesty banners | Claiming hier ERC=0 as silicon proof when sheets are hollow |
| Commercial refs | Pattern score + gap→lab | Copying marketing claims into compliance language |
| Future sheets | Explicit FUTURE / not-in-fab | Shipping stub sheets without demotion |
| Copper | Freeze when fab GO holds | Topology ECO for documentation score |

## Checklist

- [ ] Functional blocks listed with sheet/file anchors
- [ ] Every critical net class has an owner and domain
- [ ] Power injection policy stated (host / external / both)
- [ ] Clocking model stated (source, loads, AC-couple/series-R if any)
- [ ] Sidebands (PERST, WAKE, PRESENT, SMBUS) ownership clear
- [ ] Hierarchy/SoT policy written if dual files exist
- [ ] Future/optional partitions demoted in title or banner
- [ ] Non-claims listed (compliance, Gen, cold-plug, etc.)
- [ ] Gaps mapped to `verification-planning` IDs — not silent

## Failure modes

| Mode | Root cause | Mitigation |
|------|------------|------------|
| Hollow hierarchy ERC=0 treated as electrical proof | Sheetfile path quirk | Dual-SoT policy + sibling-load experiment documented |
| Architecture churn after fab GO | Score chasing | Copper freeze under constraint-management |
| Missing sideband ownership | Spec skim | Interface table mandatory |
| Over-claiming compliance | LLM fluency | Non-claims section required |

## Industrial references

- IPC-2221 design planning principles
- PCI Express Card Electromechanical / Base Spec (lane/sideband ownership — cite revision used)
- JLCPCB layout guide: schematic as absolute truth before layout ([JLCPCB Complete PCB Layout Guide](https://jlcpcb.com/blog/complete-pcb-layout-guide))
- pcbGPT: grounded generate–execute–repair; drafts need expert review (King et al., arXiv:2606.01188)
- Agentic EDA handoff contracts (arXiv:2606.19795)

## Example (compressed)

**Input:** Passive PCIe ×8 RC↔EP interposer, external 12 V brick, common REFCLK oscillator.  
**Verdict:** Accept Dolphin-class pattern (passive dual-slot, external power). Gaps: 3V3VAUX unmeasured, Z unmeasured → lab plans, not copper ECO. Dual-SoT: hierarchical customer PDF + flat archival netlist.

## Acceptance criteria

- Senior HW engineer can approve/reject from the memo alone
- No CAD mutation required to complete the review
- Every open gap has a verification owner or explicit DEFER
- Does not duplicate `kicad` detector output as architecture truth without ownership interpretation

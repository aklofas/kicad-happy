---
name: pcb-layout-review
description: >-
  Methodology for PCB layout review: placement strategy, stackup, return paths,
  plane strategy, connector seating, and fab-aligned design rules — beyond raw
  analyzer JSON. Use when reviewing layout quality, stackup choices, placement
  density, "is this layout industrial", pre-fab layout critique, or interpreting
  analyze_pcb.py / DRC results into engineering decisions.
---

# PCB Layout Review (Methodology)

Complements `kicad` `analyze_pcb.py` and `emc`. This skill is the **senior layout
engineer decision layer**: what the numbers mean, what to fix now vs defer, and
how to align rules with the fabricator.

## Related Skills

| Skill | Role |
|-------|------|
| `kicad` | Run `analyze_pcb.py --full`, DRC, cross_analysis |
| `emc` | Plane voids, edge radiation, return-path rules |
| `dfm-review` | Fab capability gate and CAM package |
| `si-review` | Diff-pair / impedance / length methodology |
| `jlcpcb` / `pcbway` | Manufacturer capability tables |
| `constraint-management` | Net classes, copper freeze |

## Purpose

Turn analyzer + DRC evidence into a layout verdict with prioritized ECO classes
(A docs / B silk / C production / D copper) without silent copper edits.

## When to invoke

- "Review my layout before order"
- Interpreting high DRC counts that are not shorts
- Stackup or plane strategy disputes
- Connector finger / CEM seating reviews
- Post-routing industrial critique

## Inputs

- `.kicad_pcb` SoT path + stackup notes
- `analyze_pcb.py --full` JSON
- DRC report (CLI and/or live GUI — state congruence)
- Fab process card (e.g. JLCPCB 4L 1oz)
- Optional: silk/assembly drawings

## Outputs

- Layout review report: placement, stackup, planes, HS corridors, DFM residuals
- ECO class table (A–D) with fab-GO impact
- Explicit LIVE vs CLI congruence note

## Decision process

1. **Confirm board SoT** and that live GUI matches CLI file (UUID affinity).
2. **Run analyzers** — do not invent geometry from memory.
3. **Separate** shorts/unconnected (blockers) from style/silk/courtyard (non-blockers).
4. **Stackup:** Signal-GND-PWR-Signal (or documented alternative) with return strategy for HS.
5. **Placement:** functional clustering; power stages; connector keepouts; courtyard overlaps.
6. **Planes:** continuity under HS; stitching; splits that HS crosses → flag via `emc`.
7. **Rules:** min width/space/via/annular ring vs fab card (JLCPCB: ~5 mil 2L / 3.5 mil 4–6L typical; verify current fab table).
8. **Verdict:** Fab GO / conditional GO / NO-GO — never upgrade GO by ignoring shorts.

### JLCPCB layout-guide anchors

Per [JLCPCB Complete PCB Layout Guide](https://jlcpcb.com/blog/complete-pcb-layout-guide):

- Schematic quality drives layout quality (netlist is absolute connectivity truth)
- Define rules before routing (width, clearance, via, stackup)
- 4-layer S-G-P-S is the default EMI-friendly stackup for cost-effective boards
- Plan manufacturability against the chosen fab’s capability page

## Checklist

- [ ] Board SoT + LIVE==CLI stated
- [ ] Shorts = 0 for GO claims
- [ ] Stackup documented and matches fab order
- [ ] HS corridors have continuous reference intent
- [ ] Power entry / fuse / bulk caps placement reviewed
- [ ] Connector seating / finger finish notes
- [ ] Courtyard density called out (accept or ECO)
- [ ] Silk/docs debt not confused with electrical blockers
- [ ] Analyzer false positives triaged

## Failure modes

| Mode | Impact | Fix |
|------|--------|-----|
| Treating all DRC as blockers | False NO-GO | Severity triage |
| Editing copper to raise EQ docs score | Invalidates fab package | Freeze copper |
| Ignoring LIVE≠CLI | False trust | Session guardian / reopen SoT only |
| Open-loop LLM track edits | DRVs | Engine-grounded edits only (PCBWorld lesson) |

## Industrial references

- JLCPCB Complete PCB Layout Guide (2025/2026)
- IPC-2221 / IPC-7351 courtyard concepts
- PCBWorld: engine-grounded interactive routing + DRC feedback beats open-loop LLM tracks (Song et al., arXiv:2607.05915)
- Quilter: PCB automation as constrained optimization, not spectacle

## Acceptance criteria

- Every recommended copper change cites DRC/analyzer/evidence
- Fab GO impact column filled for each finding
- Does not replace `kicad` scripts — interprets them

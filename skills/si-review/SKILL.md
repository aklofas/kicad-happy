---
name: si-review
description: >-
  Signal-integrity review methodology separating heuristic CAD checks from
  measured signoff: impedance, length matching, return paths, crosstalk,
  vias/stubs, and PCIe/USB/SerDes corridors. Use for SI readiness, controlled-Z
  planning, "will this pass eye", or when refusing fake compliance scores.
---

# Signal Integrity Review

## Related Skills

| Skill | Role |
|-------|------|
| `kicad` | Trace length, proximity, layer transitions |
| `emc` | Return path, edge, diff skew rules |
| `pcb-layout-review` | Corridor / stackup context |
| `clock-tree` | REFCLK SI specifics |
| `verification-planning` | TDR/VNA/eye lab plan |
| `constraint-management` | Controlled-Z order constraints |

## Purpose

Produce an SI **readiness** assessment with a hard split between heuristic CAD
checks and measured signoff. Protects scorecards from fictional compliance.

## When to invoke

- Pre-fab SI readiness
- EQ debates on SI dimension
- Controlled-impedance order planning
- Post-layout diff-pair critique

## Inputs

- PCB SoT + stackup
- HS net list (diff pairs, clocks, memory)
- `analyze_pcb.py --full` (+ proximity) and `emc` JSON
- Fab impedance options / coupon policy

## Outputs

- SI readiness memo with **tier** per claim
- Gap list → verification IDs
- Explicit non-claims (PCI-SIG, Gen eye)

## SI tiers

| Tier | Meaning | Allowed language |
|------|---------|------------------|
| H0 Heuristic | Analyzer/geometry only | “risk”, “readiness” |
| H1 Fab intent | Controlled-Z ordered | “impedance intent” |
| H2 Measured | TDR/VNA/coupon | “measured Z” |
| H3 Link | Eye / BER / enum | “link validated” |

**Never** score H2/H3 without lab evidence.

## Decision process

1. Identify HS nets.
2. Run heuristic checks (`analyze_pcb`, `emc`).
3. Confirm reference plane intent under HS.
4. Note via count / stub risk qualitatively.
5. State impedance target and whether fab coupon ordered.
6. Map gaps to lab IDs — do not invent EQ points.

## Checklist

- [ ] HS net list complete
- [ ] Diff pair skew / length notes (heuristic)
- [ ] Return path voids flagged or clear
- [ ] Impedance target + stackup cite
- [ ] Measurement plan or explicit DEFER
- [ ] Compliance non-claims (PCI-SIG, Gen)

## Failure modes

| Mode | MatriQ / literature lesson |
|------|----------------------------|
| Docs-only SI EQ bump | Physical Δ = 0 overnight |
| Open-loop LLM tracks | PCBWorld: interactive+DRC wins |
| EMC≠SI signoff | Different oracles |

## Industrial references

- PCBWorld (arXiv:2607.05915)
- Vendor SerDes SI guides
- JLCPCB impedance / stackup calculators

## Example

Short 4-layer PCIe ×8 corridor, Z unmeasured → H0 readiness ~acceptable for fab; EQ SI capped until H1/H2; unlock = controlled-Z coupon + TDR.

## Acceptance criteria

- Tier label on every SI claim
- Lab unlocks listed when score ceiling binds

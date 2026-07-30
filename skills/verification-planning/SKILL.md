---
name: verification-planning
description: >-
  Plan hardware verification and bring-up: power, SI, PCIe/enum, EMC pre-scan,
  and lab instrumentation — without claiming results not measured. Use for
  validation plans, Phase 7-style readiness, test ICDs, or EQ unlock roadmaps.
---

# Verification Planning

## Related Skills

| Skill | Role |
|-------|------|
| `power-tree` / `clock-tree` / `si-review` | What to measure |
| `emc` | Pre-compliance test plan hooks |
| `design-review` | Residuals feeding the plan |
| `product-docs` | Bring-up chapter |
| `spice` | Pre-lab simulation where models exist |

## Purpose

Convert open risks into **executable** lab/simulation gates with IDs, equipment,
pass criteria, and dependencies — never fake pass marks.

## Plan structure

| ID | Domain | Setup | Stimulus | Measure | Pass | Depends |
|----|--------|-------|----------|---------|------|---------|
| PWR-01 | Power | … | … | … | … | … |

## Decision process

1. Import residuals from architecture / SI / DFM / review.
2. Order strategically: CAD trust → power → SI coupon → link enum → EMC.
3. Define instrumentation (scope, DMM, TDR, protocol analyzer).
4. Mark simulation-only vs silicon-required.
5. Keep fab GO independent of unrun lab gates when copper frozen.

## Checklist

- [ ] Each residual risk mapped to a gate or WAIVE
- [ ] Equipment list
- [ ] Safety (hot-plug, sequencing)
- [ ] Data capture path (who files results)
- [ ] No pass criteria that require unavailable gear without DEFER

## Failure modes

- Writing plans that silently imply completion
- Blocking fab on lab that cannot run pre-board
- Skipping power before high-speed bring-up

## Industrial references

- PCIe CEM bring-up practice
- IPC testability concepts
- MatriQ Phase 7-C/D/E plan pattern

## Acceptance criteria

- Plans are runnable by a lab engineer without the author
- Claims language reserved until results filed

---
name: dfm-review
description: >-
  Design-for-manufacturing gate review: fab capability alignment, annular rings,
  drill, solder mask, assembly constraints, CAM package integrity, and traveler
  notes. Use before ordering boards, when validating JLCPCB/PCBWay readiness,
  interpreting DFM scores, or protecting a frozen fab GO package.
---

# DFM Review Gate

Complements `jlcpcb` / `pcbway` (order formats) and `kicad` DFM scoring. This
skill is the **manufacturing release gate**.

## Related Skills

| Skill | Role |
|-------|------|
| `kicad` | `analyze_pcb.py` DFM, gerbers, tombstoning |
| `jlcpcb` / `pcbway` | Capability + BOM/CPL |
| `pcb-layout-review` | Layout ECO classification |
| `bom` | MPN lock / basic vs extended parts |
| `product-docs` | Traveler / assembly SOP |
| `constraint-management` | Freeze CAM after GO |

## Purpose

Answer: **May we order this CAM package?** with evidence, residuals, and
non-blocking debt listed honestly.

## When to invoke

- Pre-order fab review
- After copper freeze when confirming GO still holds
- CEM handoff / traveler authoring
- DFM score interpretation disputes

## Inputs

- PCB SoT + Gerber/drill set or fab zip
- DRC + `analyze_pcb` DFM JSON
- Fab capability card
- BOM with MPNs / JLCPCB basic vs extended
- Prior GO statement if any

## Outputs

- DFM gate report: GO / CONDITIONAL / NO-GO
- Blocker list vs accept-with-notes
- Traveler critical populate list
- CAM pin (path, commit, or hash)

## Decision process

1. Identify fab + process (layers, Cu weight, finish, min trace/space).
2. Run DRC + `analyze_pcb` DFM + gerber check if exports exist.
3. Classify findings: order-blocker vs accept-with-notes.
4. Assembly: polarity, paste, thermal pads, fiducials, panel notes.
5. Protect frozen zip: do not regenerate casually after GO.
6. Traveler must list populate-critical parts (option resistors, XO, sense).

### JLCPCB anchors

From [JLCPCB Complete PCB Layout Guide](https://jlcpcb.com/blog/complete-pcb-layout-guide): align width/space/via/annular ring to the fab’s current capability table before routing; 4-layer S-G-P-S is the default cost-effective EMI-friendly stackup.

## Checklist

- [ ] Fab capability cited (date + URL or saved PDF)
- [ ] Shorts = 0; unconnected policy stated
- [ ] Min drill / annular ring within process
- [ ] Finish note (ENIG etc.) for fingers if needed
- [ ] BOM basic/extended split understood
- [ ] CAM zip name + hash or commit pinned
- [ ] Assembly traveler critical populate list
- [ ] Courtyard density accepted or ECO’d

## Failure modes

| Mode | Impact | Fix |
|------|--------|-----|
| Regen Gerbers after “harmless” edit | Silent fab drift | Freeze + re-DRC policy |
| Presentation score ≠ fab readiness | False delay or false GO | Separate scorecards |
| Extended-part surprise | Schedule slip | `bom` lifecycle audit |

## Industrial references

- JLCPCB / PCBWay capability pages
- IPC-A-600 / IPC-A-610 (cite class if claimed)
- kicad-happy jlcpcb skill assembly constraints

## Example

**Unconditional GO:** CLI shorts=0, DRC residuals accepted, zip `jlcpcb_production_uncond_go` pinned, traveler lists Y1/R20/R21 populate — silk courtyard WARN non-blocking.

## Acceptance criteria

- Explicit GO / CONDITIONAL / NO-GO
- Blockers empty for unconditional GO
- Residuals documented without hiding

---
name: power-tree
description: >-
  Build and review power trees: rail ownership, regulator chains, sequencing,
  current budget, sense/test points, and external vs host power injection. Use
  when reviewing power architecture, PDN, bucks/LDOs, "where does 12V go",
  inrush, fuse strategy, or interpreting kicad power-path detector output.
---

# Power Tree Review

Methodology for **power domain architecture**. Uses `kicad` analyzer power-path
output as evidence; adds ownership, budget, and bring-up gates.

## Related Skills

| Skill | Role |
|-------|------|
| `kicad` | Detector power trees, feedback ratios, decoupling inventory |
| `spice` | Simulate regulators / PDN when models exist |
| `emc` | Switching node / input loop / PDN impedance risks |
| `si-review` | Power integrity adjacent to HS corridors |
| `verification-planning` | Lab Iin / ripple / sequence plans |
| `kidoc` | Power analysis report type |

## Purpose

Produce a rail-by-rail tree with source, conversion, loads, protection, TP, and
**what is measured vs assumed**.

## Inputs

- Schematic SoT + `analyze_schematic.py` JSON
- Power intent (host rails, brick, PoE, USB-PD, etc.)
- Connector pinouts for power pins
- Optional datasheets for regulators / hot-swap

## Outputs

```
VIN / brick
├── Fuse / ideal diode / switch
├── Buck A → VoutA → loads…
└── LDO B → VoutB → loads…
```

Plus: budget table, sequence notes, open `[MEASURE]` items, ECO class.

## Decision process

1. List all power symbols / PWR flags / connector power pins.
2. Trace each regulator input→output→loads (analyzer + manual spot-check).
3. Mark **injection points** (external brick vs host golden fingers).
4. Check protection: fuse, TVS, reverse, UVLO as applicable.
5. Check decoupling strategy qualitatively; defer quantitative PDN to `emc`/`spice`.
6. Identify sense/TP coverage for bring-up.
7. Never invent measured Iin — mark MEASURE.

## Checklist

- [ ] Tree covers every rail name used on connectors
- [ ] Each regulator has enable/sequence note if multi-rail
- [ ] External injection isolated from host power policy stated
- [ ] Fuse/polyfuse ratings vs budget
- [ ] Bulk + HF caps called out per stage
- [ ] Test points listed or gap logged
- [ ] Assumptions vs MEASURE explicitly separated

## Failure modes

- Collapsing AUX and main 3V3 without EP need check
- Budget from marketing max without derating
- Claiming PI signoff from schematic alone

## Industrial references

- IPC power distribution planning practice
- Regulator datasheet typical apps (via `datasheets` skill)
- pcbGPT / PCBSchemaGen: support circuitry (bulk, feedback) is a top semantic failure class

## Acceptance criteria

- Tree reproducible from schematic evidence
- Every unknown current tagged MEASURE
- Handoff to verification-planning for lab gates

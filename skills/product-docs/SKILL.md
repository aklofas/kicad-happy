---
name: product-docs
description: >-
  Author commercial / industrial product documentation packages: hardware
  reference guides, naming standards, travelers, honest non-claims, and
  customer PDF indexes — distinct from CAD-generated engineering reports. Use
  for productization, customer manuals, industrial handoff packs, or shipping
  docs without changing copper.
---

# Commercial Product Documentation

Complements `kidoc` (CAD-driven engineering reports). This skill builds the
**product narrative and ops package** a senior customer or CEM needs.

## Related Skills

| Skill | Role |
|-------|------|
| `kidoc` | HDD, ICD, manufacturing transfer scaffolds from CAD |
| `schematic-presentation` | Drawing standards for customer PDF |
| `hw-architecture-review` | Architecture accepted content |
| `dfm-review` | Traveler / fab notes |
| `knowledge-management` | Index fragmented engineering corpus |

## Purpose

Ship Class A documentation: reference guide, naming standard, engineering notes
library, productization README — **without** mandatory copper ECO.

## Document set (typical)

1. Hardware Reference Guide (architecture, power, clocks, bring-up)
2. Industrial net naming standard (CAD SoT vs future lexicon)
3. Engineering notes (populate rules, option resistors)
4. Production traveler / CEM remarks
5. Index linking deep phase docs → product folder

## Decision process

1. Freeze architecture claims to accepted design.
2. Separate **customer truth** from lab unknowns (`[MEASURE]`).
3. Prefer docs over CAD renames when connectivity risk is high.
4. Dual-SoT: tell customers which PDF to open.
5. Non-claims: Gen, compliance lab, cold-plug, warranty bounds.

## Checklist

- [ ] Guide answers: what it is, power, clocks, connectors, bring-up
- [ ] Non-claims section present
- [ ] CAD net names used as SoT in manuals
- [ ] Traveler critical populate list
- [ ] Deep docs indexed, not duplicated wholesale
- [ ] Fab GO status stated and protected

## Failure modes

- Fragmented phase folders with no product index (MatriQ A1)
- Compliance language without lab
- Editing nets for prettier names pre-fab

## Industrial references

- IEC/ISO technical documentation structure practices
- CEM traveler conventions
- kidoc document types for engineering vs this commercial layer

## Acceptance criteria

- Senior engineer GO on docs package independent of silk polish
- Copper unchanged unless Class D explicitly approved

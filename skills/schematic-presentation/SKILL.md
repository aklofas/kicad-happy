---
name: schematic-presentation
description: >-
  Industrial schematic presentation standards: title blocks, alignment, spacing,
  hierarchy visuals, stacked text cleanup, demotion banners, and customer PDF
  export — without changing connectivity. Use for schematic polish, library
  designer review, raising presentation scores, or Altium/KiCad drawing standards.
---

# Industrial Schematic Presentation

## Related Skills

| Skill | Role |
|-------|------|
| `kicad` | ERC after cosmetic edits; export PDF/SVG |
| `product-docs` | What customer PDF must communicate |
| `constraint-management` | Wire-gated edits; no net changes |
| `design-review` | Score readability separately from electrical |
| `kidoc` | Render crops for reports |

## Purpose

Raise **drawing quality** (MatriQ 72→80 pattern) while preserving ERC and fab GO.
Connectivity edits are out of scope unless explicitly commissioned.

## Decision process

1. Confirm customer SoT sheets (not flat archival).
2. Visual QA: stacked text, title/rev drift, overlapping notes, border crowding.
3. Prefer MCP / sch API with wire-drop guards; never blind sexp regex.
4. Unify title/rev strings; add FUTURE/demotion banners where needed.
5. Export direct child PDFs if hierarchy index hollow.
6. Re-ERC; abort if connectivity deltas appear.

## Checklist

- [ ] Scope = presentation only (written)
- [ ] Title blocks consistent
- [ ] No stacked free-text on critical areas
- [ ] Future sheets demoted
- [ ] Flat archival not used as customer PDF
- [ ] ERC unchanged or understood
- [ ] Before/after PNG evidence saved

## Failure modes

- Touching wires to “nudge” symbols → ERC spikes
- Polishing flat archival instead of customer hierarchy
- Counting presentation points as SI/PI EQ

## Industrial references

- IEEE/IEC schematic drafting conventions (organization, readable flow)
- JLCPCB guide: schematic as communication tool; hierarchical sheets
- Corporate library standards (Altium/KiCad house styles)

## Acceptance criteria

- Presentation score rationale + evidence paths
- Zero intentional netlist changes

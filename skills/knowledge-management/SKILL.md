---
name: knowledge-management
description: >-
  Hardware knowledge management for AI-assisted PCB programs: journals,
  scorecards, dual-SoT indexes, decision logs, evidence packs, and preventing
  corpus fragmentation. Use when organizing phase docs, building productization
  indexes, or capturing overnight lessons into reusable memory.
---

# Hardware Knowledge Management

## Related Skills

| Skill | Role |
|-------|------|
| `product-docs` | Customer-facing index |
| `design-review` | Scorecard format |
| `constraint-management` | Policy docs as knowledge |
| `kidoc` | Generated reports filing |

## Purpose

Keep engineering truth findable: one index, named SoT, evidence beside claims,
and lessons distilled into skills — not lost in chat.

## Artifact set

| Artifact | Role |
|----------|------|
| Decision log | Binding choices |
| Risk register | Open risks → gates |
| EQ scorecard | Weighted honesty |
| Iteration log | Chronology |
| Morning brief | Shift handoff |
| Evidence dir | ERC/DRC/PNG/JSON |
| Productization index | Customer entrypoint |

## Decision process

1. Prefer append-only logs; never rewrite history without note.
2. Every score cites evidence paths.
3. Dual-SoT and freeze policies live as first-class docs.
4. Distill repeats into skills (`kicad-happy`) rather than more phase notes.
5. Index deep trees (`phase6/`, `phase7/`) from one README.

## Checklist

- [ ] Single STATUS or brief for “where are we”
- [ ] Evidence paths relative and existent
- [ ] SHAs for parent + vendor CAD
- [ ] Forbidden claims listed
- [ ] Skill distillation backlog for repeats

## Failure modes

- 100+ markdown files, no index (MatriQ productization finding)
- EQ numbers without formula
- Chat-only decisions

## Acceptance criteria

- New engineer finds SoT + GO + next actions in ≤5 minutes
- Lessons have skill or ADR owners

---
name: constraint-management
description: >-
  Manage hardware design constraints and sources of truth: copper freeze, dual
  schematic SoT, UUID/file affinity, net classes, design rules, and write-gate
  policies for AI agents. Use when locking fab packages, resolving SoT conflicts,
  session guardian / CAD trust, "do not edit copper", hierarchy Sheetfile policy,
  or constraint-guided agent workflows.
---

# Constraint & SoT Management

Implements the industrial lesson: **automation is constrained optimization**
(Quilter; PCBWorld engine feedback; PCBSchemaGen constraint-guided synthesis).

## Related Skills

| Skill | Role |
|-------|------|
| `kicad` | Read net classes, rules, board metadata |
| `pcb-layout-review` | Apply fab rules in layout critique |
| `dfm-review` | Map constraints to fab capability |
| `multi-agent-coordination` | Enforce write gates across agents |
| `design-review` | Score honesty when constraints block EQ |

## Purpose

Maintain a written constraint set that agents and humans must obey: what file is
SoT, what may be edited, what invalidates fab GO.

## Constraint categories

1. **File SoT** — PCB path; customer sch; archival sch
2. **Edit class** — docs / presentation / copper / hierarchy pins
3. **Electrical rules** — clearance, width, diff pair, via
4. **Process** — fab stackup, finish, min drill
5. **Trust** — LIVE GUI must match CLI file (UUID affinity)
6. **Claims** — what EQ/compliance language is forbidden without evidence

## Decision process

1. Publish a constraint card at campaign start (markdown table).
2. On every edit request: classify impact → allowed?
3. Copper freeze after fab GO until evidence demands ECO.
4. Dual-SoT: name roles; ban false ERC proofs.
5. Prefer engine/API edits over regex sexp rewrites.
6. Log constraint waivers with owner + expiry.

## Checklist

- [ ] PCB SoT path absolute or repo-relative, single
- [ ] Schematic customer SoT vs archival named
- [ ] Copper freeze flag + CAM zip hash/name
- [ ] Net classes exist for HS / power / default
- [ ] Fab rules imported or cited
- [ ] Agent write mode + profile documented
- [ ] LIVE==CLI procedure defined
- [ ] Waiver log location defined

## Failure modes

| Mode | MatriQ lesson |
|------|---------------|
| Hollow hier ERC=0 as proof | Dual-SoT policy required |
| Sibling Sheetfile surprise ERC | Experiment with revert path |
| Score chasing copper ECO | Freeze + lab-first EQ>95 |
| Regex CAD edits | Ban; use MCP/API |

## Industrial references

- PCBWorld engine-grounded DRC loop (arXiv:2607.05915)
- PCBSchemaGen constraint-guided synthesis + KG verifier (arXiv:2602.00510)
- Quilter constrained-optimization framing
- Agentic EDA handoff contracts (arXiv:2606.19795)

## Acceptance criteria

- Constraint card exists and is cited by agents before edits
- Fab-invalidating actions require explicit human unlock language

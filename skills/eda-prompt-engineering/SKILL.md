---
name: eda-prompt-engineering
description: >-
  Prompt patterns for EDA/hardware agents: grounded tool use, generate-execute-
  repair loops, evidence tags, non-claims, and anti-hallucination contracts. Use
  when writing agent system prompts, overnight master briefs, skill prompts, or
  debugging agents that invent DRC/EQ/compliance results.
---

# EDA Prompt Engineering

## Related Skills

| Skill | Role |
|-------|------|
| `multi-agent-coordination` | Who gets which prompt |
| `constraint-management` | Hard rules injected into prompts |
| `design-review` | Output contract |
| `kicad` | Tool surface agents must call |

## Purpose

Encode prompts that force **engine grounding**, iterative repair, and honest
uncertainty — lessons from pcbGPT, PCBSchemaGen, PCBWorld, and MatriQ overnight.

## Prompt contract (inject)

```
1. Tools before memory: call analyzers/MCP; do not invent nets/DRC.
2. Generate → execute → repair; never one-shot board files.
3. Tag every claim: [ANALYZER] [DATASHEET] [LAB] [CONJECTURE].
4. Forbidden: regex rewrite of .kicad_sch/.kicad_pcb; fake EQ lab scores.
5. Copper freeze / SoT paths: <paste constraint card>.
6. On failure: revert, log, do not score partial residue as EQ gain.
7. End with ≤3 human actions and explicit non-claims.
```

## Patterns

| Pattern | Use |
|---------|-----|
| Constrained checklist | Reviews |
| Evidence table | Findings |
| Dual-SoT honesty | Hierarchy campaigns |
| Tiered SI language | H0–H3 |
| Morning brief | Overnight handoff |

## Anti-patterns

- “Make EQ >95 overnight” without lab unlocks
- Open-loop “route all nets” LLM dumps (PCBWorld: interactive wins)
- Semantic validation without deterministic ERC/execution (pcbGPT stack)

## Failure modes

| Mode | Impact | Fix |
|------|--------|-----|
| Unbounded excellence targets | Agent hangs / false EQ | Cap to evidence unlocks |
| Missing claim tags | Fake “verified” language | Require [ANALYZER]/[LAB]/… |
| No SoT in prompt | Wrong file edited | Paste constraint card |
| One-shot board generation | DRVs / unreviewable CAD | Force execute–repair loop |

## Acceptance criteria

- Prompt includes SoT + freeze + claim tags
- Success metrics measurable without hallucinated lab

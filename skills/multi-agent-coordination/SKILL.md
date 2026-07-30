---
name: multi-agent-coordination
description: >-
  Coordinate multi-agent hardware campaigns: phase gates, write locks, specialist
  roles, timeout handling, morning briefs, and evidence packs. Use for overnight
  master agents, parallel architecture/SI/docs reviewers, or recovering from
  agent hangs without corrupting CAD SoT.
---

# Multi-Agent Hardware Coordination

## Related Skills

| Skill | Role |
|-------|------|
| `eda-prompt-engineering` | Per-role prompts |
| `constraint-management` | Global write locks |
| `design-review` | Merge specialist findings |
| `knowledge-management` | Logs / scorecards |
| `verification-planning` | Lab after agents stop |

## Purpose

Run Phase 0–7 style organisations without CAD corruption or false progress.

## Role map (example)

| Role | Edits CAD? | Output |
|------|------------|--------|
| Master / orchestrator | No (policy) | Briefs, gates |
| Architecture | No | Review memo |
| Schematic presentation | Chrome only | Before/after |
| CAD trust / guardian | Read + reopen SoT | Congruence report |
| Docs productization | No | Product pack |
| Layout ECO | Only if unlocked | ECO pack + DRC |

## Coordination rules

1. **Phase 0 gate** before mutations.
2. **Single writer** per file set; others read-only.
3. **Checkpoint commits** before risky hierarchy experiments.
4. **Timeouts ≠ progress** — residue unscored until validated.
5. **Morning brief** mandatory after overnight: SHAs, EQ, do/don’t.
6. **Handoff contracts** (Agentic EDA): receiver must be able to consume artifacts.

## Failure modes (MatriQ)

- M4 agents PING timeout scored as EQ work
- Sibling Sheetfile experiment without instant revert path
- Cursor MCP stuck readonly while config says write
- Parallel writers on same sheet

## Acceptance criteria

- Lock table published
- Revert path tested once
- Brief includes fab GO protection status

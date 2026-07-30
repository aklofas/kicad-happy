---
name: design-review
description: >-
  Design review methodology and charters: evidence-backed findings, EQ
  scorecards, severity classes, verification basis, false-positive triage, and
  honest ceilings. Use for formal design reviews, principal reviews, scorecard
  updates, or "ready for fab" verdicts that must not invent lab scores.
---

# Design Review Methodology

Orchestrates other skills into a **chartered** review. Extends the `kicad` Design
Review Contract with industrial scoring honesty (MatriQ EQ lessons).

## Related Skills

| Skill | When |
|-------|------|
| `kicad` + `emc` + `spice` | Analyzer evidence |
| `hw-architecture-review` | Topology |
| `pcb-layout-review` / `dfm-review` / `si-review` | Domain chapters |
| `verification-planning` | Residual gates |
| `multi-agent-coordination` | Parallel reviewers |
| `kidoc` | Design review package export |

## Purpose

Ship a review that a principal engineer trusts: verdict, blockers, skipped
analyses, verification basis, and score **ceilings**.

## Review charter (minimum)

1. Scope + SoT files
2. Required analyzers list (run or explicit skip)
3. Severity model (blocker / major / minor / note)
4. Verification basis labels (analyzer / datasheet / lab / conjecture)
5. False-positive triage step
6. EQ or readiness score with formula + forbidden claims

## Decision process

1. Read charter; refuse uncoped “looks good”.
2. Gather analyzer evidence; triage FPs.
3. Domain chapters via specialized skills.
4. Score only dimensions with evidence; cap SI/PI/compliance without lab.
5. Separate docs/process Δ from physical Δ.
6. Verdict: GO / CONDITIONAL / NO-GO + next human actions (≤3).

## Checklist

- [ ] SoT + LIVE==CLI
- [ ] Analyzer matrix completed
- [ ] Blockers table
- [ ] Skipped analyses disclosed
- [ ] FP triage notes
- [ ] Score ceiling rationale
- [ ] Fab GO impact explicit

## Failure modes

- Stopping after schematic+PCB JSON dump
- Claiming verified without datasheet
- EQ>95 from overnight cosmetics (MatriQ blocked by SI+silicon)
- Agent timeout residue scored as progress

## Industrial references

- kicad-happy Design Review Contract
- pcbGPT: expert review still required (pass@1 hard tasks 0.72)
- Agentic EDA handoff validity (arXiv:2606.19795)

## Acceptance criteria

- Principal can sign from the package
- Physical vs docs deltas separated

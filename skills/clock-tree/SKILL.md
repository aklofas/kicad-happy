---
name: clock-tree
description: >-
  Review clock and REFCLK trees: oscillator choice, HCSL/LVDS/CMOS distribution,
  AC-coupling, series termination, fanout, SSC, and multi-load PCIe clocking. Use
  for REFCLK reviews, crystal load-cap checks, clock domain maps, or "who drives
  the clock" disputes on PCIe/FPGA/embedded boards.
---

# Clock Tree Review

## Related Skills

| Skill | Role |
|-------|------|
| `kicad` | Crystal / oscillator detectors, load-cap checks |
| `si-review` | Length, impedance, coupling of clock traces |
| `emc` | Clock harmonic / edge radiation rules |
| `hw-architecture-review` | Clock ownership in system architecture |
| `verification-planning` | Scope REFCLK bring-up |
| `datasheets` | Oscillator / buffer integration rules |

## Purpose

Map every clock source → buffer/fanout → loads with electrical standard,
termination, and verification method. Separate **architectural correctness**
from **jitter compliance** (lab-only).

## When to invoke

- PCIe REFCLK ownership debates (host vs onboard XO vs clock gen)
- Dual-slot / dual-load clocking
- Crystal load-cap validation
- Before claiming link-ready in EQ scorecards

## Inputs

- Schematic SoT + `analyze_schematic.py` JSON
- Architecture clocking decision (common clock / SRNS / SRIS)
- Oscillator and receiver datasheets (or `datasheets` cache)
- PCB lengths for clock nets (optional `analyze_pcb`)

## Outputs

1. Clock tree diagram (text)
2. Load table: source, format, termination, sheet refs
3. Risk list → verification IDs
4. Non-claims (jitter, SSC legality, Gen timing)

## Decision process

1. Inventory oscillators, crystals, clock gens, FPGA/SoC clock pins.
2. Classify: local XTAL, distributed REFCLK, recovered clock, PLL cascade.
3. For PCIe REFCLK: common clock vs SRNS/SRIS; who sources; series-R / AC-cap policy.
4. Fanout: single load vs dual-slot; buffer needed?
5. Spread-spectrum: intentional or forbidden for the link class.
6. EMC: edge rate and harmonic risk → `emc`.
7. Lab: probe points; do not claim compliance from schematic.

### Correct vs anti-pattern

| Correct | Anti-pattern |
|---------|--------------|
| Document Option A onboard XO + series R | Swap host/onboard clocks silently |
| Dual-load flagged for scope | Assume HCSL drives N loads forever |
| MEASURE amplitude/duty | EQ credit for “looks terminated” |

## Checklist

- [ ] Source and format (HCSL/LVDS/CMOS/LVPECL) stated
- [ ] Each load listed with termination
- [ ] Coupling caps / series R refs documented
- [ ] Unused clock pins handled (PD/PU/NC per datasheet)
- [ ] Crystal CL / load caps checked (analyzer + datasheet)
- [ ] Dual-load or long stubs flagged
- [ ] MEASURE items for amplitude / duty / jitter

## Failure modes

| Mode | Root cause | Impact | Improvement |
|------|------------|--------|-------------|
| Host vs onboard ambiguity | Spec skim | Enum fail | Ownership table |
| Missing AC-coupling | Pattern copy error | Link flaky | Datasheet gate |
| Fake Gen timing claim | Score pressure | Misleading GO | Non-claims |

## Industrial references

- PCIe Base Spec clocking chapters (cite revision)
- HCSL buffer vendor app notes
- JLCPCB guide: group clock circuitry on dedicated schematic pages
- pcbGPT semantic failures often omit support passives on clock/power pins

## Example

**MatriQ-like:** Onboard Y1 HCSL REFCLK to RC and EP connectors with series resistors R20/R21 policy documented; dual-load → Phase 7-D scope gate; no jitter EQ points until measured.

## Acceptance criteria

- Clock tree diagram + load table delivered
- Explicit non-claim on jitter compliance without measurement
- Handoff IDs created in verification-planning when dual-load or long routes exist

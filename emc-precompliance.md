# EMC Pre-Compliance Guide

Deep-dive into how the EMC pre-compliance skill works, what it checks, the physics behind the formulas, and how to use the results.

## How It Works

The EMC skill reads the output of the schematic and PCB analyzers, cross-references frequency data (switching regulators, clocks, bus speeds) against PCB geometry (trace routing, zone coverage, component placement, via stitching, stackup), and identifies the most common causes of EMC test failures.

```
KiCad schematic
  -> analyze_schematic.py -> schematic.json (frequencies, subcircuits, protection devices)

KiCad PCB
  -> analyze_pcb.py --full --schematic schematic.json -> pcb.json (traces, zones, vias, stackup, placement)

Both JSONs
  -> analyze_emc.py -> emc.json (findings, risk score, test plan, regulatory coverage)
```

No external tools required — all checks work with analytical formulas alone. When ngspice, LTspice, or Xyce is available, the `--spice-enhanced` flag enables SPICE-verified PDN impedance and EMI filter insertion loss analysis for higher accuracy. Without a simulator, the analytical path runs unchanged.

## Check Categories

44 rule IDs across 18 categories:

| Category | Rule IDs | What it detects | Requires |
|----------|----------|-----------------|----------|
| **Ground plane integrity** | GP-001 to GP-005 | Signal crossing voids, zone fragmentation, missing ground planes, low fill ratio, multiple ground domains | PCB |
| **Decoupling** | DC-001 to DC-003 | Cap too far from IC, IC with no decoupling cap, cap too far from via (connection inductance) | PCB |
| **I/O filtering** | IO-001, IO-002 | Connector without filtering, insufficient ground pins for signal count | PCB + schematic |
| **Switching EMC** | SW-001 to SW-003 | Harmonic overlap with test bands, switching node copper area, input cap loop area | Schematic + PCB |
| **Clock routing** | CK-001 to CK-004 | Clock on outer layer, long clock trace, clock routed near connector, no ground pour near crystal | PCB + schematic |
| **Via stitching** | VS-001 | Ground via spacing exceeds 2x lambda/20 at highest frequency | PCB + schematic |
| **Stackup** | SU-001 to SU-003 | Adjacent signal layers, signal far from reference plane, thin interplane cap | PCB |
| **Differential pair** | DP-001 to DP-004 | Intra-pair skew vs protocol limits, CM radiation from skew, reference plane change, outer layer routing | PCB + schematic |
| **Board edge** | BE-001 to BE-003 | Signal trace near edge, incomplete ground pour ring, insufficient connector area stitching | PCB |
| **PDN impedance** | PD-001 to PD-004 | Anti-resonance peaks exceeding target impedance in decoupling network | PCB + schematic |
| **Return path** | RP-001 | Layer transition via without nearby ground stitching via | PCB |
| **Crosstalk** | XT-001 | Trace spacing violating 3H rule, aggressor-victim pairs | PCB (--proximity) |
| **EMI filter** | EF-001, EF-002 | Input filter cutoff too close to switching frequency | Schematic |
| **ESD path** | ES-001, ES-002 | TVS too far from connector, TVS with insufficient ground vias | PCB + schematic |
| **Thermal-EMC** | TH-001, TH-002 | MLCC DC bias derating (SRF shift), ferrite near heat source | PCB + schematic |
| **Shielding** | SH-001 | Connector aperture slot resonance coinciding with emission source | PCB + schematic |
| **Emission estimates** | EE-001, EE-002 | Board cavity resonance frequencies, switching harmonic envelope | PCB / schematic |
| **Magnetic leakage** | ML-001 | Unshielded or unknown-shielding switching inductors within 15mm of sensitive analog circuits (ADCs, opamps, crystals, RF) | PCB + schematic |

## The Physics

### Differential-mode loop radiation

The fundamental emission mechanism. A current loop on the PCB radiates:

```
E = 2.632 x 10^-14 x f^2 x A x I / r   (V/m, with ground plane image)
```

Where f = frequency (Hz), A = loop area (m^2), I = current (A), r = distance (m).

**Key scaling rules:**
- Double the loop area: +6 dB emissions
- Double the frequency: +12 dB emissions (f^2 dependence)
- Double the current: +6 dB emissions

This is why ground plane voids are so critical — they force return currents to detour, creating large unintentional loops.

Ref: Ott, *Electromagnetic Compatibility Engineering* (Wiley, 2009), Ch. 6; Paul, *Introduction to Electromagnetic Compatibility* (Wiley, 2006), Ch. 10.

### Common-mode cable radiation

The dominant emission path for cable-connected products:

```
E = 1.257 x 10^-6 x f x L x I_CM / r   (V/m)
```

Where L = cable length (m), I_CM = common-mode current (A). Just **5 microamps** of CM current on a 1m cable at 100 MHz exceeds FCC Class B limits.

Ref: Ott, Ch. 6; [LearnEMC CM EMI Calculator](https://learnemc.com/ext/calculators/mremc/cmode.php).

### Switching regulator harmonics

A trapezoidal switching waveform produces harmonics with a predictable envelope:
- Flat to f1 = 1/(pi x tau) where tau = pulse width
- -20 dB/decade rolloff to f2 = 1/(pi x t_r) where t_r = rise time
- -40 dB/decade rolloff above f2

A 500 kHz buck converter has its 60th-176th harmonics in the FCC 30-88 MHz test band. Minimizing the switching loop area is the primary mitigation.

Ref: Paul, *Introduction to EMC*, Ch. 3.

### Differential pair skew

Length mismatch between differential pair traces creates common-mode voltage:

```
V_CM = V_diff x skew / (2 x T_rise)
```

For USB HS (V_diff=400mV, T_rise=500ps), a 4mm mismatch creates ~8.8mV of CM voltage — enough to measurably increase cable emissions. Protocol-specific skew limits: USB HS 25ps, PCIe 5ps, Ethernet 50ps, HDMI 20ps.

Ref: Ott, Ch. 19; Johnson, *High-Speed Signal Propagation*, Ch. 11.

### Board cavity resonance

The power/ground plane pair forms a parallel-plate cavity that resonates at:

```
f_mn = (c / 2*sqrt(er)) x sqrt((m/L)^2 + (n/W)^2)
```

At these frequencies, PDN impedance spikes and emissions increase. For a 100x80mm FR4 board, the first resonance is at ~715 MHz.

Ref: Pozar, *Microwave Engineering*; [LearnEMC Cavity Resonance Calculator](https://learnemc.com/ext/calculators/cavity_resonance/pcb-res.html).

## Supported Standards

| Standard | Flag | Frequency range | Use case |
|----------|------|----------------|----------|
| FCC Part 15 Class B | `--standard fcc-class-b` | 30 MHz - 40 GHz at 3m | US residential (default) |
| FCC Part 15 Class A | `--standard fcc-class-a` | 30 MHz - 40 GHz at 10m | US commercial |
| CISPR 32 Class B / EN 55032 | `--standard cispr-class-b` | 30 MHz - 1 GHz at 10m | EU CE marking |
| CISPR 32 Class A | `--standard cispr-class-a` | 30 MHz - 1 GHz at 10m | EU commercial |
| CISPR 25 Class 5 | `--standard cispr-25` | 30 MHz - 1 GHz at 1m | Automotive |
| MIL-STD-461G RE102 | `--standard mil-std-461` | 2 MHz - 18 GHz at 1m | Military/defense |

All limit values verified against official regulatory text ([47 CFR 15.109](https://www.law.cornell.edu/cfr/text/47/15.109), IEC CISPR 32).

The `--market` flag selects all applicable standards for a target market:

| Market | Standards applied |
|--------|-------------------|
| `us` | FCC Part 15 (radiated + conducted) |
| `eu` | EN 55032 + IEC 61000-4-2 (ESD) + IEC 61000-4-4 (EFT) + IEC 61000-4-5 (Surge) |
| `automotive` | CISPR 25 + ISO 10605 (ESD) + ISO 7637-2 (Transients) |
| `medical` | EN 55032 + EN 60601-1-2 + IEC 61000-4-2/3/5 (higher levels) |
| `military` | MIL-STD-461G RE102/CE102/CS114/CS116/CS118 |

## Risk Scoring

Each rule ID contributes at most 3 findings to the score (taking the worst severity first). This prevents per-net rules like GP-001 — which fires once per net with poor ground plane coverage — from saturating the score to 0 on 2-layer boards with many nets. All findings are still reported in the output; only the summary score is capped.

```
penalty = sum(severity weight × confidence weight, worst 3 findings per rule)
score = max(0, min(100, 100 - penalty))
```

Severity weights: error = 12, warning = 3, info = 0. Confidence weights: deterministic and datasheet-backed 1.0, heuristic 0.5, so a heuristic error costs 6 points. 0 is the worst score and 100 the best; scores can be fractional. The score covers every unsuppressed finding; `--severity` only filters the list printed or written.

| Score | Assessment |
|-------|-----------|
| 90-100 | Low EMC risk — basic hygiene checks pass |
| 70-89 | Moderate risk — some issues to address |
| 50-69 | Significant risk — multiple issues likely to cause failures |
| <50 | High risk — fundamental design issues |

## Per-Net Scoring

In addition to the board-level risk score, the analyzer computes a per-net EMC score. Each net that appears in a finding gets a score from the same severity and confidence weights, counting every finding on the net (no three-per-rule cap) and weighting SPICE-verified findings ×1.5. This lets you identify the highest-risk signals at a glance:

```
Highest-risk nets:
  SPI_CLK: 79/100 (3 findings: GP-001, CK-001, BE-001)
  USB_DP:  85/100 (2 findings: DP-001, DP-004)
  USB_DM:  85/100 (2 findings: DP-001, DP-004)
  SW_NODE: 94/100 (1 finding: SW-002)
```

Output as `per_net_scores` in the JSON, sorted worst-first.

## Pre-Compliance Test Plan

The analyzer generates a test plan to help you prepare for lab testing:

**Frequency band prioritization** — ranks FCC/CISPR frequency bands by number of emission sources (switching regulator harmonics, clock harmonics, protocol frequencies). Focus your near-field probing and pre-scan on the highest-risk bands first.

**Interface risk ranking** — scores each external connector by protocol speed and filter/ESD presence. The highest-scoring interface is most likely to cause cable radiation failures.

**Suggested probe points** — lists XY coordinates of switching inductors, crystal oscillators, and unfiltered connectors. These are the spots to probe during near-field scanning.

## SPICE-Enhanced Mode

When a SPICE simulator is available (ngspice, LTspice, or Xyce), the `--spice-enhanced` flag improves four areas:

**PDN impedance (PD-001, PD-002)** — The analytical model sums the complex admittances of the capacitor branches (ESR, ESL and capacitance each), so it already includes the phase between branches. With `--spice-enhanced`, SPICE runs an AC sweep of the same RLC network using the same package-estimated ESR and ESL. PD-001 and PD-002 stay `heuristic` confidence either way, because the ESR and ESL are package estimates.

**SPICE-verified cap suggestions** — When PD-001 flags an anti-resonance peak, the tool computes a specific cap value whose SRF fills the gap (rounded to E12 standard values), then re-runs the SPICE sweep with the suggested cap added to verify the peak is resolved. The recommendation includes the exact component value and verification result: "Add 220pF 0603 MLCC (SPICE-verified: peak reduced from 33.5 ohm to 8.9 ohm)."

**EMI filter insertion loss (EF-001, EF-002)** — Instead of just checking cutoff frequency vs switching frequency, SPICE simulates the actual insertion loss including capacitor parasitics. Reports attenuation in dB at the switching frequency and its 3rd harmonic.

**Switching harmonic FFT (EE-002)** — Instead of the analytical trapezoidal envelope approximation, runs a transient SPICE simulation of the switching waveform and extracts actual harmonic amplitudes using the Goertzel algorithm. EE-002 findings show SPICE FFT results alongside the analytical envelope for comparison.

```bash
# Enable SPICE-enhanced mode
python3 skills/emc/scripts/analyze_emc.py --schematic sch.json --pcb pcb.json --spice-enhanced

# The GitHub Action enables this automatically when ngspice is installed
```

Findings from SPICE-enhanced checks are annotated "(SPICE-verified)" in the description and receive 1.5x weight in per-net scoring. Without a simulator, the analytical model runs unchanged and findings are annotated "(analytical)".

## Limitations

**What this analyzer cannot do:**
- Predict absolute emission levels better than +/-10-20 dB
- Account for enclosure effects (shielding, apertures, seams)
- Predict cable radiation without knowing external cable routing and length
- Replace full-wave simulation for complex geometries
- Guarantee compliance — only a calibrated measurement in an accredited lab can do that

**What it does well:**
- Catch ~70% of common EMC design mistakes before fabrication
- Prioritize the most likely problem areas for review
- Provide quantitative relative risk scoring
- Generate a checklist for pre-compliance lab testing
- Reduce first-spin failure rate (industry estimate: ~50% fail EMC on first attempt)

## Running Standalone

```bash
# Full analysis with both schematic and PCB
python3 skills/emc/scripts/analyze_emc.py \
  --schematic schematic.json --pcb pcb.json --output emc.json

# Select target standard
python3 skills/emc/scripts/analyze_emc.py \
  --schematic schematic.json --pcb pcb.json --standard cispr-class-b

# Select target market (sets all applicable standards)
python3 skills/emc/scripts/analyze_emc.py \
  --schematic schematic.json --pcb pcb.json --market eu

# SPICE-enhanced mode (improved PDN and filter accuracy)
python3 skills/emc/scripts/analyze_emc.py \
  --schematic schematic.json --pcb pcb.json --spice-enhanced

# Human-readable text output
python3 skills/emc/scripts/analyze_emc.py \
  --schematic schematic.json --pcb pcb.json --text

# Filter by severity
python3 skills/emc/scripts/analyze_emc.py \
  --schematic schematic.json --pcb pcb.json --severity high
```

PCB analyzer should be run with `--full` for best results (enables per-track coordinates needed for ground plane crossing, board edge proximity, and return path checks) and with `--schematic schematic.json` (without it SW-003 has no pad loop and reports only an info estimate).

## References

- Ott, H.W. *Electromagnetic Compatibility Engineering.* Wiley, 2009.
- Paul, C.R. *Introduction to Electromagnetic Compatibility.* 2nd ed., Wiley, 2006.
- Johnson, H.W. *High-Speed Digital Design.* Prentice Hall, 1993.
- Bogatin, E. *Signal and Power Integrity — Simplified.* 3rd ed., 2018.
- [47 CFR Part 15](https://www.law.cornell.edu/cfr/text/47/part-15) — FCC unintentional radiator regulations.
- [LearnEMC.com](https://learnemc.com/) — EMC education and calculators.
- Hubing, T.H. "Common PCB Layout Mistakes that Cause EMC Compliance Failures." AltiumLive 2022.

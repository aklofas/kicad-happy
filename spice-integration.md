# SPICE Integration Guide

Deep-dive into how the SPICE simulation skill works, what it can and can't do, and how to get the most out of it.

## How It Works

The SPICE skill reads the output of the schematic analyzer (and optionally the PCB analyzer), identifies subcircuits that can be simulated, generates SPICE testbenches for each one, runs them in batch mode using the detected simulator (ngspice, LTspice, or Xyce), and evaluates the results against expected values.

```
KiCad schematic
  → analyze_schematic.py → analysis.json (detects subcircuits with component values)
  → simulate_subcircuits.py → generates .cir testbenches → runs simulator → report.json

Optionally, with PCB:
  → analyze_pcb.py --full → pcb.json (trace geometry, stackup)
  → extract_parasitics.py → parasitics.json (trace R, via L, coupling C)
  → simulate_subcircuits.py --parasitics parasitics.json → parasitic-aware report
```

## Supported Simulators

| Simulator | Platform | Install | Notes |
|-----------|----------|---------|-------|
| **ngspice** | Linux, macOS, Windows | `apt install ngspice` / `brew install ngspice` / ngspice.sourceforge.io | Default choice. Full measurement support via `.control` blocks. |
| **LTspice** | Windows, macOS, Linux (wine) | analog.com/ltspice | Free, widely installed. Uses `.meas` in netlist body. |
| **Xyce** | Linux, macOS, Windows | xyce.sandia.gov | Sandia's parallel SPICE. Uses `.measure` statements. |

Auto-detected in the order above (first found wins). Override with `--simulator ngspice|ltspice|xyce` or `SPICE_SIMULATOR` env var.

The circuit netlists are standard SPICE (Berkeley SPICE3 syntax) — portable across all simulators. Only the measurement layer differs: ngspice uses `.control` blocks, LTspice/Xyce use `.meas`/`.measure` in the netlist body. The testbench architecture (SpiceTestbench objects) separates the portable circuit from the simulator-specific measurement commands.

The key insight: the schematic analyzer already detects 21+ subcircuit types (RC filters, voltage dividers, opamp circuits, etc.) with full component values and net topology. The SPICE skill turns these static detections into dynamic simulations — instead of "I found an RC filter with calculated fc=15.9kHz," it says "I simulated this RC filter and confirmed fc=15.9kHz."

## External Decks and PSpice

`run_external_deck.py` runs a complete user-supplied deck separately from the generated-testbench workflow. Select PSpice explicitly:

```bash
python3 skills/spice/scripts/run_external_deck.py example.cir --simulator pspice --timeout 120
```

The runner resolves the deck to an absolute path but invokes PSpice from the deck's parent directory using the deck filename. Relative `.include` and `.lib` paths therefore retain their simulator-native meaning. PSpice writes `<deck-stem>.out` beside the deck and may overwrite an existing file with that name.

PSpice success requires a zero process exit code, a non-empty native output file, a `JOB CONCLUDED` marker, and no `JOB ABORTED` or `ERROR --` line. Warnings and a zero-error summary do not fail the run. The JSON result records execution success only; it does not validate circuit behavior or establish regulatory compliance.

This first version does not add PSpice to `simulate_subcircuits.py`, `SPICE_SIMULATOR`, or auto-detection. It does not render or parse PSpice measurements, copy vendor libraries, inspect encryption, parse waveform binaries, or repair convergence problems.

## What Gets Simulated

18 subcircuit types across analog, power, and RF domains:

| Category | Types | Model Accuracy |
|----------|-------|---------------|
| **Passive filters** | RC filters, LC filters | Exact — ideal passives are mathematically perfect |
| **Voltage references** | Voltage dividers, feedback networks, regulator feedback | Exact — unloaded ratio validation |
| **Opamp circuits** | Inverting, non-inverting, buffer, integrator, compensator, transimpedance | Per-part behavioral (~100 common parts) or ideal fallback |
| **Discrete** | Transistor switches (MOSFET + BJT), protection devices (TVS/ESD) | Approximate — generic device models |
| **Sensors** | Current sense shunts, crystal oscillators | Exact for shunts, approximate for crystals |
| **Power** | Decoupling analysis, inrush estimation, regulator feedback verification | Mixed — passives exact, active approximate |
| **Complex** | Bridge circuits, BMS balance resistors, snubbers, RF matching, RF chain gain budget | Mixed |

## Per-Part Behavioral Models

For opamps with recognized part numbers, the skill uses a behavioral model with the actual GBW, slew rate, input offset, and output swing from the datasheet. This catches real design issues that ideal models miss.

**Example: LM358 at gain=-100**

| Parameter | Ideal Model (Phase 1) | Behavioral Model (Phase 2) | Reality |
|-----------|----------------------|---------------------------|---------|
| DC gain | 40.0 dB (correct) | 40.0 dB (correct) | 40.0 dB |
| Bandwidth | 98.8 kHz (wrong!) | ~10 kHz (correct) | ~10 kHz |
| GBW used | 10 MHz (generic) | 1 MHz (LM358 actual) | 1 MHz |

The ideal model hides the bandwidth limitation. The behavioral model correctly shows it.

### Coverage

The built-in lookup table covers ~100 common parts:
- **49 opamps** — LM358, TL072, MCP6002, OPA2340, NE5532, AD8605, OP27, and more
- **35 LDOs** — AMS1117, LM7805/L7805, AP2112, MCP1700, TPS7A02, LP5907, and more
- **9 comparators** — LM393, LM339, LM311, TLV1805, and more
- **10 voltage references** — TL431, LM4040, REF5050, and more
- **30+ crystal drivers** — STM32, ESP32, nRF52, ATmega, RP2040 oscillator specs

Parts not in the table fall back to generic ideal models with a note in the report. The lookup table can be extended by adding entries to `spice_part_library.py`.

### Model Resolution Cascade

1. **Project cache** — `<project>/spice/models/` (previously resolved, instant)
2. **Distributor API parametric data** — queries LCSC (no auth), DigiKey, element14, Mouser for real specs. Returns GBW, slew rate, etc. from structured parametric databases.
3. **Structured datasheet extraction** — reads pre-extracted specs from `<project>/datasheets/extracted/<MPN>.json`. Cached JSON with SPICE-relevant parameters extracted by Claude from PDF datasheets, scored for quality.
4. **Datasheet PDF regex extraction** — reads downloaded PDFs from `<project>/datasheets/`, extracts electrical specs via text pattern matching. Requires `pdftotext`. Last-resort fallback.
5. **Built-in lookup table** — `spice_part_library.py` (~100 common parts with datasheet-verified specs). Offline safety net.
6. **Ideal model fallback** — generic model with fixed parameters (10 MHz GBW for opamps)

Real data (APIs, structured extractions, datasheets) takes priority over the lookup table. The table is the offline fallback when no network or downloaded datasheets are available. Any distributor skill that has synced datasheets contributes — DigiKey, LCSC, element14, or Mouser. Structured extractions are produced by the `kicad` skill's datasheet extraction workflow (see `kicad/references/datasheet-extraction.md`).

Models are cached project-locally next to the schematic files, same pattern as the `datasheets/` directory. Once a model is resolved and cached, subsequent runs use the cache (tier 1) without any network calls.

## PCB Parasitic Extraction

When both schematic and PCB analysis are available, the skill can inject real PCB parasitics into the SPICE testbenches.

### What Gets Extracted

| Parasitic | Formula | Example |
|-----------|---------|---------|
| **Trace resistance** | R = rho * L / (W * T) | 25mm @ 0.25mm wide, 1oz Cu = 48 mOhm |
| **Via resistance** | R = rho * H / (pi * annular_area) | 0.3mm drill through 1.6mm board = 5 mOhm |
| **Via inductance** | L = (mu0 * H / 2pi) * ln(2H/D) | 0.3mm drill = 0.7 nH |
| **Coupling capacitance** | C = eps0 * eps_r * L * T / S | 10mm parallel run @ 0.5mm spacing = 0.3 fF |

### Trace Impedance

The PCB analyzer computes characteristic impedance per trace segment using Wheeler's microstrip equations (IPC-2141):

```
For w/h < 1: Z0 = (60/sqrt(er)) * ln(8h/w_eff + w_eff/4h)
For w/h >= 1: Z0 = (120*pi) / (sqrt(er) * (w_eff/h + 1.393 + 0.667*ln(w_eff/h + 1.444)))
```

This uses the board's stackup data (epsilon_r, dielectric thickness, copper weight). Boards without explicit stackup get a default 2-layer FR4 (1.6mm, 1oz, er=4.5).

### What Parasitics Catch

| Scenario | Without parasitics | With parasitics |
|----------|-------------------|-----------------|
| Long trace to RC filter | fc = 159 Hz | fc = 153 Hz (-3.8%) |
| Via in regulator feedback | Vout = 3.300V | Same (no DC shift, but adds HF zero) |
| Clock near ADC input | Clean ADC | 0.5pF coupling = crosstalk |
| Narrow USB traces on 2-layer | 90 Ohm assumed | 109 Ohm measured (too high) |

## Analyzer Enhancements for SPICE

Several schematic and PCB analyzer features were added to feed deeper simulations:

### Schematic Analyzer
- **Regulator output capacitors** — detects caps on the output rail, sorted by value. Reports package, estimated ESR.
- **Compensation capacitors** — detects feed-forward and compensation caps on the FB net with role classification.
- **Capacitor ESR estimation** — parses package size from KiCad footprint (0402/0603/0805/etc), estimates ESR from package and capacitance.
- **Bus load counting** — I2C buses report load count and estimated bus capacitance (5pF per device). Enables rise time validation.
- **Power dissipation** — LDO regulators get estimated Pdiss from Vin/Vout dropout and load current.

### PCB Analyzer (with --full)
- **Per-segment trace impedance** — microstrip Z0 from stackup, per segment. Flags impedance discontinuities.
- **Pad-to-pad routed distance** — actual trace routing distance between pads (not Euclidean). Dijkstra on the routing graph.
- **Return path continuity** — samples points along signal traces, checks for ground plane on opposite layer. Reports coverage %.
- **Via stub length** — computes stub from layer span vs board thickness on 4+ layer boards.
- **Trace segment detail** — per-segment width, length, and layer for parasitic extraction.

### Gerber Analyzer
- **Per-net copper usage** — draw and flash operation counts per net from X2 attributes. Proxy for copper area.

## Limitations

### Accuracy boundaries
- **Passive circuits (RC, LC, dividers, current sense)** are mathematically exact. Simulation confirms the analyzer's arithmetic.
- **Opamp circuits with behavioral models** are accurate for gain and bandwidth. Not accurate for: slew rate limiting (not yet modeled in transient), noise, CMRR, or output current.
- **Opamp circuits with ideal fallback** are accurate for DC gain only. Bandwidth is approximate (10 MHz GBW assumption).
- **Transistor circuits** confirm switching behavior but use generic threshold voltages. Real Vth depends on the specific part.
- **Crystal circuits** validate load capacitor arithmetic. Startup margin requires the driving IC's transconductance (available for ~30 MCU families in the lookup table).

### Architectural limitations
- **Subcircuits are simulated in isolation** — no loading from downstream stages, no interaction between subcircuits.
- **Testbench topology is reconstructed from analyzer data** — complex or unusual topologies may be reconstructed incorrectly.
- **Per-part models are AC/DC only** — no transient simulation (step response, settling time).
- **PCB parasitics are lumped** — one R per trace, one L per via. No distributed transmission line modeling.
- **No EM simulation** — parasitics are formula-based approximations, not field solutions.

### What it replaces vs. what it doesn't

**Replaces:** Back-of-envelope calculations, manual "does this RC filter actually give me 15.9kHz" checks, the question "did I use the right resistor values in my feedback divider."

**Does not replace:** Full-circuit SPICE simulation for stability analysis, transient behavior, Monte Carlo tolerance analysis, or thermal simulation. The SPICE skill runs targeted subcircuit testbenches, not full-board simulation. Use it for quick validation during design review; use the simulator's GUI for deep interactive analysis.

## Environment Variables

### Simulator selection

| Variable | Required | Purpose |
|----------|----------|---------|
| `SPICE_SIMULATOR` | No | Force a specific simulator: `ngspice`, `ltspice`, or `xyce`. Default: auto-detect (tries ngspice → LTspice → Xyce). Can also be set via `--simulator` CLI flag. |
| `NGSPICE_PATH` | No | Explicit path to ngspice binary (skips PATH lookup) |
| `LTSPICE_PATH` | No | Explicit path to LTspice binary |
| `XYCE_PATH` | No | Explicit path to Xyce binary |
| `PSPICE_PATH` | No | Explicit path to the PSpice executable for `run_external_deck.py`; not used by auto-detection |

Most users don't need to set any of these — the skill auto-detects whichever simulator is installed. The `*_PATH` variables are for non-standard install locations.

### Behavioral model API credentials

| Variable | Required | Purpose |
|----------|----------|---------|
| `DIGIKEY_CLIENT_ID` | No | Enables DigiKey API parametric spec lookup (OAuth 2.0 client credentials) |
| `DIGIKEY_CLIENT_SECRET` | No | Paired with CLIENT_ID |
| `ELEMENT14_API_KEY` | No | Enables element14/Newark/Farnell API parametric spec lookup |
| `MOUSER_SEARCH_API_KEY` | No | Enables Mouser API parametric spec lookup |

**LCSC requires no credentials** — the jlcsearch community API is free and is tried first in the cascade.

Without any API credentials, the skill still works — it falls through to the built-in lookup table (100+ parts) and then to ideal models. API credentials expand behavioral model coverage to any part the distributors carry.

## Testing

The SPICE skill is validated against the same 5,829-repo test corpus as the analyzers:

- **30,646 simulations** across the full corpus
- **93.1% pass rate** (28,544 pass, 1,297 warn, 5 fail, 922 skip)
- **0 script errors** — the skill never crashes on any project in the corpus
- **57.7% behavioral model coverage** for opamp circuits (626/1,085 used per-part models)

The warns are primarily opamp gain-bandwidth limitations exposed by behavioral models — these are informational (the model correctly shows the part can't achieve the desired bandwidth), not simulation errors.

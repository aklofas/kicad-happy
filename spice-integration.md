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
  → simulate_subcircuits.py --parasitics parasitics.json → report (low-pass RC filters include trace R and via L)
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

An external deck is run as trusted input: the runner does not inspect or sandbox it, decks can include arbitrary files through `.include`/`.lib`, and ngspice `.control` blocks can run shell commands. Agents should only run a deck the user explicitly names.

The runner resolves the deck to an absolute path but invokes PSpice (`pspice.exe -r -e ./<deck> -o ./<stem>.out`) from the deck's parent directory using the deck filename, prefixed with `./` (`.\` on Windows) so a name starting with `-` is never read as an option. Relative `.include` and `.lib` paths therefore retain their simulator-native meaning. The executable comes from `PSPICE_PATH` (an existing file) or, failing that, a `PATH` search; discovered paths are made absolute before PSpice is launched from the deck directory. On Windows the `PATH` search looks only for `pspice.exe` in absolute `PATH` entries (never the current directory or other `PATHEXT` suffixes), and the final executable must be an absolute path ending in `.exe`; anything else, such as a `.bat` or `.cmd` script, is rejected rather than run through `cmd.exe`. Elsewhere `pspice`, then `pspice.exe`, is looked up on `PATH`.

PSpice writes `<deck-stem>.out` beside the deck and may overwrite an existing file with that name; it also writes a `<deck-stem>.json` sidecar and, for waveform probes, a `<deck-stem>.dat` data file there. The runner never deletes the native output. Because of that, it exits with a usage error (code 2, before launching anything) when `--output` resolves to the deck, the `.out` file, or — for PSpice — the `.json` sidecar or `.dat` file (compared case-insensitively on Windows), when `--output` is a directory or its directory does not exist, or when a PSpice deck itself has a `.out`, `.json`, or `.dat` suffix (it would be overwritten by PSpice's own files); the same check refuses an LTspice deck ending `.log` or `.raw` and a Xyce deck ending `.mt0`. The result JSON is written atomically; a new file gets the normal umask-derived mode, and a replaced file keeps its existing mode.

`--timeout` defaults to 600 seconds, since real PSpice runs can take minutes. The simulator's stdout and stderr are discarded (the native `.out` is the record) so that child processes cannot hold pipes open; on timeout, or if the runner itself is interrupted (for example by Ctrl-C), it kills the simulator's entire process tree (`%SystemRoot%\System32\taskkill.exe /F /T` on Windows, a process-group kill elsewhere) and returns within the timeout plus a short grace period.

Resolve any pending PSpice dialogs or interrupted simulation-queue entries before starting a batch run. PSpice can display an interactive queue prompt after an interrupted run; the runner does not dismiss dialogs or change application preferences, so a blocked run returns a timeout failure.

PSpice success requires a zero process exit code, a native output file that was written or changed by this run (a leftover `.out` from an earlier run is not success), and a line that is exactly `JOB CONCLUDED`. A `JOB ABORTED` line, or any line starting `ERROR --` or `ERROR(ORPSIM-`, fails the run; the failure note quotes the first such error line. UTF-16 and UTF-8 byte-order marks in the `.out` are honored, and the file is scanned incrementally in bounded chunks, so large transient logs are not loaded into memory. A single line longer than 1,000,000 characters fails the run rather than being partially classified. Warnings (`WARNING(...)`) and a zero-error summary do not fail the run. The JSON result records execution success only; it does not validate circuit behavior or establish regulatory compliance.

The runner also accepts `--simulator ngspice`, `ltspice`, or `xyce`, which reuse the existing backends' `run()` unchanged and get none of the PSpice handling above (`ngspice` runs with `-n`, so a `.spiceinit` beside the deck or in the home directory is not read; put needed `set` options in the deck's `.control` block): success is the simulator's exit code only (no native-output check), the deck is passed as an absolute path from the runner's current working directory, and on timeout only the direct simulator process is killed — child processes it started may keep running. The result's `native_output` is `null` for these simulators.

This first version does not add PSpice to `simulate_subcircuits.py`, `SPICE_SIMULATOR`, or auto-detection. It does not render or parse PSpice measurements, copy vendor libraries, inspect encryption, parse waveform binaries, or repair convergence problems.

## What Gets Simulated

17 subcircuit types across analog, power, and RF domains:

| Category | Types | Model Accuracy |
|----------|-------|---------------|
| **Passive filters** | RC filters, LC filters | Exact — ideal passives are mathematically perfect |
| **Voltage references** | Voltage dividers, feedback networks, regulator feedback | Exact — unloaded ratio validation |
| **Opamp circuits** | Inverting, non-inverting, buffer, integrator, compensator, transimpedance | Per-part behavioral (49 op-amps in the built-in table, more through distributor APIs) or ideal fallback |
| **Discrete** | Transistor switches (MOSFET + BJT), protection devices (TVS/ESD) | Approximate — generic device models |
| **Sensors** | Current sense shunts, crystal oscillators | Exact for shunts, approximate for crystals |
| **Power** | Decoupling analysis, inrush estimation, regulator feedback verification | Mixed — passives exact, active approximate |
| **Complex** | Bridge circuits, BMS balance resistors, snubbers, RF matching, RF chain gain budget | Mixed |

## Per-Part Behavioral Models

For opamps with recognized part numbers, the skill uses a behavioral model with the actual GBW, slew rate, input offset, and output swing from the datasheet. This catches real design issues that ideal models miss.

**Example: LM358 at gain=-100**

| Parameter | Ideal Model | Behavioral Model | Reality |
|-----------|----------------------|---------------------------|---------|
| DC gain | 40.0 dB (correct) | 40.0 dB (correct) | 40.0 dB |
| Bandwidth | 98.8 kHz (wrong!) | ~10 kHz (correct) | ~10 kHz |
| GBW used | 10 MHz (generic) | 1 MHz (LM358 actual) | 1 MHz |

The ideal model hides the bandwidth limitation. The behavioral model correctly shows it.

### Coverage

The built-in lookup table covers 103 parts:
- **49 opamps** — LM358, TL072, MCP6002, OPA2340, NE5532, AD8605, OP27, and more
- **35 LDOs** — AMS1117, LM7805/L7805, AP2112, MCP1700, TPS7A02, LP5907, and more
- **9 comparators** — LM393, LM339, LM311, TLV1805, and more
- **10 voltage references** — TL431, LM4040, REF5050, and more
- **24 crystal-driver entries** (22 MCU families, two 32 kHz LSE variants) — STM32, ESP32, nRF52, ATmega, RP2040 oscillator specs

Parts not in the table fall back to generic ideal models with a note in the report. The lookup table can be extended by adding entries to `spice_part_library.py`.

### Model Resolution Cascade

1. **Project cache** — `<project>/spice/models/` (previously resolved, instant)
2. **Distributor API parametric data** — queries LCSC (no auth), DigiKey, element14, Mouser for real specs. Returns GBW, slew rate, etc. from structured parametric databases.
3. **Legacy structured extraction** — a `spice_specs` record from `<project>/datasheets/extracted/` (score ≥ 6 of 10). It does not read v1.4 extractions, and in practice it finds nothing from the `datasheets` skill's cache. It and the PDF tier run only when the analysis names its project.
4. **Datasheet PDF regex extraction** — reads downloaded PDFs from `<project>/datasheets/`, extracts electrical specs via text pattern matching. Requires `pdftotext`. Last-resort fallback.
5. **Built-in lookup table** — `spice_part_library.py` (103 parts with datasheet-verified specs). Offline safety net.
6. **Ideal model fallback** — generic model with fixed parameters (10 MHz GBW for opamps)

Real data (APIs, structured extractions, datasheets) takes priority over the lookup table. The table is the offline fallback when no network or downloaded datasheets are available. Any distributor skill that has synced datasheets contributes — DigiKey, LCSC, element14, or Mouser. Structured extractions come from the `datasheets` skill (see [Datasheet Extraction Guide](datasheet-extraction.md)); the SPICE resolver reads only legacy `spice_specs` records from them.

Models are cached project-locally next to the schematic files, same pattern as the `datasheets/` directory. Once a model is resolved and cached, subsequent runs use the cache (tier 1) without any network calls.

## PCB Parasitic Extraction

When both schematic and PCB analysis are available, the skill can insert PCB trace resistance and via inductance into low-pass RC-filter testbenches.

### What Gets Extracted

| Parasitic | Formula | Example |
|-----------|---------|---------|
| **Trace resistance** | R = rho * L / (W * T) | 25mm @ 0.25mm wide, 1oz Cu = 48 mOhm |
| **Via resistance** | R = rho * H / (pi * (r_outer² - r_inner²)) | 0.3mm drill through 1.6mm board ≈ 1.2 mOhm (25 µm plating) |
| **Via inductance** | L = (mu0 * H / 2pi) * ln(2H/D) | 0.3mm drill = 0.7 nH |
| **Coupling capacitance** | C = eps0 * eps_r * L * T / S | 10mm parallel run @ 0.5mm spacing ≈ 28 fF (eps_r 4.5, 1oz) |

Via resistance and coupling capacitance are reported by `extract_parasitics.py` but not inserted into testbenches.

### Trace Impedance

The PCB analyzer (`--full`) estimates characteristic impedance per trace with Hammerstad's microstrip equations, widening the trace for copper thickness (IPC-2141):

```
e_eff = (er+1)/2 + (er-1)/2 * (1 + 12h/w_eff)^-0.5      (+ (er-1)/2 * 0.04*(1 - w_eff/h)^2 when w_eff/h < 1)
For w_eff/h < 1:  Z0 = (60/sqrt(e_eff)) * ln(8h/w_eff + w_eff/4h)
For w_eff/h >= 1: Z0 = (120*pi) / (sqrt(e_eff) * (w_eff/h + 1.393 + 0.667*ln(w_eff/h + 1.444)))
```

Outer layers use `e_eff`; inner layers use the same formulas with the bulk `er`, a first-order estimate rather than a stripline model. The stackup comes from the board file. A board without one gets the stackup KiCad builds by default for its copper count and thickness (0.035 mm copper, FR4 εr 4.5, the board thickness, 1.6 mm if the file gives none, shared among the dielectrics; `setup.stackup_source: inferred`).

### What Parasitics Catch

| Scenario | What the simulation does |
|----------|--------------------------|
| Long trace to a low-pass RC filter | Adds the trace R and via L of the output net; for kΩ-range filters the cutoff moves by well under 0.1% |
| Feedback networks, LC filters, op-amp stages | Unchanged: these testbenches ignore the parasitics file |
| Crosstalk / coupling | Not simulated; `extract_parasitics.py` reports coupling C only |
| Trace impedance | Not a SPICE result; see the PCB analyzer's per-segment impedance |

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
- **Crystal circuits** validate load capacitor arithmetic. Startup margin requires the driving IC's transconductance (available for 24 crystal-driver entries in the lookup table).

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

Without any API credentials, the skill still works — it falls through to the built-in lookup table (103 parts) and then to ideal models. API credentials expand behavioral model coverage to any part the distributors carry.

## Testing

See [VALIDATION.md](VALIDATION.md) for the validation corpus, analyzer run counts and reproduction procedure.

- Results are `pass`, `warn`, `fail`, `info` (measured, no criterion) and `skip`. A run completing without error does not mean every simulated subcircuit passed.
- Warns on op-amp circuits are mostly gain-bandwidth limits that the behavioral models expose: the part cannot reach the requested bandwidth. They are informational, not simulation errors.

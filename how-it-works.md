# How It Works

This document explains the full design review workflow — what happens when you ask the AI agent to analyze your KiCad project, how the analysis scripts work, where the data comes from, what the agent actually does with it, and where the limitations are.

## The core idea

The analysis scripts are **data extraction tools**, not AI. They're deterministic Python that parses KiCad's S-expression file format into structured JSON — component lists, net connectivity, detected subcircuits, board dimensions, DFM measurements. No machine learning, no heuristics that change between runs, no cloud calls. You can run them yourself and read the output.

The agent reads that JSON, reads your datasheets, and writes a design review. The AI part is the *reasoning about* the data — not the data itself.

This separation matters because it means:

- **The data is auditable.** Run the script, read the JSON, verify any claim.
- **The reasoning is transparent.** The agent shows its work — calculations, pin traces, datasheet references. You can check every conclusion.
- **Nothing is hidden.** There's no model making invisible decisions about your design. The analysis scripts are open source, the methodology is documented, and the JSON output is "human-readable."

## What happens when you say "analyze my board"

### Step 1: Parse the files

The schematic analyzer (`analyze_schematic.py`) reads your `.kicad_sch` file and:

1. **Parses the S-expression format** into a generic tree. No KiCad-version-specific logic — the parser handles KiCad 5 through 10 because it operates on structure, not schema.

2. **Walks hierarchical sheets.** If your design has sub-sheets (including multi-instance sheets where the same sub-sheet is placed multiple times with different reference designators), the analyzer traverses them breadth-first, remapping references per instance.

3. **Extracts every component** with all its properties: reference designator, value, footprint, lib_id, MPN, datasheet URL, pin positions (after applying rotation/mirror transforms).

4. **Builds the net graph** using union-find on pin coordinates. Every wire endpoint, label, power symbol, and component pin gets a coordinate key. Points within 0.01mm are merged. Wires union their endpoints. Labels union their position with any wire they touch. The result: for every net, a complete list of which component pins are connected.

5. **Runs 60+ signal, domain, validation, and audit detectors.** Each is a pure function that looks for specific circuit patterns in the connectivity graph:

   | Detector | What it finds |
   |----------|--------------|
   | Voltage dividers | Two resistors sharing a node, one side to power/ground. Computes ratio and output voltage. |
   | RC/LC filters | Resistor-capacitor or inductor-capacitor pairs. Computes cutoff frequency. |
   | Power regulators | ICs with feedback divider networks. Computes Vout from Vref (datasheet lookup for ~60 part families, heuristic fallback). |
   | Transistor circuits | MOSFETs and BJTs with gate/base biasing, load classification, flyback diode detection. |
   | Op-amp circuits | Inverting/non-inverting/buffer/differential configurations. Gain computation from feedback resistors. |
   | Current sense | Shunt resistors with differential measurement. Power dissipation calculation. |
   | Protection devices | TVS, ESD, varistors mapped to the interfaces they protect. |
   | Crystal circuits | Crystals with load capacitor verification. |
   | Bridge circuits | H-bridge and 3-phase motor drive topologies. |
   | Bus detection | I2C (with pull-up resistance check), SPI, UART, CAN, RS-485 (with termination check). |
   | Validation detectors | Pull-up/pull-down presence, cross-domain voltage mismatch, protocol electrical validation, power sequencing dependency graph, LED resistor sizing, feedback network stability. |
   | Audit detectors | Sourcing gate (MPN/BOM coverage), datasheet coverage, rail-source audit, label-alias audit, power-pin DC-path audit. |
   | Domain detectors | RF chains, Ethernet, HDMI, memory, BMS, battery chargers, motor drivers, ADC, reset/supervisor, clock distribution, display/touch, sensors, level shifters, audio, LED drivers, RTC, thermocouple/RTD, power sequencing, debug interfaces, ESD coverage, wireless modules, transformer SMPS feedback, I2C address conflicts, energy harvesting, PWM LED dimming, headphone jacks, and more. |

   Detectors run in dependency order — voltage dividers are found first, then regulators reference those dividers for feedback network analysis. Each detector is documented in [methodology_schematic.md](skills/kicad/scripts/methodology_schematic.md).

6. **Outputs structured JSON.** Typically 60–220KB depending on board complexity. Every section is self-contained and machine-readable.

The PCB analyzer (`analyze_pcb.py`) and Gerber analyzer (`analyze_gerbers.py`) follow the same pattern for layout and fabrication files. Full methodology docs: [PCB](skills/kicad/scripts/methodology_pcb.md), [Gerbers](skills/kicad/scripts/methodology_gerbers.md).

### Step 2: Gather datasheets

The agent downloads datasheets for every component with an MPN, using the distributor API skills (DigiKey, Mouser, LCSC, element14). PDFs are stored locally in a `datasheets/` directory with a `manifest.json`. The **`datasheets` skill** then extracts structured specs from those PDFs into per-MPN JSON under `datasheets/extracted/`. v1.4 introduced a schema-driven typed extraction layer (`DatasheetFacts`, `SpecValue` with `min/typ/max/unit/condition/evidence`, six part categories, three-dimension quality scoring); the v1.3 dict-shaped format is still readable for legacy caches. See the [Datasheet Extraction Guide](datasheet-extraction.md) for the full pipeline.

This step is critical. Without datasheets, a review can only check that a design is *self-consistent* (the schematic agrees with itself). With datasheets, it can check that the design is *correct* (component values match manufacturer recommendations, absolute maximum ratings aren't exceeded, reference circuits are followed). Every finding carries a confidence label (`deterministic`, `heuristic`, `datasheet-backed`) so the reviewer can see at a glance which claims are grounded in the manufacturer's spec. v1.4 adds per-value trust gating: detectors call `best(specs, min_confidence="medium")` to filter by evidence confidence, distinguishing "field not extracted" from "extracted but below trust gate" from "trusted value present."

### Step 3: Cross-reference and review

The agent reads the analysis JSON and datasheets together, then:

- **Verifies the analysis data.** Spot-checks component counts against the raw schematic, traces critical nets pin-by-pin, confirms the analyzer's pin-to-net mapping for ICs.
- **Validates against datasheets.** Checks feedback divider Vout against the regulator's actual Vref. Verifies filter cutoff frequencies match the application note. Confirms current sense resistor power dissipation is within rating.
- **Cross-references schematic to PCB.** Component counts match? All nets routed? Thermal vias adequate for power components? Decoupling caps placed close to IC supply pins?
- **Checks fabrication files.** Gerber layers complete? Drill files present? Coordinate alignment consistent? Zip archives up-to-date?
- **Writes the review.** Structured report with findings categorized by severity (`error` / `warning` / `info`), power tree visualization, signal analysis walkthrough, and DFM assessment.

### Step 4: You review the review

This is the most important step. The output is a starting point for engineering judgment, not a replacement for it. Every calculation is shown. Every datasheet reference is cited. Every finding includes enough context to verify or dismiss it.

### Optional: Deep Review pass (v2.0)

v2.0 adds an optional **Deep Review pass** that performs per-IC LLM datasheet comparison — checking each component's actual usage against its datasheet specifications and emitting durable, evidence-linked findings in `analysis/deep_review.json`. The pass is non-destructive: Layer 1 analyzer findings are never modified, and stripping `llm_*` fields recovers the deterministic baseline. An optional `design_context` subagent can supply schematic and design-intent context as input. See `skills/kicad/references/deep-review.md` and `skills/kicad/review/README.md` for the workflow.

## What the analysis catches

Real examples from production design reviews:

| Category | Example finding |
|----------|----------------|
| **Power** | Feedback divider computes to 14.95V on a rail named +12V — Vref lookup says 1.0V for MAX17760, but verify against your specific variant's datasheet |
| **Thermal** | QFN exposed pad has 14 thermal vias (IPC-7093 recommends 16 for this pad area). Will run hot under sustained load. |
| **Protection** | USB connector has no ESD protection. VBUS has TVS but D+/D- are unprotected. |
| **Digital** | I2C pull-ups are 10kΩ to 3.3V. At 400kHz with 20pF bus capacitance, rise time is ~200ns — marginal for Fast-mode (spec: 300ns max). At higher capacitance, this fails. |
| **Analog** | Op-amp configured as non-inverting with gain of 11x (100k/10k). But output drives a 1kΩ load — output current is 3.3mA at full scale. Check datasheet for output drive capability. |
| **Manufacturing** | 0402 resistors on opposite sides of the same pad have unequal thermal relief — tombstoning risk during reflow. |
| **Gerbers** | Zip archive is 3 days older than loose gerber files — the zip doesn't reflect your latest design changes. |

## What it doesn't catch

Being honest about limitations is more useful than pretending they don't exist.

**Things the analyzer cannot detect:**

- **Wrong component choice.** If you picked an LDO that can't handle the dropout voltage in your application, or a MOSFET with insufficient Vgs threshold for your gate drive — the analyzer sees the circuit topology but doesn't know your operating conditions. The agent will flag when datasheet parameters look marginal, but it requires the right datasheet and explicit operating specs.

- **Timing and dynamic behavior.** The analysis is primarily static — it sees component values and connectivity, not waveforms. It can compute filter cutoff frequencies and time constants, trace enable chains and power_good sequencing dependencies, and the **spice** skill can simulate detected subcircuits to verify calculated values. But full transient response, oscillation stability, and signal integrity analysis require dedicated SI/PI tools.

- **Layout parasitics.** The PCB analyzer measures trace widths and via counts, and the `--proximity` flag does spatial analysis to flag signal nets running close together (crosstalk risk). When both schematic and PCB data are available, SPICE simulations can inject extracted PCB trace parasitics. But full impedance matching and return path analysis require dedicated SI tools.

- **Full EMC compliance.** The **emc** skill now performs pre-compliance risk analysis (44 rule checks, PDN impedance, switching harmonics, diff pair skew — see the [EMC guide](emc-precompliance.md)), but it's analytical, not a substitute for pre-compliance testing with actual test equipment.

- **Mechanical fit.** Board outline dimensions are extracted, but interference with enclosures, connector mating height, thermal clearance to adjacent boards — these require 3D mechanical context the analyzer doesn't have.

**Things the analyzer might get wrong:**

- **Regulator Vout estimates.** The Vref lookup table covers ~60 part families, each verified against the manufacturer's datasheet. If your regulator isn't in it, the analyzer falls back to a heuristic sweep that's right most of the time but not always. The `vref_source` field in the output tells you which method was used — `"lookup"` means datasheet-verified, `"heuristic"` means check it yourself.

- **Legacy KiCad 5 designs.** The legacy `.sch` format stores pin positions in separate `.lib` files. The analyzer parses cache libraries (`-cache.lib`) and project `.lib` files automatically, with built-in fallbacks for common standard library symbols (R, C, L, D, LED, transistors). Pin coverage is typically 92–100% depending on which `.lib` files are available in the repo. Components whose `.lib` files are missing (e.g., standard KiCad system libraries not committed to the project) will lack pin data and won't participate in signal analysis.

- **Unusual symbol conventions.** If a symbol uses non-standard pin names or a reference designator prefix the classifier doesn't recognize, the component may be misclassified. The classifier handles hundreds of conventions, but edge cases exist.

- **Pin-to-net mapping near sheet borders.** Hierarchical sheet pins can be tricky when labels don't quite align with wire endpoints. The analyzer uses tolerance-based matching that works for 99%+ of real designs, but complex hierarchical routing occasionally produces a missed connection. The review process includes explicit net tracing to catch these.

## Addressing common concerns

### "AI hallucinates. Why would I trust it with my PCB?"

Valid concern. Here's how this system is different from "paste your schematic into ChatGPT":

1. **The analysis data is deterministic.** The Python scripts produce the same JSON output every time for the same input. There's no model in the extraction loop. You can run the scripts, read the JSON, and verify any fact independently.

2. **The reasoning is grounded in data.** It's not generating circuit analysis from training data — it's reading your specific component list, your specific net connections, your specific trace widths, and cross-referencing against your specific datasheets. When it says "R3 and R4 form a voltage divider with ratio 0.234," that came from parsing the actual resistor values on the actual net.

3. **The review is verifiable.** Every finding includes the path to verify it — which components, which nets, which datasheet page. If the agent says your thermal vias are insufficient, it tells you the via count, the pad area, and the IPC recommendation. You can check.

4. **Hallucination risk is bounded by the data.** The agent can misinterpret analyzer data or draw wrong conclusions from datasheets — the same mistakes a human reviewer can make. But it can't invent components that aren't in your schematic or fabricate net connections that don't exist, because the analysis JSON constrains what it's working with.

Is it perfect? No. That's why step 4 is "you review the review." But it's a lot better than skipping the review entirely — which is what happens on most projects when time runs out before tapeout.

### "This replaces engineers with AI"

No. This replaces *not doing a design review* with doing one.

Most hardware teams don't have a formal peer review process for every board revision. The senior engineer is busy, the deadline is Thursday, and the board goes to fab with a quick eyeball check. Two weeks later it comes back and the regulator output is wrong because nobody noticed the feedback resistor values were swapped during a late-night edit.

This tool does the tedious, systematic part — trace every net, check every value, verify every pin mapping, cross-reference every datasheet. It produces a structured report that a human engineer reviews. The human makes the engineering decisions. The tool just makes sure nothing gets missed.

If you're a senior EE who already does thorough design reviews, this saves you time. If you're a solo engineer or a small team without a dedicated reviewer, this gives you a second pair of eyes you didn't have before.

### "I don't want AI touching my design files"

It doesn't. The analysis scripts *read* your KiCad files — they never modify them. The BOM management scripts (`edit_properties.py`, `sync_datasheet_urls.py`) write symbol properties back (distributor part numbers, MPNs, datasheet URLs) when you run them; both take `--dry-run` to preview the change and `--backup` to keep a `.bak` copy. The agent itself has no ability to modify your KiCad files directly.

Your design files, your git repo, your control.

### "How do I know the analysis is correct?"

Run it yourself and check:

```bash
# Run the analyzer
python3 skills/kicad/scripts/analyze_schematic.py your_board.kicad_sch --output analysis.json

# Check component count
python3 -c "import json; d=json.load(open('analysis.json')); print(f'Components: {d[\"statistics\"][\"total_components\"]}')"

# Look at detected voltage dividers (findings[] with detector='detect_voltage_dividers')
python3 -c "import json; d=json.load(open('analysis.json')); [print(f'{f[\"components\"][0]}: {f[\"summary\"]}') for f in d.get('findings',[]) if f.get('detector') == 'detect_voltage_dividers']"

# Trace a specific net
python3 -c "import json; d=json.load(open('analysis.json')); net=d['nets'].get('+3V3',{}); print(f'Pins on +3V3: {len(net.get(\"pins\",[]))}'); [print(f'  {p[\"component\"]}.{p[\"pin_number\"]} ({p[\"pin_name\"]})') for p in net.get('pins',[])]"
```

The JSON is the truth. Everything the agent says should trace back to it. If it doesn't, that's an AI reasoning error — flag it.

### "Open source analysis scripts are a liability — what if they have bugs?"

The scripts are tested against a [dedicated test harness](https://github.com/aklofas/kicad-happy-testharness) containing 5,829 open-source KiCad projects from GitHub, Codeberg, and GitLab, spanning KiCad versions 5 through 10. That's single-sheet hobby boards, multi-sheet industrial controllers, complex hierarchical designs with repeated sub-sheets, and everything in between. All parse and produce output without errors. Detection accuracy is harder to quantify — you can't count what you didn't catch — which is why this document exists and the test harness uses three layers of regression testing (see below).

More importantly, the scripts are designed so that bugs produce *missing data*, not *wrong data*. If a detector fails to recognize a circuit pattern, you get a gap in the analysis (the reviewer's blind spot). If a detector misidentifies a circuit, it reports incorrect facts (the reviewer is misled). The detection logic is tuned to avoid the second failure mode — it's better to miss a voltage divider than to report one that doesn't exist.

Every detector output includes the raw component values, net names, and pin connections so you can verify the conclusion independently. The scripts don't just say "there's a problem" — they show you exactly what they found and how they interpreted it.

The methodology documentation ([schematic](skills/kicad/scripts/methodology_schematic.md), [PCB](skills/kicad/scripts/methodology_pcb.md), [gerbers](skills/kicad/scripts/methodology_gerbers.md)) explains every algorithm, heuristic, and trade-off in detail. If you find a bug, you can trace it to the exact detector function and fix it.

## The full workflow

```
1. PARSE                    2. EXTRACT                  3. DETECT
┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│ .kicad_sch   │──parse──▶ │ Components   │──analyze─▶│ Regulators   │
│ .kicad_pcb   │           │ Nets         │           │ Filters      │
│ gerbers/     │           │ Footprints   │           │ Protection   │
│              │           │ Tracks/Vias  │           │ Bus topology │
│              │           │ Zones        │           │ DFM scores   │
│              │           │ Layers       │           │ Thermal      │
└──────────────┘           └──────────────┘           └──────┬───────┘
                                                             │
                           4. GROUND                         │
                           ┌──────────────┐                  │
                           │ Datasheets   │──────────────────┤
                           │ (per MPN)    │                  │
                           └──────────────┘                  │
                                                             ▼
                           5. REVIEW                   6. DECIDE
                           ┌──────────────┐           ┌──────────────┐
                           │ Agent reads  │           │ Engineer     │
                           │ JSON + PDFs  │──report─▶ │ reviews      │
                           │ Cross-refs   │           │ verifies     │
                           │ Validates    │           │ decides      │
                           └──────────────┘           └──────────────┘
```

Steps 1–4 are deterministic and reproducible. Step 5 is AI-assisted reasoning. Step 6 is human judgment. The engineer is always the final authority.

## How the analyzers are tested

The [kicad-happy test harness](https://github.com/aklofas/kicad-happy-testharness) validates every analyzer against 5,800+ open-source KiCad projects organized into 25+ categories — microcontrollers, motor controllers, power supplies, RF, audio, sensors, FPGA, retro computing, aerospace, and more. The corpus is pinned by commit hash for reproducibility, and the test harness never stores the projects themselves — just URLs and hashes. You clone on demand.

### Three layers of regression testing

The harness uses three complementary layers, each catching things the others miss:

**Layer 1: Baselines.** A baseline is a snapshot of all analyzer outputs at a point in time. After making changes to the analyzers, you run the corpus again and diff against the baseline. This catches output drift — did component counts change? Did a signal detector start finding fewer matches? Did a new edge case cause a crash? Compact baseline manifests are checked into git so any machine can compare.

**Layer 2: Assertions.** Assertions are machine-checkable facts about specific files — "cynthion aux_port.kicad_sch has 29–37 components," "hackrf-one has decoupling analysis detected," "this board has at least 5 capacitors." They live in `data/assertions/` and provide permanent regression protection. If an analyzer change breaks a known-good result, the assertion fails immediately. Assertions support operators like `range`, `min_count`, `exists`, `contains_match`, and more.

**Layer 3: LLM review.** Review packets pair source KiCad files with their analyzer output, and an LLM independently verifies the analysis quality — checking whether detected subcircuits make sense, whether component classifications are correct, whether the signal analysis missed anything obvious. Findings from these reviews get tracked and, once confirmed, promoted into permanent assertions (layer 2). This is how the assertion set grows over time.

### What gets exercised

- **All analyzers** (schematic, PCB, Gerber, EMC, thermal) against every discovered file in the corpus
- **SPICE simulation** — 30,000+ subcircuit simulations across 17 types, with cross-validation
- **EMC pre-compliance** — 141,000+ findings across 15 rule categories and 6 standards
- **MPN extraction** from analyzer outputs, validated against DigiKey, Mouser, LCSC, and element14 APIs
- **Datasheet download pipeline** across all four distributors — testing API auth, PDF retrieval, and MPN matching
- **BOM manager pipeline** end-to-end — from schematic analysis through distributor search to order file generation
- **Edge cases** — legacy KiCad 5 `.sch` format, multi-instance hierarchical sheets, unusual footprints, mixed file formats in the same repo

### The development cycle

1. Make changes to the analyzer scripts
2. Run the analyzers against the corpus
3. Diff against the baseline — review what changed
4. Run assertions — catch any regressions
5. Generate review packets for changed files — have the LLM verify the changes make sense
6. Promote confirmed findings to assertions
7. Create a new baseline

This means every analyzer change is validated against real hardware designs before it ships — not toy examples or hand-crafted test cases, but the actual KiCad projects that people are building.

## Further reading

- [Schematic analysis methodology](skills/kicad/scripts/methodology_schematic.md) — parsing pipeline, net building, 40 signal and domain detectors
- [PCB layout analysis methodology](skills/kicad/scripts/methodology_pcb.md) — extraction, connectivity, DFM scoring, thermal analysis
- [Gerber analysis methodology](skills/kicad/scripts/methodology_gerbers.md) — RS-274X/Excellon parsing, layer identification, completeness checks
- [Example design review report (robot controller)](example-report-1.md) — full output from a real motor-controller board
- [Example design review report (GNSSDO)](example-report-2.md) — full output from a real GNSS disciplined oscillator board
- [Analysis scripts README](skills/kicad/scripts/README.md) — developer reference for the Python scripts

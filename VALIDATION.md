# Validation Summary

This document describes how kicad-happy is tested and validated. Every change to the analysis engine is verified against a corpus of real-world KiCad projects before release.

*Auto-generated on 2026-11-15 by `generate_validation_md.py`.*

## Why this matters

Hardware design review tools must be trustworthy. A false negative (missed bug) can cost a board respin ($5K-$50K). A false positive (phantom warning) erodes trust until engineers ignore the tool entirely. kicad-happy addresses both through large-scale automated validation that no human reviewer could replicate.

## Test corpus

The [test harness](https://github.com/aklofas/kicad-happy-testharness) contains 5,858 open-source KiCad projects — the kind of designs real engineers actually build.

**Corpus diversity:**

| Dimension | Coverage |
|-----------|----------|
| Project types | Hobby boards, production hardware, motor controllers, RF frontends, battery management systems, IoT devices, audio amplifiers, power supplies, sensor boards, dev kits |
| KiCad versions | KiCad 5, KiCad 6, KiCad 7, KiCad 8, KiCad 9, KiCad 10 |
| File formats | `.kicad_sch` (S-expression), legacy `.sch` (EESchema), `.kicad_pcb` |
| Design complexity | Single-sheet through multi-sheet hierarchical, 2-layer through 6-layer |
| Component counts | 3 to 500+ components per project |
| Net complexity | Simple power supplies to multi-bus digital designs (I2C, SPI, UART, CAN, USB, Ethernet, HDMI) |

**KiCad version distribution:**

| Version | Repos |
|---------|------:|
| KiCad 5 | 2,207 |
| KiCad 6 | 1 |
| KiCad 7 | 9 |
| KiCad 8 | 1,225 |
| KiCad 9 | 1,364 |
| KiCad 10 | 40 |

A repo is counted once for each KiCad version string found in its files, so the 381 repos that hold files from more than one version appear in more than one row (KiCad 8.0 and 8.99 both count under KiCad 8); the 1,437 repos whose version the harness catalog records as unknown, empty or older than KiCad 5 are not counted.

**Category distribution:**

| Category | Repos |
|----------|------:|
| Miscellaneous KiCad projects | 1,810 |
| Keyboards | 449 |
| Synthesizers / audio | 324 |
| Motor controllers / robotics | 315 |
| LED / display | 304 |
| Arduino recreations | 295 |
| ESP32 | 294 |
| Networking / radio / SDR | 254 |
| Sensor boards / IoT | 250 |
| Retro computing | 235 |
| USB / interface adapters | 214 |
| Power / battery | 207 |
| RP2040 / Raspberry Pi | 192 |
| STM32 | 179 |
| ADC / DAC / measurement | 110 |
| *(other categories)* | 426 |

The corpus is sourced from public GitHub repositories. It is not curated for "easy" designs — it includes incomplete projects, unusual topologies, non-standard conventions, and designs with real bugs.

## What gets tested

Every analysis script runs against every applicable file in the corpus. Units that time out or crash on both the baseline and the candidate are carried as accepted baseline debt in the harness ledger (`reference/baseline_debts/`), never silently dropped.

### Crash testing

| Analyzer | Output files |
|----------|-------------|
| Schematic (`analyze_schematic.py`) | 36,463 |
| PCB (`analyze_pcb.py`) | 18,722 |
| Gerber (`analyze_gerbers.py`) | 5,505 |
| EMC (`analyze_emc.py`) | 36,544 |
| SPICE (`simulate_subcircuits.py`) | 36,544 |

The counts are output files present in the corpus tree. A new unhandled exception on any file is a release blocker; the corpus gate's `candidate_failures` count is the measured value.

### Regression assertions

Hard assertions on known-good output values. If a previously correct result changes, the assertion fails and the change must be investigated.

*Measured via `regression/run_checks.py --json` at the v3.0.2 corpus regen (`365aea9`): 2,714,810 passed / 0 failed / 0 errors out of 2,714,810 (100.0000 %).*

| Category | Assertion count | Pass rate |
|----------|----------------|-----------|
| STRUCT | 1,392,645 | 100.0000 % |
| SEED | 1,319,300 | 100.0000 % |
| FND | 2,629 | 100.0000 % |
| BUGFIX | 236 | 100.0000 % |
| **Total** | **2,714,810** | **100.0000 %** |

Assertions are seeded from validated output and checked on every run. When analyzer logic changes intentionally (new fields, corrected calculations), affected assertions are re-seeded after manual verification.

### Layer 1 regression gate (pre-tag requirement)

Before any release is tagged, the harness runs the candidate over the full corpus and diffs every analyzer envelope unit by unit against a baseline: the previous release, or, for a release built in gated waves, the previous accepted candidate of each wave. Every unit that moves (FAIL, Disappeared, Downgrades, NewUnknown) must be attributed to a budget class pre-registered in the change's review record; unexplained movement, including a severity downgrade no class covers, fails the gate. The run below is the v3.0.2 release gate, `4c2a0d6` → `365aea9` against `4c2a0d6` (the v3.0.1 release base), gated once over the whole release range. The range was built in waves (11a, 11b-1, 11b-2, 11c, 11d, 11e), each gated against the previous accepted candidate and accepted before the next began, over a gap-free chain `4c2a0d6` (released as `7d9d4d9f`: CI pin, CHANGELOG, README, VALIDATION.md) → `5510006` (pushed as `727d0ab3`: two product tests and the CI pin) → `f53d107` (pushed as `0f2deade`: CI pin only) → `6138b12` (pushed as `046985ac`: CI pin only) → `db55167` (pushed as `be070c53`: CI pin only) → `206403e` → `365aea9` (pushed as `bce60182`: CI pin only). Waves 11a and 11d changed no analyzer output; Waves 11b-1, 11b-2, 11c and 11e were output-changing, and a per-unit judge attributed every moved unit to a declared class or a filed finding. In the run below, a unit the range moved is claimed when a wave moved it and that wave's judge claimed it; the `4c2a0d6` → `206403e` part was compared again against the live `206403e` tree (the same moved set), and the candidate tree is identical to the Wave 11e candidate tree unit for unit. Records: harness `results/v302_range_gate{,_fc,_aux,_do}/`, the wave records `results/v302_w11*_gate{,_fc,_aux,_do}/` and `results/v302_h1_gate{,_fc,_aux,_do}/`, and the per-wave verdict entries in the coordination log.

Latest run: section `v302_range`, 170,022 analyzer-runs. Verdict: **CLEAN — FULL standard 149,633 unit pairs: 36,299 moved (schematic 16,643, cross-analysis 16,262, PCB 2,025, EMC 864, thermal 431, Gerber 74), 2,851,540 field deltas, every moved unit claimed by the wave that moved it (11b-1 11,220, 11b-2 18,144, 11c 3,311, 11e 420, more than one wave 3,204), 0 unexplained; full-chain 22,028 unit pairs: 4,271 moved, 0 unexplained; 0 candidate failures; SPICE-offline 933 / 8,677 reports moved, all attributed (816 follow a moved schematic, 117 op-amp / transistor bench changes); text oracle exactly the 287 artefacts the waves declared; `--schema` changed for `analyze_pcb` only (11b-2); distributor-offline the 7 artefacts 11b-1 declared; Gerber `--full` 74 units moved, the 11b-2 set**.

| Outcome | Count | Attribution |
|---------|------:|-------------|
| PASS | 142,785 | |
| FAIL | 6,027 | attributed to `wave-11b-1` (3,874 units), `wave-11b-2` (1,039 units), `wave-11c` (1,866 units), `wave-11e` (1,239 units) |
| Disappeared | 18,519 | 18,519 findings in 5,961 units, attributed to `wave-11b-1` (3,810 units), `wave-11b-2` (1,039 units), `wave-11c` (1,852 units), `wave-11e` (1,239 units) |
| Downgrades | 191 | 191 findings in 165 units, attributed to `wave-11b-1` (141 units), `wave-11b-2` (18 units), `wave-11c` (63 units), `wave-11e` (24 units) |
| Upgrades | 92 | 92 findings in 37 units, attributed to `wave-11b-1` (30 units), `wave-11b-2` (6 units), `wave-11c` (10 units), `wave-11e` (1 unit) |
| NewKnown | 9 | 9 findings in 9 units, attributed to `wave-11b-1` (9 units), `wave-11c` (4 units) |
| NewUpgraded | 9 | 9 findings in 5 units, attributed to `wave-11b-1` (5 units), `wave-11c` (3 units), `wave-11e` (1 unit) |
| NewUnknown | 10,111 | 10,111 findings in 3,357 units, attributed to `wave-11b-1` (2,167 units), `wave-11b-2` (391 units), `wave-11c` (1,081 units), `wave-11e` (1,275 units) |
| WARN | 821 | attributed to `wave-11b-1` (445 units), `wave-11b-2` (192 units), `wave-11c` (285 units), `wave-11e` (39 units) |
| SKIP | 20,389 | 4 both failed, 6 dependency missing, 20,379 not applicable, 10 in the baseline ledger |

*A gate is CLEAN when every unit counted under `FAIL`, `Disappeared`, `Downgrades` or `NewUnknown` is attributed to a budget class pre-registered in the adjudication record (a zero-delta gate has none to attribute); the Attribution column names the classes that claimed each counter's units. A unit can be counted under several outcomes. `NewKnown`/`NewUpgraded` are intentional new findings; `SKIP` units have no comparable baseline.*

## Signal detector coverage

71 active schematic detectors verified against the corpus:

| Detector | Repos with hits |
|----------|----------------|
| audit_lifecycle_skipped | 5,836 |
| audit_esd_protection | 5,050 |
| detect_design_observations | 5,021 |
| audit_rail_sources | 4,523 |
| detect_decoupling | 4,045 |
| audit_datasheet_coverage | 4,018 |
| audit_sourcing_gate | 3,952 |
| audit_led_circuits | 3,021 |
| detect_power_regulators | 3,005 |
| audit_connector_ground_distribution | 2,848 |
| analyze_connectivity | 2,624 |
| validate_pullups | 2,615 |
| detect_rc_filters | 2,510 |
| detect_voltage_dividers | 2,321 |
| detect_transistor_circuits | 2,216 |
| detect_crystal_circuits | 1,850 |
| detect_protection_devices | 1,697 |
| detect_solder_jumpers | 1,396 |
| analyze_usb_compliance | 1,291 |
| audit_power_pin_dc_paths | 1,286 |
| suggest_certifications | 1,256 |
| validate_power_sequencing | 1,123 |
| detect_wireless_modules | 1,046 |
| detect_debug_interfaces | 1,041 |
| detect_label_aliases | 1,031 |
| detect_lc_filters | 818 |
| validate_voltage_levels | 818 |
| validate_usb_bus | 748 |
| detect_opamp_circuits | 745 |
| validate_led_resistors | 499 |
| detect_memory_interfaces | 451 |
| detect_key_matrices | 424 |
| detect_level_shifters | 422 |
| detect_led_drivers | 396 |
| validate_i2c_bus | 389 |
| detect_sensor_interfaces | 373 |
| detect_addressable_leds | 366 |
| detect_pwm_led_dimming | 361 |
| analyze_voltage_derating | 326 |
| detect_buzzer_speakers | 309 |
| detect_adc_circuits | 286 |
| detect_reset_supervisors | 281 |
| detect_shorted_two_pin_components | 276 |
| detect_battery_chargers | 274 |
| detect_motor_drivers | 270 |
| detect_rf_matching | 246 |
| detect_audio_circuits | 226 |
| detect_power_path | 200 |
| detect_clock_distribution | 199 |
| detect_current_sense | 198 |
| detect_isolation_barriers | 148 |
| detect_bridge_circuits | 140 |
| validate_can_bus | 136 |
| detect_rf_chains | 123 |
| detect_rtc_circuits | 121 |
| detect_ethernet_interfaces | 119 |
| validate_spi_bus | 116 |
| validate_feedback_stability | 101 |
| detect_led_driver_ics | 84 |
| detect_hdmi_dvi_interfaces | 80 |
| detect_headphone_jack | 79 |
| detect_energy_harvesting | 61 |
| detect_integrated_ldos | 58 |
| detect_display_interfaces | 55 |
| detect_thermocouple_rtd | 48 |
| validate_crystal_load_caps | 48 |
| audit_dnp_rate | 39 |
| detect_bms_systems | 25 |
| detect_i2c_address_conflicts | 20 |
| detect_transformer_feedback | 20 |
| detect_lvds_interfaces | 15 |

## How to reproduce

Anyone can reproduce the validation:

```bash
# 1. Clone the harness
git clone https://github.com/aklofas/kicad-happy-testharness.git
cd kicad-happy-testharness

# 2. Clone test repos
python3 checkout.py

# 3. Run analyzers (auto-parallelizes across all CPU cores)
python3 run/run_schematic.py --resume
python3 run/run_pcb.py --resume
python3 run/run_emc.py --resume

# 4. Run regression assertions
python3 regression/run_checks.py
```

The harness requires Python 3.10+ and a checkout of the corpus repos. ngspice is optional but recommended for SPICE assertions. Use `--cross-section smoke` for a quick 20-repo validation.

## Issue tracking

All analyzer bugs found during validation are tracked with sequential IDs:

- `KH-001` through `KH-1108`: analyzer issues (1062 filed, 758 closed, 304 open: 4 HIGH, 80 MEDIUM, 220 LOW; LOW-MEDIUM counts as MEDIUM)
- `TH-001` through `TH-113`: harness infrastructure issues (108 filed, 106 closed, 2 open: 2 LOW)

171 of the 758 closed analyzer issues have a bugfix regression guard (175 guard entries in `regression/bugfix_registry.json`): an assertion that fails if the bug returns.

## Numbers at a glance

| Metric | Value |
|--------|-------|
| Repos in corpus | 5,858 |
| Schematic files | 36,463 |
| PCB files | 18,722 |
| Gerber directories | 5,505 |
| EMC analyses | 36,544 |
| SPICE analyzer runs | 36,544 |
| Components parsed | 1,304,449 |
| Nets traced | 1,882,743 |
| Regression assertions | 2,714,810 at 100.0000 % |
| Bugfix guards | 175 |
| Closed issues | 758 analyzer + 106 harness |
| Open issues | 304 analyzer (4 HIGH, 80 MEDIUM, 220 LOW) + 2 harness (2 LOW) |
| Schematic detectors | 71 |

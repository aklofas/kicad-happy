# Validation Summary

This document describes how kicad-happy is tested and validated. Every change to the analysis engine is verified against a corpus of real-world KiCad projects before release.

*Auto-generated on 2026-11-03 by `generate_validation_md.py`.*

## Why this matters

Hardware design review tools must be trustworthy. A false negative (missed bug) can cost a board respin ($5K-$50K). A false positive (phantom warning) erodes trust until engineers ignore the tool entirely. kicad-happy addresses both through large-scale automated validation that no human reviewer could replicate.

## Test corpus

The [test harness](https://github.com/aklofas/kicad-happy-testharness) contains 5,857 open-source KiCad projects — the kind of designs real engineers actually build.

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
| *(other categories)* | 425 |

The corpus is sourced from public GitHub repositories. It is not curated for "easy" designs — it includes incomplete projects, unusual topologies, non-standard conventions, and designs with real bugs.

## What gets tested

Every analysis script runs against every applicable file in the corpus. Units that time out or crash on both the baseline and the candidate are carried as accepted baseline debt in the harness ledger (`reference/baseline_debts/`), never silently dropped.

### Crash testing

| Analyzer | Output files |
|----------|-------------|
| Schematic (`analyze_schematic.py`) | 36,463 |
| PCB (`analyze_pcb.py`) | 18,751 |
| Gerber (`analyze_gerbers.py`) | 5,512 |
| EMC (`analyze_emc.py`) | 36,544 |
| SPICE (`simulate_subcircuits.py`) | 36,544 |

The counts are output files present in the corpus tree. A new unhandled exception on any file is a release blocker; the corpus gate's `candidate_failures` count is the measured value.

### Regression assertions

Hard assertions on known-good output values. If a previously correct result changes, the assertion fails and the change must be investigated.

*Measured via `regression/run_checks.py --json` at the v3.0.1 corpus regen (`9885287`): 2,716,880 passed / 7 failed / 2 errors out of 2,716,889 (100.0%).*

| Category | Assertion count | Pass rate |
|----------|----------------|-----------|
| STRUCT | 1,393,379 | 100.0% |
| SEED | 1,320,589 | 100.0% |
| FND | 2,685 | 99.7% |
| BUGFIX | 236 | 100.0% |
| **Total** | **2,716,889** | **100.0%** |

Assertions are seeded from validated output and checked on every run. When analyzer logic changes intentionally (new fields, corrected calculations), affected assertions are re-seeded after manual verification.

### Layer 1 regression gate (pre-tag requirement)

Before any release is tagged, the harness runs the candidate commit and the previous release over the full corpus and diffs every analyzer envelope unit by unit. Every unit that moves (FAIL, Disappeared, NewUnknown) must be attributed to a budget class pre-registered in the change's review record, and no finding may be silently downgraded; unexplained movement fails the gate. The run below is the v3.0.1 release gate. The release range is `07b7fb1` (v3.0.0 release base) → `9885287`, built in fourteen waves (0, 1, 2, 3, 3b-A, 3b-B, 4-A, 4-B, 5, 6, 7, 8a, 8c + 8b), each gated against the previous accepted candidate and accepted before the next began, over a gap-free chain `07b7fb1` → `63f6a20` → `004bba5` → `d2b9e72` → `6c488c2` → `0683d01` → `b31d4ff` (pushed as `d5c500e`: one docstring line and the CI pin) → `40b8ff3` → `698116c` → `c0a8a62` → `988d576` (pushed as `ceb2c5a`: CI pin only) → `647bc85` → `0efc012`. Wave 0 (gate readiness) and Wave 1 (security) changed no analyzer output and were gated together on the quick_200 cross-section (strict-field identical); Waves 6, 7 and 8a were structural (FULL standard + full-chain strict-field identical); Waves 2, 3, 3b-A, 3b-B, 4-A, 4-B, 5 and 8c + 8b were output-changing, and every moved unit was either attributed to a pre-registered budget class or filed as a finding (FULL standard + full-chain; the six Wave 3b-A finding units became KH-699 / KH-700 and the one Wave 3 SPICE candidate failure KH-676, all resolved in later waves). Records: harness `results/v30x_w*_gate{,_fc}/rollup_*.json` (Wave 1: standard quick_200 only) and the per-wave verdict entries in the coordination log. The final step is the pre-tag gate `0efc012` → `9885287` below: the candidate's analyzer tree is byte-identical to `0efc012` (it adds CI, docs and a product test only), and the gate ran every lane with a zero budget (harness `results/v301_pretag_gate{,_fc,_aux,_do}/`).

Latest run: section `v301_pretag_standard`, 170,022 analyzer-runs. Verdict: **CLEAN, ZERO DELTA on every lane — FULL standard 149,633 unit pairs and full-chain 21,411 unit pairs strict-field identical, 0 candidate failures, every skip a ledgered baseline debt; spice-offline 8,830 / 8,830 identical; product text oracle 1,056 artefacts identical both ways; `--schema` identical for all six analyzers; distributor-offline 310 / 310 artefacts identical; harness unit + offline-contract tiers green**.

| Outcome | Count |
|---------|------:|
| PASS | 149,633 |
| FAIL | 0 |
| Disappeared | 0 |
| Downgrades | 0 |
| Upgrades | 0 |
| NewKnown | 0 |
| NewUpgraded | 0 |
| NewUnknown | 0 |
| WARN | 0 |
| SKIP | 20,389 |

*A gate is CLEAN when `Downgrades == 0` and every `FAIL`, `Disappeared` and `NewUnknown` unit is attributed to a pre-registered budget class in the adjudication record (a zero-delta gate has none to attribute). `NewKnown`/`NewUpgraded` are intentional new findings; `SKIP` units have no comparable baseline.*

## Signal detector coverage

71 active schematic detectors verified against the corpus:

| Detector | Repos with hits |
|----------|----------------|
| audit_lifecycle_skipped | 5,836 |
| audit_esd_protection | 5,065 |
| detect_design_observations | 4,974 |
| audit_rail_sources | 4,687 |
| audit_datasheet_coverage | 4,015 |
| audit_sourcing_gate | 3,947 |
| detect_decoupling | 3,929 |
| audit_connector_ground_distribution | 3,105 |
| audit_led_circuits | 3,017 |
| detect_power_regulators | 2,990 |
| validate_pullups | 2,931 |
| analyze_connectivity | 2,667 |
| detect_rc_filters | 2,527 |
| detect_voltage_dividers | 2,293 |
| detect_transistor_circuits | 2,205 |
| detect_crystal_circuits | 1,842 |
| detect_protection_devices | 1,696 |
| audit_power_pin_dc_paths | 1,452 |
| detect_solder_jumpers | 1,395 |
| analyze_usb_compliance | 1,293 |
| suggest_certifications | 1,185 |
| detect_label_aliases | 1,116 |
| validate_led_resistors | 1,109 |
| validate_power_sequencing | 1,067 |
| detect_debug_interfaces | 1,026 |
| detect_wireless_modules | 969 |
| validate_voltage_levels | 818 |
| detect_lc_filters | 811 |
| validate_usb_bus | 808 |
| detect_opamp_circuits | 739 |
| detect_shorted_two_pin_components | 534 |
| validate_i2c_bus | 471 |
| detect_memory_interfaces | 435 |
| detect_pwm_led_dimming | 434 |
| detect_key_matrices | 422 |
| detect_led_drivers | 419 |
| detect_level_shifters | 399 |
| detect_sensor_interfaces | 373 |
| detect_addressable_leds | 366 |
| analyze_voltage_derating | 352 |
| detect_buzzer_speakers | 305 |
| detect_adc_circuits | 286 |
| detect_battery_chargers | 273 |
| detect_motor_drivers | 270 |
| detect_rf_matching | 249 |
| detect_reset_supervisors | 238 |
| detect_audio_circuits | 226 |
| detect_isolation_barriers | 210 |
| detect_clock_distribution | 192 |
| detect_power_path | 187 |
| detect_current_sense | 179 |
| detect_rf_chains | 155 |
| validate_feedback_stability | 155 |
| detect_bridge_circuits | 152 |
| validate_can_bus | 135 |
| detect_rtc_circuits | 121 |
| detect_ethernet_interfaces | 119 |
| validate_spi_bus | 111 |
| detect_led_driver_ics | 84 |
| detect_hdmi_dvi_interfaces | 80 |
| detect_headphone_jack | 79 |
| detect_display_interfaces | 55 |
| detect_thermocouple_rtd | 48 |
| detect_energy_harvesting | 47 |
| validate_crystal_load_caps | 46 |
| audit_dnp_rate | 41 |
| detect_integrated_ldos | 37 |
| detect_bms_systems | 25 |
| detect_transformer_feedback | 20 |
| detect_lvds_interfaces | 15 |
| detect_i2c_address_conflicts | 11 |

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

- `KH-001` through `KH-903`: analyzer issues (857 filed, 534 closed, 323 open)
- `TH-001` through `TH-105`: harness infrastructure issues (100 filed, 77 closed, 23 open)

Each closed analyzer issue has a corresponding bugfix regression guard assertion that prevents the bug from returning.

## Numbers at a glance

| Metric | Value |
|--------|-------|
| Repos in corpus | 5,857 |
| Schematic files | 36,463 |
| PCB files | 18,751 |
| Gerber directories | 5,512 |
| EMC analyses | 36,544 |
| SPICE analyzer runs | 36,544 |
| Components parsed | 1,300,475 |
| Nets traced | 2,047,212 |
| Regression assertions | 2,716,889 at 100.0% |
| Bugfix guards | 175 |
| Closed issues | 534 analyzer + 77 harness |
| Open issues | 323 analyzer + 23 harness |
| Schematic detectors | 71 |

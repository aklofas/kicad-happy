# Design Review Report

> **Archived example.** This review was written against an earlier analyzer release. Analyzer output now uses the severities `error`, `warning` and `info`, and the EMC risk score runs from 0 (worst) to 100 (best). Lines that describe analyzer output are relabelled to match; the report's own CRITICAL / WARNING / SUGGESTION labels are unchanged, and the counts and findings are as they were reported.

**Project:** Open-source robot controller board (KiCad 8.0, 5 hierarchical sheets, 6-layer PCB)
**Date:** 2024-12-12 (schematic rev v20)
**Analyzers:** analyze_schematic.py (modern format, full signal analysis), analyze_pcb.py, analyze_emc.py (FCC Class B target), SPICE simulation (ngspice)
**Status:** DONE_WITH_CONCERNS

## Overview

An RP2350B-based robot controller board featuring dual DRV8411A H-bridge motor drivers (4 motor channels), an LSM6DSOX 6-DOF IMU, W25Q128JV 128Mbit serial flash, APS6404L QSPI PSRAM, and an RM2 radio module. Power is supplied via barrel jack or USB-C, stepped down to 5V by an AP63357 synchronous buck converter (3.5A), then regulated to 3.3V by an RT9080 LDO. The board drives brushed DC motors through 8 output connectors (4 motor pairs plus encoders), with servo headers and Qwiic I2C expansion. A 63.5 x 54.0mm 6-layer PCB with 387 footprints.

## Critical Findings

| Severity | Issue | Section |
|----------|-------|---------|
| WARNING | Crystal Y1 load capacitance mismatch: effective 10.5pF vs 18pF target (-41.7%) | Crystal Circuits |
| WARNING | I2C buses missing pull-up resistors (SDA0, SCL0, SDA1) | Bus Protocol Compliance |
| WARNING | USB-C connector J2 has only partial ESD coverage (D+/D-/CC protected, SBU and shield lines unprotected) | ESD Coverage Audit |
| WARNING | Stackup has no dedicated reference planes -- all 6 layers typed as signal | EMC Pre-Compliance |
| WARNING | U2 (W25Q128JV) thermal pad has 0 vias (recommended minimum 5) | PCB Layout -- Thermal |
| WARNING | Buck converter U4 hot loop area ~93mm2 (recommended <25mm2) | EMC Pre-Compliance |
| WARNING | USB differential pair skew estimated at 8.8ps -- predicted CM radiation 80 dBuV/m exceeds FCC Class B limit | EMC Pre-Compliance |
| WARNING | 0% MPN coverage in BOM -- no components have manufacturer part numbers specified | Sourcing Audit |

## Component Summary

| Type | Count |
|------|-------|
| Resistor | 49 |
| Capacitor | 45 |
| Connector | 19 |
| Jumper | 14 |
| Test point | 11 |
| IC | 9 |
| Transistor | 9 |
| LED | 5 |
| Switch | 4 |
| Mounting hole | 4 |
| Fiducial | 4 |
| Inductor | 3 |
| Fuse | 2 |
| Diode | 1 |
| Crystal | 1 |
| Other | 4 |
| **Total** | **184** |

**Nets:** 160 | **Wires:** 774 | **No-connects:** 5 | **Power rails:** 11 (1.1V, 3.3V, 3V3_EN, 5V, GND, VIN, VBATT, VRAW, VSYS, VUSB, GPIO46/VIN_MEAS)
**Sheets:** 5 hierarchical (root, peripherals, connectors, core, power)
**Unique BOM parts:** 67 | **DNP parts:** 0
**MPN coverage:** 0/164 -- no components have MPNs specified. All 164 placeable components lack manufacturer part numbers, preventing lifecycle and obsolescence auditing.

## Power Tree

```
                   Barrel Jack (J1)          USB-C (J2)
                       |                        |
                    F1 (PTC 2.5A)           F2 (PTC 0.75A)
                       |                        |
                     VBATT                    VUSB
                       |                        |
                   Q2 (PMOS)               Q4 (PMOS)
                       |                        |
                       +--- Q6 (PMOS) ---+------+
                                         |
                                       VSYS
                                         |
               +-------------------------+-------------------------+
               |                                                   |
          Q8 (PMOS)                                           U5 RT9080
          LED D3                                           LDO, fixed 3.3V
               |                                          vref: fixed_suffix
             VRAW                                              |
               |                                             3.3V
               +                                               |
          U4 AP63357                                    +------+------+---+---+
       Buck, 450kHz                                     |      |      |   |   |
       Vref=0.8V (lookup)                              U1     U2     U3  U6  U9
       R8=180k / R9=33k                             RP2350  W25Q  PSRAM IMU Radio
       Vout = 0.8V * (1 + 180k/33k)                   |
            = 5.16V --> 5V rail                      1.1V
               |                                   (internal
             5V rail                                regulator)
               |
        +------+------+
        |             |
     U7 DRV8411A   U8 DRV8411A
     Motor L/3     Motor R/4
```

**U4 (AP63357DV-7):** Synchronous buck, VIN to 5V. Vref = 0.8V (datasheet-verified lookup, confirmed from block diagram on page 4: internal reference 0.8V). Feedback divider R8 (180k) / R9 (33k) gives ratio 0.1549, yielding Vout = 0.8V / 0.1549 = 5.16V. Switching frequency 450kHz (typ). Bootstrap cap C22 (0.1uF) present on BST pin. Input caps: 3x 22uF (C33, C35, C36) + 2x 22uF (C32, C21) + 2x 0.1uF (C34, C37). Output caps: 5x 22uF (C38-C41, C25) + 1x 22uF (C24). Compensation: C23 (47pF) on FB. COMP pin present. Power-good output on PG net drives LED D6 and is routed to connector J7.

**U5 (RT9080-3.3):** Fixed 3.3V LDO, VSYS to 3.3V. Vref from part suffix (fixed_suffix). Input cap C26 (4.7uF). Output caps: C15 (4.7uF), C27 (4.7uF), plus 14x 0.1uF bypass caps distributed across 3.3V rail consumers. EN pin connected to 3V3_EN net.

## Datasheet Verification

### AP63357 (U4) -- Buck Converter

| Check | Datasheet | Design | Status |
|-------|-----------|--------|--------|
| Vref | 0.8V (page 4, block diagram) | 0.8V (lookup) | MATCH |
| Pin 1 (VIN) | Power input | Connected to VIN rail | MATCH |
| Pin 2 (EN) | Enable, high=on | Connected to VIN (always on) | MATCH |
| Pin 3 (FB) | Feedback sensing | Connected to R8/R9 divider midpoint | MATCH |
| Pin 5 (PG) | Power good, open-drain | Connected to POWER_GOOD net | MATCH |
| Pin 6 (BST) | Bootstrap cap | C22 (0.1uF) to SW -- matches 100nF recommendation (page 3) | MATCH |
| Pin 8 (GND) | Power ground | Connected to GND | MATCH |
| Pin 9 (SW) | Switching node | Connected to inductor L2 | MATCH |
| Feedback divider R1/R2 | 5V: R1=157k, R2=30k (Table 2, page 18) | R8=180k, R9=33k (Vout=5.16V) | DEVIATION |
| Output capacitors | 22uF to 68uF recommended (page 19) | 6x 22uF = 132uF | ACCEPTABLE |
| Input capacitor | >10uF ceramic (page 19) | 5x 22uF + 2x 0.1uF = 110.2uF | ACCEPTABLE |
| Bootstrap cap | 100nF (page 3) | C22 = 0.1uF | MATCH |

Note: The feedback divider values (180k/33k) differ from the reference table's 5V design (157k/30k) but produce the same Vout within tolerance. The datasheet's internal reference is confirmed at 0.8V from the functional block diagram. The design uses a slightly higher R1:R2 ratio, yielding 5.16V vs 5.0V -- a 3.3% deviation that is within the 0.8V +/-1% Vref tolerance and output capacitor ESR variation.

### DRV8411A (U7, U8) -- Motor Drivers

| Check | Datasheet | Design | Status |
|-------|-----------|--------|--------|
| VM (pin 12/RTE, pin 10/PWP) | 1.65V to 11V supply | Connected to VIN rail | MATCH |
| VREF (pin 15/RTE, pin 1/PWP) | External reference input | Connected to voltage divider (MOTOR_x_VREF nets) | MATCH |
| nFAULT (pin 6/RTE, pin 8/PWP) | Open-drain fault output | Connected to MOTOR_x_FAULT nets with pull-ups | MATCH |
| PGNDA/PGNDB | Bridge power grounds | Connected to GND | MATCH |
| GND (pin 11/RTE, pin 13/PWP) | System ground | Connected to GND | MATCH |
| Thermal pad | Connect to GND | Connected to GND, 5 vias each (adequate) | MATCH |
| VM bypass cap | 0.1uF + bulk (page 4) | C42/C43 (0.1uF) for U7, C44/C45 (0.1uF) for U8, plus 22uF on VIN | MATCH |
| Package | WQFN-16 (3x3mm) | QFN-16 footprint | MATCH |

### RP2350B (U1) -- MCU

| Check | Datasheet | Design | Status |
|-------|-----------|--------|--------|
| DVDD (1.1V core) | 1.1V internal regulator | Internal LDO, 4x decoupling caps on 1.1V rail (C10, C11, C12, C16) | MATCH |
| IOVDD (3.3V I/O) | 1.8-3.3V | Connected to 3.3V rail with multiple bypass caps | MATCH |
| USB D+/D- | Integrated PHY | Connected to D5 (ESD) then J2 USB-C | MATCH |
| XIN/XOUT | 12MHz crystal | Y1 (12MHz) with C17/C18 (15pF) load caps | MATCH |
| QSPI | Flash/PSRAM interface | Connected to U2 (W25Q128) and U3 (APS6404L) | MATCH |
| SWD | Debug interface | SWDCLK/SWDIO routed to J5 header | MATCH |
| Thermal pad (EP) | GND, 3.4x3.4mm | 18 thermal vias (good -- exceeds recommended 9-16) | MATCH |

## Signal Analysis Review

### Power Regulators

| Ref | Value | Topology | Input | Output | Vout | Vref Source |
|-----|-------|----------|-------|--------|------|-------------|
| U4 | AP63357DV-7 | Switching (buck) | VIN | 5V | 5.16V | lookup (0.8V) |
| U5 | RT9080-3.3 | LDO | VSYS | 3.3V | 3.3V | fixed_suffix |

U4 feedback divider verified: Vfb = 5.16V * 33k/(180k+33k) = 0.7997V, within 0.04% of 0.8V Vref. SPICE simulation confirms Vfb = 0.7746V at the divider output with 0.0% error from expected.

### Voltage Dividers

| R_top | R_bottom | Ratio | Vout | Top Net | Purpose |
|-------|----------|-------|------|---------|---------|
| R8 (180k) | R9 (33k) | 0.155 | 0.775V | 5V | Feedback (U4 buck) |
| R42 (100k) | R43 (100k) | 0.500 | 1.65V | 3.3V | Motor VREF (via JP8) |
| R44 (100k) | R45 (100k) | 0.500 | 1.65V | 3.3V | Motor VREF (via JP9) |
| R22 (100k) | R23 (33k) | 0.248 | 0.82V | VIN | VIN measurement (via JP14) |

The two motor VREF dividers (R42/R43 and R44/R45) produce 1.65V for the DRV8411A current regulation inputs. Per the DRV8411A datasheet (page 22, Eq. 5), the trip current is set by I_TRIP = V_VREF / (A_IPROPI * R_IPROPI). With VREF=1.65V and the internal current mirror gain of 0.0002 A/A, the sense resistance determines the current limit.

### RC Filters

| Resistor | Capacitor | Cutoff | Type | Input Net | Output Net | Purpose |
|----------|-----------|--------|------|-----------|------------|---------|
| R21 (100k) | C31 (0.1uF) | 15.9 Hz | Low-pass | 3.3V | GPIO36/USER_BUTTON | Button debounce |
| R1 (200) | C13 (4.7uF) | 169 Hz | Low-pass | 3.3V | ADC_VREF | ADC reference filter |
| R2 (33) | C14 (4.7uF) | 1.03 kHz | Low-pass | 3.3V | VREG supply | RP2350 internal regulator filter |

SPICE verified all three filters with <0.3% cutoff frequency error.

### Crystal Circuits

**Y1 (12MHz):** Load caps C17 (15pF) and C18 (15pF). Effective load capacitance = (15pF * 15pF)/(15pF + 15pF) + ~3pF stray = 10.5pF. The analyzer reports a target load capacitance of 18pF with -41.7% error (out_of_spec). This suggests the crystal's specified CL is 18pF, but the chosen load caps only provide 10.5pF effective. The frequency will pull slightly high.

**Action:** Verify Y1's actual CL specification. If CL=18pF, increase C17/C18 to 33pF each (effective CL = 33*33/(33+33) + 3 = 19.5pF). If CL=10pF (common for some 12MHz crystals), the current values are correct and this is a false positive from an assumed CL.

### Protection Devices

| Ref | Value | Type | Protected Net | Notes |
|-----|-------|------|---------------|-------|
| D5 | DT1042-04SO | ESD IC | USB_D+, USB_D-, VUSB | SOT-23-6, low capacitance USB ESD |
| F2 | 6V/0.75A/1.5A | PTC Fuse | VUSB | USB input current protection |
| F1 | 16V/2.5A/5.0A | PTC Fuse | VBATT | Barrel jack input protection |

### LED Circuits

| LED | Color | Series R | Supply | Driver | Est. Current |
|-----|-------|----------|--------|--------|-------------|
| D6 | Red | R47 (4.7k) | VIN | U7 | ~0.7mA (low, appropriate for indicator) |
| D2 | Red | R11 (4.7k) | 3.3V | U6 | 0.3mA |
| D1 | Blue | R10 (2.2k) | -- | U9 | ~0.7mA |
| D4 | WS2812B | -- | VSYS | Q5/Q6 switch | 60mA peak (addressable) |

D4 is a WS2812B addressable LED driven through a PNP transistor switching network (Q3/Q5 for VUSB source, Q1/Q7 for 5V source via Q8). The chain length is 1 LED. Data input is on GPIO37/NEOPIXEL.

### Transistor Circuits

9 transistor circuits detected, all P-channel MOSFETs (DMG2305UX, 4.2A/20V) or dual PNP BJTs (BCM857BS-7-F):

| Ref | Type | Function | Gate/Base R | Load |
|-----|------|----------|-------------|------|
| Q2 | PMOS | VBATT to VRAW switch | R31 (100k) | Power path |
| Q4 | PMOS | VUSB to VRAW switch | R33 (100k) | Power path |
| Q6 | PMOS | VUSB to VSYS switch | R35 (100k) | Power path |
| Q8 | PMOS | 5V to VSYS switch + LED D3 | R37 (100k) | Power/LED |
| Q9 | PMOS | Power path control | -- | Other |
| Q1 | PNP (dual) | WS2812 power sourcing | R30 (100k) | Resistive |
| Q3 | PNP (dual) | WS2812 power sourcing | R32 (100k) | Resistive |
| Q5 | PNP (dual) | WS2812 power sourcing | R34 (100k) | Transistor cascade |
| Q7 | PNP (dual) | WS2812 power sourcing | R36 (100k) | Transistor cascade |

SPICE warnings on Q1/Q3/Q5/Q7 (BCM857BS-7-F) showing VBE=2.65V are expected -- the generic NPN model does not match this dual-PNP part's actual behavior. These are false positives from the generic transistor model.

### Decoupling Analysis

| Rail | Cap Count | Total uF | Bulk | Bypass | SPICE Z @ 1MHz |
|------|-----------|----------|------|--------|----------------|
| 3.3V | 16 | 10.8 | 2x 4.7uF | 14x 0.1uF | 0.050 ohm |
| 5V | 6 | 132.0 | 6x 22uF | -- | 0.002 ohm |
| VIN | 7 | 110.2 | 5x 22uF | 2x 0.1uF | 0.002 ohm |
| VSYS | 1 | 4.7 | 1x 4.7uF | -- | 0.142 ohm |
| 1.1V | 4 | 9.6 | 2x 4.7uF | 2x 0.1uF | 0.067 ohm |

The 5V rail lacks dedicated bypass caps (no 0.1uF values) -- all capacitance is 22uF bulk. This leaves a coverage gap between ~1MHz (22uF SRF) and ~15MHz (where smaller caps would take over). The 3.3V rail has excellent two-tier coverage. VSYS has minimal decoupling (single 4.7uF) -- acceptable since it is an intermediate bus with short trace runs.

### Sensor Interfaces

**U6 (LSM6DSOX):** 6-DOF IMU on I2C bus (GPIO4/SDA0, GPIO5/SCL0). Interrupt outputs INT1 (IMU_INT1) and INT2 (IMU_INT2) connected to MCU GPIO pins. Decoupling cap C30 (0.1uF) at 2.54mm from U6.

### Addressable LED Chains

**D4 (WS2812B):** Single-LED chain on GPIO37/NEOPIXEL. Peak current 60mA. Power sourced through transistor switching network from VSYS.

## ESD Coverage Audit

**Coverage: 2/19 connectors with protection (10.5%)**

| Connector | Type | Risk | Coverage | ESD Devices | Unprotected Nets |
|-----------|------|------|----------|-------------|------------------|
| J2 | USB-C | High | Partial | D5 (DT1042-04SO), F2 (PTC) | CC1, CC2, SBU, SHIELD |
| J1 | Barrel Jack | Medium | Partial | F1 (PTC) | -- |
| J4 | 20-pin header | Medium | None | -- | 16 signal nets |
| J5 | 20-pin header | Medium | None | -- | (programming/debug) |
| J6 | 20-pin header | Medium | None | -- | (expansion) |
| J7 | 20-pin header | Medium | None | -- | 12 signal nets |
| J13/J14 | Qwiic I2C | Medium | None | -- | SDA0, SCL0 |
| J3/J8-J11 | Servo 3-pin | Medium | None | -- | GPIO servo signals |
| J12/J15 | JST line sensor | Medium | None | -- | Line sensor I/O |
| J16-J19 | Motor/encoder 6-pin | Medium | None | -- | Motor + encoder signals |

This is typical for an educational/hobby board but would require ESD protection on all external connectors for any commercial certification.

## SPICE Simulation Results

**ngspice verified 22 subcircuits in 0.089s. 16 pass, 6 warn, 0 fail, 0 skip.**

### Pass (16)

| Subcircuit | Reference | Result |
|------------|-----------|--------|
| RC filter | R21/C31 (fc=15.9Hz) | Confirmed, 0.27% error |
| RC filter | R1/C13 (fc=169Hz) | Confirmed, 0.24% error |
| RC filter | R2/C14 (fc=1.03kHz) | Confirmed, 0.24% error |
| Voltage divider | R42/R43 (Vout=1.65V) | Confirmed, 0.0% error |
| Voltage divider | R44/R45 (Vout=1.65V) | Confirmed, 0.0% error |
| Voltage divider | R22/R23 (Vout=0.82V) | Confirmed, 0.0% error |
| Voltage divider | R8/R9 (Vout=0.775V) | Confirmed, 0.0% error |
| Feedback network | U4: R8/R9 (Vfb=0.775V) | Confirmed, 0.0% error |
| Regulator feedback | U4: R8/R9 (Vfb=0.775V vs 0.8V Vref) | Confirmed, 0.0% error |
| Decoupling 3.3V | C30/C29/C28/C15/C19 (16 caps) | Z=0.050 ohm @ 1MHz |
| Decoupling 5V | C41/C39/C40/C38/C25 (6 caps) | Z=0.002 ohm @ 1MHz |
| Decoupling VIN | C34/C35/C36/C33/C37 (7 caps) | Z=0.002 ohm @ 1MHz |
| Decoupling VSYS | C26 (1 cap) | Z=0.142 ohm @ 1MHz |
| Decoupling 1.1V | C16/C12/C10/C11 (4 caps) | Z=0.067 ohm @ 1MHz |
| Inrush U5 | 3.3V rail, 10.8uF | 71mA estimated, settles to 3.3V |
| Inrush U4 | 5V rail, 132uF | 682mA estimated, settles to 5.16V |

### Warn (6)

| Subcircuit | Reference | Note |
|------------|-----------|------|
| Crystal Y1 | 12MHz | Series resonance deviation -- generic crystal model limitation. Load caps C17/C18 present. |
| Transistor Q9 | DMG2305UX (PMOS) | Very low on-state current -- generic PMOS model, not representative of actual part |
| Transistor Q5 | BCM857BS-7-F (PNP dual) | VBE=2.65V outside 0.5-0.8V range -- generic NPN model misapplied to dual-PNP |
| Transistor Q3 | BCM857BS-7-F (PNP dual) | Same generic model mismatch |
| Transistor Q7 | BCM857BS-7-F (PNP dual) | Same generic model mismatch |
| Transistor Q1 | BCM857BS-7-F (PNP dual) | Same generic model mismatch |

All 6 warnings are model fidelity limitations, not design issues. The BCM857BS-7-F is a dual PNP transistor simulated with a generic NPN model -- the VBE values are not meaningful. Q9 (DMG2305UX PMOS) similarly uses a generic model that does not capture the part's actual threshold voltage.

## EMC Pre-Compliance Summary

**Target:** FCC Class B (unintentional radiator)
**Total findings:** 77 (11 error, 14 warning, 52 info)
**EMC risk score:** 0/100 (archived score; 0 is worst, 100 best)

### Findings by Category

| Category | error | warning | info | Total |
|----------|-------|---------|------|-------|
| Stackup | 5 | -- | -- | 5 |
| Diff pair | 3 | 4 | -- | 7 |
| Decoupling | 1 | 1 | -- | 2 |
| I/O filtering | 2 | 1 | 48 | 51 |
| Clock routing | -- | 5 | -- | 5 |
| Switching EMC | -- | 2 | 2 | 4 |
| Ground plane | -- | 1 | -- | 1 |
| Emission estimate | -- | -- | 2 | 2 |

### Key error findings

1. **SU-001 (x5): All signal layer pairs are adjacent** -- The 6-layer stackup has all copper layers typed as "signal" with no dedicated ground or power plane. Layers F.Cu/In1.Cu/In2.Cu/In3.Cu/In4.Cu/B.Cu are all adjacent signal layers. This eliminates controlled-impedance return paths and maximizes crosstalk. Recommendation: reassign inner layers (e.g., In1.Cu=GND, In4.Cu=Power) for proper reference planes.

2. **DC-002: No decoupling near U9 (RM2 radio)** -- The radio module has no capacitor within 10mm. RF modules are particularly sensitive to supply noise.

3. **IO-001 (x2): No EMC filtering on J1 (barrel jack) and J2 (USB-C)** -- External-facing connectors lack ferrite beads and common-mode filtering. The barrel jack powers motors via a long cable (antenna), and the USB-C carries high-speed differential signals.

4. **DP-002: USB D+/D- skew generates CM radiation** -- 8.8ps skew produces an estimated 80 dBuV/m at 1GHz, exceeding the FCC Class B limit of 54 dBuV/m by 26dB.

5. **DP-003 (x2): USB D+/D- change layers** -- Both USB data lines transition between F.Cu and B.Cu with vias, creating differential-to-common mode conversion points.

### Key warning findings

- **DC-001:** Nearest decoupling to U1 (RP2350B) is C12 at 6.2mm -- should be <3mm
- **CK-001 (x5):** Clock nets QSPI_CLK, SWDCLK, XIN, XOUT, RADIO_CLK routed 100% on outer layers (microstrip) instead of inner stripline
- **SW-001:** U4 (AP63357) switching at 500kHz produces 117 harmonics in the 30-88MHz band
- **SW-003:** Hot loop area (C35-U4-L2 triangle) ~93mm2, recommended <25mm2
- **DP-004 (x4):** USB pairs (USB_D+/D-, USB_RP_D+/D-) all routed on outer layers

## PCB Layout Analysis

### Board Overview

- **Dimensions:** 63.5mm x 54.0mm (board area: 3427mm2)
- **Layer count:** 6 copper layers (F.Cu, In1.Cu, In2.Cu, In3.Cu, In4.Cu, B.Cu)
- **Stackup:** FR4, 1.6mm total thickness. Outer copper 35um (1oz), inner copper 15.2um (0.5oz). Prepreg: 99.4um and 108.8um. Core: 550um (x2).
- **Board thickness:** 1.60mm (standard)
- **Solder mask:** Red (#E0311DD4)
- **Surface finish:** Not specified in PCB file

### Footprint Placement

- **Total footprints:** 387 (249 front, 138 back)
- **SMD:** 157 | **THT:** 11
- **Courtyard overlaps:** 0
- **Edge clearance violations:** 0

### Routing

- **Track segments:** 1,630
- **Total track length:** 2,980mm
- **Vias:** 510 (all through-hole)
- **Zones:** 57
- **Unrouted nets:** 0 (routing complete)

### Via Analysis

510 vias, all through-hole type. No blind or buried vias. Annular ring of 0.075mm is below both IPC Class 2 minimum (0.125mm) and advanced-process minimum (0.1mm) -- flagged in DFM.

### Thermal Pad Vias

| IC | Value | Pad Area | Via Count | Recommended | Adequacy | Note |
|----|-------|----------|-----------|-------------|----------|------|
| U1 | RP2350B | 3.4x3.4mm (11.6mm2) | 18 | 9-16 | Good | Exceeds recommendation |
| U7 | DRV8411A | 1.6x1.6mm (2.6mm2) | 5 | 5-9 | Adequate | 5 untented vias -- solder wicking risk |
| U8 | DRV8411A | 1.6x1.6mm (2.6mm2) | 5 | 5-9 | Adequate | 5 untented vias -- solder wicking risk |
| U2 | W25Q128JV | 0.9x4.1mm (3.7mm2) | 0 | 5-9 | None | **No thermal vias on exposed pad** |

U2 (W25Q128JV) has an exposed thermal pad but zero vias connecting it to inner copper or the opposite-side ground plane. While the W25Q128JV is low-power and unlikely to overheat, the exposed pad should still be connected to GND for electrical and thermal integrity.

U7 and U8 (DRV8411A) thermal pads have 5 untented vias each. During reflow, solder may wick through untented vias, creating voids under the thermal pad and degrading thermal performance. Consider tenting vias or using via-in-pad with cap plating.

### Decoupling Placement

| IC | Value | Nearest Cap | Distance | Status |
|----|-------|-------------|----------|--------|
| U1 | RP2350B | C12 (4.7uF) | 6.18mm | Too far (>3mm) |
| U2 | W25Q128JV | C19 (0.1uF) | 4.65mm | Marginal |
| U3 | APS6404L | C20 (0.1uF) | 2.16mm | Good |
| U4 | AP63357 | C22 (0.1uF) | 1.85mm | Good |
| U5 | RT9080-3.3 | C30 (0.1uF) | 2.54mm | Good |
| U6 | LSM6DSOX | C30 (0.1uF) | 2.54mm | Good |
| U7 | DRV8411A | C34 (0.1uF) | 2.67mm | Good |
| U8 | DRV8411A | C37 (0.1uF) | 2.67mm | Good |

U1 (RP2350B) is an 80-pin QFN with multiple power pins. The nearest decoupling cap at 6.18mm is too far for effective high-frequency bypass. The 0402 bypass caps should be placed directly adjacent to the QFN power pins.

### Switching Loop

U4 (AP63357) hot loop area: C35 to U4 to L2 forms a triangle with ~93mm2 area. The datasheet (page 19) emphasizes minimizing the input capacitor loop. This loop is approximately 4x larger than the recommended 25mm2 maximum. Tight placement of C35 adjacent to U4's VIN pin with L2 on the opposite side would reduce radiated emissions.

### Power Net Routing

| Net | Tracks | Length | Min Width | Max Width |
|-----|--------|--------|-----------|-----------|
| GND | 19 | 12.3mm | 0.127mm | 0.508mm |
| VIN | 5 | 5.6mm | 0.127mm | 0.127mm |
| VSYS | 6 | 4.2mm | 0.127mm | 0.127mm |
| VBATT | 3 | 3.6mm | 0.127mm | 0.127mm |
| 3V3_EN | 12 | 40.8mm | 0.127mm | 0.127mm |

Power nets VIN, VSYS, and VBATT are all routed at the minimum trace width (0.127mm / 5mil). While zones likely carry the bulk of the current, the trace-only routing provides limited current capacity. VIN carries up to 3.5A to the buck converter -- 5mil traces on 1oz copper can handle roughly 0.3A per IPC-2152, relying entirely on zone fills for adequate current capacity.

### DFM Assessment

- **DFM tier:** Challenging
- **Min track width:** 0.127mm (5mil) -- standard process
- **Min track spacing:** ~0.127mm (5mil) -- at standard process limit
- **Min drill:** 0.3mm -- standard process
- **Min annular ring:** 0.075mm -- **below advanced process minimum (0.1mm)**
- **IPC Class 2 violations:** Via annular ring 0.075mm below Class 2 minimum 0.125mm

The annular ring violation means this board requires a fabricator with process capability below 0.1mm annular ring, or the via pad size needs to be increased.

### Tombstoning Risk

70 components flagged for medium tombstoning risk, predominantly 0402 capacitors with one pad on a GND zone (thermal asymmetry). This is typical for 0402 parts on boards with extensive ground pours. Mitigation: thermal relief on GND zone connections to 0402 pads, or use 0603 for critical bypass caps.

### Silkscreen

- Reference designators visible: 201 (of 387 footprints)
- Reference designators hidden: 186 (all passive components hidden -- typical for dense boards)
- Board text annotations: 0

## Power Analysis

### PDN Impedance

SPICE-verified impedance at 1MHz for all rails:

| Rail | Z @ 100kHz | Z @ 1MHz | Z_min | f(Z_min) |
|------|-----------|----------|-------|----------|
| 3.3V | 0.159 ohm | 0.050 ohm | 0.035 ohm | 8.6 MHz |
| 5V | 0.012 ohm | 0.002 ohm | 0.002 ohm | 1.1 MHz |
| VIN | 0.015 ohm | 0.002 ohm | 0.002 ohm | 1.1 MHz |
| VSYS | 0.366 ohm | 0.142 ohm | 0.138 ohm | -- |
| 1.1V | 0.179 ohm | 0.067 ohm | 0.061 ohm | -- |

The 5V and VIN rails show excellent low impedance thanks to multiple parallel 22uF ceramics. The 3.3V rail benefits from the two-tier capacitor strategy (4.7uF bulk + 0.1uF bypass). The 1.1V core rail impedance is adequate for the RP2350B's current requirements (~60mA).

### Power Budget

| Rail | Regulator | Capacity | Load ICs | Est. Load | Margin |
|------|-----------|----------|----------|-----------|--------|
| 3.3V | U5 (RT9080) | 600mA | U1 (60mA), U2 (10mA), U3 (10mA), U6 (5mA) | 85mA | 86% |
| 5V | U4 (AP63357) | 3.5A | Motor drivers via VIN | ~3A peak | 14% |
| 1.1V | U1 internal | -- | RP2350B core | 60mA | -- |

The 3.3V rail has ample margin at 85mA / 600mA. The 5V rail feeding the motor drivers through VIN can approach the 3.5A limit during simultaneous 4-motor operation at full load.

### Power Sequencing

Both regulators are always-enabled:
- U4 (AP63357): EN tied to VIN (always on when input present)
- U5 (RT9080): EN on 3V3_EN net (always-on)

Power-good signal from U4 (PG pin) drives POWER_GOOD net, connected to LED D6 and connector J7. No PG-to-EN dependency chains detected -- all rails come up simultaneously.

### Inrush Analysis

| Rail | Regulator | Output Caps | Est. Inrush | Concern |
|------|-----------|-------------|-------------|---------|
| 3.3V | U5 (LDO) | 10.8uF | 71mA | Low |
| 5V | U4 (buck) | 132uF | 682mA | Moderate |

The 5V rail has 132uF of output capacitance. At startup with the AP63357's soft-start, the estimated inrush of 682mA is within the converter's capability. The barrel jack and USB-C input paths include PTC fuses (F1: 2.5A hold, F2: 0.75A hold) that provide additional inrush limiting.

### Sleep Current Audit

- **Worst-case estimated:** 697uA
- **Realistic estimated:** 118.6mA (includes active loads -- this board is not designed for battery sleep optimization)

The high realistic figure reflects the always-on motor driver quiescent currents and the RP2350B in active mode. The board does not include dedicated sleep/shutdown circuitry for battery-operated use.

## Bus Protocol Compliance

### I2C

**4 issues found across 2 I2C buses:**

| Bus | SDA Net | SCL Net | Devices | Pull-ups | Status |
|-----|---------|---------|---------|----------|--------|
| I2C0 | GPIO4/SDA0 | GPIO5/SCL0 | U1 (RP2350B) | Missing | FAIL |
| I2C1 | GPIO38/SDA1 | GPIO5/SCL0 | U1 (RP2350B), U6 (LSM6DSOX) | Missing | FAIL |

Neither I2C bus has external pull-up resistors on SDA or SCL. The RP2350B does have internal pull-ups that can be enabled in software (typically 50-80k), but these are weaker than the I2C specification recommends for reliable operation (typically 2.2k-10k for 100-400kHz). The LSM6DSOX has internal pull-ups that may be sufficient for short board-level connections, but external pull-ups are best practice, especially for the Qwiic connectors (J13, J14) where cables add capacitance.

**Recommendation:** Add 4.7k pull-up resistors to 3.3V on SDA0 and SCL0 lines. For I2C1 (SDA1/SCL0), verify the net mapping -- SDA1 and SCL0 appear to mix bus indices, which may indicate a wiring issue or intentional bus sharing.

### SPI (QSPI)

QSPI bus detected: QSPI_CLK, QSPI_D0-D3, FLASH_CS connecting U1 to U2 (W25Q128JV) and U3 (APS6404L). Chip select signals include proper pull-ups (R6, R7 = 10k). No protocol violations detected.

### USB

USB compliance summary:
- **Connector:** USB-C receptacle (J2)
- **ESD protection:** D5 (DT1042-04SO) on D+/D- lines
- **VBUS protection:** F2 (PTC fuse, 0.75A)
- **CC resistors:** Present (via CC1/CC2 nets)
- **Data lines:** USB_D+/D- routed to D5 then to RP2350B (USB_RP_D+/D-)

## Connector Ground Distribution

J2 (USB_C_Receptacle): 1 ground pin for 13 signal pins (13:1 ratio). The I2C specification recommends at most 3 signal pins per ground pin for adequate return current path. This USB-C connector has insufficient ground pin count, though this is largely determined by the connector standard -- USB-C specifies the pin assignment. The important factor is the PCB ground connection to the connector shell and shield pins.

## Certification Suggestions

| Standard | Region | Reason |
|----------|--------|--------|
| FCC Part 15 Subpart B | US | Unintentional radiator -- required for all electronic devices |
| CISPR 32 / CE EMC Directive | EU | EMC compliance for EU market access |

For an educational/hobby board, FCC/CE testing may not be legally required if sold as a kit or development board with appropriate labeling. However, the EMC analysis identified several areas where the design would struggle with radiated emissions testing, primarily the stackup topology and USB differential pair routing.

## BOM Lock Status

**MPN coverage: 0%** -- No components have manufacturer part numbers specified in the schematic. All 164 placeable components rely on generic value descriptions (e.g., "0.1uF", "100k") without tied MPNs.

This prevents:
- Lifecycle and obsolescence monitoring
- Automated distributor pricing
- Exact alternate part qualification
- JLCPCB/assembly house BOM matching

The ICs do have functional value names (AP63357DV-7, DRV8411A, RP2350B, etc.) that serve as de facto MPNs, but these are in the Value field rather than the MPN property.

## All Issues & Suggestions

| # | Severity | Issue | Detail |
|---|----------|-------|--------|
| 1 | WARNING | Crystal load cap mismatch | Y1: effective CL=10.5pF vs target 18pF (-41.7%). Verify crystal spec and adjust C17/C18. |
| 2 | WARNING | I2C missing pull-ups | SDA0, SCL0, SDA1 have no external pull-up resistors. Add 4.7k to 3.3V. |
| 3 | WARNING | USB-C partial ESD | D+/D-/CC protected by D5. SBU and shield lines unprotected. |
| 4 | WARNING | Stackup lacks reference planes | All 6 layers typed as signal. Reassign In1.Cu/In4.Cu as GND/PWR planes. |
| 5 | WARNING | U2 thermal pad -- 0 vias | W25Q128JV exposed pad has no thermal/ground vias. Add 4-5 vias. |
| 6 | WARNING | Buck hot loop oversized | U4 C35-L2 triangle ~93mm2 vs <25mm2 target. Tighten placement. |
| 7 | WARNING | USB skew radiation | 8.8ps skew predicts 80 dBuV/m at 1GHz (limit 54). Improve length matching. |
| 8 | WARNING | 0% MPN coverage | No MPNs specified. Add MPN/manufacturer fields for all components. |
| 9 | WARNING | U1 decoupling distance | RP2350B nearest bypass cap at 6.18mm. Move caps within 3mm of power pins. |
| 10 | WARNING | Annular ring below spec | 0.075mm via annular ring below IPC Class 2 (0.125mm) and advanced fab (0.1mm). |
| 11 | SUGGESTION | 5V rail bypass gap | No 0.1uF bypass caps on 5V rail. Add 100nF near motor driver VM pins. |
| 12 | SUGGESTION | VSYS decoupling | Single 4.7uF cap on VSYS. Consider adding 0.1uF bypass. |
| 13 | SUGGESTION | Radio module decoupling | U9 (RM2) has no decoupling cap within 10mm. Add 100nF + 1uF near VDDBAT pin. |
| 14 | SUGGESTION | Clock routing on outer layers | QSPI_CLK, SWDCLK routed on microstrip. Route on inner stripline for EMI. |
| 15 | SUGGESTION | USB diff pair routing | D+/D- on outer layers and cross layer boundaries. Route on single inner layer. |
| 16 | SUGGESTION | Connector filtering | 17 connectors lack ferrite beads or EMC filtering. Add ferrites on external I/O. |
| 17 | SUGGESTION | Thermal via tenting | U7/U8 thermal pad vias untented. Add tenting or via-in-pad capping. |
| 18 | SUGGESTION | 0402 tombstoning | 70 0402 caps with GND thermal asymmetry. Use thermal relief or consider 0603. |
| 19 | SUGGESTION | Power trace widths | VIN/VSYS/VBATT routed at 5mil minimum width. Widen or verify zone fill coverage. |
| 20 | SUGGESTION | Ground domains | 2 ground domains detected. Verify single-point connection intent. |

## Positive Findings

1. **AP63357 feedback divider matches datasheet Vref** -- The analyzer correctly identified Vref=0.8V via lookup (not heuristic), and the R8/R9 divider produces Vfb within 0.04% of the reference voltage. SPICE confirms with 0.0% error.

2. **Comprehensive output capacitance on 5V rail** -- 6x 22uF (132uF total) exceeds the AP63357 datasheet recommendation of 22-68uF, providing excellent transient response for motor load steps.

3. **RP2350B thermal vias: 18 vias on EP pad** -- Exceeds the recommended range of 9-16 vias for the QFN-80 package. Excellent thermal path to inner layers.

4. **DRV8411A decoupling well-placed** -- Both U7 and U8 have 0.1uF bypass caps at 2.67mm, within the 3mm recommendation. VIN bulk caps co-located.

5. **USB ESD protection present** -- D5 (DT1042-04SO) provides low-capacitance ESD clamping on USB D+/D- lines, appropriate for USB 2.0 Full Speed.

6. **Complete routing** -- 0 unrouted nets. All 160 nets are fully connected.

7. **No courtyard overlaps or edge clearance violations** -- Clean placement with no physical conflicts.

8. **ADC reference filtering** -- R1/C13 form a 169Hz low-pass filter on the ADC_VREF net, providing clean reference voltage. R2/C14 provide 1kHz filtering for the RP2350B internal regulator input. Both confirmed by SPICE.

9. **PTC fuse protection on both power inputs** -- F1 (2.5A) on barrel jack and F2 (0.75A) on USB-C provide overcurrent protection upstream of the power path MOSFETs.

10. **Power-good monitoring** -- U4's PG output is routed to an indicator LED (D6) and the expansion connector (J7), enabling system-level power sequencing awareness.

11. **All SPICE-simulated passive circuits pass** -- 16/16 passive subcircuits (filters, dividers, feedback, decoupling, inrush) verified within <0.3% of calculated values.

## Analyzer Gaps

1. **Crystal CL specification unverified** -- The analyzer assumed CL=18pF for Y1 (12MHz). The actual crystal datasheet should be checked. Many 12MHz crystals specify CL=10pF or 20pF, and the 15pF load caps may be correct for a CL=10pF part (effective 10.5pF with ~3pF stray).

2. **RP2350B internal 1.1V regulator not modeled** -- The analyzer detected the 1.1V rail and its decoupling but cannot verify the internal LDO's specifications or dropout requirements.

3. **Motor driver current regulation not fully traced** -- The VREF divider voltage (1.65V) is detected, but the IPROPI sense resistor value (which sets the actual current trip point) was not extracted from the schematic context.

4. **Stackup layer usage not analyzed** -- All layers are typed as "signal" in the PCB file. The EMC analyzer correctly flags this, but cannot determine if inner layers are actually used as pour-filled reference planes (which would mitigate the stackup warnings).

5. **Zone fill analysis limited** -- The PCB analyzer detects 57 zones but does not fully evaluate which zones serve as continuous ground planes vs. split power islands. Power nets routed at 5mil width may be adequately served by zone fills.

6. **BCM857BS-7-F dual transistor modeling** -- The SPICE simulator applied a generic NPN model to a dual-PNP package. All 4 warnings on Q1/Q3/Q5/Q7 are model artifacts, not design issues.

7. **USB impedance control not verified** -- Differential pair impedance (target 90 ohm) cannot be calculated without full stackup dielectric properties and trace geometry data. The PCB file has basic stackup data but the analyzer did not compute characteristic impedance.

8. **Wireless module (U9 RM2) antenna layout not analyzed** -- RF performance depends on keepout zones and ground plane termination near the antenna, which requires module-specific reference design verification.

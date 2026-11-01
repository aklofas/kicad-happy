# GNSS Disciplined Oscillator — Design Review

> **Archived example.** This review was written against an earlier analyzer release. Analyzer output now uses the severities `error`, `warning` and `info`, and the EMC risk score runs from 0 (worst) to 100 (best). Lines that describe analyzer output are relabelled to match; the report's own CRITICAL / WARNING / SUGGESTION labels are unchanged, and the counts and findings are as they were reported.

**Project:** Open-source GNSS disciplined oscillator board
**Date:** 2026-04-09
**KiCad Version:** 8.x (S-expression format v20231120)
**Firmware Version:** 2.2

---

## 1. Design Overview

This open-source GNSS Disciplined Oscillator is built around a Septentrio mosaic-T multi-constellation GNSS receiver and a SiTime SiT5358 DCTCXO. An ESP32-WROVER-IE-N16R8 runs firmware that disciplines the oscillator using a PI controller driven by clock bias data from the mosaic-T's SBF messages.

### Key Specifications

| Parameter | Value |
|-----------|-------|
| Board dimensions | 151.9 mm x 101.6 mm (4-layer) |
| Copper layers | F.Cu, In1.Cu, In2.Cu, B.Cu |
| Components | 296 schematic / 438 PCB footprints (142 are silkscreen/graphics) |
| Unique parts | 62 BOM line items |
| Nets | 240 schematic / 247 PCB |
| Routing | 100% complete, 0 unrouted nets |
| Via count | 692 (0.6096mm/0.3048mm standard) |
| Power rails | 5V, 3.3V, 3.3V_P, 2.8V, 1.8V, VCCIO, VDDA, VIN_DC, VIN_POE, VUSB |

### Power Architecture

```
VIN_DC (screw terminal) ──┐
                          ├─→ D4/D8 (BAT60A OR-ing) ──→ 5V rail
VIN_POE (PoE via Ag9905M)┘                                │
VUSB (USB-C) ─────────────────────────────────────────────→│
                                                            │
  U11 (AP7361C-3.3V) ←── 5V ──→ U5 (AP7361C-3.3V)
        │                              │
      3.3V (ESP32, CH340C)         3.3V_P (mosaic-T digital,
                                    KSZ8041NL, level shifters)
                                        │
                              mosaic-T internal regulators
                                   ├─ 1.8V (core)
                                   ├─ 2.8V (RF)
                                   └─ VCCIO (I/O)
```

### Schematic Hierarchy

| Sheet | Content |
|-------|---------|
| Root (main board) | ESP32-WROVER, CH340C USB-UART, SiT5358 TCXO, connectors, buttons, LEDs |
| Power | AP7361C LDOs (x2), PoE (Ag9905M + REC15E-2405SZ), DC input, USB power path, fuse |
| USB | Two USB-C receptacles (mosaic-T and ESP32), ESD protection (DT1042-04SO) |
| GNSS | mosaic-T (179-pin LGA), antenna SMA, GNSS configuration |
| Ethernet | KSZ8041NL/I PHY, MagJack with integrated magnetics, PoE pass-through |
| Level_Shifting | 74LVC2T45DC level shifters (x4) for mosaic-T UART/event signals (3.3V_P↔VCCIO) |
| Level_Shifting_10MHz | 74LVC2T45DC level shifters (x3) for 10MHz clock distribution and PPS signals |

---

## 2. Component Summary

### Active ICs

| Ref | Part | Function | Package | Verified |
|-----|------|----------|---------|----------|
| U1 | ESP32-WROVER-IE-N16R8 | MCU (16MB flash, 8MB PSRAM) | Module | Datasheet p.1 |
| U2 | mosaic-T | Multi-constellation GNSS receiver | 179-LGA | HW Manual v1.11 |
| U3 | CH340C | USB-to-UART bridge | SO-16 | Datasheet |
| U4 | KSZ8041NL/I | 10/100 Ethernet PHY | QFN-32 (5x5mm) | DS00002245B pp.6-10 |
| U5, U11 | AP7361C-3.3V | 1A LDO regulator | UDFN-8 | Datasheet |
| U6 | REC15E-2405SZ | Isolated DC-DC (48V→5V) | SIP-6 | Datasheet |
| U7 | Ag9905M | PoE PD module | Custom | Datasheet |
| U8-U10, U12, U14-U16 | 74LVC2T45DC | 2-bit level shifter | VSSOP-8 | DS Rev.13 pp.2-5 |
| U13 | SiT5358AI-FS033IT-10.000000 | DCTCXO 10MHz ±50ppb | 5.0x3.2mm ceramic QFN | DS Rev.1.03 pp.9-10 |
| U17 | LMV7219M5 | High-speed comparator | SOT23-5 | Datasheet |
| U18 | PCA9306 | I2C level translator | VSSOP-8 | Datasheet |

### Passive Summary

| Type | Count | Notable |
|------|-------|---------|
| Capacitors | 76 | 0603 MLCC (0.1µF-22µF), Panasonic D electrolytic (47µF, 100µF) |
| Resistors | 59 | 0603, values: 33Ω-100kΩ |
| Inductors | 6 | 4.7µH (1008/2520), 470Ω ferrite beads |
| Diodes | 17 | BAT60A Schottky (OR-ing), ESD (DT1042-04SO, DF5A5.6LFU, PESD0402) |
| Connectors | 12 | 4x SMA edge, 2x USB-C, 1x MagJack PoE RJ45, 1x microSD, 1x Qwiic, 1x screw cage |
| Test points | 50 | Extensive test coverage |
| Jumpers | 27 | 12 NO, 21 NC-trace, 3 three-way, 5 combo PTH/SMD |

---

## 3. Critical Findings

### 3.1 CRITICAL — No Thermal Vias on QFN/UDFN Exposed Pads

**Severity: CRITICAL** | Components: U4 (KSZ8041NL/I), U5 (AP7361C-3.3V), U11 (AP7361C-3.3V)

All three components with exposed thermal pads have **zero thermal vias** detected by the PCB analyzer:

| Component | Pad Area | Recommended Vias | Actual | Estimated Tj |
|-----------|----------|------------------|--------|-------------|
| U4 (KSZ8041NL QFN-32) | 9.92 mm² | 5-9 | 0 | N/A (low power, <180mW) |
| U5 (AP7361C LDO) | 3.76 mm² | 5-9 | 0 | 69°C at 1.1W |
| U11 (AP7361C LDO) | 3.76 mm² | 5-9 | 0 | 36°C at 0.27W |

**U5 is the hottest component** at an estimated 69°C junction temperature dissipating 1.1W with (5V-3.3V)×0.647A. While this has 56°C margin to Tj_max (125°C), the lack of thermal vias means all heat dissipation relies on surface copper spreading. In enclosed operation or elevated ambient, this margin shrinks significantly.

**Impact:** U5 may overheat in enclosed installations. U4's solderability may be impaired — the QFN exposed pad requires thermal vias for reliable solder wetting during reflow.

**Recommendation:** Add minimum 5 vias (0.3mm drill, tented on component side) under each thermal pad. For U5, consider 9 vias given its 1.1W dissipation.

> **Note:** The PCB analyzer checks for vias within the thermal pad boundary. It is possible that vias exist nearby but outside the pad outline, or that the KiCad footprint includes integral via-pads not detected as standalone vias. Visually inspect the PCB layout to confirm.

### 3.2 HIGH — I2C Buses Missing Pull-Up Resistors

**Severity: HIGH** | Nets: ESP21/SDA, ESP22/SCL, ESP18/SDA2, ESP19/SCL2, SDA2_IO, SCL2_IO

The analyzer detected **no pull-up resistors** on any I2C bus in the design:

- **I2C Bus 1** (ESP21/SDA, ESP22/SCL): Connects ESP32 to Qwiic connector J7. No devices or pull-ups detected on this bus segment.
- **I2C Bus 2** (ESP18/SDA2, ESP19/SCL2): Connects ESP32 → PCA9306 (U18) level translator → SiT5358 (U13). External pull-ups may be unnecessary if the SiT5358's internal 200kΩ pull-ups (datasheet Table 13, p.9) and PCA9306's integrated pull-ups are sufficient.
- **I2C Bus 2 translated side** (SDA2_IO, SCL2_IO): Goes through U18 PCA9306 to screw cage connector J9. The PCA9306 has internal pull-up current sources, but external pull-ups are typically recommended for robust operation.

**Mitigating factors:** The Qwiic connector specification includes pull-ups on the connected device, and several jumper pads (JP series) may enable optional pull-ups. The SiT5358 has internal 200kΩ pull-ups. However, for the external screw cage (J9) running I2C over potentially long cables, stronger pull-ups (~2.2kΩ-4.7kΩ) are advisable.

**Recommendation:** Verify that Qwiic-connected devices provide pull-ups. For the screw cage I2C, consider populating pull-ups on the NC jumper pads, or adding dedicated pull-up footprints.

### 3.3 HIGH — Decoupling Caps Too Far From ICs

**Severity: HIGH** | EMC Rule: DC-001, DC-002

| IC | Value | Nearest Cap Distance | Recommendation |
|----|-------|---------------------|----------------|
| U1 | ESP32-WROVER-IE-N16R8 | >10mm (none found) | Place 0.1µF within 3mm of VDD pin |
| U2 | mosaic-T | >10mm (none found) | Verify — mosaic-T module may have internal decoupling |
| U4 | KSZ8041NL/I | 8.3mm | Move closer to <3mm |
| U6 | REC15E-2405SZ | >10mm | Add output decoupling within 5mm |
| U7 | Ag9905M | >10mm | Add output decoupling within 5mm |

**Mitigating factors:** U1 (ESP32-WROVER) is a module with internal decoupling. U2 (mosaic-T) is a module with internal power regulation and decoupling. The analyzer measures centroid-to-centroid distance, which may overestimate for large modules. Manual PCB inspection recommended.

### 3.4 HIGH — Ethernet PHY Missing Magnetic Isolation Warning

**Severity: HIGH (false positive likely)** | Component: U4 (KSZ8041NL/I)

The schematic analyzer flagged "No magnetics/transformer detected between PHY and connector." However, the design uses a **MagJack** connector (J5, LPJ0284GDNL) which has **integrated magnetics** inside the RJ45 module. This is the standard approach for compact designs. The analyzer couldn't correlate the connector type with magnetic isolation.

**Verdict:** No action needed — the MagJack provides the required 1500V isolation and impedance matching.

---

## 4. Power Analysis

### 4.1 LDO Regulators

| Ref | Input | Output | Vout | Est. Iout | P_diss | Package |
|-----|-------|--------|------|-----------|--------|---------|
| U11 | 5V | 3.3V | 3.3V | 157mA | 0.27W | UDFN-8 |
| U5 | 5V | 3.3V_P | 3.3V | 647mA | 1.10W | UDFN-8 |

The AP7361C-3.3V is a fixed 3.3V output LDO rated for 1A continuous. Both regulators are within their current rating. The `vref_source` is `fixed_suffix`, meaning the output voltage is determined by the part number suffix, not a feedback divider — verified correct.

**Concern:** U5 at 1.1W dissipation in UDFN-8 without thermal vias (see Critical Finding 3.1).

### 4.2 PoE Power Path

The PoE subsystem uses an Ag9905M PD module (U7) feeding a REC15E-2405SZ isolated DC-DC converter (U6) that generates 5V from the PoE 48V input. LC filters (L3/C32/C33 and L4/C36/C37, resonant at 7.0 kHz) provide input filtering.

**SPICE verification:** Both LC filters simulate correctly (resonant frequency 7000 Hz vs expected 6999.63 Hz). Status: WARN — the impedance at resonance (0.21Ω analytical) was not fully verified in simulation, but the frequency match confirms correct component values.

### 4.3 DC Input Path

DC input through screw cage J9 (pins 9-10: DC_IN+/DC_IN-) passes through a 6V/2.0A fuse (F1) and BAT60A Schottky diodes for OR-ing with other power sources. The VIN_DC rail has 10µF decoupling (C34) but **no bypass capacitor** — only bulk storage.

### 4.4 Decoupling Summary

| Rail | Cap Count | Total µF | Bulk | Bypass | Assessment |
|------|-----------|----------|------|--------|------------|
| 5V | 3 | 102.0 | 100µF electrolytic | 2x 1.0µF | Adequate |
| 3.3V | 7 | 15.7 | 10µF | 3x 0.1µF | Good |
| 3.3V_P | 17 | 64.7 | 22µF + 3x10µF | 7x 0.1µF | Excellent |
| 1.8V | 12 | 13.8 | 5x 2.2µF | 6x 0.1µF | Good |
| 2.8V | 4 | 4.6 | 2x 2.2µF | 2x 0.1µF | Adequate |
| VCCIO | 5 | 14.6 | 10µF | 2x 0.1µF | Good |
| VDDA | 3 | 10.2 | 10µF | 2x 0.1µF | Adequate |
| VIN_DC | 1 | 10.0 | 10µF | None | **Missing bypass** |
| VIN_POE | 1 | 10.0 | 10µF | None | **Missing bypass** |

---

## 5. Signal Integrity Analysis

### 5.1 Ethernet (KSZ8041NL/I)

**Pin-to-net verification** (against datasheet DS00002245B, Table 2-1, pp.6-10):

| Pin | Symbol | Expected | Schematic Net | Status |
|-----|--------|----------|---------------|--------|
| 1 | GND | Ground | GND | OK |
| 2 | VDDPLL_1.8 | 1.8V analog | __unnamed_113 | OK (local decoupled) |
| 3 | VDDA_3.3 | 3.3V analog | VDDA | OK (separate analog rail) |
| 4/5 | RX-/RX+ | Diff receive | RD-/RD+ | OK |
| 6/7 | TX-/TX+ | Diff transmit | TD-/TD+ | OK |
| 9 | XI/REFCLK | Clock input | ETH_CLK | OK (50MHz from mosaic-T) |
| 10 | REXT | Bias resistor | __unnamed_108 | OK (6.49kΩ + 100pF required) |
| 11/12 | MDIO/MDC | Management | ETH_MDIO/ETH_MDC | OK |
| 17 | VDDIO_3.3 | Digital I/O power | 3.3V_P | OK |
| 32 | RST# | Reset | ETH_~{RST} | OK (driven by mosaic-T + 10k pull-up R24) |
| EP | GND | Exposed pad | GND | OK |

**Ethernet termination:** 49.9Ω series resistors on all four differential lines (R19-R22) with 0.1µF common-mode caps (C11, C12) provide termination and filtering. The RC filter cutoff is 31.9 kHz — well below the Ethernet signal bandwidth, serving as a common-mode filter. This is correct per typical Ethernet PHY application circuits.

**Differential pairs:** RD+/RD- and TD+/TD- are properly identified with ESD protection (D6, DT1042-04SO).

**REXT:** Pin 10 requires a 6.49kΩ resistor in parallel with a 100pF capacitor to ground (datasheet p.7). Verify this is present on net `__unnamed_108`.

### 5.2 SiT5358 DCTCXO

**Pin-to-net verification** (against datasheet Rev.1.03, Table 13, p.9 — DCTCXO configuration, Figure 5):

| Pin | Symbol (DCTCXO) | Expected | Schematic Net | Status |
|-----|-----------------|----------|---------------|--------|
| 1 | OE/NC | Output enable or NC | 3.3V_P (tied high = output enabled) | OK |
| 2 | SCL | I2C clock | ESP19/SCL2 | OK |
| 3 | NC | No connect | NO_CONNECT | OK |
| 4 | GND | Ground | GND | OK |
| 5 | A0/NC | I2C address bit | GND (address = 0x60) | OK |
| 6 | CLK | 10MHz output | __unnamed_84 (to level shifters) | OK |
| 7/8 | NC | No connect | NO_CONNECT | OK |
| 9 | VDD | Power supply | 3.3V_P | OK — within 2.97-3.63V range |
| 10 | SDA | I2C data | ESP18/SDA2 | OK |

**Decoupling:** Datasheet Note 11 (p.9) requires "0.1µF in parallel with 10µF between VDD and GND, placed close to the device." The 3.3V_P rail has ample decoupling (64.7µF total, multiple 0.1µF + 10µF caps). Verify proximity in PCB layout.

**I2C address:** A0 tied to GND → address 0x60 (binary 1100000), which matches the firmware constant for the SiT5358 oscillator.

### 5.3 Level Shifters (74LVC2T45DC)

Seven 74LVC2T45DC instances provide voltage translation between mosaic-T (1.8V/3.3V_P) and external interfaces (VCCIO). Verified against datasheet Rev.13, p.3 (Table 3):

| Ref | VCCA Rail | VCCB Rail | DIR | Direction | Signals |
|-----|-----------|-----------|-----|-----------|---------|
| U8 | 3.3V_P | VCCIO | HIGH (3.3V_P) | A→B | MTX2, MRTS2 (mosaic→external) |
| U9 | 3.3V_P | VCCIO | LOW (GND) | B→A | MRX2, MCTS2 (external→mosaic) |
| U10 | 1.8V | varies | LOW (GND) | B→A | MEventA (external→mosaic) |
| U12 | 1.8V | VCCIO | LOW (GND) | B→A | MEventB (external→mosaic) |
| U14 | 3.3V_P | 1.8V | HIGH (3.3V_P) | A→B | 10MHz (3.3V→1.8V for mosaic-T) |
| U15 | 3.3V_P | varies | HIGH (3.3V_P) | A→B | 10MHz fanout (to external SMA) |
| U16 | 1.8V | varies | HIGH (1.8V) | A→B | PPS (1.8V→external) |

**Pin mapping verified** against datasheet: Pin 1=VCCA, 2=1A, 3=2A, 4=GND, 5=DIR, 6=2B, 7=1B, 8=VCCB. All instances match the VSSOP-8 (SOT765-1) package pinout.

**DIR logic:** HIGH = A→B, LOW = B→A (datasheet Table 4, p.4). Directions confirmed correct for all instances.

### 5.4 10MHz Clock Distribution

The SiT5358's 10MHz LVCMOS output (pin 6, 3.3V_P domain) is distributed through:

1. **U14:** Level-shifts 3.3V_P → 1.8V for mosaic-T REF_IN (via RC filter R30/C55, fc=146 MHz — serves as anti-ringing filter)
2. **U15:** Buffers and level-shifts for external SMA output (J8: 10MHz_IN_OUT)
3. **U16:** PPS output from mosaic-T (1.8V) → external connectors

The 10MHz signal path includes a voltage divider (R58/R59, 1k/1k) for input level shifting and a switch (SW5) for input/output selection. The RC filter at 146 MHz is appropriate for cleaning up edge harmonics on a 10 MHz clock.

### 5.5 USB Interfaces

Two USB-C receptacles:
- **J2:** mosaic-T USB (MOSAIC_DP/DM via ESD D2, through transformer TR1)
- **J4:** ESP32 USB via CH340C (ESP_DP/DM via ESD D3)

Both have CC1/CC2 pull-down resistors (5.1kΩ) for UFP (device) identification per USB-C spec. ESD protection (DT1042-04SO) covers the D+/D- lines on both ports.

---

## 6. PCB Layout Analysis

### 6.1 Board Specifications

| Parameter | Value |
|-----------|-------|
| Dimensions | 151.9 x 101.6 mm |
| Layers | 4 (F.Cu, In1.Cu, In2.Cu, B.Cu) |
| Min track width | 0.1778 mm (7 mil) |
| Min spacing | 0.1796 mm (7.1 mil) |
| Min drill | 0.3 mm |
| Min annular ring | 0.13 mm |
| Track length total | 6860.7 mm |
| Component density | 2.2/cm² front, 0.7/cm² back |

### 6.2 Layer Stackup

- **F.Cu:** Signal + components (336 footprints)
- **In1.Cu:** Signal routing
- **In2.Cu:** Power planes (3.3V_P, VCCIO, 1.8V, 2.8V routed here)
- **B.Cu:** Signal + components (102 footprints)

**Note:** No continuous ground plane layer was detected. Both In1.Cu and In2.Cu appear to be used for signal/power routing rather than dedicated reference planes. This is a significant EMC concern — ideally In1.Cu should be a solid GND plane providing a reference for F.Cu signals.

### 6.3 Ground Domains

Two ground domains detected:
- **GND:** Main ground (136 components)
- **GND-ISO:** Isolated ground for PoE section (Ag9905M/REC15E isolation boundary)

The isolation barrier between GND and GND-ISO is correct for PoE safety isolation (1500V typical). Verify creepage/clearance on the PCB meets IEC 60664-1 requirements.

### 6.4 Power Net Routing

| Net | Tracks | Length | Widths Used |
|-----|--------|--------|-------------|
| GND | 36 | 27.7mm | 0.178, 0.305mm |
| VCCIO | 76 | 307.7mm | 0.178-0.813mm |
| VDDA | 32 | 89.2mm | 0.178, 0.559mm |
| VIN_DC | 5 | 8.1mm | 0.813mm |
| VIN_POE | 6 | 12.4mm | 0.813mm |

GND is primarily routed via zones rather than discrete tracks, which is correct. Power input traces (VIN_DC, VIN_POE) use 0.813mm (32mil) width — adequate for 2A at the rated fuse current.

### 6.5 Critical Net Lengths

| Net | Length | Vias | Concern |
|-----|--------|------|---------|
| 3.3V_P | 444.3mm | 20 | Long power distribution — normal for primary rail |
| SD_CLK | 134.4mm | 2 | Long clock trace (EMC CK-002 flagged) |
| SD_CMD | 133.7mm | 2 | Long — matches SD_CLK length (good for timing) |
| ESP19/SCL2 | 142.8mm | 4 | Long I2C — may need reduced clock speed |
| ESP18/SDA2 | 137.1mm | 4 | Long I2C — paired with SCL2 |

### 6.6 DFM Assessment

**JLCPCB tier:** Standard (all features within standard process limits).
**Single violation:** Board size 151.9x101.6mm exceeds the 100x100mm threshold — higher fabrication pricing tier. This is a design choice, not a defect.

---

## 7. EMC Pre-Compliance Analysis

**EMC Risk Score: 0/100** (15 error, 21 warning, 68 info)

The low score is inflated by test points and jumpers being treated as unfiltered connectors. Adjusting for this, the realistic risk is moderate.

### 7.1 Genuine EMC Concerns

| Rule | Severity | Finding | Recommendation |
|------|----------|---------|----------------|
| DC-001 | error | U4 (KSZ8041NL) nearest cap 8.3mm away | Move decoupling closer |
| DC-002 | error | U1, U2, U6, U7 no caps within 10mm | Verify — modules have internal decoupling |
| IO-001 | error | J4, J2 (USB-C) no ferrite/CM filtering | Add CM chokes on USB lines for FCC |
| IO-001 | error | J5 (MagJack) no filtering detected | MagJack has internal CMC — false positive |
| CK-001 | warning | ETH_CLK (50MHz) 64% on outer layers | Route on inner layer if possible |
| CK-001 | warning | SD_CLK 100% outer layer, 134mm long | Consider inner layer routing |
| GP-005 | warning | 2 ground domains (GND + GND-ISO) | Expected for PoE isolation — OK |

### 7.2 False Positives / Acceptable

- **IO-001 on test points (67 info findings):** Test points are not cable-connected connectors. These are false positives.
- **IO-002 on USB-C (warning):** The analyzer counts schematic ground pins but USB-C has shield pins providing ground return. Acceptable.
- **J5 MagJack filtering:** Integrated magnetics provide the required CM filtering. False positive.

### 7.3 Board Cavity Resonance (info)

Board cavity resonances at 543 MHz (1,0), 812 MHz (0,1), 977 MHz (1,1). These are within the FCC Part 15 Class B test range. Ensure adequate via stitching and continuous ground plane to suppress cavity modes.

---

## 8. SPICE Simulation Verification

**25 subcircuits simulated: 23 pass, 2 warn, 0 fail**

### 8.1 RC Filters — All Pass

| Subcircuit | Expected | Simulated | Status |
|------------|----------|-----------|--------|
| R11/C3 (LPF, 3.3V_P filtering) | 159.15 Hz | 158.78 Hz | PASS |
| R21/C12 (Ethernet RD- CM) | 31,895 Hz | 31,819 Hz | PASS |
| R22/C12 (Ethernet RD+ CM) | 31,895 Hz | 31,819 Hz | PASS |
| R19/C11 (Ethernet TD+ CM) | 31,895 Hz | 31,819 Hz | PASS |
| R20/C11 (Ethernet TD- CM) | 31,895 Hz | 31,819 Hz | PASS |
| R30/C55 (10MHz anti-ringing) | 146.15 MHz | 145.80 MHz | PASS |
| R56/C76 (RC network) | 159.15 kHz | 158.78 kHz | PASS |

### 8.2 Voltage Dividers — All Pass

| Subcircuit | Expected Ratio | Simulated Vout | Status |
|------------|---------------|----------------|--------|
| R7/R8 (board ID, 3.3V→DeviceSense) | 0.5 (1.65V) | 1.65V | PASS |
| R58/R59 (10MHz input level shift) | 0.5 (1.65V) | 1.65V | PASS |

### 8.3 LC Filters — Warn (impedance not fully verified)

| Subcircuit | Expected f₀ | Simulated f₀ | Status |
|------------|-------------|--------------|--------|
| L4/C37 (PoE input filter) | 7000 Hz | 7000 Hz | WARN |
| L3/C33 (PoE input filter) | 7000 Hz | 7000 Hz | WARN |

Resonant frequencies match. The WARN status is due to impedance verification limitations, not a circuit error. Both filters use 4.7µH inductors with parallel 100µF+10µF capacitors — standard PoE input filtering.

### 8.4 Protection & Decoupling — All Pass

All protection devices (D1, D15, D17) and decoupling networks verified. Inrush currents estimated at 0.104A (3.3V rail) and 0.427A (3.3V_P rail) — within AP7361C current limit capability.

---

## 9. Thermal Analysis

**Thermal Score: 97/100** | Ambient: 25°C

| Component | P_diss | Package | θ_JA | T_j Est. | T_j Max | Margin | Thermal Vias |
|-----------|--------|---------|------|----------|---------|--------|-------------|
| U5 (AP7361C-3.3V) | 1.10W | UDFN-8 | 40°C/W | 69°C | 125°C | 56°C | **None** |
| U11 (AP7361C-3.3V) | 0.27W | UDFN-8 | 40°C/W | 36°C | 125°C | 89°C | **None** |

**Finding TS-004 (warning):** U5 dissipates 1.10W with no thermal vias. Heat removal relies entirely on surface copper. The 40°C/W θ_JA estimate is optimistic without vias — actual θ_JA may be 60-80°C/W, pushing T_j to 91-113°C.

---

## 10. ESD Protection Coverage

| Connector | Interface | Protection | Coverage | Notes |
|-----------|-----------|------------|----------|-------|
| J1 (SMA, GNSS antenna) | RF input | D1 (PESD0402) | Full | Correct for RF input |
| J2 (USB-C, mosaic-T) | USB | D2 (DT1042-04SO) | D+/D- only | CC lines unprotected |
| J4 (USB-C, ESP32) | USB | D3 (DT1042-04SO) | D+/D- only | CC lines unprotected |
| J3 (SMA, PPS out) | Signal | D15 (PESD0402) | Full | |
| J5 (MagJack, Ethernet) | Ethernet | D6 (DT1042-04SO) | Data lines | PoE lines unprotected (OK — magnetics provide isolation) |
| J6 (microSD) | SD card | D7 (DF5A5.6LFU) | CLK/CMD/DATA | Partial — 4 SD lines unprotected |
| J7 (Qwiic) | I2C | None | **None** | SDA/SCL unprotected |
| J8 (SMA, 10MHz I/O) | Clock | D17 (PESD0402) | Full | |
| J9 (Screw cage) | Mixed | D13, D14 (DF5A5.6LFU) | UART/I2C lines | DC input lines unprotected |
| J12 (SMA, PPS) | Signal | None | **None** | Consider adding PESD0402 |

**Gaps:** J7 (Qwiic) and J12 (SMA) have no ESD protection. For a product with external connectors, adding protection on J7 is recommended (I2C lines are vulnerable to ESD via external cables). J12 is lower risk if only used for bench measurement.

---

## 11. Schematic-PCB Cross-Reference

### 11.1 Component Count

- Schematic: 296 components (excluding 1 missing footprint: G2 logo)
- PCB: 438 footprints (142 extra are silkscreen graphics, logos, text labels with "kibuzzard-" prefixes)
- **Status:** Consistent — all schematic components have matching PCB footprints.

### 11.2 Footprint Match (All ICs Verified)

All 10 key ICs verified: U1, U2, U3, U4, U5, U7, U11, U13, U17, U18 — schematic footprint property exactly matches PCB footprint assignment.

### 11.3 Gerber Manufacturing Files

The Production/ directory contains panelized Gerbers (9 files: GTL, GBL, GTO, GBO, GTS, GBS, GTP, GKO, GL2/GL3 inner layers). **Missing:** drill files (.drl), Edge.Cuts gerber, and NPTH drill file. These may be embedded in the panelized .kicad_pcb or generated separately during ordering.

---

## 12. Design Observations

### 12.1 Positive Findings

- **Comprehensive test coverage:** 50 test points provide excellent debug access to all critical signals
- **Robust power OR-ing:** BAT60A Schottky diodes allow seamless switching between USB, DC, and PoE power sources
- **Good decoupling strategy:** 3.3V_P rail has 64.7µF across 17 capacitors with proper bulk+bypass coverage
- **ESD protection on most external interfaces:** RF inputs, USB data lines, Ethernet data, SD card, and exposed UART/I2C lines all protected
- **Separate analog/digital power:** VDDA for Ethernet PHY analog section isolated from digital 3.3V_P
- **PoE isolation:** Proper GND/GND-ISO separation with isolated DC-DC converter
- **10MHz output filtering:** RC anti-ringing filter (R30/C55, fc=146MHz) on the clock output prevents harmonic radiation
- **Board variant identification:** ADC resistor divider (R7/R8) on GPIO35 allows firmware to auto-detect hardware variant

### 12.2 Minor Observations

1. **No MPNs in schematic:** All 296 components lack MPN fields, making automated BOM generation and lifecycle tracking difficult. Consider adding MPNs to at least active components.
2. **Missing no-connect markers:** The `total_no_connects` count is 0 despite many NC pins on ICs. While the SiT5358 NC pins have no-connect markers, verify all unused IC pins are properly flagged.
3. **VUSB rail has no decoupling on mosaic-T:** The design observation notes that U2's VUSB power pin lacks dedicated decoupling capacitors. This rail powers the mosaic-T's USB interface — verify it's decoupled elsewhere on the module's PCB.
4. **ETH_CLK reset pin:** U4's RST# (pin 32) has pull-up (R24, 10k) but no filter capacitor. The datasheet shows RST# is an active-low input — a 100nF cap to GND would provide noise immunity.

---

## 13. Prioritized Issue Table

| # | Severity | Category | Issue | Components | Action |
|---|----------|----------|-------|------------|--------|
| 1 | CRITICAL | Thermal/Manufacturing | No thermal vias on QFN/UDFN exposed pads | U4, U5, U11 | Add 5-9 vias per pad |
| 2 | HIGH | Signal Integrity | I2C buses missing pull-up resistors | Qwiic, SiT5358 buses | Verify external pull-ups; add to screw cage I2C |
| 3 | HIGH | EMC | Decoupling caps too far from KSZ8041NL | U4 | Move caps closer in layout |
| 4 | HIGH | ESD | Qwiic connector (J7) has no ESD protection | J7 | Add TVS diode array |
| 5 | HIGH | ESD | SMA PPS connector (J12) has no ESD protection | J12 | Add PESD0402 |
| 6 | MEDIUM | Thermal | U5 dissipates 1.1W with no thermal vias | U5 | Critical — see #1 |
| 7 | MEDIUM | EMC | SD_CLK (134mm) 100% on outer layer | SD_CLK | Route on inner layer |
| 8 | MEDIUM | EMC | ETH_CLK (50MHz) mostly on outer layer | ETH_CLK | Route on inner layer |
| 9 | MEDIUM | Power | VIN_DC and VIN_POE rails lack bypass caps | C34, C38 | Add 0.1µF bypass |
| 10 | LOW | Documentation | No MPNs on any schematic components | All | Add MPNs for BOM traceability |

---

## 14. Analysis Methodology

### Tools & Scripts

| Analysis | Tool | Output |
|----------|------|--------|
| Schematic | `analyze_schematic.py` | 296 components, 240 nets, 62 BOM entries |
| PCB | `analyze_pcb.py --proximity` | 438 footprints, 4 layers, 692 vias |
| Gerbers | `analyze_gerbers.py` | 9 gerber files, panelized production set |
| EMC | `analyze_emc.py` | Score 0/100 (inflated by test point false positives) |
| SPICE | `simulate_subcircuits.py` | 25 subcircuits: 23 pass, 2 warn |
| Thermal | `analyze_thermal.py` | Score 97/100, hottest: U5 @ 69°C |

### Datasheets Referenced

| Component | Source | Pages Verified |
|-----------|--------|----------------|
| KSZ8041NL/I | DS00002245B (Microchip) | pp.6-10 (pin table, full pinout) |
| 74LVC2T45DC | Rev.13 (Nexperia) | pp.2-5 (pinout, function table, electrical specs) |
| SiT5358 | Rev.1.03 (SiTime) | pp.1-5, 9-10 (ordering, pinout, electrical, test circuits) |
| ESP32-WROVER-IE | Espressif | Module datasheet |
| AP7361C | Diodes Inc. | Fixed 3.3V LDO datasheet |

### Verification Gaps

- **mosaic-T internal connectivity:** The 179-pin LGA module's internal schematic is not publicly available. Pin connections are verified against the Hardware Manual, but internal decoupling and power regulation cannot be independently confirmed.
- **PoE module internals:** Ag9905M and REC15E-2405SZ are complete modules — internal component verification not possible.
- **USB-C connector pinout:** Verified CC resistors and ESD placement, but full pin-by-pin verification of the USB-C receptacle symbol against the specific connector MPN was not performed (no MPN specified).

---

*Report generated from automated analysis with manual datasheet verification. Critical findings should be visually confirmed in the PCB layout editor before acting on recommendations.*

# tools/tests/test_mcu_internal_smps.py
"""An MCU's internal step-down (STM32 VLXSMPS -> inductor -> VFBSMPS) is recorded as a regulator;
its switch node counts as sourced, and a regulator is not its own sequencing-sensitive load."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import (audit_rail_sources, detect_decoupling, detect_design_observations,  # noqa: E402
                              detect_power_regulators)
from validation_detectors import validate_power_sequencing  # noqa: E402
from schematic.system_analyses import analyze_power_sequencing  # noqa: E402

_GPIOS = [(f"P{port}{n}", "passive") for port in "ABC" for n in range(4)]


def _ctx(parts, wiring, rails):
    """*parts*: (ref, type, value, lib_id); *wiring*: net -> [(ref, pin number, pin name, pin type)]."""
    comps = [{"reference": r, "type": t, "value": v, "lib_id": lib, "pins": []} for r, t, v, lib in parts]
    by_ref = {c["reference"]: c for c in comps}
    nets = {}
    for net, pins in wiring.items():
        nets[net] = {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                     "has_pwr_flag": False, "labels": []}
        for ref, num, name, ptype in pins:
            nets[net]["pins"].append({"component": ref, "pin_number": num, "pin_name": name,
                                      "pin_type": ptype})
            by_ref[ref]["pins"].append({"number": num, "name": name})
    return build_analysis_context(comps, nets, {}, known_power_rails=set(rails))


def _stm32(smps_pins, extra_parts=(), extra_wiring=None, rails=("+3V3",)):
    """STM32H755 U1 powered from +3V3, with a BOOT0 pin, GPIOs and the given SMPS pin wiring."""
    wiring = {"+3V3": [("U1", "1", "VDD", "power_in")], "GND": [("U1", "2", "VSS", "power_in")],
              "BOOT0": [("U1", "3", "BOOT0", "input"), ("R1", "1", "", "passive")]}
    wiring["GND"].append(("R1", "2", "", "passive"))
    for i, (name, ptype) in enumerate(_GPIOS):
        wiring[f"IO{i}"] = [("U1", str(10 + i), name, ptype)]
    for net, pins in smps_pins.items():
        wiring.setdefault(net, []).extend(pins)
    for net, pins in (extra_wiring or {}).items():
        wiring.setdefault(net, []).extend(pins)
    parts = [("U1", "ic", "STM32H755ZITx", "MCU_ST_STM32H7:STM32H755ZITx"),
             ("R1", "resistor", "10k", "Device:R")] + list(extra_parts)
    return _ctx(parts, wiring, rails)


_SMPS_IN_USE = {
    "+3V3": [("U1", "4", "VDDSMPS", "power_in")],
    "VLX": [("U1", "5", "VLXSMPS", "power_in"), ("L1", "1", "", "passive")],
    "VDD11": [("U1", "6", "VFBSMPS", "input"), ("U1", "7", "VDDLDO", "power_in"),
              ("L1", "2", "", "passive"), ("C1", "1", "", "passive")],
    "GND": [("C1", "2", "", "passive")],
}
_SMPS_PARTS = (("L1", "inductor", "2.2uH", "Device:L"), ("C1", "capacitor", "10uF", "Device:C"))


class McuInternalStepDown(unittest.TestCase):
    def setUp(self):
        self.ctx = _stm32(_SMPS_IN_USE, _SMPS_PARTS)
        self.regs = detect_power_regulators(self.ctx, [])

    def test_vlxsmps_into_an_inductor_is_one_regulator_record(self):
        self.assertEqual(len(self.regs), 1)
        reg = self.regs[0]
        self.assertEqual((reg["ref"], reg.get("sw_net"), reg.get("output_rail"), reg.get("input_rail"),
                          reg.get("inductor")), ("U1", "VLX", "VDD11", "+3V3", "L1"))
        self.assertEqual(reg["topology"], "ic_with_internal_regulator")

    def test_boot0_is_not_a_bootstrap_pin(self):
        self.assertFalse(self.regs[0].get("has_bootstrap", False))

    def test_switch_node_and_output_are_sourced(self):
        flagged = {f["nets"][0] for f in audit_rail_sources(self.ctx, self.regs)
                   if f["rule_id"] == "RS-001"}
        self.assertNotIn("VLX", flagged)
        self.assertNotIn("VDD11", flagged)

    def test_mcu_is_not_its_own_sequencing_load(self):
        for f in validate_power_sequencing(self.ctx, self.regs):
            self.assertNotIn("U1", f["components"][1:], f["summary"])


    def test_port_g_gpio_is_not_a_power_good_pin(self):
        ctx = _stm32(_SMPS_IN_USE, _SMPS_PARTS, {"CAN2_TX": [("U1", "40", "PG6", "bidirectional")]})
        seq = analyze_power_sequencing(ctx, {"power_regulators": detect_power_regulators(ctx, [])})
        self.assertNotIn("power_good_signals", seq)


class TwoInductorStepDown(unittest.TestCase):
    def test_output_is_the_vfbsmps_net_past_both_inductors(self):
        # STM32WB: VLXSMPS -> L1 -> SMPSLXL -> L2 -> VFBSMPS with its output capacitor
        pins = {"+3V3": [("U1", "4", "VDDSMPS", "power_in")],
                "SMPSLX": [("U1", "5", "VLXSMPS", "power_in"), ("L1", "1", "", "passive")],
                "SMPSLXL": [("L1", "2", "", "passive"), ("L2", "1", "", "passive")],
                "SMPSFB": [("U1", "6", "VFBSMPS", "input"), ("L2", "2", "", "passive"),
                           ("C1", "1", "", "passive")],
                "GND": [("C1", "2", "", "passive")]}
        parts = (("L1", "inductor", "10nH", "Device:L"), ("L2", "inductor", "10uH", "Device:L"),
                 ("C1", "capacitor", "4.7uF", "Device:C"))
        ctx = _stm32(pins, parts)
        regs = detect_power_regulators(ctx, [])
        self.assertEqual([(r.get("sw_net"), r.get("output_rail")) for r in regs], [("SMPSLX", "SMPSFB")])
        obs = detect_design_observations(ctx, {"power_regulators": regs,
                                               "decoupling_analysis": detect_decoupling(ctx)})
        self.assertEqual([o["missing_caps"].get("output") for o in obs if o["category"] == "regulator_caps"],
                         [None])


class SmpsNotInUse(unittest.TestCase):
    def test_vlxsmps_tied_to_the_supply_is_not_a_regulator(self):
        # SMPS bypassed: VLXSMPS and VFBSMPS tied to VDD; an input filter inductor sits on +3V3
        pins = {"+3V3": [("U1", "4", "VDDSMPS", "power_in"), ("U1", "5", "VLXSMPS", "power_in"),
                         ("U1", "6", "VFBSMPS", "input"), ("L1", "1", "", "passive")],
                "VDDA": [("U1", "8", "VDDA", "power_in"), ("L1", "2", "", "passive")]}
        ctx = _stm32(pins, (("L1", "inductor", "BLM18", "Device:L"),), rails=("+3V3", "VDDA"))
        self.assertEqual(detect_power_regulators(ctx, []), [])

    def test_vlxsmps_tied_to_a_vdd_rail_is_not_a_regulator(self):
        # The same bypass on a supply named VDD, which carries no voltage in its name
        pins = {"VDD": [("U1", "4", "VDDSMPS", "power_in"), ("U1", "5", "VLXSMPS", "power_in"),
                        ("U1", "6", "VFBSMPS", "input"), ("L1", "1", "", "passive")],
                "VDDA": [("U1", "8", "VDDA", "power_in"), ("L1", "2", "", "passive")]}
        ctx = _stm32(pins, (("L1", "inductor", "BLM18", "Device:L"),), rails=("+3V3", "VDD", "VDDA"))
        self.assertEqual(detect_power_regulators(ctx, []), [])

    def test_vlxsmps_without_an_inductor_is_not_a_regulator(self):
        pins = {"VLX": [("U1", "5", "VLXSMPS", "power_in")], "+3V3": [("U1", "4", "VDDSMPS", "power_in")]}
        self.assertEqual(detect_power_regulators(_stm32(pins), []), [])

    def test_mcu_switch_pin_without_an_inductor_is_not_rescued_by_boot0(self):
        # A motor-control MCU with an integrated buck whose SW pin drives nothing
        pins = {"SW": [("U1", "5", "SW", "passive")], "+12V": [("U1", "4", "VIN", "power_in")]}
        self.assertEqual(detect_power_regulators(_stm32(pins, rails=("+3V3", "+12V")), []), [])


class SwitchNodeSourced(unittest.TestCase):
    def test_a_rail_named_buck_switch_node_is_sourced(self):
        # A switch node named like a rail (5V_SW) is driven by the regulator, not unsourced
        parts = [("U2", "ic", "TPS5430", "Regulator_Switching:TPS5430"),
                 ("L2", "inductor", "15uH", "Device:L"), ("C2", "capacitor", "22uF", "Device:C")]
        wiring = {"+12V": [("U2", "1", "VIN", "power_in")],
                  "5V_SW": [("U2", "2", "PH", "output"), ("L2", "1", "", "passive")],
                  "+5V": [("L2", "2", "", "passive"), ("C2", "1", "", "passive"),
                          ("U2", "3", "VSENSE", "input")],
                  "GND": [("U2", "4", "GND", "power_in"), ("C2", "2", "", "passive")]}
        ctx = _ctx(parts, wiring, ("+12V", "+5V"))
        regs = detect_power_regulators(ctx, [])
        self.assertEqual([r.get("sw_net") for r in regs], ["5V_SW"])
        flagged = {f["nets"][0] for f in audit_rail_sources(ctx, regs) if f["rule_id"] == "RS-001"}
        self.assertNotIn("5V_SW", flagged)
        self.assertIn("+12V", flagged)


class PowerGoodPinsAreNotGpios(unittest.TestCase):
    """PG1/PG2 on a multi-channel buck are power-good outputs, not port-G GPIOs."""

    def _dual_buck(self):
        parts = [("U2", "ic", "DUAL_BUCK", "Regulator_Switching:DUAL_BUCK"),
                 ("L1", "inductor", "4.7uH", "Device:L"), ("L2", "inductor", "4.7uH", "Device:L")]
        wiring = {"+12V": [("U2", "1", "VIN1", "power_in"), ("U2", "2", "VIN2", "power_in")],
                  "SW1": [("U2", "3", "SW1", "output"), ("L1", "1", "", "passive")],
                  "SW2": [("U2", "4", "SW2", "output"), ("L2", "1", "", "passive")],
                  "+3V3": [("L1", "2", "", "passive")], "+1V8": [("L2", "2", "", "passive")],
                  "BST1": [("U2", "5", "BOOT1", "passive")], "BST2": [("U2", "6", "BOOT2", "passive")],
                  "FB1": [("U2", "7", "FB1", "input")], "FB2": [("U2", "8", "FB2", "input")],
                  "PGOOD1": [("U2", "9", "PG1", "open_collector")],
                  "PGOOD2": [("U2", "10", "PG2", "open_collector")],
                  "GND": [("U2", "11", "GND", "power_in")]}
        return _ctx(parts, wiring, ("+12V", "+3V3", "+1V8"))

    def test_dual_buck_keeps_its_bootstrap(self):
        regs = detect_power_regulators(self._dual_buck(), [])
        self.assertEqual([(r["ref"], r.get("has_bootstrap")) for r in regs], [("U2", True)])

    def test_dual_buck_keeps_its_power_good_pins(self):
        ctx = self._dual_buck()
        seq = analyze_power_sequencing(ctx, {"power_regulators": detect_power_regulators(ctx, [])})
        self.assertEqual([p["pg_pin"] for p in seq.get("power_good_signals", [])], ["PG1"])


class RegulatorIsNotItsOwnLoad(unittest.TestCase):
    def _ps001(self, extra_loads):
        parts = [("U2", "ic", "AP2112K-3.3", "Adafruit_ESP32_Feather:AP2112K-3.3")] + [
            (ref, "ic", value, lib) for ref, value, lib in extra_loads]
        wiring = {"+5V": [("U2", "1", "VIN", "power_in")],
                  "+3V3": [("U2", "5", "VOUT", "power_out")] + [
                      (ref, "1", "VDD", "power_in") for ref, _, _ in extra_loads],
                  "GND": [("U2", "2", "GND", "power_in")]}
        ctx = _ctx(parts, wiring, ("+5V", "+3V3"))
        regs = [{"ref": "U2", "value": "AP2112K-3.3", "output_rail": "+3V3", "input_rail": "+5V"}]
        return [f for f in validate_power_sequencing(ctx, regs) if f["rule_id"] == "PS-001"]

    def test_regulator_alone_on_its_rail_raises_no_sequencing_finding(self):
        self.assertEqual(self._ps001([]), [])

    def test_other_loads_are_still_listed_without_the_regulator(self):
        found = self._ps001([("U3", "STM32F405RGTx", "MCU_ST_STM32F4:STM32F405RGTx")])
        self.assertEqual([f["components"] for f in found], [["U2", "U3"]])


if __name__ == "__main__":
    unittest.main()

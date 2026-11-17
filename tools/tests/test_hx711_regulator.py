# tools/tests/test_hx711_regulator.py
"""The HX711's analog-supply regulator (an LDO controller: VSUP in, BASE drives an external PNP,
AVDD out, VFB senses a divider) is recorded as an LDO with VAVDD = VBG x (R1 + R2) / R1, VBG
1.25 V; an HX711 wired with the regulator unused (VFB to ground, BASE open) is not a regulator."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_power_regulators, detect_voltage_dividers  # noqa: E402

# The HX711's own pins that are not part of the regulator
_ADC_PINS = {"INA-": "input", "INA+": "input", "INB-": "input", "INB+": "input", "PD_SCK": "input",
             "DOUT": "output", "XO": "passive", "XI": "passive", "RATE": "input", "DVDD": "power_in"}


def _ctx(wiring, parts, rails=("5V",)):
    """*wiring*: net -> [(ref, pin name)]; *parts*: (ref, type, value, lib_id)."""
    comps = [{"reference": r, "type": t, "value": v, "lib_id": lib, "pins": []} for r, t, v, lib in parts]
    by_ref = {c["reference"]: c for c in comps}
    nets = {}
    for net, pins in wiring.items():
        nets[net] = {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                     "has_pwr_flag": False, "labels": []}
        for ref, name in pins:
            num = str(len(by_ref[ref]["pins"]) + 1)
            nets[net]["pins"].append({"component": ref, "pin_number": num, "pin_name": name,
                                      "pin_type": "passive"})
            by_ref[ref]["pins"].append({"number": num, "name": name})
    return build_analysis_context(comps, nets, {}, known_power_rails=set(rails))


def _hx711(regulator_wiring, extra_parts=()):
    wiring = {"5V": [("U3", "VSUP")], "GND": [("U3", "AGND")], "VBG": [("U3", "VBG"), ("C2", "1")]}
    wiring["GND"].append(("C2", "2"))
    for name in _ADC_PINS:
        wiring[f"ADC_{name}"] = [("U3", name)]
    for net, pins in regulator_wiring.items():
        wiring.setdefault(net, []).extend(pins)
    parts = [("U3", "ic", "HX711", "SparkFun-Sensor:HX711"),
             ("C2", "capacitor", "0.1uF", "Device:C")] + list(extra_parts)
    return _ctx(wiring, parts)


# SparkFun OpenScale: Q2 (S8550) emitter on 5V, base on BASE, collector on AVDD;
# R12 20k from AVDD to VFB, R9 8.2k from VFB to ground
_SPARKFUN = {
    "5V": [("Q2", "E")],
    "__unnamed_14": [("U3", "BASE"), ("Q2", "B")],
    "__unnamed_15": [("U3", "AVDD"), ("Q2", "C"), ("R12", "1"), ("C6", "1")],
    "__unnamed_16": [("U3", "VFB"), ("R12", "2"), ("R9", "1")],
    "GND": [("R9", "2"), ("C6", "2")],
}
_SPARKFUN_PARTS = (("Q2", "transistor", "S8550", "Device:Q_PNP_BEC"),
                   ("R12", "resistor", "20k", "Device:R"), ("R9", "resistor", "8.2k", "Device:R"),
                   ("C6", "capacitor", "10uF", "Device:C"))


def _regulators(ctx):
    return detect_power_regulators(ctx, detect_voltage_dividers(ctx)["voltage_dividers"])


class AnalogSupplyRegulatorInUse(unittest.TestCase):
    def setUp(self):
        self.regs = _regulators(_hx711(_SPARKFUN, _SPARKFUN_PARTS))

    def test_one_ldo_record_from_vsup_to_avdd(self):
        self.assertEqual([(r["ref"], r["topology"], r.get("input_rail"), r.get("output_rail"))
                          for r in self.regs], [("U3", "LDO", "5V", "__unnamed_15")])

    def test_avdd_is_the_bandgap_times_the_divider_gain(self):
        reg = self.regs[0]
        self.assertEqual((reg.get("assumed_vref"), reg.get("vref_source"), reg.get("estimated_vout")),
                         (1.25, "lookup", 4.299))
        self.assertEqual(reg["feedback_divider"]["r_top"]["ref"], "R12")

    def test_the_external_pass_transistor_not_the_ic_dissipates_the_drop(self):
        self.assertNotIn("power_dissipation", self.regs[0])


class AnalogSupplyRegulatorUnused(unittest.TestCase):
    def test_vfb_to_ground_and_base_open_is_not_a_regulator(self):
        # Datasheet: with the regulator unused VFB goes to AGND, BASE is NC, VSUP ties to AVDD
        ctx = _hx711({"5V": [("U3", "AVDD")], "GND": [("U3", "VFB")], "BASE_NC": [("U3", "BASE")]})
        self.assertEqual(_regulators(ctx), [])

    def test_base_driving_nothing_is_not_a_regulator(self):
        # BASE on a net of its own: no pass transistor, so AVDD is not regulated from VSUP
        ctx = _hx711({"5V": [("U3", "AVDD")], "BASE_NC": [("U3", "BASE")],
                      "FB": [("U3", "VFB"), ("R9", "1")], "GND": [("R9", "2")]},
                     (("R9", "resistor", "8.2k", "Device:R"),))
        self.assertEqual(_regulators(ctx), [])


if __name__ == "__main__":
    unittest.main()

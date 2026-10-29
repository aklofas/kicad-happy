# tools/tests/test_net_classification_tokens.py
"""Net classes: keywords match name tokens (a whole token, or its start or end), a supply-stem
token such as VCCINT is never a keyword hit, and a net left as a plain signal whose IC pins are
all supply inputs by type and by name is power."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _classify_nets  # noqa: E402


def _comp(ref, ctype, value):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": "", "pins": []}


def _classes(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(components, full, {}, known_power_rails={"+3V3", "GND"})
    return _classify_nets(ctx)


PARTS = [_comp("U1", "ic", "XC7A35T"), _comp("U2", "ic", "STM32F103C8Tx"),
         _comp("U3", "ic", "STM32WB55CEU6"), _comp("U4", "ic", "TPS62A01"),
         _comp("U5", "ic", "Pico"), _comp("U6", "ic", "MT41K256M16TW"),
         _comp("U7", "ic", "AD5697R"), _comp("U8", "ic", "AMS1117-3.3"),
         _comp("C1", "capacitor", "100n"), _comp("C2", "capacitor", "10u"),
         _comp("R1", "resistor", "1k"), _comp("R2", "resistor", "1k"),
         _comp("L1", "inductor", "10n"), _comp("FB1", "ferrite_bead", "600R")]


def _signal_pin(net_pin_name):
    return [("U2", "10", net_pin_name, "input")]


class KeywordTokens(unittest.TestCase):
    def test_vccint_with_fpga_supply_pins_is_power(self):
        pins = [("U1", f"H{i}", "VCCINT", "power_in") for i in range(6)]
        pins += [("C1", "1", "~", "passive"), ("C2", "1", "~", "passive")]
        self.assertEqual(_classes(PARTS, {"/fpga-pg5/VCCINT": pins})["/fpga-pg5/VCCINT"], "power")

    def test_vccint_without_pins_is_not_interrupt(self):
        self.assertNotEqual(_classes(PARTS, {"VCCINT": []})["VCCINT"], "interrupt")

    def test_interrupt_names_keep_their_class(self):
        names = ["nINT", "INT1", "EXTINT", "INTB", "~{INT}", "/MCU_INT", "IRQ0", "INTn"]
        got = _classes(PARTS, {n: _signal_pin("PB1") for n in names})
        self.assertEqual({n: got[n] for n in names}, {n: "interrupt" for n in names})

    def test_glued_keywords_keep_their_class(self):
        want = {"TXD": "data", "CLKOUT": "clock", "CANH": "high_speed", "USBP": "high_speed"}
        got = _classes(PARTS, {n: _signal_pin("PA2") for n in want})
        self.assertEqual({n: got[n] for n in want}, want)

    def test_active_low_and_enable_forms_keep_their_class(self):
        want = {"~ROMCSB": "chip_select", "SCSN": "chip_select", "FJ_En": "control",
                "VCCOEN_PL_M2C": "control", "PROGTXD": "data", "xCLKCPU": "clock"}
        got = _classes(PARTS, {n: _signal_pin("PA3") for n in want})
        self.assertEqual({n: got[n] for n in want}, want)

    def test_keyword_inside_a_word_is_no_hit(self):
        # "EN" sits inside SENSE and "SS" inside ASSERT: neither is a control or chip-select net
        got = _classes(PARTS, {"VBUS_SENSE": _signal_pin("PA0"), "ASSERT": _signal_pin("PA1")})
        self.assertEqual((got["VBUS_SENSE"], got["ASSERT"]), ("signal", "signal"))


class PowerInputNets(unittest.TestCase):
    def test_power_in_plus_ic_output_is_not_promoted(self):
        pins = [("U2", "1", "VDD", "power_in"), ("U4", "5", "OUT", "output")]
        self.assertEqual(_classes(PARTS, {"NODE_A": pins})["NODE_A"], "signal")

    def test_regulator_power_out_on_the_net_is_not_promoted(self):
        pins = [("U2", "1", "VDD", "power_in"), ("U8", "2", "VO", "power_out"),
                ("C1", "1", "~", "passive")]
        self.assertEqual(_classes(PARTS, {"NODE_B": pins})["NODE_B"], "signal")

    def test_analog_supply_through_a_ferrite_is_power(self):
        pins = [("U2", "9", "VDDA", "power_in"), ("FB1", "2", "~", "passive"),
                ("C1", "1", "~", "passive")]
        self.assertEqual(_classes(PARTS, {"FILT_A": pins})["FILT_A"], "power")

    def test_module_3v3_pin_is_a_supply_input(self):
        pins = [("U5", "36", "3V3", "power_in"), ("C1", "1", "~", "passive")]
        self.assertEqual(_classes(PARTS, {"NODE_C": pins})["NODE_C"], "power")

    def test_switch_node_is_not_promoted(self):
        pins = [("U3", "40", "VLXSMPS", "power_in"), ("L1", "1", "~", "passive")]
        self.assertEqual(_classes(PARTS, {"SMPSLX": pins})["SMPSLX"], "signal")

    def test_divider_fed_reference_keeps_its_class(self):
        pins = [("U6", "H1", "VREFDQ", "power_in"), ("U6", "M8", "VREFCA", "power_in"),
                ("R1", "2", "~", "passive"), ("R2", "1", "~", "passive")]
        self.assertEqual(_classes(PARTS, {"DDR_VREF": pins})["DDR_VREF"], "analog")

    def test_ground_pin_on_an_odd_named_net_is_not_power(self):
        pins = [("U5", "3", "GND", "power_in")]
        self.assertEqual(_classes(PARTS, {"Ground": pins})["Ground"], "signal")

    def test_mistyped_scl_pin_stays_clock(self):
        pins = [("U7", "9", "SCL", "power_in")]
        self.assertEqual(_classes(PARTS, {"SCL": pins})["SCL"], "clock")


if __name__ == "__main__":
    unittest.main()

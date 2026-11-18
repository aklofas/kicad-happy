"""An IC or reference-diode output pin sources the rail it drives; a load switch's output
and an output pin named like a supply input (a symbol typing error) do not."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources  # noqa: E402


def _unsourced(comps, pins):
    """RS-001 nets for *pins* = {net: [(ref, number, name, type), ...]}."""
    nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": [],
                "pins": [dict(component=r, pin_number=num, pin_name=name, pin_type=t)
                         for r, num, name, t in ps]}
            for n, ps in pins.items()}
    ctx = build_analysis_context(comps, nets, {})
    return sorted(f["nets"][0] for f in audit_rail_sources(ctx) if f["rule_id"] == "RS-001")


def _part(ref, typ, value, lib_id=""):
    return {"reference": ref, "type": typ, "value": value, "lib_id": lib_id}


_LOAD = ("U2", "1", "VDD", "power_in")
_GND = {"GND": [("U2", "2", "GND", "power_in")]}


class OutputPinSource(unittest.TestCase):
    def test_reference_diode_output_sources_its_rail(self):
        comps = [_part("D1", "diode", "LM4040"), _part("U2", "ic", "ADC")]
        self.assertEqual(_unsourced(comps, {"+2V5": [("D1", "1", "K", "output"), _LOAD], **_GND}), [])

    def test_ic_output_pin_sources_its_rail(self):
        comps = [_part("U1", "ic", "W5500"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"+1V2": [("U1", "10", "1V2O", "output"), _LOAD], **_GND}), [])

    def test_output_pin_named_like_a_supply_input_is_not_a_source(self):
        comps = [_part("U1", "ic", "CH340G"), _part("U2", "ic", "MCU")]
        for name in ("VCC", "VDD", "AVDD", "VDDIO", "VCC_IO", "VCCQ2", "VIO", "VIN", "IN", "VS"):
            self.assertEqual(_unsourced(comps, {"+3V3": [("U1", "1", name, "output"), _LOAD], **_GND}),
                             ["+3V3"], name)

    def test_output_pin_of_a_connector_or_resistor_is_not_a_source(self):
        comps = [_part("J1", "connector", "Conn"), _part("R1", "resistor", "10k"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"+5V": [("J1", "1", "OUT", "output"), _LOAD],
                                            "+12V": [("R1", "1", "OUT", "output"),
                                                     ("U2", "3", "VCC", "power_in")], **_GND}),
                         ["+12V", "+5V"])

    def test_load_switch_output_with_an_unsourced_input_is_not_a_source(self):
        comps = [_part("U1", "ic", "MT9700", "Power_Management:MT9700"), _part("U2", "ic", "MCU")]
        self.assertEqual(_unsourced(comps, {"+5V": [("U1", "1", "VIN", "power_in")],
                                            "+5V_SW": [("U1", "2", "VOUT", "output"), _LOAD],
                                            "GND": [("U1", "3", "GND", "power_in"),
                                                    ("U2", "2", "GND", "power_in")]}),
                         ["+5V", "+5V_SW"])


if __name__ == "__main__":
    unittest.main()

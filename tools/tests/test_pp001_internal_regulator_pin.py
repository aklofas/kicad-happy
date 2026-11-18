import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context
from signal_detectors import audit_power_pin_dc_paths


def _pp001(pin_name, net="__unnamed_3"):
    comps = [{"reference": "U1", "type": "ic", "value": "MCU"},
             {"reference": "C1", "type": "capacitor", "value": "2.2u"}]
    nets = {net: {"name": net, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                  "labels": [],
                  "pins": [dict(component="U1", pin_number="1", pin_name=pin_name, pin_type="power_in"),
                           dict(component="C1", pin_number="1", pin_name="", pin_type="passive")]},
            "GND": {"name": "GND", "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                    "labels": [],
                    "pins": [dict(component="C1", pin_number="2", pin_name="", pin_type="passive")]}}
    ctx = build_analysis_context(comps, nets, {}, known_power_rails={"+3V3"})
    return [f for f in audit_power_pin_dc_paths(ctx) if f["rule_id"] == "PP-001"]


class InternalRegulatorPin(unittest.TestCase):
    def test_internal_regulator_output_pins_are_info(self):
        for name in ("VCAP_1", "VCAP", "VDD_DR", "VDDCORE", "VDD_CORE", "VREG", "VREG12",
                     "VREG_OUT", "VREGOUT", "VREGA_OUT", "vcap_2", "VCAP1/PA0"):
            f = _pp001(name)
            self.assertEqual([x["severity"] for x in f], ["info"], name)

    def test_regulator_supply_inputs_keep_the_error(self):
        for name in ("VREG_VIN", "VREG_IN", "VREGIN", "VREG_AVDD", "VREG_PGND", "VDD"):
            f = _pp001(name)
            self.assertEqual([x["severity"] for x in f], ["error"], name)


if __name__ == "__main__":
    unittest.main()

# tools/tests/test_regulator_output_caps.py
"""A regulator's output capacitor to ground is found on an output net that is unnamed or not
named like a rail; a capacitor in series or to a signal net is not one."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_decoupling, detect_design_observations  # noqa: E402


def _missing(out_net, cap_other_net, ground_pin_net="GND"):
    """missing_caps of LDO U1 (+5V in with C1, a passive VO pin on *out_net*) with C2 from
    *out_net* to *cap_other_net*; U1's GND pin sits on *ground_pin_net*."""
    comps = [{"reference": "U1", "type": "ic", "value": "AMS1117-3.3", "lib_id": "Regulator_Linear:AMS1117-3.3"},
             {"reference": "C1", "type": "capacitor", "value": "10uF", "lib_id": "Device:C"},
             {"reference": "C2", "type": "capacitor", "value": "22uF", "lib_id": "Device:C"},
             {"reference": "R1", "type": "resistor", "value": "1k", "lib_id": "Device:R"}]
    wiring = [("+5V", [("U1", "3", "VI", "power_in"), ("C1", "1", "", "passive")]),
              ("GND", [("C1", "2", "", "passive")]),
              (ground_pin_net, [("U1", "1", "GND", "power_in")]),
              (out_net, [("U1", "2", "VO", "passive"), ("C2", "1", "", "passive")]),
              (cap_other_net, [("C2", "2", "", "passive"), ("R1", "1", "", "passive")])]
    by_ref = {c["reference"]: dict(c, pins=[]) for c in comps}
    nets = {}
    for net, pins in wiring:
        entry = nets.setdefault(net, {"name": net, "pins": [], "point_count": 0, "no_connect": False,
                                      "has_pwr_flag": False, "labels": []})
        for ref, num, name, ptype in pins:
            entry["pins"].append({"component": ref, "pin_number": num, "pin_name": name, "pin_type": ptype})
            by_ref[ref]["pins"].append({"number": num, "name": name})
    ctx = build_analysis_context(list(by_ref.values()), nets, {}, known_power_rails={"+5V"})
    regs = [{"ref": "U1", "value": "AMS1117-3.3", "input_rail": "+5V", "output_rail": out_net}]
    obs = detect_design_observations(ctx, {"power_regulators": regs,
                                           "decoupling_analysis": detect_decoupling(ctx)})
    return [o["missing_caps"] for o in obs if o["category"] == "regulator_caps"]


class OutputCapacitorOnAnyNet(unittest.TestCase):
    def test_cap_to_ground_on_an_unnamed_output_net_counts(self):
        self.assertEqual(_missing("__unnamed_4", "GND"), [])

    def test_cap_to_ground_on_a_signal_named_output_net_counts(self):
        self.assertEqual(_missing("SYS", "GND"), [])

    def test_cap_to_the_regulators_own_ground_pin_net_counts(self):
        self.assertEqual(_missing("__unnamed_4", "-BATT", ground_pin_net="-BATT"), [])

    def test_cap_to_a_supply_rail_the_ground_pin_is_miswired_to_does_not_count(self):
        self.assertEqual(_missing("__unnamed_4", "+5V", ground_pin_net="+5V"),
                         [{"output": "__unnamed_4"}])

    def test_series_cap_to_a_signal_net_is_not_an_output_cap(self):
        self.assertEqual(_missing("__unnamed_4", "AUDIO_OUT"), [{"output": "__unnamed_4"}])

    def test_cap_to_a_signal_named_output_is_not_an_output_cap(self):
        self.assertEqual(_missing("SYS", "SENSE"), [{"output": "SYS"}])


if __name__ == "__main__":
    unittest.main()

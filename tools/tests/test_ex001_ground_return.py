import sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "datasheets"))

import lookup_detectors  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


def _pin(ref, num, name, ptype):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=ptype)


def _ic(ref, value, pins):
    return {"reference": ref, "type": "ic", "value": value, "lib_id": "Regulator_Linear:" + value,
            "footprint": "", "properties": {}, "pins": [{"number": n, "name": nm} for n, nm in pins]}


def _passive(ref, kind, value):
    return {"reference": ref, "type": kind, "value": value, "lib_id": "Device:" + kind,
            "footprint": "", "properties": {}, "pins": [{"number": "1"}, {"number": "2"}]}


def _ctx(extra_ground_cap=False):
    comps = [_ic("U1", "TPS1", [("1", "VIN"), ("2", "GND"), ("3", "VOUT"), ("4", "FB")]),
             _passive("C1", "capacitor", "10p"), _passive("R1", "resistor", "10k")]
    nets = {
        "+3V3": [_pin("U1", "3", "VOUT", "power_out"), _pin("C1", "1", "", "passive")],
        "FB": [_pin("U1", "4", "FB", "input"), _pin("C1", "2", "", "passive"),
               _pin("R1", "1", "", "passive")],
        "GND": [_pin("U1", "2", "GND", "power_in"), _pin("R1", "2", "", "passive")],
    }
    if extra_ground_cap:
        comps.append(_passive("C2", "capacitor", "10u"))
        nets["+3V3"].append(_pin("C2", "1", "", "passive"))
        nets["GND"].append(_pin("C2", "2", "", "passive"))
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+3V3", "GND"}, source="test")


def _run(ctx):
    facts = SimpleNamespace(regulator=SimpleNamespace(cin_min=None, cout_min=["x"],
                                                      inductor_range=None))
    regs = [{"ref": "U1", "mpn": "TPS1", "output_rail": "+3V3", "input_rail": None}]
    with patch.object(lookup_detectors, "get_facts", lambda *a, **k: facts), \
         patch.object(lookup_detectors, "has_data", bool), \
         patch.object(lookup_detectors, "best",
                      lambda *a, **k: SimpleNamespace(min=1e-5, typ=None, max=None)):
        return [f for f in lookup_detectors.detect_missing_required_components(ctx, regs)
                if f.get("rule_id") == "EX-001"]


class Ex001GroundReturnTest(unittest.TestCase):
    def test_feedforward_cap_is_not_an_output_cap(self):
        found = _run(_ctx())
        self.assertEqual(len(found), 1)
        self.assertIn("output cap", found[0]["summary"] + found[0].get("description", ""))

    def test_grounded_output_cap_satisfies_cout(self):
        self.assertEqual(_run(_ctx(extra_ground_cap=True)), [])


if __name__ == "__main__":
    unittest.main()

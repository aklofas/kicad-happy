"""A power-good output wired to another regulator's enable is a sequencing edge whichever
regulator the schematic lists first."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_power_sequencing  # noqa: E402


def _ctx():
    # U1 enable on PG_3V3; U2 power-good on PG_3V3; U3 power-good on PG_LED, which only an LED reads
    pins = {"U1": [("1", "VIN", "+5V"), ("2", "EN", "PG_3V3"), ("3", "VOUT", "+1V8")],
            "U2": [("1", "VIN", "+5V"), ("2", "EN", "+5V"), ("3", "VOUT", "+3V3"),
                   ("4", "PG", "PG_3V3")],
            "U3": [("1", "VIN", "+5V"), ("2", "EN", "EN_3"), ("3", "VOUT", "+2V5"),
                   ("4", "PGOOD", "PG_LED")],
            "D1": [("1", "A", "PG_LED")],
            "R1": [("1", "1", "EN_3")]}
    comps, nets = [], {}
    for ref, plist in pins.items():
        kind = {"D": "led", "R": "resistor"}.get(ref[0], "ic")
        comps.append({"reference": ref, "type": kind, "value": "X", "lib_id": "L:X", "footprint": "",
                      "properties": {}, "pins": [{"number": n, "name": nm} for n, nm, _ in plist]})
        for n, nm, net in plist:
            nets.setdefault(net, []).append(dict(component=ref, pin_number=n, pin_name=nm,
                                                 pin_type="passive"))
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+5V"}, source="test")


def _deps(order):
    regs = [{"ref": r, "output_rail": {"U1": "+1V8", "U2": "+3V3", "U3": "+2V5"}[r]} for r in order]
    out = analyze_power_sequencing(_ctx(), {"power_regulators": regs})
    return {d["regulator"]: d for d in out["dependencies"]}


class PowerGoodToEnable(unittest.TestCase):
    def test_edge_found_when_the_enabled_regulator_is_listed_first(self):
        dep = _deps(["U1", "U2", "U3"])["U1"]
        self.assertEqual(dep.get("sequenced_after"), "U2")
        self.assertEqual(dep.get("sequence_signal"), "power_good")

    def test_edge_found_when_the_power_good_regulator_is_listed_first(self):
        dep = _deps(["U2", "U3", "U1"])["U1"]
        self.assertEqual(dep.get("sequenced_after"), "U2")
        self.assertEqual(dep.get("sequence_signal"), "power_good")

    def test_power_good_that_drives_no_enable_makes_no_edge(self):
        for order in (["U1", "U2", "U3"], ["U3", "U2", "U1"]):
            deps = _deps(order)
            for ref in ("U2", "U3"):
                self.assertNotIn("sequenced_after", deps[ref], (order, ref))
                self.assertNotIn("sequence_signal", deps[ref], (order, ref))


if __name__ == "__main__":
    unittest.main()

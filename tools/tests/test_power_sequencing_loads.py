# tools/tests/test_power_sequencing_loads.py
"""PS-001 names each sequencing-sensitive load once, however many supply pins it has."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from validation_detectors import validate_power_sequencing  # noqa: E402

_MCU = "MCU_ST_STM32F4:STM32F405RGTx"
_REG = {"ref": "U2", "value": "AP2204R-3.3", "output_rail": "+3V3", "input_rail": "+5V"}


def _ps001(loads):
    """*loads*: ref -> list of supply pin numbers (one entry per pin) sitting on +3V3."""
    comps = [{"reference": "U2", "type": "ic", "value": "AP2204R-3.3", "lib_id": "Regulator:AP2204R",
              "pins": []}]
    comps += [{"reference": r, "type": "ic", "value": "STM32F405RGTx", "lib_id": _MCU, "pins": []}
              for r in loads]
    by_ref = {c["reference"]: c for c in comps}
    pins = [{"component": "U2", "pin_number": "5", "pin_name": "VOUT", "pin_type": "power_out"}]
    for ref, nums in loads.items():
        for n in nums:
            pins.append({"component": ref, "pin_number": n, "pin_name": "VDD", "pin_type": "power_in"})
            by_ref[ref]["pins"].append({"number": n, "name": "VDD"})
    nets = {"+3V3": {"name": "+3V3", "pins": pins, "point_count": 0, "no_connect": False,
                     "has_pwr_flag": False, "labels": []}}
    ctx = build_analysis_context(comps, nets, {}, known_power_rails={"+5V", "+3V3"})
    return [f for f in validate_power_sequencing(ctx, [_REG]) if f["rule_id"] == "PS-001"]


class LoadListedOnce(unittest.TestCase):
    def test_a_load_with_three_supply_pins_is_listed_once(self):
        found = _ps001({"U3": ["1", "2", "3"]})
        self.assertEqual([f["components"] for f in found], [["U2", "U3"]])
        self.assertEqual(found[0]["description"].count("U3"), 1)

    def test_distinct_loads_are_all_listed_in_first_seen_order(self):
        found = _ps001({"U3": ["1", "2"], "U4": ["1"]})
        self.assertEqual([f["components"] for f in found], [["U2", "U3", "U4"]])

    def test_pins_of_one_part_spread_across_units_are_one_load(self):
        found = _ps001({"U3": ["1", "20", "40"], "U4": ["7"]})
        self.assertEqual(found[0]["components"], ["U2", "U3", "U4"])

    def test_repeated_pins_no_longer_hide_a_third_distinct_load(self):
        found = _ps001({"U3": ["1", "2", "3"], "U4": ["1"], "U5": ["1"]})
        self.assertEqual(found[0]["components"], ["U2", "U3", "U4", "U5"])


if __name__ == "__main__":
    unittest.main()

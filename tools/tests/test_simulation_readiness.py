"""Simulation readiness counts a net tie or a jumper as simulatable: neither
needs a part model."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.audits import check_simulation_readiness  # noqa: E402


def _part(ref, ctype, lib_id="lib:part"):
    return {"reference": ref, "type": ctype, "lib_id": lib_id}


class SimulationReadinessShorts(unittest.TestCase):
    def test_net_tie_and_jumper_are_simulatable(self):
        parts = [_part("R1", "resistor"), _part("NT1", "net_tie"),
                 _part("JP1", "jumper"), _part("U1", "ic")]
        r = check_simulation_readiness(parts, {})
        self.assertEqual(r["total_components"], 4)
        self.assertEqual(r["likely_simulatable"], 3)
        self.assertEqual(r["needs_model"], 1)
        self.assertEqual(r["components_without_model"], ["U1"])
        self.assertEqual(r["simulatable_percent"], 75.0)

    def test_parts_without_a_model_still_need_one(self):
        parts = [_part("U1", "ic"), _part("J1", "connector"),
                 _part("NT1", "net_tie")]
        r = check_simulation_readiness(parts, {})
        self.assertEqual(r["components_without_model"], ["J1", "U1"])
        self.assertEqual(r["needs_model"], 2)


if __name__ == "__main__":
    unittest.main()

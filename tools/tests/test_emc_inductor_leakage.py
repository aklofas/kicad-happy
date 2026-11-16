"""ML-001 reads RF-chain components given as bare refdes strings, the shape detect_rf_chains emits."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_inductor_leakage, run_all_checks  # noqa: E402
from finding_schema import Det  # noqa: E402


def _inputs(rf_components):
    sch = {"findings": [
        {"detector": Det.POWER_REGULATORS, "ref": "U5", "topology": "buck",
         "inductor": "L2", "switching_frequency_hz": 500e3},
        {"detector": Det.RF_CHAINS, "components": rf_components}]}
    pcb = {"footprints": [
        {"reference": "L2", "x": 100.0, "y": 100.0,
         "library": "Inductor_SMD:L_1210_3225Metric", "value": "4.7uH", "mpn": ""},
        {"reference": "U1", "x": 105.0, "y": 100.0},   # 5 mm: in range
        {"reference": "U2", "x": 130.0, "y": 100.0}]}  # 30 mm: out of range
    return sch, pcb


def _ml001(findings):
    return [f for f in findings if f["rule_id"] == "ML-001"]


class RfChainComponentShapes(unittest.TestCase):
    def test_bare_refdes_chain_flags_the_near_part(self):
        sch, pcb = _inputs(["U1", "U2"])
        findings = check_inductor_leakage(pcb, sch)
        self.assertEqual([(f["rule_id"], f["components"], f["severity"]) for f in findings],
                         [("ML-001", ["L2", "U1"], "warning")])
        self.assertIn("5.0mm from sensitive U1", findings[0]["summary"])

    def test_dict_entries_read_the_same(self):
        sch, pcb = _inputs([{"ref": "U1"}, {"reference": "U2"}])
        self.assertEqual([f["components"] for f in check_inductor_leakage(pcb, sch)],
                         [["L2", "U1"]])

    def test_out_of_range_part_is_silent(self):
        sch, pcb = _inputs(["U2"])
        self.assertEqual(check_inductor_leakage(pcb, sch), [])

    def test_full_rule_run_does_not_crash(self):
        sch, pcb = _inputs(["U1", "U2"])
        self.assertEqual([f["components"] for f in _ml001(run_all_checks(sch, pcb))],
                         [["L2", "U1"]])


if __name__ == "__main__":
    unittest.main()

"""A regulator Value that reads as a label ('LDO1', 'BUCK5V', 'DCDC24V/5V NUM') names no
part, so it does not overrule the symbol's own part when the SPICE bench picks its Vref."""
import shutil, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "spice" / "scripts"))

from kicad_core.parts import is_label_like_value  # noqa: E402


class LabelLikeValueTest(unittest.TestCase):
    def test_labels(self):
        for v in ("LDO1", "BUCK5V", "U3V3", "DCDC24V/5V NUM", "BOOST12", "SMPS3V3", "PSU1",
                  "DCDC1", "ldo2", "3V3 LDO", "TPS61023 (5V)"):
            with self.subTest(v=v):
                self.assertTrue(is_label_like_value(v))

    def test_part_numbers(self):
        for v in ("TPS61023DRLR", "LM338_TO220", "REG1117", "LD33CV", "SPX1117-ADJ", "LM317",
                  "MP2359DJ", "UA78M05", "", None):
            with self.subTest(v=v):
                self.assertFalse(is_label_like_value(v))


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class LabelValueKeepsTheSymbolCriterionTest(unittest.TestCase):
    def test_label_value_on_an_lm317_symbol_is_judged(self):
        # LM317 symbol, Value 'LDO1': 5 - 5*820/1090 = 1.2385 V across OUT-ADJ, 0.92 % from 1.25 V
        from tools.tests.test_spice_measured_pass import _regulator, _run
        import spice_results as R
        import spice_templates as T
        det = dict(_regulator(270, 820, "+5V", 1.25, "lookup", reference="out_adj", value="LDO1"),
                   lib_id="Regulator_Linear:LM317_TO220")
        r = _run(T.generate_regulator_feedback, R.evaluate_regulator_feedback, det)
        self.assertEqual(r["status"], "pass")
        self.assertAlmostEqual(r["delta"]["vfb_vs_vref_pct"], 0.92, delta=0.01)


if __name__ == "__main__":
    unittest.main()

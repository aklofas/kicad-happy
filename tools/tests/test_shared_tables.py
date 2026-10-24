# tools/tests/test_shared_tables.py
"""Pins the shared tables and the named ground / IC-role policies."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))


class SharedTables(unittest.TestCase):
    def test_default_switching_freq_table(self):
        from kicad_core.parts import default_switching_freq
        self.assertEqual(default_switching_freq("buck"), 500e3)
        self.assertEqual(default_switching_freq("sepic"), 300e3)
        self.assertIsNone(default_switching_freq("ldo"))

    def test_emc_and_signal_share_the_core_function(self):
        import emc_rules, signal_detectors
        from kicad_core.parts import default_switching_freq
        self.assertIs(emc_rules._default_switching_freq, default_switching_freq)
        self.assertFalse(hasattr(signal_detectors, "_default_switching_freq"))

    def test_non_component_types(self):
        from kicad_core.classify import NON_COMPONENT_TYPES
        self.assertIsInstance(NON_COMPONENT_TYPES, frozenset)
        self.assertEqual(NON_COMPONENT_TYPES, {"power_symbol", "power_flag", "flag", "test_point",
                                               "mounting_hole", "fiducial", "graphic"})

    def test_ground_policies_differ_as_documented(self):
        from kicad_core.netnames import is_ground_name
        from emc_rules import is_emc_ground_name
        from cross_analysis import is_cross_analysis_ground_name
        self.assertTrue(is_emc_ground_name("VEE"))
        self.assertFalse(is_ground_name("VEE"))
        self.assertTrue(is_ground_name("COM"))
        self.assertFalse(is_emc_ground_name("COM"))
        self.assertTrue(is_cross_analysis_ground_name("CHASSIS"))
        self.assertFalse(is_cross_analysis_ground_name("/Power/GND"))   # today's behaviour, preserved

    def test_mlcc_parasitic_tables_live_in_kicad_core(self):
        import emc_formulas
        from kicad_core.parts import MLCC_ESL, MLCC_ESR
        self.assertIs(emc_formulas.MLCC_ESL, MLCC_ESL)
        self.assertIs(emc_formulas.MLCC_ESR, MLCC_ESR)
        pkgs = ["0201", "0402", "0603", "0805", "1206", "1210", "1812", "2220"]
        self.assertEqual(list(MLCC_ESL), pkgs)
        self.assertEqual(list(MLCC_ESR), pkgs)
        self.assertEqual(MLCC_ESL["0402"], 0.5e-9)
        self.assertEqual(MLCC_ESR["2220"], 0.015)
        src = (ROOT / "skills" / "kicad" / "scripts" / "schematic" / "system_analyses.py").read_text(encoding="utf-8")
        self.assertIn("esl_by_pkg = MLCC_ESL", src)
        self.assertIn("esr_base_by_pkg = MLCC_ESR", src)

    def test_audio_codec_keywords_single_definition(self):
        import domain_detectors
        src = Path(domain_detectors.__file__).read_text(encoding="utf-8")
        self.assertEqual(src.count("\n_AUDIO_CODEC_KEYWORDS = ("), 1)


if __name__ == "__main__":
    unittest.main()

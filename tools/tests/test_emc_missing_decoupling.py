"""DC-002 flags real ICs, including TPS / TP4056 parts, and exempts protection arrays and test points."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import check_missing_decoupling  # noqa: E402
from finding_schema import Det  # noqa: E402


def _flagged(parts, schematic=None):
    pcb = {"footprints": [{"reference": r, "value": v} for r, v in parts], "decoupling_placement": []}
    return [c for f in check_missing_decoupling(pcb, schematic) for c in f["components"]]


class MissingDecoupling(unittest.TestCase):
    def test_tps_and_tp4056_are_ics(self):
        self.assertEqual(_flagged([("U1", "TPS5430"), ("U2", "TP4056")]), ["U1", "U2"])

    def test_value_tp_is_a_test_point(self):
        for value in ("TP", "tp_1", "Test Point"):
            self.assertEqual(_flagged([("U1", value)]), [], value)

    def test_pcb_only_esd_and_tvs_values_stay_exempt(self):
        self.assertEqual(_flagged([("U1", "PESD5V0S1BL"), ("U2", "TVS_SMAJ")]), [])

    def test_pcb_only_ti_tpd_arrays_stay_exempt(self):
        self.assertEqual(_flagged([("U1", "TPD4E05U06"), ("U2", "TPD2E001"), ("U3", "TPS5430")]), ["U3"])

    def test_schematic_protection_array_is_skipped(self):
        sch = {"findings": [{"detector": Det.PROTECTION_DEVICES, "ref": "U1", "type": "esd_ic"}]}
        self.assertEqual(_flagged([("U1", "USBLC6-2SC6"), ("U2", "TPS2378")], sch), ["U2"])

    def test_a_fuse_in_the_protection_list_does_not_exempt_the_ref(self):
        sch = {"findings": [{"detector": Det.PROTECTION_DEVICES, "ref": "U1", "type": "fuse"}]}
        self.assertEqual(_flagged([("U1", "USBLC6-2SC6")], sch), ["U1"])


if __name__ == "__main__":
    unittest.main()

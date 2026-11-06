import sys, unittest
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
for sub in ("skills/kicad/scripts", "skills/datasheets", "skills/datasheets/scripts"):
    sys.path.insert(0, str(_ROOT / sub))

import datasheet_features  # noqa: E402
from datasheet_types.trust_gating import facts_trusted  # noqa: E402
from domain_detectors import detect_lvds_interfaces  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402


class FactsTrustRule(unittest.TestCase):
    def test_detector_and_feature_gate_agree(self):
        for quality, stale, expected in [(60, False, True), (59, False, False), (80, True, False),
                                         (None, False, False), (True, False, False)]:
            f = SimpleNamespace(quality=quality, stale=stale)
            self.assertEqual(facts_trusted(f), expected, (quality, stale))
            self.assertEqual(datasheet_features._quality_v14(f)["trusted"], expected, (quality, stale))


class LvdsByMpn(unittest.TestCase):
    def _found(self, mpn):
        comp = {"reference": "U1", "type": "ic", "value": "SER1", "lib_id": "x:IC", "mpn": mpn, "pins": []}
        return detect_lvds_interfaces(build_analysis_context([comp], {}, {}))

    def test_lvds_part_named_only_in_mpn_is_detected(self):
        self.assertEqual([f["reference"] for f in self._found("DS90UB953TRHBRQ1")], ["U1"])

    def test_other_mpn_is_not_detected(self):
        self.assertEqual(self._found("LM358DR"), [])


if __name__ == "__main__":
    unittest.main()

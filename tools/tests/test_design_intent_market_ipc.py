"""A medical or aerospace target market suggests IPC Class 3 in the detection signals but does
not set `ipc_class`: DFM judges the class the config, fab notes or title block name, and the
reported class matches it."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from design_intent import resolve_design_intent  # noqa: E402


class MarketSuggestsIpcClass(unittest.TestCase):
    def test_medical_market_suggests_class_3_without_applying_it(self):
        intent = resolve_design_intent({"design_intent": {"target_market": "medical"}})
        self.assertEqual((intent["ipc_class"], intent["source"]["ipc_class"]), (2, "auto"))
        self.assertTrue(any(s.startswith("IPC Class 3 suggested by medical market")
                            and "not applied" in s for s in intent["detection_signals"]))

    def test_aerospace_market_suggests_class_3_without_applying_it(self):
        intent = resolve_design_intent({"design_intent": {"target_market": "aerospace"}})
        self.assertEqual(intent["ipc_class"], 2)
        self.assertTrue(any(s.startswith("IPC Class 3 suggested by aerospace market")
                            for s in intent["detection_signals"]))

    def test_explicit_class_is_kept_and_not_suggested(self):
        intent = resolve_design_intent({"design_intent": {"target_market": "medical",
                                                          "ipc_class": 3}})
        self.assertEqual((intent["ipc_class"], intent["source"]["ipc_class"]), (3, "config"))
        self.assertFalse(any("suggested by" in s for s in intent["detection_signals"]))


if __name__ == "__main__":
    unittest.main()

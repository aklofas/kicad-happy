# tools/tests/test_pcb_project_discovery.py
"""A board opens the `.kicad_pro` and `.kicad_dru` named like the board and no other; the
schematic side keeps finding a project by its sibling (a KiCad 10 multi-root project)."""
import json, os, sys, tempfile, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.project import load_kicad_dru, load_kicad_pro  # noqa: E402
from pcb.pipeline import analyze_pcb  # noqa: E402

BOARD = "(kicad_pcb (version 20221018) (generator pcbnew)\n  (general (thickness 1.6))\n)\n"
PRO = json.dumps({"net_settings": {"classes": [{"name": "Default", "clearance": 0.3}]}})
DRU = '(version 1)\n(rule "r" (constraint track_width (min 0.2)))\n'


def make(tmp, files):
    for name, text in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            f.write(text)
    return os.path.join(tmp, "target.kicad_pcb")


class BoardDiscoveryTest(unittest.TestCase):
    def run_board(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            board = make(tmp, dict(files, **{"target.kicad_pcb": BOARD}))
            return analyze_pcb(board).get("project_settings", {})

    def test_foreign_project_and_rules_are_not_borrowed(self):
        ps = self.run_board({"boardA.kicad_pro": PRO, "onlyone.kicad_dru": DRU})
        self.assertNotIn("source", ps)
        self.assertNotIn("custom_rules", ps)

    def test_own_project_and_rules_load(self):
        ps = self.run_board({"target.kicad_pro": PRO, "target.kicad_dru": DRU})
        self.assertEqual(ps["source"], "target.kicad_pro")
        self.assertEqual(ps["custom_rules"][0]["name"], "r")

    def test_own_project_with_other_case_loads(self):
        ps = self.run_board({"Target.kicad_pro": PRO})
        self.assertEqual(ps["source"], "Target.kicad_pro")

    def test_exact_pro_ignores_the_sole_sibling_and_default_keeps_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = make(tmp, {"proj.kicad_pro": PRO, "target.kicad_pcb": BOARD})
            self.assertIsNone(load_kicad_pro(board, exact=True))
            self.assertIsNotNone(load_kicad_pro(board))
            self.assertIsNone(load_kicad_dru(make(tmp, {"x.kicad_dru": DRU})))


if __name__ == "__main__":
    unittest.main()

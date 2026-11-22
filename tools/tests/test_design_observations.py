"""The single-pin nets design observation lists the nets it counts."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.tests._fixtures import fixture_path, have

SCRIPT = Path(__file__).resolve().parents[2] / "skills/kicad/scripts/analyze_schematic.py"
DUAL_OPAMP = fixture_path("multi-unit", "dual_opamp.kicad_sch")
MIR12 = fixture_path("mirror-oracle", "mir12.kicad_sch")


def _observations(sch):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "schematic.json")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", KICAD_HAPPY_OFFLINE="1")
        r = subprocess.run([sys.executable, str(SCRIPT), str(sch), "-o", out,
                            "--no-hierarchy", "--only-deterministic"],
                           capture_output=True, text=True, cwd=tmp, env=env)
        if not os.path.exists(out):
            raise AssertionError(r.stderr)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
    return [x for x in data["findings"] if x.get("rule_id") == "DO-DET"]


def _single_pin(sch):
    found = [o for o in _observations(sch) if o.get("category") == "single_pin_nets"]
    return found[0] if found else None


EXPECTED_DUAL_OPAMP_OTHERS = {'category': 'decoupling',
 'component': 'U1',
 'value': 'LM358',
 'rails_without_caps': ['+5V'],
 'rails_with_caps': [],
 'detector': 'detect_design_observations',
 'rule_id': 'DO-DET',
 'severity': 'info',
 'confidence': 'heuristic',
 'evidence_source': 'topology',
 'summary': 'IC U1 missing decoupling on +5V',
 'description': 'IC power pin(s) without decoupling capacitors',
 'components': ['U1'],
 'nets': [],
 'pins': [],
 'recommendation': '',
 'report_context': {'section': 'Design Observations', 'impact': '', 'standard_ref': ''},
 'provenance': {'evidence': 'obs_topology',
                'confidence': 'heuristic',
                'claimed_components': ['U1'],
                'excluded_by': [],
                'suppressed_candidates': []},
 'detection_id': '',
 'stages': ['schematic']}


@unittest.skipUnless(have(DUAL_OPAMP) and have(MIR12), "KH_FIXTURES not set")
class SinglePinNetsObservation(unittest.TestCase):
    def test_single_pin_nets_lists_net_names(self):
        obs = _single_pin(DUAL_OPAMP)
        self.assertEqual(obs["count"], 1)
        self.assertEqual(len(obs["nets"]), 1)
        self.assertTrue(all(isinstance(n, str) and n for n in obs["nets"]))
        obs = _single_pin(MIR12)
        self.assertEqual(obs["count"], 48)
        self.assertEqual(len(obs["nets"]), 48)
        self.assertEqual(len(set(obs["nets"])), 48)

    def test_single_pin_nets_key_order(self):
        self.assertEqual(list(_single_pin(DUAL_OPAMP))[:3], ["category", "count", "nets"])

    def test_single_pin_nets_record_keeps_its_other_fields(self):
        obs = _single_pin(MIR12)
        self.assertEqual(obs["summary"], "Single-pin nets (48 nets)")
        self.assertEqual(len(obs["components"]), 48)
        self.assertEqual(obs["pins"], [])

    def test_other_design_observations_are_unchanged(self):
        def body(o):
            return {k: v for k, v in o.items() if k != "finding_id"}
        others = [body(o) for o in _observations(DUAL_OPAMP) if o["category"] != "single_pin_nets"]
        self.assertEqual(others, [EXPECTED_DUAL_OPAMP_OTHERS])
        self.assertEqual([o for o in _observations(MIR12) if o["category"] != "single_pin_nets"], [])


if __name__ == "__main__":
    unittest.main()

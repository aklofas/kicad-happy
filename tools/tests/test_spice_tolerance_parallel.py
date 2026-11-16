"""Monte Carlo samples each part of a parallel resistor, capacitor or inductor arm on its
own, at the tolerance in its value; an arm whose members cannot be resolved, and a plain
part, sample as one part in the same draw order as before."""
import math
import random
import shutil
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "spice" / "scripts"))
import spice_tolerance as T  # noqa: E402

ARM = {"ref": "R1", "value": "2 resistors parallel", "ohms": 500.0, "parallel_refs": ["R1", "R2"]}


def _rc(resistor, capacitor=None):
    return {"detector": "detect_rc_filters", "type": "low-pass", "resistor": resistor,
            "capacitor": capacitor or {"ref": "C9", "value": "100n", "farads": 1e-7},
            "input_net": "IN", "output_net": "OUT", "ground_net": "GND"}


def _an(*parts):
    return {"components": [{"reference": r, "value": v, "type": t} for r, v, t in parts]}


def _spread(det, an, key="resistor", vkey="ohms", nominal=500.0, n=4000):
    comps = T.find_toleranceable_components(det)
    members = T.parallel_members(det, comps, an)
    rng = random.Random(1)
    xs = [T.sample_detection(det, comps, rng, "uniform", det_type="rc_filters",
                             members=members)[key][vkey] for _ in range(n)]
    return statistics.pstdev(xs) / nominal, members


class ParallelArmTest(unittest.TestCase):
    def test_equal_members_narrow_the_spread(self):
        an = _an(("R1", "1k", "resistor"), ("R2", "1k", "resistor"), ("C9", "100n", "capacitor"))
        sd, members = _spread(_rc(dict(ARM)), an)
        self.assertEqual(len(members), 1)
        self.assertAlmostEqual(sd, 0.05 / 3 ** 0.5 / 2 ** 0.5, delta=0.0015)

    def test_member_tolerance_is_read(self):
        an = _an(("R1", "1k 1%", "resistor"), ("R2", "1k 1%", "resistor"),
                 ("C9", "100n", "capacitor"))
        sd, _ = _spread(_rc(dict(ARM)), an)
        self.assertAlmostEqual(sd, 0.01 / 3 ** 0.5 / 2 ** 0.5, delta=0.0004)

    def test_parallel_caps_sum(self):
        arm = {"ref": "C1", "value": "2 caps parallel", "farads": 2e-7,
               "parallel_refs": ["C1", "C2"]}
        det = _rc({"ref": "R5", "value": "1k", "ohms": 1000.0}, arm)
        an = _an(("R5", "1k", "resistor"), ("C1", "100n", "capacitor"),
                 ("C2", "100n", "capacitor"))
        sd, members = _spread(det, an, key="capacitor", vkey="farads", nominal=2e-7)
        self.assertEqual(len(members), 1)
        self.assertAlmostEqual(sd, 0.10 / 3 ** 0.5 / 2 ** 0.5, delta=0.003)

    def test_mixed_member_tolerances_are_each_sampled(self):
        an = _an(("R1", "1k 1%", "resistor"), ("R2", "1k 5%", "resistor"),
                 ("C9", "100n", "capacitor"))
        det = _rc(dict(ARM))
        comps = T.find_toleranceable_components(det)
        members = T.parallel_members(det, comps, an)
        self.assertEqual(list(members.values()), [[(1000.0, 0.01), (1000.0, 0.05)]])

    def test_plain_arm_samples_as_today(self):
        det = _rc({"ref": "R1", "value": "1k", "ohms": 1000.0})
        an = _an(("R1", "1k", "resistor"), ("C9", "100n", "capacitor"))
        comps = T.find_toleranceable_components(det)
        members = T.parallel_members(det, comps, an)
        self.assertEqual(members, {})
        sampled = T.sample_detection(det, comps, random.Random(7), "uniform",
                                     det_type="rc_filters", members=members)
        ref = random.Random(7)
        r_factor = 1 + ref.uniform(-0.05, 0.05)
        c_factor = 1 + ref.uniform(-0.10, 0.10)
        self.assertEqual(sampled["resistor"]["ohms"], 1000.0 * r_factor)
        self.assertEqual(sampled["capacitor"]["farads"], 1e-7 * c_factor)
        # the same samples without the argument at all
        again = T.sample_detection(det, comps, random.Random(7), "uniform", det_type="rc_filters")
        self.assertEqual(again["resistor"]["ohms"], sampled["resistor"]["ohms"])
        self.assertEqual(again["capacitor"]["farads"], sampled["capacitor"]["farads"])

    def test_unresolvable_members_fall_back(self):
        cases = {
            "member missing": _an(("R1", "1k", "resistor"), ("C9", "100n", "capacitor")),
            "member unparsed": _an(("R1", "1k", "resistor"), ("R2", "DNP", "resistor"),
                                   ("C9", "100n", "capacitor")),
            "members do not recombine": _an(("R1", "1k", "resistor"), ("R2", "2k", "resistor"),
                                            ("C9", "100n", "capacitor")),
        }
        for name, an in cases.items():
            with self.subTest(name):
                sd, members = _spread(_rc(dict(ARM)), an)
                self.assertEqual(members, {})
                self.assertAlmostEqual(sd, 0.05 / 3 ** 0.5, delta=0.002)

    def test_no_analysis_falls_back(self):
        det = _rc(dict(ARM))
        comps = T.find_toleranceable_components(det)
        self.assertEqual(T.parallel_members(det, comps, None), {})


@unittest.skipUnless(shutil.which("ngspice"), "ngspice not installed")
class MonteCarloRowTest(unittest.TestCase):
    def test_parallel_arm_row_states_the_member_tolerance(self):
        import simulate_subcircuits as S
        from spice_model_cache import ModelOptions
        det = dict(_rc(dict(ARM)), cutoff_hz=1 / (2 * math.pi * 500.0 * 1e-7))
        an = dict(_an(("R1", "1k 1%", "resistor"), ("R2", "1k 1%", "resistor"),
                      ("C9", "100n", "capacitor")), findings=[det])
        with tempfile.TemporaryDirectory() as tmp:
            report = S.simulate_subcircuits(an, workdir=tmp, monte_carlo_n=3,
                                            model_options=ModelOptions(cache_dir=tmp, offline=True))
        rows = report["simulation_results"][0]["tolerance_analysis"]["components"]
        self.assertEqual([(r["ref"], r["tolerance_pct"]) for r in rows], [("R1", 1.0), ("C9", 10.0)])


if __name__ == "__main__":
    unittest.main()

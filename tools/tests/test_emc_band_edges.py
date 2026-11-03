"""A frequency on the edge between two emission-limit bands gets the tighter limit
(47 CFR 15.209(b); CISPR: the lower limit applies at the transition frequency), and the
top edge of a table is inside it."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))
from emc_formulas import get_emission_limit  # noqa: E402


def lim(mhz, std):
    r = get_emission_limit(mhz * 1e6, std)
    return None if r is None else r[0]


class BandEdges(unittest.TestCase):
    CASES = {
        "fcc-class-b": [(30, 40.0), (50, 40.0), (88, 40.0), (150, 43.5), (216, 43.5),
                        (500, 46.0), (960, 46.0), (2000, 54.0), (40000, 54.0)],
        "fcc-class-a": [(30, 39.1), (50, 39.1), (88, 39.1), (150, 43.5), (216, 43.5),
                        (500, 46.4), (960, 46.4), (2000, 49.5), (40000, 49.5)],
        "cispr-class-b": [(30, 30.0), (100, 30.0), (230, 30.0), (500, 37.0), (1000, 37.0)],
        "cispr-class-a": [(30, 40.0), (100, 40.0), (230, 40.0), (500, 47.0), (1000, 47.0)],
        "cispr-25": [(30, 34.0), (50, 34.0), (68, 28.0), (90, 28.0), (108, 26.0),
                     (150, 26.0), (230, 26.0), (500, 32.0), (1000, 32.0)],
        "mil-std-461": [(2, 24.0), (30, 24.0), (500, 24.0), (1000, 24.0), (18000, 24.0)],
    }

    def test_edges_and_midbands(self):
        for std, rows in self.CASES.items():
            for mhz, want in rows:
                with self.subTest(std=std, mhz=mhz):
                    self.assertEqual(lim(mhz, std), want)

    def test_out_of_range_is_none(self):
        for std, below, above in [("fcc-class-b", 29.9, 40001), ("fcc-class-a", 29.9, 40001),
                                  ("cispr-class-b", 29.9, 1000.1), ("cispr-class-a", 29.9, 1000.1),
                                  ("cispr-25", 29.9, 1000.1), ("mil-std-461", 1.9, 18001)]:
            with self.subTest(std=std):
                self.assertIsNone(lim(below, std))
                self.assertIsNone(lim(above, std))

    def test_cispr25_upper_band_tighter(self):
        self.assertEqual(lim(68, "cispr-25"), 28.0)
        self.assertEqual(lim(108, "cispr-25"), 26.0)

    def test_distance_follows_the_tighter_band(self):
        self.assertEqual(get_emission_limit(88e6, "fcc-class-b"), (40.0, 3))
        self.assertEqual(get_emission_limit(1000e6, "cispr-class-b"), (37.0, 10))


if __name__ == "__main__":
    unittest.main()

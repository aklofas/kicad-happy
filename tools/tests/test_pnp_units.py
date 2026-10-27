"""Position files from kicad-cli carry no unit; the translator must not guess millimetres."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "bom" / "scripts" / "translate_bom_pnp.py"

# `kicad-cli pcb export pos --format csv --side both` on one board: inches
# (default) and the same rows with --units mm.
POS_IN = (
    "Ref,Val,Package,PosX,PosY,Rot,Side\n"
    '"D2","D","D_A-405_P7.62mm_Horizontal",4.220472,-4.834646,180.000000,bottom\n'
    '"J3","Conn_01x10_Pin","PinSocket_1x10_P2.54mm_Vertical",3.681102,-2.381890,180.000000,bottom\n'
)
MM_EXPECTED = {"D2": ("107.2000mm", "-122.8000mm"), "J3": ("93.5000mm", "-60.5000mm")}


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


class PnpUnits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def write(self, text):
        p = self.d / "pos.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def rows(self, out):
        lines = out.read_text(encoding="utf-8").splitlines()[1:]
        return {f[0]: (f[1], f[2]) for f in (ln.split(",") for ln in lines)}

    def test_inches_flag_matches_kicad_mm_export(self):
        out = self.d / "out.csv"
        r = run("pnp", str(self.write(POS_IN)), "-o", str(out), "--units", "in")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(out), MM_EXPECTED)

    def test_no_unit_is_a_usage_error(self):
        out = self.d / "out.csv"
        r = run("pnp", str(self.write(POS_IN)), "-o", str(out))
        self.assertEqual(r.returncode, 2)
        self.assertIn("--units", r.stderr)
        self.assertFalse(out.exists())

    def test_header_unit_wins_over_flag(self):
        out = self.d / "out.csv"
        src = self.write("Designator,Mid X (mil),Mid Y (mil),Layer,Rotation\nR1,100,200,T,0\n")
        r = run("pnp", str(src), "-o", str(out), "--units", "in")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(out), {"R1": ("2.5400mm", "5.0800mm")})

    def test_cell_suffixes_need_no_flag(self):
        out = self.d / "out.csv"
        src = self.write("Designator,Mid X,Mid Y,Layer,Rotation\nR1,100mil,200mil,T,0\n")
        r = run("pnp", str(src), "-o", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(out), {"R1": ("2.5400mm", "5.0800mm")})


if __name__ == "__main__":
    unittest.main()

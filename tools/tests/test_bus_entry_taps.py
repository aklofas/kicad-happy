"""A bus-entry tap reads the labels of the net it lands on before any tap is joined to its
member, so a second tap onto an already-joined net is not reported as unlabelled; a tap
onto a wire with no label still is."""
import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_global_bus_members import (  # noqa: E402
    HEAD, R_LIB, _member, _resistor, _uuid, _wire)
from schematic.pipeline import analyze_schematic  # noqa: E402


def unresolved(extra=""):
    # An unlabelled bus with two entries onto wires both labelled D0 (one net).
    body = (f'(bus (pts (xy 50 40) (xy 50 100)) (stroke (width 0) (type default)) (uuid "{_uuid()}"))\n'
            + _member("a", "R1", "D0", 60) + _member("a", "R2", "D0", 70) + extra)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.kicad_sch")
        Path(path).write_text(HEAD.format("00000000-0000-0000-0000-0000000000aa") + R_LIB + body + ")\n",
                              encoding="utf-8")
        with redirect_stderr(StringIO()):
            return analyze_schematic(path)["bus_topology"]["unresolved"]


class BusEntryTapTest(unittest.TestCase):
    def test_second_tap_onto_a_joined_net_is_not_unlabelled(self):
        self.assertEqual(unresolved(), [])

    def test_tap_onto_an_unlabelled_wire_is_reported(self):
        bare = (f'(bus_entry (at 50 {80 - 2.54}) (size 2.54 2.54) (stroke (width 0) (type default))'
                f' (uuid "{_uuid()}"))\n' + _wire(52.54, 80, 75, 80) + _resistor("a", "R3", 80))
        self.assertEqual(unresolved(bare), [{"reason": "unlabeled_entry_tap", "name": None}])


if __name__ == "__main__":
    unittest.main()

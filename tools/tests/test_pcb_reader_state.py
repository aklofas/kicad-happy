import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

HEADER = ('(kicad_pcb (version 20260101) (generator "pcbnew") (generator_version "10.0")\n'
          '  (general (thickness 1.6))\n'
          '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n')


def pad(ref, x, net_name):
    return (f'  (footprint "Test:Pad" (layer "F.Cu") (uuid "aaaaaaaa-0000-0000-0000-00000000{x:04d}") (at {x} 100)\n'
            f'    (property "Reference" "{ref}")\n'
            f'    (pad "1" smd rect (at 0 0) (size 2 2) (layers "F.Cu" "F.Mask") (net "{net_name}"))\n'
            f'  )\n')


BOARD_A = HEADER + pad("U1", 100, "COMMON") + ")\n"
BOARD_B = HEADER + pad("U1", 100, "AAA") + pad("U2", 110, "COMMON") + ")\n"


def _net_number(result, ref):
    fp = next(f for f in result["footprints"] if f["reference"] == ref)
    return result["net_name_to_id"][fp["pad_nets"]["1"]["net"]]


class ReaderState(unittest.TestCase):
    def test_net_id_resolves_numeric_name_and_empty(self):
        from kicad_core.model import PcbReaderState
        st = PcbReaderState()
        self.assertEqual(st.net_id(None), 0)
        self.assertEqual(st.net_id(""), 0)
        self.assertEqual(st.net_id("7"), 7)
        self.assertEqual(st.net_id("COMMON"), 0)
        st.net_name_to_id["COMMON"] = 3
        self.assertEqual(st.net_id("COMMON"), 3)

    def test_module_net_id_is_pure_during_extraction(self):
        import analyze_pcb as ap
        self.assertEqual(ap._net_id("COMMON"), 0)
        self.assertEqual(ap._net_id("12"), 12)
        self.assertFalse(hasattr(ap, "_net_name_to_id"))

    def test_same_process_a_b_a_is_identical_on_kicad10_boards(self):
        import analyze_pcb as ap
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a.kicad_pcb"; a.write_text(BOARD_A, encoding="utf-8")
            b = Path(d) / "b.kicad_pcb"; b.write_text(BOARD_B, encoding="utf-8")
            r1 = ap.analyze_pcb(str(a)); ap.analyze_pcb(str(b)); r3 = ap.analyze_pcb(str(a))
        self.assertEqual(r1["nets"], {"1": "COMMON"})
        self.assertEqual(r1["net_name_to_id"], r3["net_name_to_id"])
        self.assertEqual(_net_number(r1, "U1"), _net_number(r3, "U1"))
        self.assertEqual(json.dumps(r1, sort_keys=True, default=str), json.dumps(r3, sort_keys=True, default=str))


if __name__ == "__main__":
    unittest.main()

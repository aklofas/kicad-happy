"""Gerber X2 object/aperture attributes are read as KiCad writes and gerbview reads them."""
import os, sys, tempfile, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import analyze_gerbers as ag  # noqa: E402

# KiCad writes %TO.P (with the ref) on outer copper pads and no %TO.C.
PADS = ("%TO.P,R1,1*%\n%TO.N,GND*%\nX0Y0D03*\n%TD*%\n"
        "%TO.P,R1,2*%\n%TO.N,VCC*%\nX2000000Y0D03*\n%TD*%\n")


def _gbr(d, name, ff, body=""):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(f"%TF.FileFunction,{ff}*%\n%FSLAX46Y46*%\n%MOMM*%\n"
                f"%ADD10C,0.1*%\nD10*\n{body}M02*\n")
    return os.path.join(d, name)


def _parse(body):
    with tempfile.TemporaryDirectory() as d:
        return ag.parse_gerber(_gbr(d, "b-F_Cu.gtl", "Copper,L1,Top", body))


def _board(front, back=""):
    with tempfile.TemporaryDirectory() as d:
        _gbr(d, "b-F_Cu.gtl", "Copper,L1,Top", front)
        _gbr(d, "b-B_Cu.gbl", "Copper,L2,Bot", back)
        return ag.analyze_gerbers(d, full=True)


def _comment_form(body):
    """KiCad's --no-x2 output: each %T...*% attribute as a G04 #@! structured comment."""
    out = []
    for line in body.splitlines():
        if line.startswith("%T") and line.endswith("*%"):
            line = "G04 #@! " + line[1:-1]
        out.append(line)
    return "\n".join(out) + "\n"


class PadComponentTest(unittest.TestCase):
    def test_to_p_registers_component_front(self):
        r = _board(PADS)
        self.assertEqual(r["component_analysis"], {
            "total_unique": 1, "front_side": 1, "back_side": 0,
            "component_refs": ["R1"], "has_x2_data": True,
            "pads_per_component": {"R1": 2}, "total_pads": 2})

    def test_to_p_registers_component_back(self):
        ca = _board("", PADS)["component_analysis"]
        self.assertEqual((ca["front_side"], ca["back_side"]), (0, 1))

    def test_pad_ref_does_not_outlive_its_object(self):
        # A flash after %TD*% and a pad with an empty ref are not R1's pads.
        body = ("%TO.P,R1,1*%\nX0Y0D03*\n%TD*%\nX1000000Y0D03*\n"
                "%TO.P,,1*%\nX2000000Y0D03*\n%TD*%\n")
        x2 = _parse(body)["x2_objects"]
        self.assertEqual(x2["component_refs"], ["R1"])
        self.assertEqual(x2["component_pads"], {"R1": 1})
        self.assertEqual(x2["pin_mappings"],
                         [{"ref": "R1", "pin": "1", "pin_name": "", "net": ""}])

    def test_through_hole_pads_keep_the_silk_side(self):
        # KiCad writes %TO.P on both outer coppers for a through-hole pad;
        # the back silkscreen's %TO.C places the part on the back.
        with tempfile.TemporaryDirectory() as d:
            _gbr(d, "b-F_Cu.gtl", "Copper,L1,Top", PADS)
            _gbr(d, "b-B_Cu.gbl", "Copper,L2,Bot", PADS)
            _gbr(d, "b-B_Silkscreen.gbo", "Legend,Bot", "%TO.C,R1*%\nX0Y0D03*\n%TD*%\n")
            ca = ag.analyze_gerbers(d)["component_analysis"]
        self.assertEqual((ca["front_side"], ca["back_side"]), (0, 1))

    def test_pad_nets_credited(self):
        x2 = _parse(PADS)["x2_objects"]
        self.assertEqual(x2["component_nets"], {"R1": ["GND", "VCC"]})


class EscapeTest(unittest.TestCase):
    def _net(self, raw):
        return _parse(f"%TO.N,{raw}*%\nX0Y0D02*\nX1000000Y0D01*\n%TD*%\n")["x2_objects"]["net_names"]

    def test_escaped_asterisk(self):
        self.assertEqual(self._net("Net-(U1-\\u002ARESET)"), ["Net-(U1-*RESET)"])

    def test_non_ascii_any_case(self):
        self.assertEqual(self._net("\\u00D8\\u00f81"), ["Øø1"])

    def test_control_character_dropped(self):
        self.assertEqual(self._net("A\\u0007B"), ["AB"])

    def test_malformed_stays_literal(self):
        self.assertEqual(self._net("A\\uZZZZ"), ["A\\uZZZZ"])

    def test_old_backslash_hex_form_not_decoded(self):
        self.assertEqual(self._net("A\\005CB"), ["A\\005CB"])

    def test_escaped_comma_in_pin_ref(self):
        x2 = _parse("%TO.P,R\\u002C1,1*%\nX0Y0D03*\n%TD*%\n")["x2_objects"]
        self.assertEqual(x2["pin_mappings"],
                         [{"ref": "R,1", "pin": "1", "pin_name": "", "net": ""}])
        self.assertEqual(x2["component_refs"], ["R,1"])


class StructuredCommentTest(unittest.TestCase):
    def test_comment_form_equals_native(self):
        native = _board(PADS)
        comment = _board(_comment_form(PADS))
        for key in ("component_analysis", "net_analysis", "connectivity"):
            self.assertEqual(comment.get(key), native.get(key), key)
        self.assertEqual(comment["connectivity"],
                         [{"ref": "R1", "pin": "1", "pin_name": "", "net": "GND"},
                          {"ref": "R1", "pin": "2", "pin_name": "", "net": "VCC"}])

    def test_comment_aperture_function(self):
        body = ("G04 #@! TA.AperFunction,SMDPad,CuDef*\n%ADD11R,1X1*%\nG04 #@! TD*\n"
                "D11*\nX0Y0D03*\n")
        aa = _parse(body)["aperture_analysis"]
        self.assertEqual(aa["by_function_flashes"], {"SMDPad": 1})


class ApertureFunctionTest(unittest.TestCase):
    def test_rotrect_counted(self):
        body = ("%TA.AperFunction,SMDPad,CuDef*%\n"
                "%ADD11RotRect,0.5X0.1X0.1X0.5X-0.1X-0.5X-0.1X-0.5X0.1*%\n%TD*%\n"
                "D11*\nX0Y0D03*\nX1000000Y0D03*\n")
        aa = _parse(body)["aperture_analysis"]
        self.assertEqual(aa["by_function"], {"SMDPad": 1})
        self.assertEqual(aa["by_function_flashes"], {"SMDPad": 2})

    def test_named_td_clears_function(self):
        body = ("%TA.AperFunction,SMDPad,CuDef*%\n%ADD11C,1*%\n%TD.AperFunction*%\n"
                "%ADD12C,1*%\n")
        aps = _parse(body)["apertures"]
        self.assertEqual(aps["D11"].get("function"), "SMDPad,CuDef")
        self.assertNotIn("function", aps["D12"])


class EmptyNetTest(unittest.TestCase):
    def test_empty_net_is_not_a_net(self):
        x2 = _parse("%TO.P,H1,1*%\n%TO.N,*%\nX0Y0D03*\n%TD*%\n")["x2_objects"]
        self.assertEqual(x2["net_names"], [])
        self.assertEqual(x2["pin_mappings"],
                         [{"ref": "H1", "pin": "1", "pin_name": "", "net": ""}])
        self.assertIsNone(_board("%TO.P,H1,1*%\n%TO.N,*%\nX0Y0D03*\n%TD*%\n").get("net_analysis"))


class KicadVersionReadTest(unittest.TestCase):
    """The generator version is only read for bare .g<n> names, the one place it is used."""

    def test_not_read_for_named_layers(self):
        with mock.patch.object(ag, "_kicad_major", side_effect=AssertionError("read")):
            self.assertEqual(_parse("")["layer_type"], "F.Cu")

    def test_read_for_bare_protel_inner(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b.g2")
            with open(path, "w", encoding="utf-8") as f:
                f.write("G04 Created by KiCad (PCBNEW 8.0.9) date*\n%FSLAX46Y46*%\n%MOMM*%\nM02*\n")
            with mock.patch.object(ag, "_kicad_major", wraps=ag._kicad_major) as km:
                self.assertEqual(ag.parse_gerber(path)["layer_type"], "In1.Cu")
            self.assertEqual(km.call_count, 1)


if __name__ == "__main__":
    unittest.main()

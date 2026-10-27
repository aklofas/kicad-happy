"""Escaped net names as KiCad 10 names them: the text as written, with `/` escaped
(EscapeString CTX_NETNAME, string_utils.cpp), is the net identity in the schematic and on the
board; the decoded form is the schematic display_name and the text findings print.  Schematic
expectations are the kicad-cli 10.0.6 netlist of the same generated file."""
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from kicad_core.netnames import is_ground_name, is_power_net_name  # noqa: E402
from kicad_core import sexp  # noqa: E402
from pcb.pipeline import analyze_pcb  # noqa: E402
from project_config import matches_suppression  # noqa: E402
from tools.tests.test_body_style_and_hidden_pins import net_of  # noqa: E402
from tools.tests.test_bus_conformance import (  # noqa: E402
    CHILD_FILE_UUID, CHILD_PATH, bus, doc, label, sheet_block, tap)
from tools.tests.test_bus_conformance import analyze as analyze_bus  # noqa: E402
from tools.tests.test_bus_conformance import across_pin, groups, pin1_groups  # noqa: E402
from tools.tests.test_same_sheet_power_names import (  # noqa: E402
    CHILD_SHEET_UUID, ROOT_UUID, R_LIB, Sheet, power_lib, run)
from tools.tests.test_same_sheet_power_names import CHILD_FILE_UUID as SAME_CHILD_FILE_UUID  # noqa: E402
from tools.tests.test_same_sheet_power_names import sheet_block as same_sheet_block  # noqa: E402


def members(result, key):
    return sorted(f'{p["component"]}.{p["pin_number"]}' for p in result["nets"][key]["pins"]
                  if not p["component"].startswith("#"))


# --- schematic fixtures (kicad-cli 10.0.6 netlist quoted in each test) ----------------------

def boert_files():
    """R1 on a wire labelled {slash}RAS, R2 on a wire labelled RAS (boert 16M2164)."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40); s.label("label", "{slash}RAS", 50, 45)
    s.r("R2", 80, 50); s.wire(80, 50, 80, 40); s.label("label", "RAS", 80, 45)
    return {"t.kicad_sch": s.text([R_LIB])}


def raw_slash_files():
    """A KiCad 6 file whose label text holds a plain '/' (NanoV3.3 writes D1/TX)."""
    s = Sheet(20211123)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40); s.label("label", "D1/TX", 50, 45)
    return {"t.kicad_sch": s.text([R_LIB])}


def power_value_files():
    """R1 on a power symbol whose Value is +5V/USB."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40)
    s.symbol("power:+5V", "#PWR1", "+5V/USB", 50, 40, ("1",))
    return {"t.kicad_sch": s.text([R_LIB, power_lib("power:+5V", "+5V")])}


def signal_slash_files():
    """R1-R2 joined by a wire labelled +1{slash}I (a PatinhoFeio logic signal)."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.r("R2", 60, 50); s.wire(50, 50, 60, 50)
    s.label("label", "+1{slash}I", 55, 50)
    return {"t.kicad_sch": s.text([R_LIB])}


ALIAS = '(bus_alias "ADC" (members "ADC2/GPIO2" "AREF"))'


def alias_files():
    """A bus {ADC} (alias members "ADC2/GPIO2", AREF) crosses sheet pin {ADC}; both sides tap
    the member as a wire labelled ADC2{slash}GPIO2 (KiABOM test-project1)."""
    p = [ALIAS, bus(100, 50, 150, 50), label("label", "{ADC}", 105, 50)]
    p += tap(120, 50, "ADC2{slash}GPIO2", "R1")
    p.append(sheet_block("{ADC}", 150, 40, 30, 30, 50))
    c = [ALIAS, bus(50, 50, 100, 50), label("hierarchical_label", "{ADC}", 50, 50)]
    c += tap(60, 50, "ADC2{slash}GPIO2", "R11", CHILD_PATH)
    return {"t.kicad_sch": doc(p), "child.kicad_sch": doc(c, CHILD_FILE_UUID, root=False)}


def escaped_rail_files():
    """+5V{slash}USB rail: R1 from the power symbol to a no-source rail (RS-001 prints it)."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40)
    s.symbol("power:+5V", "#PWR1", "+5V{slash}USB", 50, 40, ("1",))
    return {"t.kicad_sch": s.text([R_LIB, power_lib("power:+5V", "+5V")])}


class TokenTest(unittest.TestCase):
    def test_token_keeps_the_text_as_written(self):
        t = sexp.parse('(a "x{slash}y" b{slash}c plain "q")')
        self.assertEqual(t[1], "x/y")
        self.assertEqual(sexp.raw_text(t[1]), "x{slash}y")
        self.assertEqual(sexp.raw_text(t[2]), "b{slash}c")
        self.assertIs(type(t[3]), str)
        self.assertIs(type(t[4]), str)
        self.assertEqual(sexp.raw_text(t[3]), "plain")

    def test_raw_accessor(self):
        node = sexp.parse('(seg (net "/A{slash}B") (layer "F.Cu"))')
        self.assertEqual(sexp.get_value(node, "net"), "/A/B")
        self.assertEqual(sexp.get_value(node, "net", raw=True), "/A{slash}B")

    def test_net_name_escape_is_kicad_ctx_netname(self):
        # string_utils.cpp EscapeString(CTX_NETNAME): '/' -> {slash}, CR/LF dropped, nothing else.
        self.assertEqual(sexp.net_name_escape("D1/TX"), "D1{slash}TX")
        self.assertEqual(sexp.net_name_escape("A{slash}B"), "A{slash}B")
        self.assertEqual(sexp.net_name_escape("A\nB\r"), "AB")
        self.assertEqual(sexp.net_name_escape("A{space}B,C"), "A{space}B,C")


class SchematicIdentityTest(unittest.TestCase):
    def test_escaped_and_plain_labels_are_two_nets(self):
        # kicad-cli: {slash}RAS = R1.1; /RAS = R2.1
        r = run(boert_files())
        self.assertEqual(net_of(r, "R1", "1"), "{slash}RAS")
        self.assertEqual(net_of(r, "R2", "1"), "RAS")
        self.assertEqual(r["nets"]["{slash}RAS"]["display_name"], "/RAS")
        self.assertNotIn("display_name", r["nets"]["RAS"])
        self.assertEqual(sorted(l["name"] for l in r["labels"]), ["RAS", "{slash}RAS"])

    def test_plain_slash_in_label_text_is_escaped(self):
        # kicad-cli: /D1{slash}TX = R1.1
        r = run(raw_slash_files())
        self.assertEqual(net_of(r, "R1", "1"), "D1{slash}TX")
        self.assertEqual(r["nets"]["D1{slash}TX"]["display_name"], "D1/TX")

    def test_power_symbol_value_is_escaped(self):
        # kicad-cli: +5V{slash}USB = R1.1 (sch_pin.cpp: EscapeString(value, CTX_NETNAME))
        r = run(power_value_files())
        self.assertEqual(net_of(r, "R1", "1"), "+5V{slash}USB")
        self.assertEqual(r["nets"]["+5V{slash}USB"]["display_name"], "+5V/USB")

    def test_bus_alias_member_joins_the_escaped_label(self):
        # kicad-cli: /ADC2{slash}GPIO2 = R1.1 R11.1 (sch_connection.cpp escapes alias members)
        r = analyze_bus(alias_files())
        self.assertEqual(net_of(r, "R1", "1"), net_of(r, "R11", "1"))
        self.assertEqual(net_of(r, "R1", "1"), "ADC2{slash}GPIO2")
        self.assertEqual(members(r, "ADC2{slash}GPIO2"), ["R1.1", "R11.1"])

    def test_escaped_group_member_joins_its_label_across_a_sheet_pin(self):
        # kicad-cli: /R{slash}W = R1.1 R11.1; /EN = R2.1 R12.1
        g = "{R{slash}W EN}"
        r = analyze_bus(across_pin([g], g, g, ["R{slash}W", "EN"], ["R{slash}W", "EN"]))
        self.assertEqual(pin1_groups(r), groups({"R1", "R11"}, {"R2", "R12"}))
        self.assertEqual(net_of(r, "R1", "1"), "R{slash}W")

    def test_escaped_vector_members_stay_apart_across_a_sheet_pin(self):
        # kicad-cli: /A{slash}B0 = R1.1; /A{slash}B1 = R2.1; /child/A{slash}B0 = R11.1;
        # /child/A{slash}B1 = R12.1 (vector members keep the decoded name, so a tap label
        # A{slash}B0 is not the member A/B0)
        v = "A{slash}B[0..1]"
        r = analyze_bus(across_pin([v], v, v, ["A{slash}B0", "A{slash}B1"],
                                   ["A{slash}B0", "A{slash}B1"]))
        self.assertEqual(pin1_groups(r), groups({"R1"}, {"R2"}, {"R11"}, {"R12"}))

    def test_group_prefix_and_nested_vector_keep_slash_members_apart(self):
        # kicad-cli: P{slash}Q{R{slash}W EN} taps stay on their sheet (four nets); in
        # {A{slash}B[0..1] EN} only EN joins (R3.1 R13.1), the A{slash}B<n> taps stay apart.
        g = "P{slash}Q{R{slash}W EN}"
        taps = ["P{slash}Q.R{slash}W", "P{slash}Q.EN"]
        r = analyze_bus(across_pin([g], g, g, taps, taps))
        self.assertEqual(pin1_groups(r), groups({"R1"}, {"R2"}, {"R11"}, {"R12"}))
        g = "{A{slash}B[0..1] EN}"
        taps = ["A{slash}B0", "A{slash}B1", "EN"]
        r = analyze_bus(across_pin([g], g, g, taps, taps))
        self.assertEqual(pin1_groups(r),
                         groups({"R1"}, {"R2"}, {"R11"}, {"R12"}, {"R3", "R13"}))

    def test_other_escapes_are_decoded_in_the_name(self):
        # kicad-cli: the label's shown text (UnescapeString) escaped as a net name.
        expected = {"A{space}B": "A B", "A{comma}B": "A,B", "A{dollar}B": "A$B",
                    "K{colon}L": "K:L", "C{lt}D": "C<D", "Z{brace}": "Z{",
                    "X{amp}Y": "X{amp}Y", "E{unknown}F": "E{unknown}F",
                    "~{slash}Q": "~{slash}Q", "G{slash}{slash}H": "G{slash}{slash}H"}
        r = run({"t.kicad_sch": _labels(list(expected))})
        for i, (label_text, net) in enumerate(expected.items(), 1):
            self.assertEqual(net_of(r, f"R{i}", "1"), net, label_text)


def pair_files():
    """Local X{slash}D_P / X{slash}D_N on the root (R1, R2) and on a child sheet (R11, R12):
    four nets with sheet-qualified keys whose display_name is X/D_P or X/D_N."""
    def side(first, path):
        s = Sheet(20250114, path=path)
        s.r(f"R{first}", 50, 50); s.wire(50, 50, 50, 40); s.label("label", "X{slash}D_P", 50, 45)
        s.r(f"R{first + 1}", 80, 50); s.wire(80, 50, 80, 40); s.label("label", "X{slash}D_N", 80, 45)
        return s
    root, child = side(1, f"/{ROOT_UUID}"), side(11, f"/{ROOT_UUID}/{CHILD_SHEET_UUID}")
    return {"t.kicad_sch": root.text([R_LIB], extra=same_sheet_block(
                "child", "child.kicad_sch", 150, 40, [])),
            "child.kicad_sch": child.text([R_LIB], uuid=SAME_CHILD_FILE_UUID, root=False)}


class DiffPairSheetTest(unittest.TestCase):
    def test_pairs_stay_on_their_sheet_with_decoded_display_names(self):
        r = run(pair_files())
        self.assertEqual(r["nets"]["/child/X{slash}D_P"]["display_name"], "X/D_P")
        pairs = {(d["positive"], d["negative"]) for d in r["design_analysis"]["differential_pairs"]}
        self.assertEqual(pairs, {("/t/X{slash}D_P", "/t/X{slash}D_N"),
                                 ("/child/X{slash}D_P", "/child/X{slash}D_N")})


class DecodedHeuristicsTest(unittest.TestCase):
    def test_escaped_signal_name_is_not_a_rail(self):
        # The shown name is +1/I: a signal under sheet-path stripping, as before.
        self.assertFalse(is_power_net_name("+1{slash}I"))
        self.assertEqual(is_power_net_name("+1{slash}I"), is_power_net_name("+1/I"))
        r = run(signal_slash_files())
        key = net_of(r, "R1", "1")
        self.assertEqual(key, "+1{slash}I")
        self.assertNotEqual(r["design_analysis"]["net_classification"][key], "power")
        self.assertFalse([f for f in r["findings"] if key in f.get("nets", [])
                          and f.get("rule_id") == "RS-001"])

    def test_zero_is_ground_when_a_power_symbol_names_it(self):
        # The SPICE ground symbol names its net 0 (hoellwerth Anchor-Control); a connector
        # pin labelled 0 (an M2K DIO0 line) is a signal.
        self.assertTrue(is_ground_name("0", {"0", "GND"}))
        self.assertFalse(is_ground_name("0"))
        self.assertFalse(is_ground_name("0", {"GND"}))
        self.assertFalse(is_ground_name("10", {"10"}))
        self.assertFalse(is_ground_name("0V9"))
        r = run(zero_power_files())
        self.assertEqual(r["design_analysis"]["net_classification"]["0"], "ground")
        r = run({"t.kicad_sch": _labels(["0"], "global_label")})
        self.assertEqual(r["design_analysis"]["net_classification"]["0"], "signal")


def zero_power_files():
    """R1 on a power symbol whose Value is 0 (the Simulation_SPICE:0 ground symbol)."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40)
    s.symbol("power:0", "#PWR1", "0", 50, 40, ("1",))
    return {"t.kicad_sch": s.text([R_LIB, power_lib("power:0", "0")])}


def _labels(names, kind="label"):
    """R<i> pin 1 on a wire carrying a label names[i-1] of the given kind."""
    s = Sheet(20250114)
    for i, name in enumerate(names):
        x = 50 + 20 * i
        s.r(f"R{i + 1}", x, 50); s.wire(x, 50, x, 40); s.label(kind, name, x, 45)
    return s.text([R_LIB])


class FindingTextTest(unittest.TestCase):
    def test_finding_text_shows_the_decoded_name(self):
        r = run(escaped_rail_files())
        hits = [f for f in r["findings"] if "+5V{slash}USB" in f.get("nets", [])]
        self.assertTrue(hits)
        for f in hits:
            for k in ("summary", "description", "recommendation"):
                self.assertNotIn("{slash}", f.get(k) or "", (f["rule_id"], k))
        self.assertTrue(any("+5V/USB" in f["summary"] for f in hits))

    def test_warning_messages_show_the_decoded_name(self):
        # KiCad shows a net name through UnescapeString; the net field keeps the identity.
        from types import SimpleNamespace
        from schematic.audits import validate_label_shapes
        from schematic.net_analysis import _check_erc_warnings
        net = "D1{slash}TX"
        pin = {"component": "U1", "pin_number": "1", "pin_type": "input"}
        nets = {net: {"pins": [pin, dict(pin, component="U2")]}}
        labels = [{"type": "global_label", "name": net, "shape": s} for s in ("input", "output")]
        ctx = SimpleNamespace(nets=nets, is_ground=lambda n: False, is_power_net=lambda n: False)
        warnings = validate_label_shapes(labels, nets) + _check_erc_warnings(ctx)
        self.assertTrue(warnings)
        for w in warnings:
            self.assertEqual(w["net"], net)
            self.assertIn("'D1/TX'", w["message"])

    def test_suppression_written_against_the_shown_name_matches(self):
        f = {"rule_id": "RS-001", "nets": ["D1{slash}TX"], "components": []}
        self.assertTrue(matches_suppression(f, {"rule_id": "RS-001", "nets": ["D1/TX"]}))
        self.assertTrue(matches_suppression(f, {"rule_id": "RS-001", "nets": ["D1{slash}TX"]}))
        self.assertFalse(matches_suppression(f, {"rule_id": "RS-001", "nets": ["D1/RX"]}))


# --- board fixtures ---------------------------------------------------------------------------

_FP = ('(footprint "R:R" (layer "F.Cu") (at {x} {y})'
       ' (property "Reference" "{ref}" (at 0 0 0) (layer "F.SilkS"))'
       ' (property "Value" "1k" (at 0 0 0) (layer "F.Fab"))'
       ' (pad "{n1}" smd rect (at -1 0) (size 1 1) (layers "F.Cu") {net1})'
       ' (pad "{n2}" smd rect (at 1 0) (size 1 1) (layers "F.Cu") {net2}))')

BOERT_PCB = ('(kicad_pcb (version 20221018) (generator "pcbnew")'
             ' (general (thickness 1.6))'
             ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))'
             ' (net 0 "") (net 1 "{slash}RAS") (net 2 "/RAS")'
             + _FP.format(x=10, y=10, ref="J2", n1="2", n2="3",
                          net1='(net 1 "{slash}RAS")', net2='(net 2 "/RAS")')
             + _FP.format(x=30, y=20, ref="U1", n1="8", n2="9",
                          net1='(net 1 "{slash}RAS")', net2='(net 2 "/RAS")')
             + ' (segment (start 9 10) (end 29 20) (width 0.25) (layer "F.Cu") (net 1))'
             + ' (segment (start 11 10) (end 31 20) (width 0.25) (layer "F.Cu") (net 2))'
             + ')\n')

K10_PCB = ('(kicad_pcb (version 20250901) (generator "pcbnew") (generator_version "10.0")'
           ' (general (thickness 1.6))'
           ' (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))'
           + _FP.format(x=10, y=10, ref="R1", n1="1", n2="2",
                        net1='(net "/A{slash}B")', net2='(net "/A/B")')
           + ' (segment (start 9 10) (end 5 10) (width 0.25) (layer "F.Cu") (net "/A{slash}B"))'
           + ')\n')


def analyze_board(text, **kw):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.kicad_pcb")
        Path(path).write_text(text, encoding="utf-8")
        with redirect_stderr(StringIO()):
            return analyze_pcb(path, **kw)


class BoardIdentityTest(unittest.TestCase):
    def test_escaped_and_plain_board_nets_stay_apart(self):
        # netinfo_item.cpp keeps the declared name: {slash}RAS and /RAS are two nets.
        r = analyze_board(BOERT_PCB, include_trace_segments=True)
        self.assertEqual(r["nets"], {"1": "{slash}RAS", "2": "/RAS"})
        graph = r["connectivity_graph"]
        for name in ("{slash}RAS", "/RAS"):
            self.assertEqual(graph[name]["islands"], 1, name)
            self.assertFalse(graph[name].get("disconnected_pads"), name)

    def test_kicad10_by_name_nets_stay_apart(self):
        r = analyze_board(K10_PCB)
        self.assertEqual(sorted(r["nets"].values()), ["/A/B", "/A{slash}B"])


if __name__ == "__main__":
    unittest.main()

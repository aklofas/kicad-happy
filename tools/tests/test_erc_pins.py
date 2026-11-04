"""ERC pin conflicts, undriven nets and connected no-connects as KiCad 10.0.7 reports them with
its default settings. Expected values come from eeschema/erc/erc_settings.cpp (m_defaultPinMap,
default severities), erc.cpp (TestPinToPin, TestNoConnectPins, the driver sets) and
connection_graph.cpp (ercCheckNoConnects)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from schematic.net_analysis import _check_erc_warnings, analyze_connectivity  # noqa: E402
from tools.tests.test_same_sheet_power_names import R_LIB, Sheet, members, power_lib, run  # noqa: E402


def pin(ref, num, ptype, name=None):
    return {"component": ref, "pin_number": num, "pin_name": name or f"P{num}", "pin_type": ptype}


def comp(ref, pins):
    """A component whose pins are (number, type, name, x, y)."""
    return {"reference": ref, "type": "ic", "_sheet": 0,
            "pins": [{"number": n, "type": t, "name": nm, "x": x, "y": y} for n, t, nm, x, y in pins]}


def erc(nets, components=()):
    ctx = SimpleNamespace(nets=nets, components=list(components),
                          is_ground=lambda n: False, is_power_net=lambda n: False)
    return _check_erc_warnings(ctx)


def by_type(records, kind):
    return [r for r in records if r["type"] == kind]


def two_pin_net(t1, t2, **net):
    """U1 pin 1 of type t1 and U2 pin 1 of type t2 at different places."""
    comps = [comp("U1", [("1", t1, "A", 0, 0)]), comp("U2", [("1", t2, "B", 10, 0)])]
    return {"N": dict({"pins": [pin("U1", "1", t1, "A"), pin("U2", "1", t2, "B")]}, **net)}, comps


class PinToPinTest(unittest.TestCase):
    def level(self, t1, t2):
        nets, comps = two_pin_net(t1, t2)
        recs = by_type(erc(nets, comps), "pin_to_pin")
        return recs[0]["severity"] if recs else None

    def test_kicad_default_pin_map(self):
        cases = [
            ("output", "output", "error"),
            ("output", "open_collector", "error"),
            ("output", "open_emitter", "error"),
            ("tri_state", "tri_state", None),
            ("output", "tri_state", "warning"),
            ("power_out", "power_out", "error"),
            ("passive", "unspecified", "warning"),
            ("input", "passive", None),
            # NC-type pins never join a net (SCH_PIN::ConnectionPropagatesTo), so no marker.
            ("no_connect", "passive", None),
            ("unconnected", "input", None),   # legacy 'N' pin = no_connect
        ]
        for t1, t2, want in cases:
            with self.subTest(t1=t1, t2=t2):
                self.assertEqual(self.level(t1, t2), want)

    def test_pin_map_nc_row(self):
        from schematic.erc_pins import ERROR, pair_level
        self.assertEqual(pair_level("no_connect", "passive"), ERROR)
        self.assertEqual(pair_level("unconnected", "input"), ERROR)

    def test_record_lists_the_pair(self):
        nets, comps = two_pin_net("output", "output")
        rec = by_type(erc(nets, comps), "pin_to_pin")[0]
        self.assertEqual(rec["pairs"], [{"pins": ["U1.1", "U2.1"], "pin_types": ["output", "output"],
                                         "severity": "error"}])
        self.assertEqual(rec["net"], "N")

    def test_stacked_pins_are_not_a_conflict(self):
        # Same symbol, position and name: SCH_PIN::IsStacked.
        c = [comp("U1", [("1", "output", "Q", 5, 5), ("2", "output", "Q", 5, 5)])]
        nets = {"N": {"pins": [pin("U1", "1", "output", "Q"), pin("U1", "2", "output", "Q")]}}
        self.assertEqual(by_type(erc(nets, c), "pin_to_pin"), [])

    def test_same_symbol_other_position_conflicts(self):
        c = [comp("U1", [("1", "output", "Q", 5, 5), ("2", "output", "Q", 5, 10)])]
        nets = {"N": {"pins": [pin("U1", "1", "output", "Q"), pin("U1", "2", "output", "Q")]}}
        self.assertEqual([r["severity"] for r in by_type(erc(nets, c), "pin_to_pin")], ["error"])

    def test_one_marker_per_pin_as_kicad_places_them(self):
        # TestPinToPin: by descending type weight (tri_state 5, output 3; equal weights in the
        # order a hinted multimap insert leaves them) each pin takes its remaining conflicts and
        # names the nearest other pin. kicad-cli 10.0.7 on the same layout (test below):
        # U2 -> U3 warning, U3 -> U1 error; U1 gets no marker of its own.
        c = [comp("U1", [("1", "output", "A", 50, 50)]), comp("U2", [("1", "tri_state", "A", 55, 50)]),
             comp("U3", [("1", "output", "A", 59, 50)])]
        nets = {"N": {"pins": [pin("U1", "1", "output", "A"), pin("U2", "1", "tri_state", "A"),
                               pin("U3", "1", "output", "A")]}}
        rec = by_type(erc(nets, c), "pin_to_pin")[0]
        self.assertEqual(rec["severity"], "error")
        self.assertEqual([(p["pins"], p["severity"]) for p in rec["pairs"]],
                         [(["U2.1", "U3.1"], "warning"), (["U3.1", "U1.1"], "error")])

    def test_one_pin_against_many_gets_one_marker(self):
        # An unspecified pin (weight 10) outranks passives (9) and takes all its conflicts.
        c = [comp("U1", [("1", "unspecified", "A", 0, 0)])] + [
            comp(f"R{k}", [("1", "passive", "~", 10 * k, 0)]) for k in range(1, 6)]
        nets = {"N": {"pins": [pin("U1", "1", "unspecified")]
                      + [pin(f"R{k}", "1", "passive") for k in range(1, 6)]}}
        rec = by_type(erc(nets, c), "pin_to_pin")[0]
        self.assertEqual([p["pins"] for p in rec["pairs"]], [["U1.1", "R1.1"]])

    def test_numeric_reference_order(self):
        from schematic.erc_pins import str_num_cmp
        self.assertEqual(str_num_cmp("U9", "U10"), -1)
        self.assertEqual(str_num_cmp("R10", "R10"), 0)
        self.assertEqual(str_num_cmp("A1", "A1B"), -1)

    def test_output_conflict_is_retired(self):
        nets, comps = two_pin_net("output", "output")
        self.assertEqual(by_type(erc(nets, comps), "output_conflict"), [])


class MultiDriverTest(unittest.TestCase):
    def drivers(self, t1, t2):
        nets, comps = two_pin_net(t1, t2)
        return analyze_connectivity(comps, nets, [])["multi_driver_nets"]

    def test_error_level_driver_pairs_only(self):
        self.assertEqual(self.drivers("tri_state", "tri_state"), [])
        self.assertEqual(self.drivers("output", "tri_state"), [])
        md = self.drivers("output", "open_collector")
        self.assertEqual([(m["net"], m["severity"], [p["component"] for p in m["drivers"]]) for m in md],
                         [("N", "error", ["U1", "U2"])])

    def test_power_symbol_pins_are_not_drivers(self):
        comps = [comp("U1", [("1", "power_out", "VO", 0, 0)]), comp("#PWR1", [("1", "power_out", "V", 9, 0)])]
        nets = {"N": {"pins": [pin("U1", "1", "power_out"), pin("#PWR1", "1", "power_out")]}}
        self.assertEqual(analyze_connectivity(comps, nets, [])["multi_driver_nets"], [])


class UndrivenTest(unittest.TestCase):
    def kinds(self, nets, comps=()):
        return [(r["type"], r["severity"]) for r in erc(nets, comps)
                if r["type"] in ("no_driver", "power_pin_not_driven")]

    def test_passive_drives_an_input(self):
        self.assertEqual(self.kinds(two_pin_net("input", "passive")[0]), [])

    def test_open_collector_alone_does_not_drive(self):
        self.assertEqual(self.kinds(two_pin_net("input", "open_collector")[0]), [("no_driver", "error")])

    def test_power_in_on_passive_is_not_driven(self):
        self.assertEqual(self.kinds(two_pin_net("power_in", "passive")[0]),
                         [("power_pin_not_driven", "error")])

    def test_pwr_flag_drives_a_power_net(self):
        self.assertEqual(self.kinds(two_pin_net("power_in", "passive", has_pwr_flag=True)[0]), [])

    def test_no_connect_marker_silences(self):
        self.assertEqual(self.kinds(two_pin_net("input", "input", no_connect=True, _nc_marker=True)[0]), [])

    def test_nc_pin_does_not_silence_the_drive_test(self):
        # The NC pin is not part of the net; only a no-connect marker silences the test.
        self.assertEqual(self.kinds(two_pin_net("input", "no_connect", no_connect=True)[0]),
                         [("no_driver", "error")])

    def test_marker_silences_with_an_nc_pin_on_the_net(self):
        c = [comp("U1", [("1", "input", "A", 0, 0)]), comp("U2", [("1", "no_connect", "NC", 5, 0)]),
             comp("U3", [("1", "input", "B", 9, 0)])]
        nets = {"N": {"pins": [pin("U1", "1", "input"), pin("U2", "1", "no_connect", "NC"),
                               pin("U3", "1", "input")], "no_connect": True, "_nc_marker": True}}
        self.assertEqual(self.kinds(nets, c), [])

    def test_lone_input_pin(self):
        nets = {"__unnamed_0": {"pins": [pin("U1", "1", "input")]}}
        self.assertEqual(self.kinds(nets), [("no_driver", "error")])

    def test_power_and_ground_names_are_checked(self):
        nets = {"GND": {"pins": [pin("U1", "1", "power_in"), pin("#PWR1", "1", "power_in")]}}
        recs = by_type(erc(nets), "power_pin_not_driven")
        self.assertEqual([p["component"] for p in recs[0]["pins"]], ["U1"])


class NoConnectConnectedTest(unittest.TestCase):
    def test_nc_pin_wired_to_a_resistor(self):
        # The NC pin is a net of its own; the wire on its point makes it connected.
        c = [comp("U1", [("1", "no_connect", "NC", 0, 0)]), comp("R1", [("1", "passive", "~", 10, 0)])]
        nets = {"N": {"pins": [pin("R1", "1", "passive", "~")]},
                "__unnamed_1": {"pins": [pin("U1", "1", "no_connect", "NC")], "no_connect": True,
                                "_nc_touched": True}}
        recs = by_type(erc(nets, c), "no_connect_connected")
        self.assertEqual([(r["net"], r["severity"]) for r in recs], [("__unnamed_1", "warning")])
        self.assertEqual([p["component"] for p in recs[0]["pins"]], ["U1"])

    def test_untouched_nc_pin(self):
        nets = {"__unnamed_0": {"pins": [pin("U1", "1", "no_connect", "NC")], "no_connect": True}}
        self.assertEqual(by_type(erc(nets), "no_connect_connected"), [])

    def test_stacked_nc_pins_alone(self):
        # TestNoConnectPins skips a point where every item is an NC-type pin.
        c = [comp("U1", [("1", "no_connect", "NC", 5, 5), ("2", "no_connect", "NC", 5, 5)])]
        nets = {"__unnamed_0": {"pins": [pin("U1", "1", "no_connect", "NC"),
                                         pin("U1", "2", "no_connect", "NC")], "no_connect": True}}
        self.assertEqual(by_type(erc(nets, c), "no_connect_connected"), [])

    def test_nc_pins_of_other_names_at_one_point(self):
        # Not stacked (names differ) but still all NC pins at one point: no record.
        c = [comp("U1", [("1", "no_connect", "NC1", 5, 5), ("2", "no_connect", "NC2", 5, 5)])]
        nets = {"__unnamed_0": {"pins": [pin("U1", "1", "no_connect", "NC1"),
                                         pin("U1", "2", "no_connect", "NC2")], "no_connect": True}}
        self.assertEqual(by_type(erc(nets, c), "no_connect_connected"), [])

    def test_marker_on_a_two_pin_net(self):
        nets, comps = two_pin_net("passive", "passive", no_connect=True, _nc_marker=True)
        recs = by_type(erc(nets, comps), "no_connect_connected")
        self.assertEqual([[p["component"] for p in r["pins"]] for r in recs], [["U1", "U2"]])

    def test_marker_on_one_pin(self):
        nets = {"N": {"pins": [pin("U1", "1", "input")], "no_connect": True, "_nc_marker": True}}
        self.assertEqual(erc(nets), [])


def _flag_lib():
    return ('(symbol "power:PWR_FLAG" (power) (in_bom yes) (on_board yes)'
            ' (property "Reference" "#FLG" (at 0 0 0)) (property "Value" "PWR_FLAG" (at 0 0 0))'
            ' (symbol "PWR_FLAG_0_1" (pin power_out line (at 0 0 90) (length 0) (name "pwr") (number "1"))))')


def _u_lib(ptype):
    return ('(symbol "t:U" (in_bom yes) (on_board yes)'
            ' (property "Reference" "U" (at 0 0 0)) (property "Value" "U" (at 0 0 0))'
            f' (symbol "U_1_1" (pin {ptype} line (at -5.08 0 0) (length 0) (name "A") (number "1"))))')


def _stacked_nc_lib():
    return ('(symbol "t:NN" (in_bom yes) (on_board yes)'
            ' (property "Reference" "U" (at 0 0 0)) (property "Value" "NN" (at 0 0 0))'
            ' (symbol "NN_1_1" (pin no_connect line (at 0 0 270) (length 0) (name "NC") (number "1"))'
            ' (pin no_connect line (at 0 0 270) (length 0) (name "NC") (number "2"))))')


def net_of_pin(result, ref, num):
    return next(n for n, info in result["nets"].items()
                if any(p["component"] == ref and p["pin_number"] == num for p in info["pins"]))


def _one_pin_lib(name, ptype):
    return (f'(symbol "t:{name}" (in_bom yes) (on_board yes)'
            f' (property "Reference" "U" (at 0 0 0)) (property "Value" "{name}" (at 0 0 0))'
            f' (symbol "{name}_1_1" (pin {ptype} line (at 0 0 270) (length 0) (name "A") (number "1"))))')


class SchematicTest(unittest.TestCase):
    def test_pwr_flag_on_a_power_input(self):
        # U1 power_in wired to R1 with a PWR_FLAG on the wire: driven, no record.
        s = Sheet(20250114)
        s.symbol("t:U", "U1", "U", 55.08, 50, ("1",))
        s.r("R1", 40, 50); s.wire(40, 50, 45, 50); s.wire(45, 50, 50, 50)
        s.symbol("power:PWR_FLAG", "#FLG1", "PWR_FLAG", 45, 50, ("1",))
        r = run({"t.kicad_sch": s.text([R_LIB, _u_lib("power_in"), _flag_lib()])})
        kinds = [w["type"] for w in r["design_analysis"]["erc_warnings"]]
        self.assertNotIn("power_pin_not_driven", kinds)

    def test_power_input_without_a_flag(self):
        s = Sheet(20250114)
        s.symbol("t:U", "U1", "U", 55.08, 50, ("1",))
        s.r("R1", 40, 50); s.wire(40, 50, 50, 50)
        r = run({"t.kicad_sch": s.text([R_LIB, _u_lib("power_in")])})
        recs = [w for w in r["design_analysis"]["erc_warnings"] if w["type"] == "power_pin_not_driven"]
        self.assertEqual([sorted(p["component"] for p in w["pins"]) for w in recs], [["R1", "U1"]])

    def test_pin_to_pin_markers_match_kicad(self):
        # kicad-cli 10.0.7 sch erc on this file: pin_to_pin error [U3 Pin 1, U1 Pin 1],
        # pin_to_pin warning [U2 Pin 1, U3 Pin 1].
        s = Sheet(20250114)
        s.symbol("t:O", "U1", "O", 50, 50, ("1",))
        s.symbol("t:T", "U2", "T", 55, 50, ("1",))
        s.symbol("t:O", "U3", "O", 59, 50, ("1",))
        s.wire(50, 50, 55, 50); s.wire(55, 50, 59, 50)
        r = run({"t.kicad_sch": s.text([_one_pin_lib("O", "output"), _one_pin_lib("T", "tri_state")])})
        recs = [w for w in r["design_analysis"]["erc_warnings"] if w["type"] == "pin_to_pin"]
        self.assertEqual([sorted((p["pins"][0], p["pins"][1], p["severity"]) for p in w["pairs"])
                          for w in recs],
                         [[("U2.1", "U3.1", "warning"), ("U3.1", "U1.1", "error")]])

    def test_wired_nc_pin_as_kicad(self):
        # kicad-cli 10.0.7: only no_connect_connected [U2 Pin 1, wire]; netlist keeps U2.1 on
        # its own unconnected net, U1 (input) and U3 (passive) share a driven net.
        s = Sheet(20250114)
        s.symbol("t:I", "U1", "I", 50, 50, ("1",))
        s.symbol("t:N", "U2", "N", 60, 50, ("1",))
        s.symbol("t:P", "U3", "P", 70, 50, ("1",))
        s.wire(50, 50, 60, 50); s.wire(60, 50, 70, 50)
        r = run({"t.kicad_sch": s.text([_one_pin_lib("I", "input"), _one_pin_lib("N", "no_connect"),
                                        _one_pin_lib("P", "passive")])})
        kinds = sorted((w["type"], w["severity"]) for w in r["design_analysis"]["erc_warnings"])
        self.assertEqual(kinds, [("no_connect_connected", "warning")])

    def test_marker_and_wired_nc_pin_as_kicad(self):
        # kicad-cli 10.0.7: no_connect_connected [U2 Pin 1, wire] and no_connect_connected
        # [marker, U3 Pin 1]; no pin_not_driven (the marker on the U1/U3 net silences the drive test).
        s = Sheet(20250114)
        s.symbol("t:I", "U1", "I", 50, 50, ("1",))
        s.symbol("t:N", "U2", "N", 60, 50, ("1",))
        s.symbol("t:I", "U3", "I", 70, 50, ("1",))
        s.wire(50, 50, 60, 50); s.wire(60, 50, 70, 50)
        s.items.append('(no_connect (at 70 50) (uuid "00000000-0000-0000-0000-00000000fffe"))')
        r = run({"t.kicad_sch": s.text([_one_pin_lib("I", "input"), _one_pin_lib("N", "no_connect")])})
        recs = r["design_analysis"]["erc_warnings"]
        self.assertEqual(sorted((w["type"], tuple(sorted(p["component"] for p in w["pins"])))
                                for w in recs),
                         [("no_connect_connected", ("U1", "U3")), ("no_connect_connected", ("U2",))])
        self.assertEqual([p["component"] for p in r["nets"][net_of_pin(r, "U2", "1")]["pins"]], ["U2"])

    def test_nc_pin_wired_to_a_label_is_its_own_net(self):
        # kicad-cli 10.0.7: U2.1 on its own net unconnected-(U2-A-Pad1), U1.1 on TEST;
        # no_connect_connected [U2 Pin 1, wire].
        s = Sheet(20250114)
        s.symbol("t:N", "U2", "N", 60, 50, ("1",))
        s.symbol("t:I", "U1", "I", 80, 50, ("1",))
        s.wire(60, 50, 70, 50); s.label("label", "TEST", 70, 50)
        s.wire(80, 50, 80, 40); s.label("label", "TEST", 80, 40)
        r = run({"t.kicad_sch": s.text([_one_pin_lib("I", "input"), _one_pin_lib("N", "no_connect")])})
        self.assertEqual([p["component"] for p in r["nets"]["TEST"]["pins"]], ["U1"])
        own = net_of_pin(r, "U2", "1")
        self.assertTrue(own.startswith("__unnamed_"))
        self.assertEqual([p["component"] for p in r["nets"][own]["pins"]], ["U2"])
        recs = [w for w in r["design_analysis"]["erc_warnings"] if w["type"] == "no_connect_connected"]
        self.assertEqual([w["net"] for w in recs], [own])

    def test_stacked_nc_pins_are_two_nets(self):
        # kicad-cli 10.0.7: two single-pin nets, no ERC record (only NC pins at the point).
        s = Sheet(20250114)
        s.symbol("t:NN", "U1", "NN", 50, 50, ("1", "2"))
        r = run({"t.kicad_sch": s.text([_stacked_nc_lib()])})
        self.assertNotEqual(net_of_pin(r, "U1", "1"), net_of_pin(r, "U1", "2"))
        self.assertEqual(r["design_analysis"]["erc_warnings"], [])

    def test_nc_pin_on_a_wire_stub(self):
        # kicad-cli 10.0.7: no_connect_connected [U1 Pin 1, wire].
        s = Sheet(20250114)
        s.symbol("t:N", "U1", "N", 50, 50, ("1",))
        s.wire(50, 50, 60, 50)
        r = run({"t.kicad_sch": s.text([_one_pin_lib("N", "no_connect")])})
        recs = r["design_analysis"]["erc_warnings"]
        self.assertEqual([(w["type"], [p["component"] for p in w["pins"]]) for w in recs],
                         [("no_connect_connected", ["U1"])])

    def test_nc_pin_on_ground_leaves_the_ground_net(self):
        # kicad-cli 10.0.7: GND holds R1.1 only; U1.1 is unconnected-(U1-A-Pad1).
        s = Sheet(20250114)
        s.symbol("t:N", "U1", "N", 50, 50, ("1",))
        s.symbol("power:GND", "#PWR01", "GND", 50, 50, ("1",))
        s.r("R1", 40, 50); s.wire(40, 50, 50, 50)
        r = run({"t.kicad_sch": s.text([R_LIB, _one_pin_lib("N", "no_connect"),
                                        power_lib("power:GND", "GND", hidden=False)])})
        self.assertEqual(members(r, "GND"), ["R1.1"])
        self.assertFalse(r["nets"]["GND"]["no_connect"])
        self.assertTrue(r["nets"][net_of_pin(r, "U1", "1")]["no_connect"])

    def test_no_connect_marker_on_a_wired_pin(self):
        s = Sheet(20250114)
        s.symbol("t:U", "U1", "U", 55.08, 50, ("1",))
        s.r("R1", 40, 50); s.wire(40, 50, 50, 50)
        s.items.append('(no_connect (at 50 50) (uuid "00000000-0000-0000-0000-00000000ffff"))')
        r = run({"t.kicad_sch": s.text([R_LIB, _u_lib("input")])})
        recs = [w for w in r["design_analysis"]["erc_warnings"] if w["type"] == "no_connect_connected"]
        self.assertEqual([(w["severity"], sorted(p["component"] for p in w["pins"])) for w in recs],
                         [("warning", ["R1", "U1"])])


if __name__ == "__main__":
    unittest.main()

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
from tools.tests.test_same_sheet_power_names import R_LIB, Sheet, run  # noqa: E402


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
            ("no_connect", "passive", "error"),
            ("unconnected", "input", "error"),   # legacy 'N' pin = no_connect
        ]
        for t1, t2, want in cases:
            with self.subTest(t1=t1, t2=t2):
                self.assertEqual(self.level(t1, t2), want)

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

    def test_record_severity_is_the_worst_pair(self):
        c = [comp("U1", [("1", "output", "A", 0, 0)]), comp("U2", [("1", "tri_state", "B", 5, 0)]),
             comp("U3", [("1", "output", "C", 9, 0)])]
        nets = {"N": {"pins": [pin("U1", "1", "output"), pin("U2", "1", "tri_state"),
                               pin("U3", "1", "output")]}}
        rec = by_type(erc(nets, c), "pin_to_pin")[0]
        self.assertEqual(rec["severity"], "error")
        self.assertEqual(sorted(p["severity"] for p in rec["pairs"]), ["error", "warning", "warning"])

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
        self.assertEqual(self.kinds(two_pin_net("input", "input", no_connect=True)[0]), [])

    def test_lone_input_pin(self):
        nets = {"__unnamed_0": {"pins": [pin("U1", "1", "input")]}}
        self.assertEqual(self.kinds(nets), [("no_driver", "error")])

    def test_power_and_ground_names_are_checked(self):
        nets = {"GND": {"pins": [pin("U1", "1", "power_in"), pin("#PWR1", "1", "power_in")]}}
        recs = by_type(erc(nets), "power_pin_not_driven")
        self.assertEqual([p["component"] for p in recs[0]["pins"]], ["U1"])


class NoConnectConnectedTest(unittest.TestCase):
    def test_nc_pin_wired_to_a_resistor(self):
        nets, comps = two_pin_net("no_connect", "passive", no_connect=True)
        recs = by_type(erc(nets, comps), "no_connect_connected")
        self.assertEqual([(r["net"], r["severity"]) for r in recs], [("N", "warning")])

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
        nets, comps = two_pin_net("passive", "passive", no_connect=True)
        recs = by_type(erc(nets, comps), "no_connect_connected")
        self.assertEqual([[p["component"] for p in r["pins"]] for r in recs], [["U1", "U2"]])

    def test_marker_on_one_pin(self):
        nets = {"N": {"pins": [pin("U1", "1", "input")], "no_connect": True}}
        self.assertEqual(erc(nets), [])


def _flag_lib():
    return ('(symbol "power:PWR_FLAG" (power) (in_bom yes) (on_board yes)'
            ' (property "Reference" "#FLG" (at 0 0 0)) (property "Value" "PWR_FLAG" (at 0 0 0))'
            ' (symbol "PWR_FLAG_0_1" (pin power_out line (at 0 0 90) (length 0) (name "pwr") (number "1"))))')


def _u_lib(ptype):
    return ('(symbol "t:U" (in_bom yes) (on_board yes)'
            ' (property "Reference" "U" (at 0 0 0)) (property "Value" "U" (at 0 0 0))'
            f' (symbol "U_1_1" (pin {ptype} line (at -5.08 0 0) (length 0) (name "A") (number "1"))))')


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

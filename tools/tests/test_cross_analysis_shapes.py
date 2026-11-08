"""Cross-analysis rules read the keys the schematic and PCB analyzers write."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.tests._fixtures import fixture

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cross_analysis as ca  # noqa: E402


def _run(script, *args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True,
                       text=True, encoding="utf-8", env=env)
    return r


class Shapes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        r = _run("analyze_schematic.py", str(fixture("determinism", "usb_dual_esd.kicad_sch")),
                 "--output", str(t / "sch.json"))
        assert r.returncode == 0, r.stderr
        r = _run("analyze_pcb.py", str(fixture("simple-project", "simple.kicad_pcb")), "--full",
                 "--output", str(t / "pcb.json"))
        assert r.returncode == 0, r.stderr
        cls.sch = json.loads((t / "sch.json").read_text(encoding="utf-8"))
        cls.pcb = json.loads((t / "pcb.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _checks(self, sch, pcb=None):
        findings, runs = ca.run_all_checks(sch, pcb)
        return findings, {r["check"] if "check" in r else r.get("rule_id"): r for r in runs}, runs

    def test_producer_shapes(self):
        for fp in self.pcb["footprints"]:
            self.assertIn("pad_nets", fp)
            self.assertNotIn("pads", fp)
        for c in self.sch["components"]:
            self.assertIn("pin_nets", c)
        u3 = [f for f in self.sch["findings"] if f.get("detector") == "detect_power_regulators"
              and f.get("output_rail") == "+3V3"][0]
        self.assertEqual(u3["power_dissipation"]["estimated_iout_A"], 0.087)
        dc = [f for f in self.sch["findings"] if f.get("detector") == "detect_decoupling"]
        self.assertTrue(dc)
        for f in dc:
            self.assertIn("rail", f)
            self.assertIn("capacitors", f)

    def test_eg001_usb_dual_esd(self):
        eg = [f for f in ca.check_esd_coverage_gaps(self.sch, None) if f["rule_id"] == "EG-001"]
        self.assertEqual(len(eg), 1)
        self.assertEqual(eg[0]["components"], ["J1"])
        self.assertEqual(set(eg[0]["nets"]), {"__unnamed_24", "__unnamed_25"})
        self.assertEqual(eg[0]["severity"], "info")

    @staticmethod
    def _usb_conn(pin_nets):
        return {"components": [{"reference": "J9", "type": "connector", "value": "USB_C",
                                "lib_id": "Connector:USB_C", "pin_nets": pin_nets}],
                "findings": []}

    def test_eg001_sheet_ground_excluded(self):
        sch = self._usb_conn({"1": "/Sheet/GND", "2": "/Sheet/CC1"})
        eg = ca.check_esd_coverage_gaps(sch, None)
        self.assertEqual([f["nets"] for f in eg], [["/Sheet/CC1"]])

    def test_eg001_sheet_power_excluded(self):
        sch = self._usb_conn({"1": "/USB/VBUS", "2": "/USB/CC1", "3": "/Slider_DAC/+24V",
                              "4": "/Power/+5V"})
        eg = ca.check_esd_coverage_gaps(sch, None)
        self.assertEqual([f["nets"] for f in eg], [["/USB/CC1"]])
        self.assertIn("1 unprotected", eg[0]["summary"])

    def test_da001_usb_dual_esd(self):
        rec = []

        class R:
            def record(self, check, ran, reason, items, n):
                rec.append((check, ran, items, n))
        self.assertEqual(ca.check_decoupling_adequacy(self.sch, None, recorder=R()), [])
        self.assertEqual(rec, [("DA-001", True, 4, 0)])

        sch = copy.deepcopy(self.sch)
        for f in sch["findings"]:
            if f.get("detector") == "detect_decoupling" and f["rail"] == "+3V3":
                f["capacitors"] = f["capacitors"][:1]
        out = ca.check_decoupling_adequacy(sch, None)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["severity"], "info")
        self.assertEqual(out[0]["nets"], ["+3V3"])
        self.assertIn("1 caps for 3 ICs", out[0]["summary"])

    def test_da001_skips_unfitted_ics(self):
        def ic(ref, **flags):
            return {"reference": ref, "type": "ic", "pin_nets": {"1": "+3V3", "2": "GND"}, **flags}
        sch = {"components": [ic("U1", dnp=False, on_board=True), ic("U2", dnp=True, on_board=True),
                              ic("U3", dnp=False, on_board=False)],
               "findings": [{"detector": "detect_decoupling", "rail": "+3V3",
                             "capacitors": [{"ref": "C1"}]}]}
        self.assertEqual(ca.check_decoupling_adequacy(sch, None), [])

        sch["components"].append(ic("U4", dnp=False, on_board=True))
        out = ca.check_decoupling_adequacy(sch, None)
        self.assertEqual(len(out), 1)
        self.assertIn("1 caps for 2 ICs", out[0]["summary"])
        self.assertEqual(out[0]["recommendation"], "Add 1 more 100nF caps on +3V3.")

    @staticmethod
    def _sch(iout, in_rail, out_rail, connector=None):
        comps = [{"reference": connector, "type": "connector"}] if connector else []
        return {"components": comps, "findings": [{
            "detector": "detect_power_regulators", "input_rail": in_rail, "output_rail": out_rail,
            "power_dissipation": {"estimated_iout_A": iout}}]}

    @staticmethod
    def _pcb(width, net, footprints=()):
        return {"nets": {"1": net}, "footprints": list(footprints),
                "tracks": {"segments": [{"net": 1, "width": width}]}}

    def test_tw001_interpolates(self):
        sch = self._sch(0.087, "VBUS", "+3V3")
        self.assertEqual(ca.check_trace_width_power(sch, self._pcb(0.1, "+3V3")), [])
        self.assertAlmostEqual(ca._min_trace_width_for_current(0.087), 0.0435, places=4)
        sch = self._sch(0.9, "VBUS", "+3V3")
        self.assertAlmostEqual(ca._min_trace_width_for_current(0.9), 0.45, places=6)
        fired = ca.check_trace_width_power(sch, self._pcb(0.3, "+3V3"))
        self.assertEqual([f["rule_id"] for f in fired], ["TW-001"])
        self.assertEqual(ca.check_trace_width_power(sch, self._pcb(0.4, "+3V3")), [])

    _CONN = {"reference": "J1", "courtyard": {"min_x": 0, "min_y": 0, "max_x": 5, "max_y": 5},
             "pad_nets": {"1": {"net": "+24V"}, "2": {"net": "+24V"},
                          "3": {"net": "+24V"}, "4": {"net": "GND"}}}

    def test_cc001_reads_pad_nets(self):
        sch = self._sch(2.1, "+24V", "+5V", connector="J1")
        pcb = self._pcb(0.25, "+24V", [self._CONN])
        pcb["tracks"]["segments"][0].update(x1=1, y1=1, x2=30, y2=1)
        out = ca.check_connector_current(sch, pcb)
        self.assertEqual([f["rule_id"] for f in out], ["CC-001"])
        self.assertEqual(out[0]["nets"], ["+24V"])
        self.assertIn("~2.1A (est.)", out[0]["summary"])
        self.assertIn("output capacitance", out[0]["description"])
        self.assertIn("narrowest trace leaving the connector is 0.25mm", out[0]["description"])

    def test_cc001_measures_the_connector_to_regulator_path(self):
        # A thin stub elsewhere on the net does not fire when the path to the regulator is wide.
        sch = self._sch(2.1, "+24V", "+5V", connector="J1")
        sch["findings"][0]["ref"] = "U1"
        pcb = self._pcb(0.25, "+24V", [self._CONN])
        pcb["pad_to_pad_distances"] = {
            "J1.1-U1.3": {"net": "+24V", "min_width_mm": 1.5},
            "J1.1-C4.1": {"net": "+24V", "min_width_mm": 0.25}}
        self.assertEqual(ca.check_connector_current(sch, pcb), [])
        pcb["pad_to_pad_distances"]["J1.1-U1.3"]["min_width_mm"] = 0.3
        out = ca.check_connector_current(sch, pcb)
        self.assertIn("between the connector and those regulators is 0.30mm", out[0]["description"])

    def test_cc001_falls_back_to_the_track_leaving_the_connector(self):
        # No routed path was measured: the wide track leaving the connector counts, not a
        # thin track elsewhere on the net.
        sch = self._sch(2.1, "+24V", "+5V", connector="J1")
        pcb = self._pcb(0.25, "+24V", [self._CONN])
        pcb["tracks"]["segments"][0].update(x1=20, y1=20, x2=30, y2=20)
        pcb["tracks"]["segments"].append(
            {"net": 1, "width": 1.5, "x1": 2, "y1": 2, "x2": 20, "y2": 2})
        self.assertEqual(ca.check_connector_current(sch, pcb), [])

    def test_cc001_without_a_measured_track_does_not_fire(self):
        sch = self._sch(2.1, "+24V", "+5V", connector="J1")
        pcb = self._pcb(0.25, "+24V", [self._CONN])
        pcb["tracks"]["segments"][0].update(x1=10, y1=10, x2=30, y2=10)
        self.assertEqual(ca.check_connector_current(sch, pcb), [])

    def test_regulator_input_current(self):
        ldo = {"output_rail": "+3V3", "power_dissipation": {
            "estimated_iout_A": 1.0, "vin_estimated_V": 5.0, "vout_V": 3.3}}
        self.assertEqual(ca._reg_iin(ldo), 1.0)
        # 2.0 A out at +5V from 24 V at 85 %: 2 * 5 / (24 * 0.85) = 0.49 A in.
        buck = {"output_rail": "+5V", "power_dissipation": {
            "estimated_iout_A": 2.0, "vin_estimated_V": 24.0, "vout_V": 2.0,
            "efficiency_assumed": 0.85}}
        self.assertAlmostEqual(ca._reg_iin(buck), 2.0 * 5 / (24 * 0.85))   # Vout from the rail name
        self.assertEqual(round(ca._reg_iin(buck), 2), 0.49)
        buck["output_rail"] = "VOUT"
        self.assertAlmostEqual(ca._reg_iin(buck), 2.0 * 2.0 / (24 * 0.85))

    def test_tw001_input_rail_carries_input_current(self):
        sch = self._sch(2.0, "+24V", "+5V")
        sch["findings"][0]["power_dissipation"].update(
            vin_estimated_V=24.0, vout_V=5.0, efficiency_assumed=0.85)
        self.assertEqual(ca.check_trace_width_power(sch, self._pcb(0.25, "+24V")), [])
        out = ca.check_trace_width_power(sch, self._pcb(0.25, "+5V"))
        self.assertEqual([f["summary"] for f in out],
                         ["Power net +5V: trace 0.25mm too narrow for ~2.0A (est.)"])

    def test_cc001_without_tracks_records_not_run(self):
        rec = []

        class R:
            def record(self, check, ran, reason, items, n):
                rec.append((check, ran, reason, items, n))
        sch = self._sch(2.1, "+24V", "+5V", connector="J1")
        fp = {"reference": "J1", "pad_nets": {"1": {"net": "+24V"}}}
        pcb = {"nets": {"1": "+24V"}, "footprints": [fp], "tracks": {}}
        self.assertEqual(ca.check_connector_current(sch, pcb, recorder=R()), [])
        self.assertEqual(rec, [("CC-001", False, "no PCB track segments present", 0, 0)])

        rec.clear()
        pcb = self._pcb(0.25, "+24V", [self._CONN])
        pcb["tracks"]["segments"][0].update(x1=1, y1=1, x2=30, y2=1)
        ca.check_connector_current(sch, pcb, recorder=R())
        self.assertEqual(rec, [("CC-001", True, None, 1, 1)])

    def test_dp005_dp_dm_pairs(self):
        def cls(*names):
            return {"net_classifications": {n: {"differential": True} for n in names}}
        self.assertEqual(ca._find_diff_pairs(cls("USB_DP", "USB_DM")), [("USB_DP", "USB_DM")])
        self.assertEqual(ca._find_diff_pairs(cls("USB_DP", "USB_DN")), [("USB_DP", "USB_DN")])
        self.assertEqual(ca._find_diff_pairs({"net_classifications": {"INP": {}, "INN": {}}}), [])

    def test_non_full_pcb_no_crash(self):
        t = Path(self.tmp.name)
        r = _run("analyze_pcb.py", str(fixture("simple-project", "simple.kicad_pcb")),
                 "--output", str(t / "plain.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        pcb = json.loads((t / "plain.json").read_text(encoding="utf-8"))
        sch = {"components": [], "findings": []}
        findings, runs = ca.run_all_checks(sch, pcb)
        self.assertEqual([f for f in findings if not f["rule_id"].startswith("XV-")], [])
        self.assertTrue(runs)
        for entry in runs:
            self.assertIn("ran", entry)


class EsdGapPowerSymbolRail(unittest.TestCase):
    @staticmethod
    def _sch(extra_pins):
        pins = extra_pins + [{"component": "U1", "pin_type": "input"},
                             {"component": "J1", "pin_type": "passive"}]
        return {"components": [
                    {"reference": "J1", "type": "connector", "value": "USB_C",
                     "lib_id": "Connector:USB_C_Receptacle", "pin_nets": {"1": "VPP"}},
                    {"reference": "U1", "type": "ic"}],
                "nets": {"VPP": {"pins": pins}}, "findings": []}

    def test_vpp_net_marked_as_rail_by_a_power_symbol_is_not_a_gap(self):
        sch = self._sch([{"component": "#PWR01", "pin_type": None}])
        self.assertEqual(ca.check_esd_coverage_gaps(sch, None), [])

    def test_vpp_signal_without_a_power_symbol_is_still_a_gap(self):
        eg = ca.check_esd_coverage_gaps(self._sch([]), None)
        self.assertEqual([f["nets"] for f in eg], [["VPP"]])


if __name__ == "__main__":
    unittest.main()

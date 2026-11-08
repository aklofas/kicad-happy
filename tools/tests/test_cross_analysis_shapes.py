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

    def test_cc001_reads_pad_nets(self):
        sch = self._sch(2.1, "+24V", "+5V", connector="J1")
        fp = {"reference": "J1", "pad_nets": {"1": {"net": "+24V"}, "2": {"net": "+24V"},
                                              "3": {"net": "+24V"}, "4": {"net": "GND"}}}
        out = ca.check_connector_current(sch, self._pcb(0.25, "+24V", [fp]))
        self.assertEqual([f["rule_id"] for f in out], ["CC-001"])
        self.assertEqual(out[0]["nets"], ["+24V"])
        self.assertIn("output capacitance", out[0]["description"])
        self.assertIn("J1 carries 2.1A (estimated from the regulator output", out[0]["description"])

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
        ca.check_connector_current(sch, self._pcb(0.25, "+24V", [fp]), recorder=R())
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

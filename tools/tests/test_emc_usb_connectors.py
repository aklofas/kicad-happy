"""EMC USB speed (DP-001) and connector pad nets (IO-001 fallback, test plan)."""
import json, math, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import (check_connector_filtering, check_diff_pair_skew,  # noqa: E402
                       generate_test_plan)
from finding_schema import Det  # noqa: E402

# m258 (RP2040 board): USB-RP2040-DP 141.489 mm, USB-RP2040-DM 135.384 mm on εr 4.5.
# Skew = 6.105 mm × √((4.5+1)/2) / c = 33.8 ps; 33.8 / 25 − 1 = 35 % over the USB 2.0 HS budget.
DP, DM = "USB-RP2040-DP", "USB-RP2040-DM"
PCB_PAIR = {"setup": {"stackup": [{"name": "F.Cu", "type": "copper"},
                                  {"name": "dielectric 1", "type": "core", "epsilon_r": 4.5}]},
            "net_lengths": [{"net": DP, "total_length_mm": 141.489},
                            {"net": DM, "total_length_mm": 135.384}],
            "footprints": []}


def _pair_schematic(project_dir):
    return {"inputs": {"source_files": [str(Path(project_dir) / "board.kicad_sch")]},
            "components": [{"reference": "U1", "type": "ic", "value": "RP2040", "mpn": "RP2040"}],
            "design_analysis": {"differential_pairs": [
                {"type": "USB", "positive": DP, "negative": DM, "shared_ics": ["U1"]}]}}


def _write_extraction(project_dir, speed, score=8.0):
    d = Path(project_dir) / "datasheets" / "extracted"
    d.mkdir(parents=True)
    (d / "RP2040.json").write_text(json.dumps({
        "topology": "mcu", "peripherals": {"usb": {"speed": speed}},
        "extraction_metadata": {"extraction_score": score, "extraction_version": 2}}), encoding="utf-8")


class UsbSpeed(unittest.TestCase):
    def test_arithmetic(self):
        skew = 6.105 * math.sqrt((4.5 + 1) / 2) / 0.299792458
        self.assertEqual(f"{skew:.1f}", "33.8")
        self.assertEqual(f"{(skew / 25 - 1) * 100:.0f}", "35")

    def test_unresolved_speed_uses_the_full_speed_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            fs = check_diff_pair_skew(PCB_PAIR, _pair_schematic(tmp))
        self.assertEqual([f for f in fs if f["rule_id"] == "DP-001"], [])

    def test_extracted_full_speed_part_has_no_dp001(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_extraction(tmp, "FS")
            fs = check_diff_pair_skew(PCB_PAIR, _pair_schematic(tmp))
        self.assertEqual(fs, [])

    def test_trusted_high_speed_extraction_holds_the_25ps_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_extraction(tmp, "HS")
            fs = check_diff_pair_skew(PCB_PAIR, _pair_schematic(tmp))
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["severity"], "error")
        self.assertIn("(33.8 ps skew)", fs[0]["description"])
        self.assertIn("limit of 25 ps by 35%", fs[0]["description"])
        self.assertIn("USB-HS", fs[0]["summary"])

    def test_untrusted_high_speed_extraction_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_extraction(tmp, "HS", score=3.0)
            fs = check_diff_pair_skew(PCB_PAIR, _pair_schematic(tmp))
        self.assertEqual(fs, [])

    def test_part_number_must_match_the_extraction_exactly(self):
        # An RP2040 extraction says nothing about an "RP2040X" part.
        with tempfile.TemporaryDirectory() as tmp:
            _write_extraction(tmp, "HS")
            sch = _pair_schematic(tmp)
            sch["components"][0].update(value="RP2040X", mpn="RP2040X")
            fs = check_diff_pair_skew(PCB_PAIR, sch)
        self.assertEqual(fs, [])


def _prot(ref, ptype, net):
    return {"detector": Det.PROTECTION_DEVICES, "rule_id": "PD-DET", "ref": ref, "type": ptype,
            "protected_net": net, "protected_nets": [net]}


def _usb_c(pad_nets, ref="J1", **extra):
    fp = {"reference": ref, "value": "USB_C_Receptacle", "x": 0.0, "y": 0.0,
          "library": "Connector_USB:USB_C_Receptacle_GCT_USB4085",
          "pad_nets": {num: {"net": net} for num, net in pad_nets.items()}}
    fp.update(extra)
    return fp


USB_PADS = {"A1": "GND", "A4": "VBUS", "A6": "USB_D+", "A7": "USB_D-", "B1": "GND"}


def _io001(pcb, sch):
    return [(f["components"], f["severity"]) for f in check_connector_filtering(pcb, sch)
            if f["rule_id"] == "IO-001"]


class ConnectorPadNets(unittest.TestCase):
    def _pcb(self, conn):
        # The protection part sits 40 mm away: outside the 25 mm footprint search.
        return {"footprints": [conn, {"reference": "U2", "value": "USBLC6-2SC6", "x": 40.0, "y": 0.0}]}

    def test_esd_ic_on_the_connector_data_net_clears_io001(self):
        sch = {"components": [], "findings": [_prot("U2", "esd_ic", "USB_D+")]}
        self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS)), sch), [])

    def test_fuse_on_vbus_clears_nothing(self):
        sch = {"components": [], "findings": [_prot("F1", "fuse", "VBUS")]}
        self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS)), sch), [(["J1"], "error")])

    def test_fuse_on_a_signal_net_clears_nothing(self):
        sch = {"components": [], "findings": [_prot("F1", "fuse", "USB_D+")]}
        self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS)), sch), [(["J1"], "error")])

    def test_reverse_polarity_diode_on_a_ground_clears_nothing(self):
        pads = dict(USB_PADS, B1="GNDD")
        sch = {"components": [], "findings": [_prot("D1", "reverse_polarity", "GNDD")]}
        self.assertEqual(_io001(self._pcb(_usb_c(pads)), sch), [(["J1"], "error")])

    def test_tvs_on_a_rail_the_shared_classifier_knows_clears_nothing(self):
        # +BATT and +VSW are rails to kicad_core.netnames but not to the EMC prefix list.
        for rail in ("+BATT", "+VSW"):
            pads = dict(USB_PADS, A4=rail)
            sch = {"components": [], "findings": [_prot("D1", "diode", rail)]}
            self.assertEqual(_io001(self._pcb(_usb_c(pads)), sch), [(["J1"], "error")], rail)

    def test_dnp_protection_part_clears_nothing(self):
        sch = {"components": [{"reference": "U2", "type": "ic", "dnp": True}],
               "findings": [_prot("U2", "esd_ic", "USB_D+")]}
        self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS)), sch), [(["J1"], "error")])

    def test_protection_on_another_connectors_net_clears_nothing(self):
        sch = {"components": [], "findings": [_prot("U2", "esd_ic", "UART_TX")]}
        self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS)), sch), [(["J1"], "error")])

    def test_dnp_connector_pad_nets_add_no_io001(self):
        # The pad-net fallback only clears an IO-001: a DNP connector is judged like a fitted one.
        for findings in ([], [_prot("U2", "esd_ic", "USB_D+")], [_prot("F1", "fuse", "VBUS")]):
            sch = {"components": [], "findings": findings}
            self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS, dnp=True)), sch),
                             _io001(self._pcb(_usb_c(USB_PADS)), sch))


class TestPlanPadNets(unittest.TestCase):
    def test_interface_risk_reads_the_connector_pad_nets(self):
        sch = {"design_analysis": {"differential_pairs": [
            {"positive": "USB_D+", "negative": "USB_D-", "type": "USB"}]}}
        pcb = {"footprints": [_usb_c(USB_PADS)]}
        plan = generate_test_plan(sch, pcb, [])
        self.assertEqual([[r["connector"], r["protocol"], r["risk_score"]] for r in plan["interface_risks"]],
                         [["J1", "USB", 7]])

    def test_no_pairs_no_protocol(self):
        plan = generate_test_plan({"design_analysis": {}}, {"footprints": [_usb_c(USB_PADS)]}, [])
        self.assertEqual([[r["connector"], r["protocol"], r["risk_score"]] for r in plan["interface_risks"]],
                         [["J1", "unknown", 3]])


if __name__ == "__main__":
    unittest.main()

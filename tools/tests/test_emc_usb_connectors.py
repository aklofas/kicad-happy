"""EMC USB speed (DP-001) and connector pad nets (IO-001 fallback, test plan)."""
import json, math, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from emc_rules import (_is_superspeed_net, check_connector_filtering,  # noqa: E402
                       check_diff_pair_skew, generate_test_plan)
from finding_schema import Det  # noqa: E402

# m258 (RP2040 board): USB-RP2040-DP 141.489 mm, USB-RP2040-DM 135.384 mm on εr 4.5.
# Skew = 6.105 mm × √((4.5+1)/2) / c = 33.8 ps; 33.8 / 25 − 1 = 35 % over the USB 2.0 HS budget.
DP, DM = "USB-RP2040-DP", "USB-RP2040-DM"
PCB_PAIR = {"setup": {"stackup": [{"name": "F.Cu", "type": "copper"},
                                  {"name": "dielectric 1", "type": "core", "epsilon_r": 4.5}]},
            "net_lengths": [{"net": DP, "total_length_mm": 141.489},
                            {"net": DM, "total_length_mm": 135.384}],
            "footprints": []}


def _pair_schematic(project_dir, positive=DP, negative=DM):
    return {"inputs": {"source_files": [str(Path(project_dir) / "board.kicad_sch")]},
            "components": [{"reference": "U1", "type": "ic", "value": "RP2040", "mpn": "RP2040"}],
            "design_analysis": {"differential_pairs": [
                {"type": "USB", "positive": positive, "negative": negative, "shared_ics": ["U1"]}]}}


def _pcb_pair(positive, negative):
    pcb = json.loads(json.dumps(PCB_PAIR))
    pcb["net_lengths"][0]["net"], pcb["net_lengths"][1]["net"] = positive, negative
    return pcb


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

    def test_superspeed_part_holds_its_d_pair_to_the_hs_budget(self):
        # On a USB 3 part D+/D- is a USB 2.0 HS link: 25 ps, not the SuperSpeed 5 ps.
        with tempfile.TemporaryDirectory() as tmp:
            _write_extraction(tmp, "SS")
            fs = check_diff_pair_skew(PCB_PAIR, _pair_schematic(tmp))
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["severity"], "error")
        self.assertIn("(33.8 ps skew)", fs[0]["description"])
        self.assertIn("limit of 25 ps by 35%", fs[0]["description"])
        self.assertIn("USB-HS", fs[0]["summary"])

    def test_superspeed_lane_on_the_same_part_takes_the_5ps_budget(self):
        # 33.8 ps / 5 ps − 1 = 575 %.
        skew = 6.105 * math.sqrt((4.5 + 1) / 2) / 0.299792458
        self.assertEqual(f"{(skew / 5 - 1) * 100:.0f}", "575")
        tx_p, tx_n = "/USB/USB3_TX_P", "/USB/USB3_TX_N"
        with tempfile.TemporaryDirectory() as tmp:
            _write_extraction(tmp, "SS")
            fs = check_diff_pair_skew(_pcb_pair(tx_p, tx_n), _pair_schematic(tmp, tx_p, tx_n))
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0]["severity"], "error")
        self.assertIn("(33.8 ps skew)", fs[0]["description"])
        self.assertIn("limit of 5 ps by 575%", fs[0]["description"])
        self.assertIn("USB3", fs[0]["summary"])

    def test_superspeed_part_tx_rx_pairs_need_usb_in_their_own_name(self):
        # A sheet path typed these pairs USB; their leaf names are Ethernet / RS-485 lanes, so
        # they keep the HS 25 ps of a USB pair. USB3_TX1± names a SuperSpeed lane: 5 ps.
        cases = (("/USB_ETH/ETH_TX_P", "/USB_ETH/ETH_TX_N", "limit of 25 ps by 35%", "USB-HS"),
                 ("/USB_RS485/TX+", "/USB_RS485/TX-", "limit of 25 ps by 35%", "USB-HS"),
                 ("USB3_TX1+", "USB3_TX1-", "limit of 5 ps by 575%", "USB3"))
        for pos, neg, text, label in cases:
            with tempfile.TemporaryDirectory() as tmp:
                _write_extraction(tmp, "SS")
                fs = check_diff_pair_skew(_pcb_pair(pos, neg), _pair_schematic(tmp, pos, neg))
            self.assertEqual(len(fs), 1, pos)
            self.assertEqual(fs[0]["severity"], "error", pos)
            self.assertIn(text, fs[0]["description"], pos)
            self.assertIn(label, fs[0]["summary"], pos)

    def test_superspeed_needs_usb_or_ss_as_a_token(self):
        for name in ("USB3_TX1+", "SSTX1+", "SS_TX+", "/USB/SSRX_N"):
            self.assertTrue(_is_superspeed_net(name), name)
        for name in ("CLASS_TX+", "PASS_RX-", "/USB/BUSS_TX_P"):
            self.assertFalse(_is_superspeed_net(name), name)

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

    def test_esd_array_clears_through_any_of_its_protected_nets(self):
        # A multi-line array lists every line; its first sorted net need not be on this connector.
        esd = dict(_prot("U2", "esd_ic", "AUX_SDA"), protected_nets=["AUX_SDA", "USB_D+", "USB_D-"])
        self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS)), {"components": [], "findings": [esd]}), [])

    def test_excluded_parts_clear_nothing_through_protected_nets(self):
        for ptype, comps in (("fuse", []), ("reverse_polarity", []),
                             ("esd_ic", [{"reference": "U2", "type": "ic", "dnp": True}])):
            pd = dict(_prot("U2", ptype, "AUX_SDA"), protected_nets=["AUX_SDA", "USB_D+", "USB_D-"])
            self.assertEqual(_io001(self._pcb(_usb_c(USB_PADS)), {"components": comps, "findings": [pd]}),
                             [(["J1"], "error")], ptype)

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

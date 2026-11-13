"""Ground names: COM by power symbol, virtual grounds, 0-10 V interface nets, ground tokens."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import is_ground_name, is_virtual_ground_name, is_vss_name  # noqa: E402
from pcb.routing import analyze_ground_domains, analyze_trace_proximity  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources, detect_label_aliases, detect_solder_jumpers  # noqa: E402
from schematic.audits import classify_ground_domains  # noqa: E402

GROUNDS = ["AVSS", "DVSS", "GROUND", "ground", "AGND_CODEC", "PGND_3V3", "HEATER_GND_1",
           "ESP_GND2", "AGND1", "V+_GND_CH1", "0VA", "0V_A", "/Codec/AGND_CODEC"]
NOT_GROUNDS = ["VGND", "HP_VGND", "VGND1", "Virtual_Ground", "/Audio/VGND", "0V_10V", "0V_32V",
               "Net-(U1-GND)", "DAC_VSS", "REFGND_0.5V", "Earth"]


class GroundName(unittest.TestCase):
    def test_com_is_ground_only_when_a_power_symbol_names_it(self):
        self.assertTrue(is_ground_name("COM", {"COM"}))
        self.assertFalse(is_ground_name("COM"))
        self.assertFalse(is_ground_name("COM", {"GND"}))

    def test_com_rail_membership_is_by_full_name(self):
        self.assertTrue(is_ground_name("COM", {"COM"}))
        self.assertFalse(is_ground_name("/x/COM", {"COM"}))
        self.assertTrue(is_ground_name("/x/COM", {"/x/COM"}))

    def test_escaped_slash_does_not_split_a_virtual_ground_token(self):
        self.assertTrue(is_ground_name("AGND{slash}VGND"))

    def test_grounds(self):
        for name in GROUNDS:
            with self.subTest(name=name):
                self.assertTrue(is_ground_name(name))

    def test_not_grounds(self):
        for name in NOT_GROUNDS:
            with self.subTest(name=name):
                self.assertFalse(is_ground_name(name))

    def test_virtual_grounds(self):
        for name in ("VGND", "HP_VGND", "VGND1", "Virtual_Ground", "/Audio/VGND"):
            with self.subTest(name=name):
                self.assertTrue(is_virtual_ground_name(name))
        for name in ("GND", "AGND", "", None, "Net-(VR1-ADJ{slash}VGND)"):
            with self.subTest(name=name):
                self.assertFalse(is_virtual_ground_name(name))

    def test_avss_and_dvss_are_vss(self):
        self.assertTrue(is_vss_name("AVSS"))
        self.assertTrue(is_vss_name("/ADC/DVSS"))
        self.assertFalse(is_vss_name("DAC_VSS"))


class PcbGroundDomains(unittest.TestCase):
    def test_substring_grounds_stay_domains_and_virtual_grounds_leave(self):
        gd = analyze_ground_domains([], {1: "GND", 2: "PVSS1", 3: "ISOGND12", 4: "VGND1",
                                         5: "HP_VGND"}, [])
        self.assertEqual(sorted(d["net"] for d in gd["domains"]), ["GND", "ISOGND12", "PVSS1"])


def _ctx(nets, comps=(), rails=frozenset({"COM"})):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in v.get("pins", [])],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": v.get("labels", [])}
            for n, v in nets.items()}
    return build_analysis_context(list(comps), full, {}, known_power_rails=set(rails))


class PowerSymbolComIsGroundToItsCallers(unittest.TestCase):
    def test_rail_source_audit_skips_a_power_symbol_com(self):
        nets = {"COM": {"pins": [("#PWR1", "1", "COM", "power_in"), ("U1", "4", "VSS", "power_in")]}}
        comps = [{"reference": "U1", "type": "ic", "value": "X"}]
        self.assertEqual([f for f in audit_rail_sources(_ctx(nets, comps)) if f["rule_id"] == "RS-001"], [])
        self.assertEqual(len([f for f in audit_rail_sources(_ctx(nets, comps, rails=()))
                              if f["rule_id"] == "RS-001"]), 1)

    def test_label_alias_audit_skips_a_power_symbol_com(self):
        labels = [{"name": "RET_A", "type": "global_label"}, {"name": "RET_B", "type": "global_label"}]
        nets = {"COM": {"labels": labels}}
        self.assertEqual(detect_label_aliases(_ctx(nets)), [])
        self.assertEqual(len(detect_label_aliases(_ctx(nets, rails=()))), 1)

    def test_solder_jumper_reads_a_power_symbol_com_as_ground(self):
        comps = [{"reference": "JP1", "type": "jumper", "value": "SolderJumper_2_Bridged",
                  "lib_id": "Jumper:SolderJumper_2_Bridged",
                  "footprint": "Jumper:SolderJumper-2_P1.3mm_Bridged_Pad1.0x1.5mm"}]
        nets = {"COM": {"pins": [("JP1", "1", "A", "passive")]},
                "SENSE": {"pins": [("JP1", "2", "B", "passive")]}}
        got = [f for f in detect_solder_jumpers(_ctx(nets, comps)) if f.get("reference") == "JP1"]
        self.assertEqual(got[0]["ground_nets"], ["COM"])

    def test_schematic_ground_domains_count_a_power_symbol_com(self):
        nets = {"COM": {"pins": [{"component": "#PWR1", "pin_type": "power_in"},
                                 {"component": "K1", "pin_type": "passive"}]},
                "GND": {"pins": [{"component": "U1", "pin_type": "power_in"}]}}
        def nets_in_domains(**kw):
            return sorted(classify_ground_domains(nets, [], **kw)["ground_nets"])
        self.assertEqual(nets_in_domains(power_rails={"COM"}), ["COM", "GND"])
        self.assertEqual(nets_in_domains(), ["GND"])

    def test_trace_proximity_leaves_out_a_power_symbol_com(self):
        tracks = {"segments": [dict(x1=0, y1=0, x2=10, y2=0, layer="F.Cu", net=1),
                               dict(x1=0, y1=0.1, x2=10, y2=0.1, layer="F.Cu", net=2)]}
        names = {1: "COM", 2: "SIG"}
        self.assertEqual(analyze_trace_proximity(tracks, names, power_rails={"COM"})["total_pairs_found"], 0)
        self.assertEqual(analyze_trace_proximity(tracks, names)["total_pairs_found"], 1)


if __name__ == "__main__":
    unittest.main()

"""diff matches findings by identity: rich findings and PCB findings are compared, positional
`#N` finding_ids and `__unnamed_N` nets never pair two different findings, footprint swaps show."""
import copy, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import diff_engine  # noqa: E402
from finding_schema import assign_finding_ids  # noqa: E402


def _f(detector, rule_id, components, nets, summary, severity, **extra):
    """One finding with the producer's field names (schematic --schema)."""
    f = {"detector": detector, "rule_id": rule_id, "category": extra.pop("category", "test"),
         "severity": severity, "confidence": "heuristic", "evidence_source": "topology",
         "summary": summary, "description": summary, "components": list(components),
         "nets": list(nets), "pins": [], "recommendation": "", "detection_id": None}
    f.update(extra)
    return f


def _doc(findings, source="schematic", **extra):
    """An analyzer document whose finding_ids are assigned by the producer's own pass."""
    findings = copy.deepcopy(findings)
    for f in findings:
        f.pop("finding_id", None)
    assign_finding_ids(findings, source)
    doc = {"analyzer_type": source, "findings": findings}
    doc.update(extra)
    return doc


def _vd(ref, value, net, volts, rating_kind, sev):
    word = "exceeds" if sev == "error" else "has marginal"
    return _f("analyze_voltage_derating", "VD-001", [ref], [net],
              f"{ref} ({value} 16V) {word} voltage derating on {net} ({volts:.1f}V on 16V {rating_kind} cap)",
              sev, category="component_derating")


def _dc(rail, caps):
    """DC-DET as detect_decoupling emits it: every instance carries the same detection_id."""
    return _f("detect_decoupling", "DC-DET", caps, [], f"Decoupling on {rail}", "info",
              detection_id="decoupling_analysis:9a1adf60f6b2", rail=rail, rail_net=None)


def _nt(pin, num, net):
    return _f("analyze_connectivity", "NT-001", ["D1"], [net],
              f"Single-pin net: D1.{pin} only connects to D1.{num} ({pin}) (passive)", "info")


def _total(analyzer, diff):
    return diff_engine.build_summary(analyzer, diff)["total_changes"]


class SchematicFindingIdentity(unittest.TestCase):
    def test_rail_rename_reports_new_and_worsened_derating(self):
        # AmpStation +12V -> +24V (survey oracle): VD-001 C11 added (error), C14 warning -> error.
        base = _doc([_vd("C14", "100nF", "+12V", 12.0, "ceramic", "warning")])
        head = _doc([_vd("C11", "470µF", "+24V", 24.0, "electrolytic", "error"),
                     _vd("C14", "100nF", "+24V", 24.0, "ceramic", "error")])
        sa = diff_engine.diff_schematic(base, head, 1.0)["signal_analysis"]["analyze_voltage_derating"]
        self.assertEqual([(a["rule_id"], a["components"], a["severity"]) for a in sa["added"]],
                         [("VD-001", ["C11"], "error")])
        self.assertEqual(sa["removed"], [])
        self.assertEqual(len(sa["modified"]), 1)
        sev = [c for c in sa["modified"][0]["changes"] if c["field"] == "severity"]
        self.assertEqual(sev, [{"field": "severity", "base": "warning", "head": "error"}])

    def test_rich_finding_without_detection_id_is_not_dropped(self):
        rs = _f("audit_rail_sources", "RS-001", ["U1"], ["+5V"], "+5V has no source", "warning")
        diff = diff_engine.diff_schematic(_doc([]), _doc([rs]), 1.0)
        self.assertEqual(len(diff["signal_analysis"]["audit_rail_sources"]["added"]), 1)
        self.assertEqual(_total("schematic", diff), 1)

    def test_shared_detection_id_findings_are_all_compared(self):
        base = _doc([_dc("+3V3", ["C5", "C6"]), _dc("VBUS", ["C4"])])
        head = _doc([_dc("+3V3", ["C5", "C6"]), _dc("VBUS", ["C4"]), _dc("+3.3VA", ["C9"])])
        sa = diff_engine.diff_schematic(base, head, 1.0)["signal_analysis"]["decoupling_analysis"]
        self.assertEqual([a["components"] for a in sa["added"]], [["C9"]])
        self.assertEqual(sa["removed"], [])
        self.assertEqual(sa["modified"], [])

    def test_reordered_rerun_of_the_same_design_has_no_changes(self):
        # A re-run with the sheets in another order: the producer hands out `#N` suffixes in a
        # different order and renumbers unnamed nets. Nothing about the design changed.
        dcs = [_dc("+3V3", ["C10", "C5", "C6"]), _dc("VBUS_ADC", ["C3"]),
               _dc("VBUS", ["C4"]), _dc("+3.3VA", ["C9"])]
        base = _doc(dcs + [_nt("K", 1, "__unnamed_1"), _nt("A", 2, "__unnamed_2")])
        head = _doc([dcs[2], dcs[0], dcs[3], dcs[1],
                     _nt("A", 2, "__unnamed_1"), _nt("K", 1, "__unnamed_2")])
        self.assertNotEqual([f["summary"] for f in base["findings"] if f["finding_id"].endswith("#1")],
                            [f["summary"] for f in head["findings"] if f["finding_id"].endswith("#1")])
        diff = diff_engine.diff_schematic(base, head, 1.0)
        self.assertNotIn("signal_analysis", diff)
        self.assertEqual(_total("schematic", diff), 0)

    def test_renumbered_unnamed_net_is_not_a_value_change(self):
        # stm32 REV1.0 -> 1.1: D5 protects the same unnamed net, numbered __unnamed_18 then __unnamed_17
        pd = _f("detect_protection_devices", "PD-DET", ["D5"], [], "Protection D5 tvs", "info",
                detection_id="protection_devices:aa809ad0f4d9", ref="D5", reference=None, type="tvs",
                protected_net="__unnamed_18")
        pp = _f("audit_power_pin_dc_paths", "PP-001", ["U1"], ["__unnamed_4"],
                "U1 pin 3 (VDD) on __unnamed_4 has no DC path to a rail", "warning")
        base = _doc([pd, pp])
        head = _doc([dict(pd, protected_net="__unnamed_17"),
                     dict(pp, nets=["__unnamed_9"], summary=pp["summary"].replace("_4", "_9"))])
        self.assertNotIn("signal_analysis", diff_engine.diff_schematic(base, head, 1.0))

    def test_erc_warning_on_a_renumbered_unnamed_net(self):
        # Digital-signal-converter re-run with its sheets reversed: the same pin_to_pin warning,
        # its net numbered __unnamed_2 then __unnamed_77.
        def erc(n, pins):
            return {"type": "pin_to_pin", "net": f"__unnamed_{n}", "severity": "warning",
                    "message": f"Net '__unnamed_{n}' connects conflicting pin types (1 pin(s))",
                    "pairs": [{"pins": pins, "pin_types": ["unspecified", "passive"], "severity": "warning"}]}
        base = _doc([], design_analysis={"erc_warnings": [erc(2, ["U11.9", "C89.2"])]})
        same = _doc([], design_analysis={"erc_warnings": [erc(77, ["U11.9", "C89.2"])]})
        self.assertNotIn("erc", diff_engine.diff_schematic(base, same, 1.0))
        other = _doc([], design_analysis={"erc_warnings": [erc(77, ["U11.9", "C89.2"]),
                                                           erc(78, ["U11.1", "C52.1"])]})
        self.assertEqual([w["pairs"][0]["pins"] for w in
                          diff_engine.diff_schematic(base, other, 1.0)["erc"]["new_warnings"]],
                         [["U11.1", "C52.1"]])

    def test_one_more_instance_is_one_addition(self):
        base = _doc([_dc("VBUS", ["C4"])])
        head = _doc([_dc("+3V3", ["C5"]), _dc("VBUS", ["C4"])])
        sa = diff_engine.diff_schematic(base, head, 1.0)["signal_analysis"]["decoupling_analysis"]
        self.assertEqual(([a["components"] for a in sa["added"]], sa["removed"], sa["modified"]),
                         ([["C5"]], [], []))

    def test_severity_change_on_a_registry_keyed_detection(self):
        b = _f("detect_rc_filters", "RC-DET", ["R1", "C1"], ["N1"], "RC low-pass 159 Hz", "info",
               detection_id="rc_filters:aaaaaaaaaaaa", resistor={"ref": "R1"}, capacitor={"ref": "C1"},
               cutoff_hz=159.0)
        h = dict(b, severity="warning")
        mod = diff_engine.diff_schematic(_doc([b]), _doc([h]), 1.0)["signal_analysis"]["rc_filters"]["modified"]
        self.assertEqual([c["field"] for c in mod[0]["changes"]], ["severity"])

    def test_legacy_severity_word_is_not_a_change(self):
        ep = _f("audit_esd_protection", "EP-AUD", ["J1"], [], "J1 has no ESD protection", "WARN")
        emc = _f("check_esd", "ES-001", ["J1"], [], "J1 unprotected", "CRITICAL")
        self.assertNotIn("signal_analysis", diff_engine.diff_schematic(
            _doc([ep]), _doc([dict(ep, severity="warning")]), 1.0))
        self.assertNotIn("findings", diff_engine.diff_emc(
            _doc([emc], "emc"), _doc([dict(emc, severity="error")], "emc"), 1.0))

    def test_no_attribution_from_a_ref_that_is_only_a_prefix(self):
        comps = lambda v: [{"reference": "C1", "value": v}, {"reference": "C11", "value": "1u"}]  # noqa: E731
        # two findings on C11 share a finding_id stem, so they are matched by content
        b = [_vd("C11", "1u", "+12V", 12.0, "ceramic", "warning"),
             _vd("C11", "1u", "+9V", 9.0, "ceramic", "warning")]
        base = _doc(b, components=comps("100n"))
        head = _doc([dict(b[0], severity="error"), b[1]], components=comps("220n"))
        mod = diff_engine.diff_schematic(base, head, 1.0)["signal_analysis"]["analyze_voltage_derating"]["modified"]
        self.assertEqual(len(mod), 1)
        self.assertNotIn("attributed_to", mod[0])


    def test_removed_member_of_a_shared_key_is_the_one_reported_removed(self):
        # Two RC filters share one detection_id; the 100 Hz one goes away, the 900 Hz one stays.
        rc = _f("detect_rc_filters", "RC-DET", ["R1", "C1"], ["N1"], "RC", "info",
                detection_id="rc_filters:x", resistor={"ref": "R1"}, capacitor={"ref": "C1"},
                cutoff_hz=100.0)
        rc900 = dict(rc, cutoff_hz=900.0)
        base, head = _doc([rc, rc900]), _doc([rc900])
        sa = diff_engine.diff_schematic(base, head, 1.0)["signal_analysis"]["rc_filters"]
        self.assertEqual((len(sa["added"]), len(sa["removed"]), sa["modified"]), (0, 1, []))
        base_map, head_map = diff_engine.match_findings(base["findings"], head["findings"])
        gone = [f["cutoff_hz"] for k, f in base_map.items() if k not in head_map]
        self.assertEqual(gone, [100.0])

    def test_erc_pair_listed_in_the_other_pin_order(self):
        def erc(n, pins, types):
            return {"type": "pin_to_pin", "net": f"__unnamed_{n}", "severity": "warning",
                    "message": f"Net '__unnamed_{n}' connects conflicting pin types (1 pin(s))",
                    "pairs": [{"pins": pins, "pin_types": types, "severity": "warning"}]}
        base = _doc([], design_analysis={"erc_warnings": [erc(2, ["U1.1", "U2.1"], ["output", "input"])]})
        flipped = _doc([], design_analysis={"erc_warnings": [erc(5, ["U2.1", "U1.1"], ["input", "output"])]})
        diff = diff_engine.diff_schematic(base, flipped, 1.0)
        self.assertNotIn("erc", diff)
        self.assertEqual(diff_engine.classify_severity("schematic", diff), "none")
        # the same pins with their types swapped is a different warning
        swapped = _doc([], design_analysis={"erc_warnings": [erc(5, ["U2.1", "U1.1"], ["output", "input"])]})
        self.assertIn("erc", diff_engine.diff_schematic(base, swapped, 1.0))

    def test_value_change_is_attributed_to_the_derated_cap(self):
        comps = lambda v: [{"reference": "C14", "value": v}]  # noqa: E731
        base = _doc([_vd("C14", "100nF", "+12V", 12.0, "ceramic", "warning")], components=comps("100nF"))
        head = _doc([_vd("C14", "100nF", "+12V", 12.0, "ceramic", "error")], components=comps("220nF"))
        mod = diff_engine.diff_schematic(base, head, 1.0)["signal_analysis"]["analyze_voltage_derating"]["modified"]
        self.assertEqual(mod[0]["identity"], "schematic:VD-001:c14")
        self.assertEqual(mod[0]["attributed_to"],
                         [{"ref": "C14", "base_value": "100nF", "head_value": "220nF"}])

    def test_no_attribution_of_c1_to_a_c11_finding_keyed_by_id(self):
        comps = lambda v: [{"reference": "C1", "value": v}, {"reference": "C11", "value": "1u"}]  # noqa: E731
        base = _doc([_vd("C11", "1u", "+12V", 12.0, "ceramic", "warning")], components=comps("100n"))
        head = _doc([_vd("C11", "1u", "+12V", 12.0, "ceramic", "error")], components=comps("220n"))
        mod = diff_engine.diff_schematic(base, head, 1.0)["signal_analysis"]["analyze_voltage_derating"]["modified"]
        self.assertEqual(len(mod), 1)
        self.assertNotIn("attributed_to", mod[0])


class FindingKey(unittest.TestCase):
    def test_finding_id_is_the_key_when_it_is_not_positional(self):
        f = _doc([_vd("C14", "100nF", "+12V", 12.0, "ceramic", "warning")])["findings"][0]
        self.assertEqual(diff_engine.finding_key(f), "schematic:VD-001:c14")

    def test_positional_id_gets_a_content_key(self):
        a, b = _doc([_nt("K", 1, "__unnamed_1"), _nt("A", 2, "__unnamed_2")])["findings"]
        self.assertTrue(b["finding_id"].endswith("#1"))
        self.assertNotIn("#", diff_engine.finding_key(b))
        # the same pin on a renumbered net and with its lists reordered keeps its key
        moved = dict(b, finding_id=a["finding_id"] + "#4", nets=["__unnamed_9"])
        self.assertEqual(diff_engine.finding_key(moved), diff_engine.finding_key(b))
        self.assertNotEqual(diff_engine.finding_key(a), diff_engine.finding_key(b))

    def test_content_key_is_deterministic(self):
        f = _f("x", "DC-DET", ["C2", "C1"], ["B", "A"], "s", "info", finding_id="schematic:d#2")
        g = dict(f, components=["C1", "C2"], nets=["A", "B"], finding_id="schematic:d#7")
        self.assertEqual(diff_engine.finding_key(f), diff_engine.finding_key(g))


class PcbDiff(unittest.TestCase):
    def _fp(self, ref, footprint):
        return {"reference": ref, "value": "1k", "footprint": footprint, "library": footprint, "layer": "F.Cu"}

    def test_new_pcb_finding_is_reported(self):
        # micro-nico V1 -> V1.0.1 (survey oracle): one new PCB finding, PM-002 on JP1.
        pm = _f("analyze_placement", "PM-002", ["JP1"], [], "JP1 courtyard overhangs board edge by 0.3mm",
                "error", category="placement", confidence="deterministic")
        diff = diff_engine.diff_pcb(_doc([], "pcb"), _doc([pm], "pcb"), 1.0)
        self.assertEqual([(n["rule_id"], n["components"]) for n in diff["findings"]["new"]],
                         [("PM-002", ["JP1"])])
        self.assertEqual(_total("pcb", diff), 1)

    def test_footprint_swap_on_one_ref(self):
        base = _doc([], "pcb", footprints=[self._fp("R1", "Resistor_SMD:R_0402_1005Metric")])
        head = _doc([], "pcb", footprints=[self._fp("R1", "Resistor_SMD:R_0603_1608Metric")])
        mod = diff_engine.diff_pcb(base, head, 1.0)["footprints"]["modified"]
        self.assertEqual(mod, [{"reference": "R1", "changes": [
            {"field": "footprint", "base": "Resistor_SMD:R_0402_1005Metric",
             "head": "Resistor_SMD:R_0603_1608Metric"}]}])

    def test_added_footprint_names_its_footprint(self):
        head = _doc([], "pcb", footprints=[self._fp("R2", "Resistor_SMD:R_0402_1005Metric")])
        added = diff_engine.diff_pcb(_doc([], "pcb", footprints=[]), head, 1.0)["footprints"]["added"]
        self.assertEqual(added[0]["footprint"], "Resistor_SMD:R_0402_1005Metric")


class EmcThermalDiff(unittest.TestCase):
    def _dc001(self, caps, sev, summary):
        return _f("check_decoupling", "DC-001", ["U3"] + caps, [], summary, sev, category="decoupling")

    def test_emc_finding_keeps_its_identity_when_its_caps_change(self):
        # stm32 REV1.0 -> 1.1 (survey oracle): DC-001 U3 error -> warning, its caps changed.
        base = _doc([self._dc001(["C19", "C14"], "error", "Decoupling cap too far from U3")], "emc")
        head = _doc([self._dc001(["C13", "C18"], "warning", "Decoupling cap moderately far from U3")], "emc")
        fd = diff_engine.diff_emc(base, head, 1.0)["findings"]
        self.assertEqual((fd["new"], fd["resolved"]), ([], []))
        self.assertEqual([(c["base_severity"], c["head_severity"]) for c in fd["changed_severity"]],
                         [("error", "warning")])

    def test_identical_emc_findings_against_themselves(self):
        sw = [_f("check_switching", "SW-001", ["U1"], ["SW"], f"harmonic {n}", "warning") for n in (1, 2, 3)]
        base = _doc(sw, "emc")
        self.assertNotIn("findings", diff_engine.diff_emc(base, copy.deepcopy(base), 1.0))
        self.assertNotIn("findings", diff_engine.diff_emc(base, _doc(sw[::-1], "emc"), 1.0))

    def test_nested_by_severity_is_read(self):
        base = _doc([], "emc", summary={"emc_risk_score": 80, "by_severity": {"error": 2, "warning": 1, "info": 0}})
        head = _doc([], "emc", summary={"emc_risk_score": 80, "by_severity": {"error": 3, "warning": 1, "info": 0}})
        self.assertEqual(diff_engine.diff_emc(base, head, 1.0)["by_severity"],
                         {"summary.by_severity.error": {"base": 2, "head": 3, "delta": 1}})

    def test_thermal_finding_keeps_its_identity(self):
        t = _f("analyze_thermal", "TS-001", ["U1", "C1"], [], "U1 runs hot", "warning")
        head = _doc([dict(t, components=["U1", "C2"], severity="error")], "thermal")
        fd = diff_engine.diff_thermal(_doc([t], "thermal"), head, 1.0)["findings"]
        self.assertEqual((fd["new"], fd["resolved"], len(fd["changed_severity"])), ([], [], 1))


if __name__ == "__main__":
    unittest.main()

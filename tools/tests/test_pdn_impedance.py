"""PDN impedance adds parallel branches as complex impedances (EMC and the schematic
`pdn_impedance` share the combination); trace inductance uses the free-space phase
velocity; PD-004 names the downstream regulator with the largest reflected transient."""
import math, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_pdn_impedance  # noqa: E402
import emc_formulas as ef  # noqa: E402
import emc_rules as er  # noqa: E402

# 1 µF ‖ 10 nF, each 1 nH and 10 mΩ: anti-resonance where the two reactances cancel,
# f = √((1/C₁ + 1/C₂)/(2L)) / 2π = 35.77 MHz; there |Z| = 2.431 Ω.
PAIR = [{"farads": 1e-6, "esr_ohm": 0.01, "esl_h": 1e-9},
        {"farads": 10e-9, "esr_ohm": 0.01, "esl_h": 1e-9}]
F_PAIR = math.sqrt((1 / 1e-6 + 1 / 10e-9) / 2e-9) / (2 * math.pi)


class ComplexCombination(unittest.TestCase):
    def test_pair_anti_resonance_frequency(self):
        self.assertAlmostEqual(F_PAIR / 1e6, 35.77, places=2)

    def test_pair_anti_resonance_height(self):
        self.assertAlmostEqual(ef.parallel_cap_impedance(F_PAIR, PAIR), 2.431, delta=2.431 * 0.01)

    def test_shared_helper(self):
        from kicad_core.pdn import cap_branch_z, parallel_impedance
        z = parallel_impedance([cap_branch_z(F_PAIR, c["farads"], c["esr_ohm"], c["esl_h"]) for c in PAIR])
        self.assertAlmostEqual(abs(z), 2.431, delta=2.431 * 0.01)
        self.assertIsNone(parallel_impedance([]))

    def test_exact_cancellation_gives_none_and_a_short_gives_zero(self):
        from kicad_core.pdn import parallel_impedance
        # Two lossless branches whose reactances cancel: no finite combination.
        self.assertIsNone(parallel_impedance([1j, -1j]))
        # A shorted branch shorts the network.
        self.assertEqual(parallel_impedance([0j, complex(1, 1)]), 0j)

    def test_emc_caps_with_a_zero_esr_take_the_default(self):
        # A lossless pair would peak without bound at f0; ESR 0 is read as the 0.1 ohm default.
        lossless = [dict(c, esr_ohm=0) for c in PAIR]
        lossy = [dict(c, esr_ohm=0.1) for c in PAIR]
        self.assertEqual(ef.parallel_cap_impedance(F_PAIR, lossless), ef.parallel_cap_impedance(F_PAIR, lossy))

    def test_power_tree_never_models_a_zero_esr(self):
        regs = [{"ref": "U1", "output_rail": "+3V3", "estimated_vout": 3.3, "topology": "ldo",
                 "output_capacitors": [{"ref": "C1", "farads": 1e-6, "package": "0603", "esr_ohm": 0}]}]
        tree = ef.build_power_tree(regs, {}, [])
        self.assertEqual(tree["+3V3"]["output_caps"][0]["esr_ohm"], ef.estimate_esr("0603"))


class DistributedSweep(unittest.TestCase):
    """Z_IC = Z_local ∥ (Z_reg + R + jωL), all complex."""

    @staticmethod
    def _branch(f, c, esr, esl):
        w = 2 * math.pi * f
        return complex(esr, w * esl - 1 / (w * c))

    def _node(self, caps):
        return {"output_caps": caps, "trace_r_total_ohm": 0.05, "trace_l_total_h": 10e-9,
                "load_ics": [{"ref": "U2", "estimated_mA": 300}]}

    REG = {"ref": "C1", "farads": 10e-6, "esr_ohm": 0.01, "esl_h": 1e-9, "location": "regulator_output"}
    LOCAL = {"ref": "C2", "farads": 100e-9, "esr_ohm": 0.02, "esl_h": 0.5e-9, "location": "ic_decoupling"}

    def test_one_point_by_hand(self):
        res = ef.distributed_pdn_impedance_sweep(self._node([self.REG, self.LOCAL]))
        pt = res["sweep_at_worst_ic"][200]
        f = pt["freq_hz"]
        self.assertAlmostEqual(f, 1e7, delta=1)
        z_remote = self._branch(f, 10e-6, 0.01, 1e-9) + complex(0.05, 2 * math.pi * f * 10e-9)
        z_local = self._branch(f, 100e-9, 0.02, 0.5e-9)
        want = abs(1 / (1 / z_local + 1 / z_remote))
        self.assertAlmostEqual(pt["impedance_ohm"], want, delta=want * 1e-9)
        self.assertEqual(res["worst_ic_ref"], "U2")

    def test_no_regulator_caps_leaves_the_local_caps(self):
        res = ef.distributed_pdn_impedance_sweep(self._node([self.LOCAL]))
        pt = res["sweep_at_worst_ic"][200]
        want = abs(self._branch(pt["freq_hz"], 100e-9, 0.02, 0.5e-9))
        self.assertAlmostEqual(pt["impedance_ohm"], want, delta=want * 1e-9)


# F.Cu | 0.1 mm | In1.Cu | 1.0 mm | In2.Cu | 0.1 mm | B.Cu, εr 4.5 everywhere.
STACKUP = [{"name": "F.Cu", "type": "copper"}, {"name": "dielectric 1", "type": "prepreg", "thickness": 0.1, "epsilon_r": 4.5},
           {"name": "In1.Cu", "type": "copper"}, {"name": "dielectric 2", "type": "core", "thickness": 1.0, "epsilon_r": 4.5},
           {"name": "In2.Cu", "type": "copper"}, {"name": "dielectric 3", "type": "prepreg", "thickness": 0.1, "epsilon_r": 4.5},
           {"name": "B.Cu", "type": "copper"}]


def _zone(net, layer, area):
    return {"net_name": net, "layers": [layer], "is_filled": True, "filled_area_mm2": area}


def _plane_pcb(*zones):
    return {"setup": {"stackup": STACKUP}, "statistics": {"board_width_mm": 100, "board_height_mm": 100},
            "zones": [_zone("GND", "In1.Cu", 6000.0), _zone("GND", "B.Cu", 6000.0), *zones]}


class RailPlane(unittest.TestCase):
    """Only a rail's own zone copper facing a ground zone across a thin dielectric is a plane branch."""

    def _sweep_plane(self, pcb, rail, caps):
        sch = {"findings": [_reg("U1", rail, 1.8, topo="ldo", caps=caps)]}
        seen = []
        real = er.pdn_impedance_sweep
        with mock.patch.object(er, "pdn_impedance_sweep",
                               side_effect=lambda c, plane_cap_f=0, **k: seen.append(plane_cap_f) or real(c, plane_cap_f=plane_cap_f, **k)):
            found = er.check_pdn_impedance(pcb, sch)
        return seen[0], found

    def test_rail_without_a_plane_gets_no_plane_branch(self):
        # 22 µF ∥ 10 µF 0603 on a board with a thin GND pair: the rail has no zone, so no plane
        # branch and no cap-ESL ↔ plane anti-resonance (the board-wide plane gave one near 90 MHz).
        plane, found = self._sweep_plane(_plane_pcb(), "1V8", [("C1", 22e-6), ("C2", 10e-6)])
        self.assertEqual(plane, 0.0)
        self.assertEqual([f for f in found if f["rule_id"] == "PD-001"], [])

    def test_own_plane_facing_ground_is_sized_by_its_zone(self):
        # 1000 mm² of 1V8 on In2.Cu, 0.1 mm from GND on B.Cu: C = ε0·εr·A/d = 398.4 pF.
        plane, _ = self._sweep_plane(_plane_pcb(_zone("1V8", "In2.Cu", 1000.0)), "1V8", [("C1", 10e-6)])
        self.assertAlmostEqual(plane, 8.8541878128e-12 * 4.5 * 1000e-6 / 0.1e-3, delta=0.4e-12)

    def test_ground_fill_bounds_the_overlap(self):
        pcb = _plane_pcb(_zone("1V8", "In2.Cu", 1000.0))
        pcb["zones"][1]["filled_area_mm2"] = 250.0  # GND on B.Cu
        self.assertAlmostEqual(er._rail_plane_cap_f(pcb, "1V8"), 8.8541878128e-12 * 4.5 * 250e-6 / 0.1e-3, delta=0.1e-12)

    def test_neighbouring_rail_plane_is_not_borrowed(self):
        # +5V routed on F.Cu next to a +3V3 plane on In2.Cu (facing GND on B.Cu): +5V has no plane.
        pcb = _plane_pcb(_zone("+3V3", "In2.Cu", 4000.0))
        self.assertGreater(er._rail_plane_cap_f(pcb, "+3V3"), 0)
        self.assertEqual(er._rail_plane_cap_f(pcb, "+5V"), 0.0)

    def test_thick_dielectric_is_not_a_plane_pair(self):
        # +3V3 on In2.Cu faces GND on In1.Cu only across the 1.0 mm core.
        pcb = _plane_pcb(_zone("+3V3", "In2.Cu", 4000.0))
        pcb["zones"] = [z for z in pcb["zones"] if z["layers"] != ["B.Cu"]]
        self.assertEqual(er._rail_plane_cap_f(pcb, "+3V3"), 0.0)


class TraceInductance(unittest.TestCase):
    def test_free_space_phase_velocity(self):
        # w/h 1.5: Z0,air = 120π / (1.5 + 1.393 + 0.667 ln(2.944)) = 104.3 Ω; L = Z0,air / c₀.
        self.assertAlmostEqual(ef.trace_inductance_nh_per_mm(0.3, 0.2), 0.348, places=3)


def _ctx(caps, rail="+3V3"):
    comps = [{"reference": r, "type": "capacitor", "value": v, "lib_id": "Device:C", "pins": [],
              "footprint": ""} for r, v in caps]
    nets = {rail: [(r, "1") for r, _ in caps], "GND": [(r, "2") for r, _ in caps]}
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name="~", pin_type="passive")
                                    for r, p in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={rail})


class SchematicPdn(unittest.TestCase):
    def test_branches_combine_as_complex_admittances(self):
        # 10 µF and 100 nF with unknown packages take the 0.5 nH / 0.012 Ω·√µF fallback (ESR 0.005,
        # 0.0379 Ω). At 15.85 MHz Z₁ = 0.005 + j0.04879, Z₂ = 0.0379 − j0.05063; 1/(1/Z₁ + 1/Z₂)
        # has |Z| = 0.07223 Ω (the magnitude sum gave 0.02762 Ω).
        res = analyze_pdn_impedance(_ctx([("C1", "10u"), ("C2", "100n")]))
        prof = {p["freq_hz"]: p["impedance_ohm"] for p in res["rails"]["+3V3"]["impedance_profile"]}
        self.assertAlmostEqual(prof[15848932], 0.07223, delta=0.0001)

    def test_regulator_output_is_a_complex_branch(self):
        # LDO R = 50 mΩ, bandwidth 100 kHz: Z = R + jR·f/bw (|Z| = R√(1 + (f/bw)²)), in parallel
        # with a 1 µF cap (fallback ESR 0.012 Ω, ESL 0.5 nH). The VRM's inductive part (R/2π·bw =
        # 79.6 nH) resonates with the cap near 564 kHz; at the 501 kHz sweep point the complex
        # parallel is 0.897 Ω (the magnitude sum gave 0.140 Ω).
        res = analyze_pdn_impedance(_ctx([("C1", "1u")]),
                                    {"power_regulators": [{"output_rail": "+3V3", "topology": "LDO"}]})
        prof = {p["freq_hz"]: p["impedance_ohm"] for p in res["rails"]["+3V3"]["impedance_profile"]}
        f = min(prof, key=lambda k: abs(k - 564e3))
        w = 2 * math.pi * f
        z_vrm = complex(0.05, 0.05 * f / 100e3)
        z_cap = complex(0.012, w * 0.5e-9 - 1 / (w * 1e-6))
        want = abs(1 / (1 / z_vrm + 1 / z_cap))
        self.assertAlmostEqual(want, 0.897, places=3)
        self.assertAlmostEqual(prof[f], want, delta=want * 0.01)


def _reg(ref, out, vout, in_rail="", topo="buck", caps=()):
    return {"detector": "detect_power_regulators", "ref": ref, "output_rail": out, "estimated_vout": vout,
            "input_rail": in_rail, "topology": topo, "value": ref,
            "output_capacitors": [{"ref": r, "farads": c, "package": "0402"} for r, c in caps]}


class Pd004(unittest.TestCase):
    def test_names_the_largest_reflected_transient(self):
        sch = {"findings": [_reg("U1", "+5V", 5.0, topo="ldo", caps=[("C1", 100e-9)]),
                            _reg("U2", "+3V3", 3.3, "+5V"), _reg("U3", "+1V8", 1.8, "+5V"),
                            _reg("U4", "+1V2", 1.2, "+5V")],
               "power_budget": {}}
        trans = {"U2": 0.3, "U3": 0.4, "U4": 0.5}
        with mock.patch.object(er, "cross_rail_transient_current",
                               side_effect=lambda node, v: (trans[node["regulator"]["ref"]], 1e6)):
            found = [f for f in er.check_pdn_distributed(None, sch) if f["rule_id"] == "PD-004"]
        self.assertEqual(len(found), 1)
        self.assertIn("from U4", found[0]["summary"])
        self.assertEqual(found[0]["components"], ["U1", "U4"])


class Pd003Held(unittest.TestCase):
    """The rail's trace parasitics are not read from the PCB yet: a rail with routed copper
    still gets no PD-003 (a whole-net trace sum is not the regulator-to-IC path)."""

    def _sch(self):
        reg = _reg("U1", "+3V3", 3.3, "+5V", topo="ldo", caps=[("C1", 10e-6)])
        dec = {"detector": "detect_decoupling", "rail": "+3V3",
               "capacitors": [{"ref": "C2", "farads": 100e-9, "package": "0402"}]}
        return {"findings": [reg, dec],
                "power_budget": {"rails": {"+3V3": {"ics": [{"ref": "U5", "estimated_mA": 500}]}}}}

    def _pcb(self, key):
        return {"net_lengths": [{key: "+3V3", "total_length_mm": 400.0, "via_count": 10,
                                 "trace_segments": [{"length_mm": 400.0, "width_mm": 0.2}]}]}

    def test_rail_decoupling_joins_the_tree(self):
        sch = self._sch()
        tree = ef.build_power_tree([sch["findings"][0]], sch["power_budget"], [sch["findings"][1]])
        self.assertEqual([(c["ref"], c["location"]) for c in tree["+3V3"]["output_caps"]],
                         [("C1", "regulator_output"), ("C2", "ic_decoupling")])

    def test_routed_rail_gets_no_pd003(self):
        found = er.check_pdn_distributed(self._pcb("net"), self._sch())
        self.assertEqual([f for f in found if f["rule_id"] == "PD-003"], [])


if __name__ == "__main__":
    unittest.main()

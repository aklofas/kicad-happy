# tools/tests/test_kh454_kh455.py
"""RS-001 does not audit a net whose only power_in pins are bootstrap pins (KH-454); PP-001
dedups on (ref, pin, net) so duplicate / unannotated refs keep every power pin (KH-455)."""
import copy, json, subprocess, sys, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have
from unittest import mock
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import audit_rail_sources, audit_power_pin_dc_paths  # noqa: E402

BEFORE = "0490c49"
FX = fixture_path()


def _ctx(components, nets, flagged=()):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": n in flagged, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails={"+5V", "+3V3"})


def _rules(findings, rule):
    return [f for f in findings if f["rule_id"] == rule]


class BootstrapNetIsNotARail(unittest.TestCase):
    def _buck(self, extra_nets=None):
        comps = [{"reference": "U1", "type": "ic", "value": "BUCK"},
                 {"reference": "C1", "type": "capacitor", "value": "100n"},
                 {"reference": "U2", "type": "ic", "value": "MCU"}]
        nets = {"+5V": [("U1", "1", "VIN", "power_in")],
                "GND": [("U1", "2", "GND", "power_in")],
                "SW": [("U1", "3", "SW", "output"), ("C1", "2", "~", "passive")],
                "BST": [("U1", "4", "BST", "power_in"), ("C1", "1", "~", "passive")]}
        nets.update(extra_nets or {})
        return _ctx(comps, nets, flagged={"+5V"})

    def test_bootstrap_only_net_gets_no_rs001(self):
        f = audit_rail_sources(self._buck())
        self.assertEqual([x["nets"][0] for x in _rules(f, "RS-001")], [])

    def test_non_bootstrap_power_in_net_still_gets_rs001(self):
        f = audit_rail_sources(self._buck({"IO_CTL": [("U2", "7", "VDDIO", "power_in")]}))
        self.assertEqual([x["nets"][0] for x in _rules(f, "RS-001")], ["IO_CTL"])

    def test_mixed_bootstrap_and_supply_pin_is_still_a_rail(self):
        f = audit_rail_sources(self._buck({"BST": [("U1", "4", "BST", "power_in"),
                                                   ("U2", "7", "VDD", "power_in")]}))
        self.assertEqual([x["nets"][0] for x in _rules(f, "RS-001")], ["BST"])


class DuplicateRefPowerPins(unittest.TestCase):
    COMPS = [{"reference": "U?", "type": "ic", "value": "DRV"},
             {"reference": "U?", "type": "ic", "value": "MCU"},
             {"reference": "C1", "type": "capacitor", "value": "100n"},
             {"reference": "C2", "type": "capacitor", "value": "100n"}]

    def test_bootstrap_and_vdd_on_same_ref_and_pin(self):
        nets = {"BST_A": [("U?", "48", "BST_A", "power_in"), ("C2", "1", "~", "passive")],
                "__unnamed_1": [("U?", "48", "VDD", "power_in"), ("C1", "1", "~", "passive")],
                "GND": [("C1", "2", "~", "passive")]}
        f = _rules(audit_power_pin_dc_paths(_ctx(self.COMPS, nets)), "PP-001")
        self.assertEqual([x["pins"] for x in f], [["U?.48 (VDD)"]])

    def test_second_symbol_power_pin_is_not_masked(self):
        # The first U?.48 sits on a named rail (evaluated, no finding); the second, AC-coupled
        # U?.48 shares its (ref, pin) label and was skipped by the old dedup.
        nets = {"+3V3": [("U?", "48", "VCC", "power_in")],
                "__unnamed_1": [("U?", "48", "VDD", "power_in"), ("C1", "1", "~", "passive")],
                "GND": [("C1", "2", "~", "passive")]}
        f = _rules(audit_power_pin_dc_paths(_ctx(self.COMPS, nets)), "PP-001")
        self.assertEqual([x["pins"] for x in f], [["U?.48 (VDD)"]])


def _old_module():
    rel = "skills/kicad/scripts/signal_detectors.py"
    try:
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BEFORE}:{rel}"], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise unittest.SkipTest(f"{BEFORE} not readable from git: {exc}")
    ns = {"__name__": "_before_signal_detectors", "__file__": str(ROOT / rel)}
    exec(compile(src, rel, "exec"), ns)
    return ns


def _canon(findings, rule):
    # schema_era was stamped on both rules after BEFORE; it is not a set difference.
    return sorted(json.dumps({k: v for k, v in f.items() if k != "schema_era"}, sort_keys=True)
                  for f in findings if f["rule_id"] == rule)


class FixtureSetsUnchanged(unittest.TestCase):
    """On every parseable fixture schematic the RS-001 / PP-001 sets equal the BEFORE module's,
    except a bootstrap-only RS-001 removal or a duplicate-ref PP-001 addition."""

    def _compare(self, sch, old):
        from schematic import pipeline
        seen = {}

        def tap(name, new_fn):
            def wrapper(ctx, *a, **kw):
                new = new_fn(ctx, *a, **kw)
                # copied now: the pipeline stamps detection_id on the returned list later
                seen[name] = (copy.deepcopy(new), old[name](ctx, *a, **kw), ctx)
                return new
            return wrapper

        with mock.patch.object(pipeline, "audit_rail_sources", tap("audit_rail_sources", audit_rail_sources)), \
             mock.patch.object(pipeline, "audit_power_pin_dc_paths",
                               tap("audit_power_pin_dc_paths", audit_power_pin_dc_paths)):
            pipeline.analyze_schematic(str(sch))
        self.assertEqual(set(seen), {"audit_rail_sources", "audit_power_pin_dc_paths"}, sch)
        for name, rule in (("audit_rail_sources", "RS-001"), ("audit_power_pin_dc_paths", "PP-001")):
            new, before, ctx = seen[name]
            n, b = _canon(new, rule), _canon(before, rule)
            if n == b:
                continue
            removed = [json.loads(x) for x in sorted(set(b) - set(n))]
            added = [json.loads(x) for x in sorted(set(n) - set(b))]
            print(f"\n{sch}: {rule} removed {[x['summary'] for x in removed]} added {[x['summary'] for x in added]}")
            refs = [c.get("reference") for c in ctx.components or []]
            for x in removed:
                pins = [p for p in ctx.nets[x["nets"][0]]["pins"] if p.get("pin_type") == "power_in"]
                self.assertEqual(rule, "RS-001", x)
                self.assertTrue(pins and all(_bootstrap(p.get("pin_name")) for p in pins), x)
            for x in added:
                self.assertEqual(rule, "PP-001", x)
                self.assertGreater(refs.count(x["components"][0]), 1, x)

    def test_simple_project_and_every_fixture(self):
        if not have(FX):
            raise unittest.SkipTest(f"{FX} absent")
        old = _old_module()
        schs = sorted(p for p in FX.rglob("*.kicad_sch") if p.is_file())
        self.assertIn(FX / "simple-project" / "simple.kicad_sch", schs)
        for sch in schs:
            with self.subTest(sch=str(sch.relative_to(FX))):
                self._compare(sch, old)


def _bootstrap(name):
    from signal_detectors import _is_bootstrap_pin_name
    return _is_bootstrap_pin_name(name)


if __name__ == "__main__":
    unittest.main()

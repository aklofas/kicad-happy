"""The datasheet-backed lookup checks (AM-001, OV-001, TJ-001, FT-001, PM-001, EX-001) read
only a current extraction scored at least 60, and a named supply domain falls back to the
part's VDD/VCC rating, never to another named domain's."""
import math, sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "datasheets"))

import lookup_detectors  # noqa: E402
from datasheet_types import Evidence, SpecValue  # noqa: E402

MPN = "PART-1"
UNTRUSTED = (dict(quality=90, stale=True), dict(quality=59, stale=False),
             dict(quality=None, stale=False), dict(quality=math.nan, stale=False))


def _sv(unit="V", **values):
    return SpecValue(unit=unit, evidence=Evidence(page=1, confidence="high", method="table"),
                     **values)


def _pin(**kw):
    fields = dict(numbers=["1"], name="P1", power_domain=None, type="power_in",
                  absolute_max=None, is_5v_tolerant=None, alt_functions=[])
    fields.update(kw)
    return SimpleNamespace(**fields)


def _facts(quality=90, stale=False, absolute_max=None, recommended_operating=None,
           thermal=None, pinout=(), regulator=None):
    base = SimpleNamespace(absolute_max=absolute_max or {}, pinout=list(pinout),
                           recommended_operating=recommended_operating or {},
                           thermal=thermal or {})
    return SimpleNamespace(quality=quality, stale=stale, base=base, regulator=regulator)


def _ctx(net, volts):
    return SimpleNamespace(
        components=[{"reference": "U1", "mpn": MPN}], pin_net={("U1", "1"): (net, None)},
        nets={}, comp_lookup={}, cache_dir="cache", diagnostics=[], source="test",
        rail_source_fields=lambda n: {}, is_ground=lambda n: False,
        get_two_pin_nets=lambda r: []), {net: volts}


def _run(detector, facts, *args, **kwargs):
    with patch.object(lookup_detectors, "get_facts", lambda *a, **k: facts):
        return detector(*args, **kwargs)


class _Family:
    """One detector family: the trusted extraction gives one finding, an untrusted one none."""

    def fire(self, **trust):
        raise NotImplementedError

    def test_trusted_extraction_gives_the_finding(self):
        self.assertEqual(len(self.fire(quality=90, stale=False)), 1)
        self.assertEqual(len(self.fire(quality=60, stale=False)), 1)

    def test_skips_a_stale_extraction(self):
        self.assertEqual(self.fire(quality=90, stale=True), [])

    def test_skips_a_low_or_missing_score(self):
        for trust in UNTRUSTED[1:]:
            with self.subTest(**trust):
                self.assertEqual(self.fire(**trust), [])


class AbsoluteMaxTest(_Family, unittest.TestCase):
    def fire(self, **trust):
        facts = _facts(absolute_max={"VDD": [_sv(max=3.6)]},
                       pinout=[_pin(power_domain="VDD")], **trust)
        ctx, rails = _ctx("+5V", 5.0)
        return _run(lookup_detectors.detect_absolute_max_violations, facts, ctx, rails)


class RecommendedOperatingTest(_Family, unittest.TestCase):
    def fire(self, **trust):
        facts = _facts(recommended_operating={"VDD": [_sv(min=1.8, max=3.6)]},
                       pinout=[_pin(power_domain="VDD")], **trust)
        ctx, rails = _ctx("+5V", 5.0)
        return _run(lookup_detectors.detect_vcc_outside_recommended, facts, ctx, rails)


class JunctionTemperatureTest(_Family, unittest.TestCase):
    def fire(self, **trust):
        facts = _facts(thermal={"theta_ja": [_sv(unit="°C/W", typ=50.0)]},
                       absolute_max={"TJ": [_sv(unit="°C", max=100.0)]}, **trust)
        assessments = [{"ref": "U1", "mpn": MPN, "ambient_c": 25.0, "pdiss_w": 2.0}]
        return _run(lookup_detectors.detect_tj_exceeds_max, facts, assessments,
                    source="test", cache_dir="cache")


class FiveVoltTolerantTest(_Family, unittest.TestCase):
    def fire(self, **trust):
        facts = _facts(pinout=[_pin(type="input", is_5v_tolerant=False)], **trust)
        ctx, rails = _ctx("SIG", 5.0)
        return _run(lookup_detectors.detect_5v_on_non_tolerant_pin, facts, ctx, rails)


class SignalTypeTest(_Family, unittest.TestCase):
    def fire(self, **trust):
        af = SimpleNamespace(peripheral="SPI1", name="SPI1_MOSI")
        facts = _facts(pinout=[_pin(type="bidirectional", alt_functions=[af])], **trust)
        ctx, _ = _ctx("UART_TX", 3.3)
        return _run(lookup_detectors.detect_wrong_signal_type, facts, ctx)


class RequiredComponentsTest(_Family, unittest.TestCase):
    def fire(self, **trust):
        regulator = SimpleNamespace(cin_min=[_sv(unit="F", min=1e-5)], cout_min=None,
                                    inductor_range=None)
        facts = _facts(regulator=regulator, **trust)
        ctx, _ = _ctx("VIN", 12.0)
        regs = [{"ref": "U1", "mpn": MPN, "input_rail": "VIN", "output_rail": None}]
        return _run(lookup_detectors.detect_missing_required_components, facts, ctx, regs)


class SupplyDomainTest(unittest.TestCase):
    def _am(self, domain, block):
        facts = _facts(absolute_max=block, pinout=[_pin(power_domain=domain)])
        ctx, rails = _ctx("+5V", 5.0)
        return [f["absolute_max_v"] for f in
                _run(lookup_detectors.detect_absolute_max_violations, facts, ctx, rails)]

    def _ov(self, domain, block):
        facts = _facts(recommended_operating=block, pinout=[_pin(power_domain=domain)])
        ctx, rails = _ctx("+5V", 5.0)
        return len(_run(lookup_detectors.detect_vcc_outside_recommended, facts, ctx, rails))

    def test_specific_domain_does_not_borrow_another(self):
        self.assertEqual(self._am("VDDA", {"VDDIO": [_sv(max=3.6)]}), [])
        self.assertEqual(self._ov("VDDA", {"VDDIO": [_sv(min=1.6, max=3.6)]}), 0)

    def test_specific_domain_falls_back_to_the_part_supply(self):
        self.assertEqual(self._am("VDDA", {"VDD": [_sv(max=4.0)]}), [4.0])
        self.assertEqual(self._am("VBAT", {"VDD": [_sv(max=4.0)]}), [4.0])
        self.assertEqual(self._ov("VDDA", {"VDD": [_sv(min=2.0, max=3.6)]}), 1)

    def test_generic_domains_share_a_limit(self):
        self.assertEqual(self._am("VCC", {"VDD": [_sv(max=3.6)]}), [3.6])
        self.assertEqual(self._am("VDD", {"VCC": [_sv(max=3.6)]}), [3.6])

    def test_spelling_variants_of_one_domain_share_a_limit(self):
        self.assertEqual(self._am("VDDA", {"AVDD": [_sv(max=3.6)]}), [3.6])
        self.assertEqual(self._am("DVDD", {"VDDD": [_sv(max=3.6)]}), [3.6])
        self.assertEqual(self._am("VCC_dual_supply", {"VCC_single_supply": [_sv(max=3.6)]}),
                         [3.6])

    def test_own_domain_wins_over_the_part_supply(self):
        self.assertEqual(self._am("VDDA", {"VDD": [_sv(max=4.0)], "VDDA": [_sv(max=3.6)]}),
                         [3.6])


if __name__ == "__main__":
    unittest.main()

"""PU-001 value check and the top arm of a divider.

The top resistor of a divider into an input sets a threshold together with the bottom arm
(an enable threshold from the input rail); recommending 4.7 k to 10 k there would move
the threshold. On an output pin (open collector PG, say) the same resistor is the pull-up.
"""
import unittest

from tools.tests.test_validation_w4 import ctx_of, ic, res, rule, vd


def _divider(top_ref, top_ohms, bottom_ref, bottom_ohms, mid="EN_NODE"):
    return {"r_top": {"ref": top_ref, "ohms": top_ohms, "value": str(top_ohms)},
            "r_bottom": {"ref": bottom_ref, "ohms": bottom_ohms, "value": str(bottom_ohms)},
            "top_net": "VIN", "mid_net": mid, "bottom_net": "GND",
            "ratio": bottom_ohms / (top_ohms + bottom_ohms)}


def _ctx(pin_name, pin_type, top, bottom=None):
    comps = [ic("U1", "REG"), res("R1", top)]
    nets = {"SIG": [("U1", "1", pin_name, pin_type), ("R1", "2", "~", "passive")],
            "VIN": [("R1", "1", "~", "passive")]}
    if bottom:
        comps.append(res("R2", bottom))
        nets["SIG"].append(("R2", "1", "~", "passive"))
        nets["GND"] = [("R2", "2", "~", "passive")]
    return ctx_of(comps, nets, {"VIN"})


def _value_findings(ctx, dividers=None):
    return [f for f in rule(vd.validate_pullups(ctx, dividers), "PU-001")
            if "value too" in f["summary"]]


class PullUpDividerTop(unittest.TestCase):
    def test_enable_divider_top_resistor_is_not_sized_as_a_pullup(self):
        ctx = _ctx("EN", "input", "470k", "100k")
        self.assertEqual(_value_findings(ctx, [_divider("R1", 470000, "R2", 100000, "SIG")]), [])

    def test_enable_divider_top_resistor_is_sized_without_the_divider_list(self):
        ctx = _ctx("EN", "input", "470k", "100k")
        got = _value_findings(ctx)
        self.assertEqual(len(got), 1)
        self.assertIn("too high", got[0]["summary"])

    def test_lone_resistor_to_the_rail_on_an_enable_pin_is_still_too_high(self):
        ctx = _ctx("EN", "input", "470k")
        self.assertEqual(len(_value_findings(ctx, [])), 1)

    def test_open_collector_power_good_with_a_divider_still_gets_the_value_check(self):
        ctx = _ctx("PG", "open_collector", "105k", "55k")
        got = _value_findings(ctx, [_divider("R1", 105000, "R2", 55000, "SIG")])
        self.assertEqual(len(got), 1)
        self.assertIn("too high", got[0]["summary"])

    def test_divider_that_ends_on_another_net_does_not_exempt_this_one(self):
        ctx = _ctx("EN", "input", "470k")
        self.assertEqual(len(_value_findings(ctx, [_divider("R1", 470000, "R2", 100000, "OTHER")])), 1)


if __name__ == "__main__":
    unittest.main()

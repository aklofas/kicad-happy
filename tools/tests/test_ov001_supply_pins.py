# tools/tests/test_ov001_supply_pins.py
"""OV-001 compares a part's supply pins, not its signal pins, with the datasheet's supply minimum."""
import shutil, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "datasheets" / "scripts"))

from lookup_detectors import detect_vcc_outside_recommended  # noqa: E402

_PINS = {("U1", "1"): "VIN", ("U1", "2"): "SW", ("U1", "3"): "GND", ("U1", "4"): "FB", ("U1", "5"): "GND"}


def _ov001(vin):
    """OV-001 findings for an LM2596-ADJ on a rail at *vin* with ON/OFF (pin 5) tied to ground."""
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "extracted"
        cache.mkdir()
        shutil.copy(ROOT / "skills" / "datasheets" / "examples" / "lm2596-adj.json",
                    cache / "LM2596S-ADJ.json")
        ctx = SimpleNamespace(
            components=[{"reference": "U1", "type": "ic", "value": "LM2596S-ADJ",
                         "mpn": "LM2596S-ADJ"}],
            pin_net={k: (v, None) for k, v in _PINS.items()},
            cache_dir=cache, diagnostics=None, source="test",
            rail_source_fields=lambda net: {})
        return detect_vcc_outside_recommended(
            ctx, {"VIN": vin, "GND": 0.0, "SW": vin, "FB": 1.2})


class Ov001SupplyPinsOnly(unittest.TestCase):
    def test_enable_input_on_ground_is_not_a_supply_undervoltage(self):
        self.assertEqual(_ov001(12.0), [])

    def test_only_the_supply_pin_fires_when_the_supply_is_low(self):
        found = _ov001(3.0)
        self.assertEqual([f["pins"][0]["name"] for f in found], ["VIN"])
        self.assertIn("below recommended min 4.5V", found[0]["summary"])


if __name__ == "__main__":
    unittest.main()

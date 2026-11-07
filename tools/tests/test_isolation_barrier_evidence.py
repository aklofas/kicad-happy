"""An isolation barrier needs isolation evidence: an isolation part, an ISO ground domain, or a
rail named ISO or _SEC. An SPI MISO net is not an ISO rail, and a _B rail alone (USB-B, bank B,
channel B) shows no isolation."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from domain_detectors import detect_isolation_barriers  # noqa: E402


def _barriers(rails):
    comps = [{"reference": "U1", "type": "ic", "value": "MCU", "lib_id": "MCU:MCU", "pins": []}]
    names = ["GND", "AGND"] + list(rails)
    nets = {n: {"name": n, "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": [],
                "pins": [dict(component="U1", pin_number=str(i), pin_name=n, pin_type="power_in")]}
            for i, n in enumerate(names, 1)}
    ctx = build_analysis_context(comps, nets, {}, known_power_rails=set(names))
    return [b["isolated_power_rails"] for b in detect_isolation_barriers(ctx)]


class IsolationEvidence(unittest.TestCase):
    def test_spi_miso_and_a_lone_b_rail_are_not_isolation(self):
        self.assertEqual(_barriers(["SPI_MISO", "+5V_USB_B"]), [])

    def test_iso_and_sec_rails_still_show_isolation(self):
        for rail in ("+3V3_ISO", "+5VISO", "V_ISOOUT", "+V_SEC"):
            self.assertEqual(_barriers([rail]), [[rail]], rail)

    def test_b_rail_beside_an_iso_rail_is_listed(self):
        self.assertEqual(_barriers(["+3V3_ISO", "3.3V_B", "SPI_MISO"]), [["+3V3_ISO", "3.3V_B"]])


if __name__ == "__main__":
    unittest.main()

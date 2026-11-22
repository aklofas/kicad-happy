# tools/tests/test_net_leaf.py
"""net_leaf: behind a path of sheet ids everything is the label (a KiCad 5 label can hold a
'/'); any other path is split at its last '/'. Net classes read the net's own name."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_core.netnames import net_leaf  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _classify_nets  # noqa: E402

UUID = "0b3f2a1c-4d5e-4f60-8a7b-9c0d1e2f3a4b"


class NetLeaf(unittest.TestCase):
    def test_label_holding_a_slash_behind_sheet_ids_is_whole(self):
        self.assertEqual(net_leaf("/54E8D6A6/I2S_MCLKC/D3"), "I2S_MCLKC/D3")
        self.assertEqual(net_leaf("/5553F933/5553F9A1/20/A6"), "20/A6")

    def test_plain_paths_split_at_the_last_slash(self):
        self.assertEqual(net_leaf("/Power/3V3"), "3V3")
        self.assertEqual(net_leaf(f"/{UUID}/{UUID}/EN"), "EN")
        self.assertEqual(net_leaf("/54E8D6A6/EN"), "EN")

    def test_root_label_and_escaped_slash_stay_whole(self):
        self.assertEqual(net_leaf("1V/Oct"), "1V/Oct")
        self.assertEqual(net_leaf("/Sheet/A{slash}B"), "A{slash}B")


def _classes(nets):
    full = {n: {"name": n, "pins": [], "point_count": 0, "no_connect": False,
                "labels": labels} for n, labels in nets.items()}
    ctx = build_analysis_context([], full, {}, known_power_rails={"+3V3", "GND"})
    return _classify_nets(ctx)


class SlashLabelClass(unittest.TestCase):
    def test_legacy_label_with_a_slash_is_classified_by_its_whole_name(self):
        lbl = [{"name": "BUS_SCL/3.4A", "_bare_name": "BUS_SCL/3.4A"}]
        got = _classes({"/Power/BUS_SCL/3.4A": lbl, "/Sheet2/BUS_SCL/3.4A": lbl})
        self.assertEqual(set(got.values()), {"clock"})

    def test_sheet_path_still_does_not_classify_the_net(self):
        got = _classes({"/SPI_CS/NODE7": [{"name": "NODE7", "_bare_name": "NODE7"}]})
        self.assertEqual(got["/SPI_CS/NODE7"], "signal")


if __name__ == "__main__":
    unittest.main()

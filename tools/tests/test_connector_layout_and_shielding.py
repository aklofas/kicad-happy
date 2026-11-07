# tools/tests/test_connector_layout_and_shielding.py
"""Connector row layout and inductor shielding are read from the part name: Conn_01xNN is
KiCad's single-row naming, and NON_SHIELDED / SEMI_SHIELDED do not read as shielded."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import classify_connector  # noqa: E402
from kicad_core.passives import classify_inductor_shielding  # noqa: E402


def layout(lib_id, value=""):
    return classify_connector(lib_id, value)[1]


class ConnectorLayout(unittest.TestCase):
    def test_single_row_conn_symbol(self):
        self.assertEqual(layout("Connector_Generic:Conn_01x04"), "single")
        self.assertEqual(layout("Connector:Conn_01x02_Male", "Conn_01x02"), "single")

    def test_single_row_pin_header(self):
        self.assertEqual(layout("Connector:Pin_Header_1x06"), "single")

    def test_dual_row_conn_symbol(self):
        self.assertEqual(layout("Connector_Generic:Conn_02x05_Odd_Even"), "dual")
        self.assertEqual(layout("Connector:Pin_Header_2x10"), "dual")

    def test_dual_symbol_with_single_row_value_is_dual(self):
        self.assertEqual(layout("Connector_Generic:Conn_02x02_Odd_Even", "Conn_01x02_Pin"), "dual")
        self.assertEqual(layout("Connector_Generic:Conn_02x20_Odd_Even", "Conn_01x20"), "dual")

    def test_single_symbol_with_dual_row_value_is_single(self):
        self.assertEqual(layout("Connector_Generic:Conn_01x05", "Conn_02x05_Socket"), "single")

    def test_value_names_the_layout_when_the_symbol_does_not(self):
        self.assertEqual(layout("MyLib:HEADER", "Conn_02x05"), "dual")
        self.assertEqual(layout("MyLib:HEADER", "Pin_Header_1x04"), "single")


class InductorShielding(unittest.TestCase):
    def test_non_shielded_is_unshielded(self):
        for fp in ("Inductor_SMD:L_NON_SHIELDED_4x4", "Inductor_SMD:L_NonShielded_4x4",
                   "Inductor_SMD:L_Non-Shielded_4x4", "Inductor_SMD:L_Unshielded_4x4"):
            self.assertEqual(classify_inductor_shielding(fp), "unshielded", fp)

    def test_semi_shielded(self):
        for fp in ("Inductor_SMD:L_SEMI_SHIELDED_4x4", "Inductor_SMD:L_Semi-Shielded_4x4",
                   "Inductor_SMD:L_SemiShielded_4x4"):
            self.assertEqual(classify_inductor_shielding(fp), "semi-shielded", fp)

    def test_shielded_word(self):
        self.assertEqual(classify_inductor_shielding("Inductor_SMD:L_Shielded_4x4"), "shielded")


if __name__ == "__main__":
    unittest.main()

# tools/tests/test_connector_layout_and_shielding.py
"""Connector row layout and inductor shielding are read from the part name: Conn_01xNN is
KiCad's single-row naming, and NON_SHIELDED / SEMI_SHIELDED do not read as shielded."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import classify_connector  # noqa: E402
from kicad_core.passives import classify_inductor_shielding  # noqa: E402


def layout(lib_id, value="", footprint=""):
    return classify_connector(lib_id, value, 0, footprint)[1]


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

    def test_footprint_row_count_beats_a_value_when_the_symbol_is_silent(self):
        self.assertEqual(layout("43650-0400", "Conn_01x04",
                                "Connector_Molex:Molex_Micro-Fit_3.0_43045-0400_2x02_P3.00mm_Horizontal"), "dual")
        self.assertEqual(layout("Connector:AVR-ISP-6", "AVR-ISP-6",
                                "Connector_IDC:IDC-Header_2x03_P2.54mm_Vertical"), "dual")
        self.assertEqual(layout("x:WireConnector", "WireConnector", "Wire_1x01_D40mil_OD80mil"), "single")

    def test_library_nickname_is_not_read(self):
        self.assertEqual(layout("Proj_2x5:Header", "HDR"), "other")

    def test_symbol_name_still_outranks_the_footprint(self):
        self.assertEqual(layout("Connector_Generic:Conn_01x10", "Conn_01x10",
                                "PinSocket_2x05_P2.54mm_Vertical"), "single")
        self.assertEqual(layout("Connector_Generic:Conn_02x02_Odd_Even", "Conn_01x02_Pin",
                                "JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal"), "dual")

    def test_pad_body_and_cell_sizes_are_not_row_counts(self):
        for fp in ("PAD_SMD_1x2.65", "Keystone_1x12mm", "BatteryHolder_Keystone_1060_1x2032",
                   "U-FL4P-SMD-1_7X1_7X1_0MM"):
            self.assertEqual(layout("x:Opaque", "", fp), "other", fp)

    def test_unpadded_n_by_one_footprint_is_one_row(self):
        for fp in ("complib:CONN_3x1", "PIN_ARRAY_2X1", "3.5MM_2X1", "PINHEADER_127_2X1"):
            self.assertEqual(layout("x:Opaque", "", fp), "single", fp)
        self.assertEqual(layout("x:Opaque", "", "PinHeader_2x01_P2.54mm_Vertical"), "dual")
        self.assertEqual(layout("x:Opaque", "", "PinHeader_2x01"), "dual")

    def test_footprint_nickname_is_not_read(self):
        self.assertEqual(layout("x:Opaque", "", "Proj_2x5:Foo"), "other")

    def test_body_size_triple_is_stripped(self):
        self.assertEqual(layout("x:Opaque", "", "SHDR3W50P0X200_1X3_650X240X440P"), "single")

    def test_special_layouts_and_external_status_ignore_the_footprint(self):
        self.assertEqual(layout("Connector:USB_C_Receptacle", "", "PinHeader_2x05"), "usb_c")
        for lib, val in (("Connector:Conn_01x04", ""), ("Connector:USB_B", "")):
            self.assertEqual(classify_connector(lib, val, 4)[0],
                             classify_connector(lib, val, 4, "PinHeader_2x02")[0])


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

    def test_spaced_words(self):
        self.assertEqual(classify_inductor_shielding("", "NON SHIELDED", ""), "unshielded")
        self.assertEqual(classify_inductor_shielding("", "Non  Shielded 10uH", ""), "unshielded")
        self.assertEqual(classify_inductor_shielding("", "SEMI SHIELDED", ""), "semi-shielded")
        self.assertEqual(classify_inductor_shielding("", "NON - SHIELDED", ""), "unshielded")
        self.assertEqual(classify_inductor_shielding("", "", "Semi\tShielded"), "semi-shielded")

    def test_words_do_not_join_across_fields(self):
        self.assertEqual(classify_inductor_shielding("", "SHIELDED", ""), "shielded")
        self.assertEqual(classify_inductor_shielding("Inductor_SMD:L_NON", "SHIELDED 4.7uH", ""),
                         "shielded")
        self.assertEqual(classify_inductor_shielding("Inductor_SMD:L_SEMI", "", "SHIELDED"), "shielded")

    def test_empty_fields_are_unknown(self):
        self.assertEqual(classify_inductor_shielding("", "", ""), "unknown")
        self.assertEqual(classify_inductor_shielding(None, None, None), "unknown")
        self.assertEqual(classify_inductor_shielding(" ", "", ""), "unknown")


if __name__ == "__main__":
    unittest.main()

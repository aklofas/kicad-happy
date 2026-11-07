# tools/tests/test_v_prefix_connector_type.py
"""A V reference reads as a varistor, but a V-prefixed header, connector or jumper is the
part its library and footprint say it is. A real varistor stays a varistor."""
import sys, unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kicad_core.classify import classify_component  # noqa: E402


class VPrefixConnectorsAndJumpers(unittest.TestCase):
    def test_header_under_v_reference_is_connector(self):
        self.assertEqual(classify_component(
            "V12", "dvhx-kicad-library:Header_1x2_male", "Header_1x2_male",
            footprint="dvhx-kicad-library:Header_1x2_male_upright"), "connector")

    def test_header_value_and_footprint_alone_type_a_connector(self):
        self.assertEqual(classify_component(
            "V19", "dvhx-kicad-library:R", "Header_1x2_male",
            footprint="dvhx-kicad-library:Header_1x2_male_upright"), "connector")

    def test_jumper_library_under_v_reference_is_jumper(self):
        self.assertEqual(classify_component("V4", "Jumper:Jumper_2_Bridged", "V"), "jumper")

    def test_vga_socket_under_longer_v_prefix_is_connector(self):
        self.assertEqual(classify_component(
            "VGA1", "AgonLight2_Rev_A:VGA15-F(CD0515S21J0)", "VGA15",
            footprint="OLIMEX_Connectors-FP:VGA15-F(CD0515S21J0)"), "connector")

    def test_conn_symbol_under_longer_v_prefix_is_connector(self):
        self.assertEqual(classify_component("VP1", "CONN_1", "S"), "connector")

    def test_varistor_stays_varistor(self):
        self.assertEqual(classify_component(
            "V1", "Device:Varistor", "S14K275",
            footprint="Varistor:RV_Disc_D12mm_W4.2mm_P7.5mm"), "varistor")
        self.assertEqual(classify_component("VAR1", "Device:Varistor", "V10E250P"), "varistor")

    def test_varistor_word_wins_over_a_connector_word(self):
        self.assertEqual(classify_component(
            "V2", "MyLib:Varistor", "CG0603MLC",
            footprint="MyConnectors:0603"), "varistor")

    def test_v_reference_without_connector_or_jumper_evidence_is_unchanged(self):
        self.assertEqual(classify_component("V3", "MyLib:MOV", "JMV0805"), "varistor")


if __name__ == "__main__":
    unittest.main()

# tools/tests/test_pchannel_parts.py
"""A MOSFET named only by its part number, a generic P name or a "P-CH" description reads
as P-channel. The table holds whole part numbers, never family prefixes, because families
mix the two channels; every entry is cited below."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_core import parts  # noqa: E402
from kicad_core.parts import names_pchannel_fet  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402

# Entry -> (symbol, text) in KiCad's Transistor_FET library: KiCad 9.0 Transistor_FET.kicad_sym
# Description (or ki_keywords where named), and KiCad 5 Transistor_FET.dcm for the two DirectFET parts.
KICAD_SYMBOLS = {
    "AO3401": ("AO3401A", "P-Channel MOSFET"),
    "AON6411": ("AON6411", "P-Channel MOSFET"),
    "BS250": ("BS250", "P-Channel MOSFET"),
    "BSS83P": ("BSS83P", "P-Channel MOSFET"),
    "BSS84": ("BSS84", "P-Channel MOSFET"),
    "CSD25302Q2": ("CSD25302Q2", "NexFET P-Channel Power MOSFET"),
    "CSD25402Q3A": ("CSD25402Q3A", "NexFET P-Channel Power MOSFET"),
    "CSD25480F3": ("CSD25480F3", "P-Channel MOSFET"),
    "DMG2301L": ("DMG2301L", "P-Channel MOSFET"),
    "DMP3013SFV": ("DMP3013SFV", "P-Channel Power MOSFET"),
    "DMP3099L": ("DMP3099L", "P-Channel MOSFET"),
    "DMP6050SSD": ("DMP6050SSD", "P-Channel Power MOSFET"),
    "FDN340P": ("FDN340P", "P-Channel MOSFET"),
    "FDS9435A": ("FDS9435A", "P-Channel MOSFET"),
    "FQP27P06": ("FQP27P06", "QFET P-Channel MOSFET"),
    "IRF4905": ("IRF4905", "Single P-Channel HEXFET Power MOSFET"),
    "IRF7324": ("IRF7324", "Dual HEXFET P-Channel MOSFET"),
    "IRF7404": ("IRF7404", "P-Channel HEXFET Power MOSFET"),
    "IRF7606": ("IRF7606PBF", "HexFET P-MOS Power MOSFET"),
    "IRF9383M": ("IRF9383M", "P-Channel MOSFET"),
    "IRF9540N": ("IRF9540N", "P-Channel HEXFET Power MOSFET"),
    "IRFTS9342": ("IRFTS9342PBF", "P-Channel HEXFET Power MOSFET"),
    "IRLML5203": ("IRLML5203", "P-Channel HEXFET Power MOSFET"),
    "IRLML6401": ("IRLML6401", "P-Channel HEXFET Power MOSFET"),
    "IRLML6402": ("IRLML6402", "P-Channel HEXFET Power MOSFET"),
    "IRLML9301": ("IRLML9301", "P-Channel HEXFET Power MOSFET"),
    "NTR2101P": ("NTR2101P", "P-Channel MOSFET"),
    "PMN48XP": ("PMN48XP", "P-Channel Power MOSFET"),
    "QM6015D": ("QM6015D", "P-Channel Power MOSFET"),
    "SI2319CDS": ("Si2319CDS", "P-Channel MOSFET"),
    "SI2371EDS": ("Si2371EDS", "P-Channel MOSFET"),
    "SI7141DP": ("Si7141DP", "keywords: P-Channel MOSFET"),
    "SI7617DN": ("Si7617DN", "keywords: P-Channel MOSFET"),
    "SIA449DJ": ("SiA449DJ", "P-Channel MOSFET"),
    "SIA453EDJ": ("SiA453EDJ", "P-Channel MOSFET"),
    "SIS415DNT": ("SiS415DNT", "P-Channel MOSFET"),
    "SIS443DN": ("SiS443DN", "P-Channel MOSFET"),
    "SISS27DN": ("SiSS27DN", "P-Channel MOSFET"),
    "SQJQ131EL": ("SQJQ131EL", "P-Channel MOSFET"),
    "SUD08P06-155L": ("SUD08P06-155L", "TrenchFET P-Channel Power MOSFET"),
    "SUD09P10-195": ("SUD09P10-195", "TrenchFET P-Channel Power MOSFET"),
    "SUD19P06-60": ("SUD19P06-60", "TrenchFET P-Channel Power MOSFET"),
    "SUD45P03-09": ("SUD45P03-09", "TrenchFET P-Channel Power MOSFET"),
    "SUD50P04-08": ("SUD50P04-08", "TrenchFET P-Channel Power MOSFET"),
    "SUD50P06-15": ("SUD50P06-15", "TrenchFET P-Channel Power MOSFET"),
    "SUD50P08-25L": ("SUD50P08-25L", "TrenchFET P-Channel Power MOSFET"),
    "SUD50P10-43L": ("SUD50P10-43L", "TrenchFET P-Channel Power MOSFET"),
    "TP0610": ("TP0610T", "P-Channel MOSFET"),
    "TSM2301ACX": ("TSM2301ACX", "P-Channel MOSFET"),
    "VP0610": ("VP0610T", "P-Channel MOSFET"),
    "ZXMP4A16G": ("ZXMP4A16G", "P-Channel MOSFET"),
    "IRF9394M": ("IRF9394M", "KiCad 5 .dcm: P-Channel MOSFET, DirectFET MC"),
    "IRF9395M": ("IRF9395M", "KiCad 5 .dcm: P-Channel MOSFET, DirectFET MC"),
}

# Entry -> maker datasheet (title, revision, page: text).
DATASHEETS = {
    "AO3407": "AOS AO3407A, Rev 5.1 July 2023, p. 1: 30V P-Channel MOSFET",
    "AO3415": "AOS AO3415A, Rev. 3.1 August 2023, p. 1: 20V P-Channel MOSFET",
    "AO3423": "AOS AO3423, Rev 5.1 December 2023, p. 1: 20V P-Channel MOSFET",
    "AO4407A": "AOS AO4407A, Rev. 11.1 March 2024, p. 1: 30V P-Channel MOSFET",
    "DMG2305UX": "Diodes DMG2305UX, DS36196 Rev. 8-2, p. 1: P-CHANNEL ENHANCEMENT MODE MOSFET",
    "FDN302P": "onsemi FDN302P, Rev. 4 March 2023, p. 1: MOSFET - P-Channel, 2.5 V",
    "FDN360P": "onsemi FDN360P, Rev. 8 January 2023, p. 1: MOSFET - Single, P-Channel",
    "FDS6673BZ": "onsemi FDS6673BZ/D, Rev. 5 September 2022, p. 1: MOSFET - P-Channel",
    "FDV304P": "onsemi FDV304P, Rev. 6 February 2022, p. 1: Digital FET, P-Channel",
    "FQD5P20": "Fairchild FQD5P20 / FQU5P20, Rev. C0, p. 1: P-Channel QFET MOSFET",
    "FQU5P20": "Fairchild FQD5P20 / FQU5P20, Rev. C0, p. 1: P-Channel QFET MOSFET",
    "IRF5305": "Infineon IRF5305PbF, Rev. 2.1 2026-07-24, p. 1: P-Channel",
    "IRFR5305": "International Rectifier IRFR5305PbF/IRFU5305PbF, PD-95025A 12/13/04, p. 1: VDSS = -55V",
    "IRFU5305": "International Rectifier IRFR5305PbF/IRFU5305PbF, PD-95025A 12/13/04, p. 1: VDSS = -55V",
    "IRLML2244": "International Rectifier IRLML2244TRPbF, PD-97631 1/24/11, p. 1: VDS -20 V",
    "NDT456P": "onsemi NDT456P, Rev. 6 September 2017, p. 2: P-Channel Enhancement Mode Field Effect Transistor",
    "NTD25P03L": "onsemi NTD25P03L, Rev. 5 May 2019, p. 1: P-Channel, Logic Level",
    "NTR4171P": "onsemi NTR4171P, Rev. 3 February 2026, p. 1: P-Channel, SOT-23",
    "SI2301CDS": "Vishay Si2301CDS, Document 68741 S10-2430 Rev. C 25-Oct-10, p. 1: P-Channel 20 V (D-S) MOSFET",
}

# N-channel parts in the same families (AO3400A/AO3402/AO3414: AOS "N-Channel MOSFET";
# DMG2302U: Diodes "N-CHANNEL"; Si2302: N-channel) and look-alike part numbers.
NOT_PCHANNEL = ("AO3400A", "AO3402", "AO3414", "DMG2302U", "SI2302", "SI2302-TP", "2N7002",
                "BSS138", "AO34015", "DMG2302UK-7", "Si2302CDS-T1-GE3", "BSS138,215")

PCHANNEL = ("AO3401A", "AO3401", "AO3407A", "IRLML6402TRPBF", "IRLML6402 TRPBF 01AH (SOT-23)",
            "DMG2305UX-13", "IRF5305PBF", "BSS84AK,215", "TP0610T", "DMG2305UX-7",
            "Si2301CDS-T1-GE3", "BSS84,215")


def _is_pchannel(value="", lib_id="Device:Q_NMOS_GDS", description="", mpn=""):
    """is_pchannel of Q1, a FET whose source sits on +5V and whose drain feeds R1 to ground."""
    comps = [
        {"reference": "Q1", "type": "transistor", "value": value, "lib_id": lib_id,
         "description": description, "mpn": mpn},
        {"reference": "R1", "type": "resistor", "value": "1k", "lib_id": "Device:R"},
    ]
    nets = {
        "+5V": [("Q1", "2", "S", "passive")],
        "OUT": [("Q1", "3", "D", "passive"), ("R1", "1", "~", "passive")],
        "GATE": [("Q1", "1", "G", "input")],
        "GND": [("R1", "2", "~", "passive")],
    }
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in comps:
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    ctx = build_analysis_context(comps, full, {}, known_power_rails={"+5V", "GND"})
    fet_pins = {"Q1": {"gate": "GATE", "drain": "OUT", "source": "+5V",
                       "value": value, "lib_id": lib_id}}
    (circuit,) = [c for c in sd.detect_transistor_circuits(ctx, set(), fet_pins)
                  if c["reference"] == "Q1"]
    return circuit["is_pchannel"]


class PChannelPartTable(unittest.TestCase):
    def test_every_entry_is_cited(self):
        self.assertEqual(set(parts._PCHANNEL_FET_PARTS), set(KICAD_SYMBOLS) | set(DATASHEETS))

    def test_every_cited_part_reads_p_channel(self):
        for pn in list(KICAD_SYMBOLS) + list(DATASHEETS):
            with self.subTest(pn=pn):
                self.assertTrue(names_pchannel_fet(pn))

    def test_n_channel_family_members_and_look_alikes_stay_n(self):
        for pn in NOT_PCHANNEL:
            with self.subTest(pn=pn):
                self.assertFalse(names_pchannel_fet(pn))

    def test_ordering_and_packing_suffixes_keep_p(self):
        for pn in PCHANNEL:
            with self.subTest(pn=pn):
                self.assertTrue(names_pchannel_fet(pn))

    def test_any_of_several_names_may_match(self):
        self.assertTrue(names_pchannel_fet("", "Q", "IRLML6402"))
        self.assertFalse(names_pchannel_fet("", None, "2N7002"))


class PChannelTransistorCircuit(unittest.TestCase):
    def test_part_number_value_on_a_generic_symbol(self):
        self.assertTrue(_is_pchannel(value="IRLML6402", lib_id="Device:Q_NMOS_GSD"))

    def test_part_number_value_beats_a_copied_n_symbol(self):
        self.assertTrue(_is_pchannel(value="AO3401A", lib_id="Transistor_FET:AO3400A"))

    def test_part_number_in_mpn(self):
        self.assertTrue(_is_pchannel(value="Q", lib_id="MyParts:FET", mpn="DMG2305UX-13"))

    def test_part_number_as_library_symbol(self):
        self.assertTrue(_is_pchannel(value="Q1", lib_id="Transistor_FET:IRLML6402"))

    def test_n_channel_value_on_an_n_symbol_stays_n(self):
        self.assertFalse(_is_pchannel(value="AO3400A", lib_id="Transistor_FET:AO3400A"))

    def test_2n7002_stays_n(self):
        self.assertFalse(_is_pchannel(value="2N7002", lib_id="Transistor_FET:2N7002"))

    def test_generic_p_value_names(self):
        for value in ("MOSFET_P", "MOS_P", "PFET", "P-MOS", "Pch", "P-CH"):
            with self.subTest(value=value):
                self.assertTrue(_is_pchannel(value=value, lib_id="MyParts:FET"))

    def test_p_ch_description(self):
        self.assertTrue(_is_pchannel(value="Q", lib_id="MyParts:FET",
                                     description="SMD MOSFET P-CH 30V-4.3A"))

    def test_complementary_pair_description_stays_n(self):
        self.assertFalse(_is_pchannel(value="QS6M4", lib_id="MyParts:FET",
                                      description="combines Pch MOSFET with a Nch MOSFET"))


if __name__ == "__main__":
    unittest.main()

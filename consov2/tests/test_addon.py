"""Tests de l'add-on sans matériel : python3 -m unittest discover -s consov2/tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rootfs", "app"))

from consov2 import arkteos, influx, legacy, tic  # noqa: E402
from consov2.aggregator import Aggregator  # noqa: E402
from consov2.model import Measurement  # noqa: E402
from consov2.spool import Spool  # noqa: E402


def group(label: str, value: str, date: str = "") -> bytes:
    payload = label.encode() + b"\t" + ((date.encode() + b"\t") if date else b"") + value.encode() + b"\t"
    return b"\n" + payload + bytes([tic.checksum(payload)]) + b"\r"


def frame(**fields) -> bytes:
    return b"\x02" + b"".join(group(k, v) for k, v in fields.items()) + b"\x03"


class TicTest(unittest.TestCase):
    def test_checksum(self):
        # Mode standard : somme des octets de l'étiquette jusqu'à la dernière tabulation, & 0x3F, + 0x20.
        payload = b"SINSTS\t01234\t"
        self.assertEqual(tic.checksum(payload), (sum(payload) & 0x3F) + 0x20)
        self.assertEqual(chr(tic.checksum(b"VTIC\t02\t")), "J")

    def test_frame(self):
        raw = frame(ADSC="041876097274", EASF01="017667900", SINSTS="01234", LTARF="    BASE    ")
        frames = tic.FrameAssembler().feed(raw)
        self.assertEqual(len(frames), 1)
        fields, bad = tic.parse_frame(frames[0])
        self.assertEqual(bad, 0)
        self.assertEqual(fields["EASF01"], 17667900)
        self.assertEqual(fields["SINSTS"], 1234)
        self.assertEqual(fields["ADSC"], "041876097274")
        self.assertEqual(fields["LTARF"], "BASE")

    def test_group_horodate(self):
        g = group("SMAXSN", "06520", "E261009142530")
        self.assertEqual(tic.parse_group(g), ("SMAXSN", "06520"))

    def test_checksum_faux(self):
        g = bytearray(group("EASF01", "017667900"))
        g[-2] ^= 1
        self.assertIsNone(tic.parse_group(bytes(g)))

    def test_trame_coupee(self):
        asm = tic.FrameAssembler()
        raw = b"junk" + frame(SINSTS="00500") + frame(SINSTS="00600")
        out = asm.feed(raw[:20]) + asm.feed(raw[20:])
        self.assertEqual([tic.parse_frame(f)[0]["SINSTS"] for f in out], [500, 600])


class ArkteosTest(unittest.TestCase):
    def test_decode_signe(self):
        f163 = bytearray(163)
        f163[24], f163[25] = (-35) & 0xFF, ((-35) >> 8) & 0xFF   # -3,5 °C
        f227 = bytearray(227)
        f227[54], f227[55] = 352 & 0xFF, 352 >> 8                  # 35,2 °C
        f227[62] = 15                                              # 1,5 bar
        v = arkteos.decode(bytes(f163))
        self.assertEqual(v, {"exterieur_temp": -3.5})
        v = arkteos.decode(bytes(f227))
        self.assertEqual(v["primaire_temp_eau_aller"], 35.2)
        self.assertEqual(v["primaire_pression"], 1.5)


class AggregatorTest(unittest.TestCase):
    def test_moyenne_et_index(self):
        a = Aggregator()
        for v in (100, 200, 300):
            a.add(Measurement("circuit_cuisson", v, "W", 1000, "shelly"))
        a.add(Measurement("elec_index", 1000, "Wh", 1001, "linky", "counter"))
        a.add(Measurement("elec_index", 1010, "Wh", 1002, "linky", "counter"))
        out = {m.metric: m for m in a.flush(1200)}
        self.assertEqual(out["circuit_cuisson"].value, 200)
        self.assertEqual(out["elec_index"].value, 1010)
        self.assertEqual(out["elec_index"].kind, "counter")
        self.assertTrue(all(m.ts == 1200 for m in out.values()))
        self.assertEqual(a.flush(1500), [])

    def test_seuil_ecs(self):
        a, events = Aggregator(), []
        a.watch("circuit_appoint_ecs", 500, events.append)
        for v in (4, 5, 1800, 1900, 3):
            a.add(Measurement("circuit_appoint_ecs", v, "W", 1, "shelly"))
        self.assertEqual(events, [True, False])


class SpoolTest(unittest.TestCase):
    def test_ordre_et_reessai(self):
        with tempfile.TemporaryDirectory() as d:
            s = Spool(os.path.join(d, "q.sqlite"), max_batches=3)
            for i in range(5):
                s.push([Measurement("x", i, "W", 1000 + i, "t")])
            self.assertEqual(s.pending(), 3)          # les 2 plus anciens sont oubliés
            first = s.next_due(10)
            s.retry_later(first[0], 100)
            self.assertIsNone(s.next_due(50))         # jamais un récent avant l'ancien
            self.assertEqual(s.next_due(100)[0], first[0])
            s.done(first[0])
            self.assertEqual(s.pending(), 2)


class OutputsTest(unittest.TestCase):
    def test_line_protocol(self):
        self.assertEqual(influx.line("EASF01", {"host": "raspberry", "region": "linky"}, 17667900, 1700000000),
                         "EASF01,host=raspberry,region=linky value=17667900i 1700000000")
        self.assertEqual(influx.line("LTARF", {}, 'BA"SE', 1), 'LTARF value="BA\\"SE" 1')
        self.assertEqual(influx.line("SHELLYEM1_0", {}, 12.0, 1), "SHELLYEM1_0 value=12.0 1")

    def test_legacy(self):
        batch = [Measurement("elec_index", 17667900, "Wh", 1, "linky", "counter"),
                 Measurement("circuit_a", 12.6, "W", 1, "shelly")]
        q = legacy.build_query(batch, "elec_index", ["circuit_a", "circuit_b"])
        self.assertEqual(q, "cindex=17667.9&q1=13&q2=0")
        self.assertEqual(legacy.build_query(batch[1:], "elec_index", ["circuit_a"]), "")


if __name__ == "__main__":
    unittest.main()

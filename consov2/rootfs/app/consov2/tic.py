"""Téléinformation Linky en mode standard (9600 bauds, 7 bits, parité paire).

Une trame commence par STX (0x02) et finit par ETX (0x03). Chaque groupe est
  ETIQUETTE <HT> [HORODATAGE <HT>] DONNEE <HT> CHECKSUM <CR>
précédé de LF. Le checksum couvre l'étiquette jusqu'à la dernière tabulation
incluse : (somme des octets & 0x3F) + 0x20.
"""
import logging
import threading
import time
from typing import Callable, Dict, Optional, Tuple

log = logging.getLogger("linky")

# Champs texte : jamais convertis en nombre.
TEXT_FIELDS = {"ADSC", "VTIC", "DATE", "NGTF", "LTARF", "MSG1", "MSG2", "PRM", "NJOURF", "NJOURF+1",
               "PJOURF+1", "PPOINTE", "STGE", "RELAIS", "DPM1", "FPM1", "DPM2", "FPM2", "DPM3", "FPM3"}


def checksum(payload: bytes) -> int:
    return (sum(payload) & 0x3F) + 0x20


def parse_group(raw: bytes) -> Optional[Tuple[str, str]]:
    """Décode un groupe « ETIQUETTE\\t[DATE\\t]VALEUR\\tCHECKSUM ». None si invalide."""
    raw = raw.strip(b"\r\n")
    if len(raw) < 4 or raw[-2:-1] != b"\t":
        return None
    payload, check = raw[:-1], raw[-1]
    if checksum(payload) != check:
        return None
    parts = payload[:-1].split(b"\t")
    if len(parts) < 2:
        return None
    try:
        label = parts[0].decode("ascii")
        value = parts[-1].decode("ascii", errors="replace").strip()
    except UnicodeDecodeError:
        return None
    return label, value


def parse_frame(frame: bytes) -> Tuple[Dict[str, object], int]:
    """Décode une trame complète (sans STX/ETX). Renvoie (champs, nombre de groupes rejetés)."""
    fields: Dict[str, object] = {}
    bad = 0
    for group in frame.split(b"\n"):
        if not group.strip(b"\r\n"):
            continue
        parsed = parse_group(group)
        if parsed is None:
            bad += 1
            continue
        label, value = parsed
        if label in TEXT_FIELDS:
            fields[label] = value
        else:
            try:
                fields[label] = int(value)
            except ValueError:
                fields[label] = value
    return fields, bad


class FrameAssembler:
    """Reçoit des octets dans le désordre et rend les trames complètes."""

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes):
        self.buf += data
        frames = []
        while True:
            start = self.buf.find(b"\x02")
            if start < 0:
                self.buf = b""
                break
            end = self.buf.find(b"\x03", start + 1)
            if end < 0:
                self.buf = self.buf[start:]
                if len(self.buf) > 8192:  # trame anormalement longue : on repart de zéro
                    self.buf = b""
                break
            frames.append(self.buf[start + 1:end])
            self.buf = self.buf[end + 1:]
        return frames


class LinkyReader(threading.Thread):
    """Lit le port série en continu et appelle on_frame(champs, ts) pour chaque trame valide."""

    def __init__(self, port: str, on_frame: Callable[[dict, int], None], stop: threading.Event):
        super().__init__(name="linky", daemon=True)
        self.port, self.on_frame, self.stop = port, on_frame, stop
        self.frames = 0
        self.last_frame_ts = 0

    def run(self):
        import serial  # pyserial
        delay = 5
        while not self.stop.is_set():
            try:
                with serial.Serial(self.port, 9600, bytesize=serial.SEVENBITS, parity=serial.PARITY_EVEN,
                                   stopbits=serial.STOPBITS_ONE, timeout=2) as ser:
                    log.info("Port série ouvert : %s", self.port)
                    delay = 5
                    asm = FrameAssembler()
                    while not self.stop.is_set():
                        data = ser.read(512)
                        if not data:
                            continue
                        for frame in asm.feed(data):
                            fields, bad = parse_frame(frame)
                            if bad:
                                log.debug("%d groupe(s) TIC rejeté(s) (checksum)", bad)
                            if fields:
                                self.frames += 1
                                self.last_frame_ts = int(time.time())
                                self.on_frame(fields, self.last_frame_ts)
            except Exception as exc:  # port absent, câble débranché…
                log.warning("Linky : %s. Nouvel essai dans %d s.", exc, delay)
                self.stop.wait(delay)
                delay = min(delay * 2, 300)

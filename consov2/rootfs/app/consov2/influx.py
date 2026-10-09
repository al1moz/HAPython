"""Écriture InfluxDB 2.x en « line protocol », sans bibliothèque externe.

Les noms de mesures, les étiquettes et les types de champs reprennent ceux des
anciens add-ons, pour que les tableaux Grafana existants continuent de marcher.
"""
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List

log = logging.getLogger("influx")


def _escape_key(s: str) -> str:
    return s.replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _field(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return "%di" % value          # entier, comme l'ancien add-on Linky
    if isinstance(value, float):
        return repr(value)
    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')


def line(measurement: str, tags: Dict[str, str], value, ts: int) -> str:
    tag_part = "".join(",%s=%s" % (_escape_key(k), _escape_key(v)) for k, v in sorted(tags.items()))
    return "%s%s value=%s %d" % (_escape_key(measurement), tag_part, _field(value), ts)


class InfluxWriter(threading.Thread):
    """Accumule les points et les écrit par paquets toutes les flush_seconds."""

    MAX_BUFFER = 50000

    def __init__(self, url: str, token: str, org: str, stop: threading.Event, flush_seconds: int = 10):
        super().__init__(name="influx", daemon=True)
        self.url, self.token, self.org, self.stop = url.rstrip("/"), token, org, stop
        self.flush_seconds = flush_seconds
        self._lock = threading.Lock()
        self._buffers: Dict[str, List[str]] = {}
        self.last_error = ""

    def write(self, bucket: str, measurement: str, tags: Dict[str, str], value, ts: int):
        with self._lock:
            buf = self._buffers.setdefault(bucket, [])
            buf.append(line(measurement, tags, value, ts))
            if len(buf) > self.MAX_BUFFER:
                del buf[:len(buf) - self.MAX_BUFFER]

    def _send(self, bucket: str, lines: List[str]) -> bool:
        query = urllib.parse.urlencode({"org": self.org, "bucket": bucket, "precision": "s"})
        req = urllib.request.Request(self.url + "/api/v2/write?" + query, data="\n".join(lines).encode("utf-8"),
                                     method="POST", headers={"Authorization": "Token " + self.token,
                                                             "Content-Type": "text/plain; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=20):
                self.last_error = ""
                return True
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            self.last_error = "HTTP %s" % exc.code
            log.warning("InfluxDB refuse l'écriture dans %s (HTTP %s) : %s", bucket, exc.code, detail)
            # 4xx (sauf 429) : points invalides ou bucket absent, les renvoyer ne servirait à rien.
            return 400 <= exc.code < 500 and exc.code != 429
        except Exception as exc:
            self.last_error = str(exc)[:120]
            log.warning("InfluxDB injoignable : %s", exc)
            return False

    def flush(self):
        with self._lock:
            buffers, self._buffers = self._buffers, {}
        for bucket, lines in buffers.items():
            for i in range(0, len(lines), 5000):
                chunk = lines[i:i + 5000]
                if not self._send(bucket, chunk):
                    with self._lock:  # on garde les points pour le prochain essai
                        rest = lines[i:]
                        self._buffers[bucket] = (rest + self._buffers.get(bucket, []))[-self.MAX_BUFFER:]
                    break

    def run(self):
        while not self.stop.wait(self.flush_seconds):
            self.flush()
        self.flush()

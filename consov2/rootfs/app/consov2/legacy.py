"""Envoi optionnel vers l'ancien site (receiver.php?cindex=…&q1=…&q8=…), pendant la transition."""
import logging
import urllib.parse
import urllib.request
from typing import List

from .model import Measurement

log = logging.getLogger("legacy")


def build_query(measurements: List[Measurement], index_metric: str, circuits: List[str]) -> str:
    values = {m.metric: m for m in measurements}
    index = values.get(index_metric)
    if index is None or not any(c in values for c in circuits):
        return ""
    params = {"cindex": str(index.value / 1000)}  # Wh -> kWh
    for i, metric in enumerate(circuits[:8], start=1):
        m = values.get(metric)
        params["q%d" % i] = str(round(m.value)) if m is not None else "0"
    return urllib.parse.urlencode(params)


def send(url: str, measurements: List[Measurement], index_metric: str, circuits: List[str]):
    query = build_query(measurements, index_metric, circuits)
    if not query:
        log.info("Ancien site : pas d'index Linky ou pas de Shelly sur cette période, rien d'envoyé.")
        return
    try:
        with urllib.request.urlopen(url + ("&" if "?" in url else "?") + query, timeout=20) as resp:
            log.debug("Ancien site : HTTP %s", resp.status)
    except Exception as exc:
        log.warning("Ancien site injoignable : %s", exc)

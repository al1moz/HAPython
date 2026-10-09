"""Envoi des lots en file d'attente vers l'API du site (POST /api/v1/measurements)."""
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from . import __version__
from .spool import Spool

log = logging.getLogger("api")

BACKOFF_MIN, BACKOFF_MAX = 30, 900


class Sender(threading.Thread):
    def __init__(self, url: str, token: str, spool: Spool, stop: threading.Event, wake: threading.Event):
        super().__init__(name="api", daemon=True)
        self.endpoint = url.rstrip("/") + "/api/v1/measurements"
        self.token, self.spool, self.stop, self.wake = token, spool, stop, wake
        self.backoff = BACKOFF_MIN
        self.last_ok = 0
        self.last_error = ""

    def post(self, idem: str, body: str):
        req = urllib.request.Request(self.endpoint, data=body.encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.token,
            "Idempotency-Key": idem,
            "User-Agent": "consov2-addon/" + __version__,
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def run(self):
        while not self.stop.is_set():
            now = int(time.time())
            row = self.spool.next_due(now)
            if row is None:
                self.wake.wait(60)
                self.wake.clear()
                continue
            batch_id, idem, body, attempts = row
            try:
                status, text = self.post(idem, body)
            except Exception as exc:  # réseau, DNS, délai dépassé…
                status, text = 0, str(exc)
            if status in (200, 202):
                self.spool.done(batch_id)
                self.backoff = BACKOFF_MIN
                self.last_ok = now
                self.last_error = ""
                try:
                    result = json.loads(text)
                    if isinstance(result, dict) and result.get("rejected"):
                        log.warning("Lot %s : %s mesure(s) refusée(s) : %s", idem, result["rejected"],
                                    result.get("errors", [])[:5])
                    else:
                        log.debug("Lot %s : %s", idem, result)
                        accepted = result.get("accepted") if isinstance(result, dict) else None
                        log.info("Envoyé au site : %s mesure(s)%s, %d lot(s) encore en file.",
                                 "?" if accepted is None else accepted,
                                 "" if not isinstance(result, dict) or not result.get("duplicates")
                                 else " (%s déjà reçue(s))" % result["duplicates"],
                                 self.spool.pending())
                except ValueError:
                    log.warning("Lot %s : réponse du site illisible (HTTP %s) : %s", idem, status, text[:300])
                continue
            if status in (413, 422) or (400 <= status < 500 and status not in (401, 403, 408, 429)):
                # Le site refuse ce lot tel quel : le renvoyer ne servirait à rien.
                log.error("Lot %s abandonné (HTTP %s) : %s", idem, status, text[:300])
                self.spool.done(batch_id)
                self.last_error = "HTTP %s" % status
                continue
            if status in (401, 403):
                self.last_error = "jeton refusé (HTTP %s)" % status
                log.error("Le site refuse le jeton (HTTP %s). Vérifiez api.token ; les mesures restent en file.",
                          status)
                delay = BACKOFF_MAX
            else:
                self.last_error = ("HTTP %s" % status) if status else text[:120]
                delay = self.backoff
                self.backoff = min(self.backoff * 2, BACKOFF_MAX)
                log.warning("Envoi impossible (%s), nouvel essai dans %d s (%d lot(s) en attente).",
                            self.last_error, delay, self.spool.pending())
            self.spool.retry_later(batch_id, now + delay)

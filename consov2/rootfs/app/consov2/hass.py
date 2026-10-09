"""Lecture d'entités Home Assistant via l'API du Supervisor (Netatmo, sondes…)."""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

from .model import Measurement

log = logging.getLogger("hass")

SUPERVISOR = "http://supervisor"


def supervisor_get(path: str, timeout: float = 10.0) -> Optional[dict]:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    req = urllib.request.Request(SUPERVISOR + path, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def mqtt_service() -> Optional[dict]:
    """Identifiants du broker MQTT fournis par le Supervisor (add-on Mosquitto)."""
    try:
        data = supervisor_get("/services/mqtt")
    except Exception as exc:
        log.debug("Service MQTT du Supervisor indisponible : %s", exc)
        return None
    return (data or {}).get("data") or None


class EntityPoller(threading.Thread):
    """Interroge chaque entité toutes les `interval` secondes et transmet les valeurs numériques."""

    def __init__(self, entities: List[dict], interval: int, on_value: Callable[[Measurement], None],
                 stop: threading.Event, base_url: str = SUPERVISOR + "/core/api"):
        super().__init__(name="hass", daemon=True)
        self.entities, self.interval, self.on_value, self.stop = entities, interval, on_value, stop
        self.base_url = base_url.rstrip("/")
        self._warned: Dict[str, str] = {}

    def read(self, entity_id: str) -> Optional[dict]:
        req = urllib.request.Request(self.base_url + "/states/" + entity_id, headers={
            "Authorization": "Bearer " + os.environ.get("SUPERVISOR_TOKEN", ""),
            "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _warn_once(self, entity_id: str, message: str):
        if self._warned.get(entity_id) != message:
            log.warning("%s : %s", entity_id, message)
            self._warned[entity_id] = message

    def poll(self):
        for ent in self.entities:
            entity_id = ent.get("entity_id", "")
            try:
                state = self.read(entity_id)
            except urllib.error.HTTPError as exc:
                self._warn_once(entity_id, "HTTP %s (entité inconnue ?)" % exc.code)
                continue
            except Exception as exc:
                self._warn_once(entity_id, str(exc))
                continue
            try:
                value = float(state.get("state"))
            except (TypeError, ValueError):
                continue  # « unavailable », « unknown »…
            self._warned.pop(entity_id, None)
            unit = ent.get("unit") or (state.get("attributes") or {}).get("unit_of_measurement") or ""
            self.on_value(Measurement(ent["metric"], value, unit, int(time.time()),
                                      ent.get("source") or "homeassistant"))

    def run(self):
        while not self.stop.is_set():
            self.poll()
            self.stop.wait(self.interval)

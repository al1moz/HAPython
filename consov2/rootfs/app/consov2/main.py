"""Point d'entrée de l'add-on ConsoV2 : collecteurs -> agrégation -> site, InfluxDB et MQTT."""
import json
import logging
import os
import signal
import sys
import threading
import time
from typing import List

from . import __version__, arkteos, hass, legacy
from .aggregator import Aggregator
from .api import Sender
from .model import Measurement, MetricInfo
from .spool import Spool

log = logging.getLogger("consov2")

OPTIONS = os.environ.get("CONSOV2_OPTIONS", "/data/options.json")
DATA_DIR = os.environ.get("CONSOV2_DATA", "/data")
LEVELS = {"trace": logging.DEBUG, "debug": logging.DEBUG, "info": logging.INFO, "notice": logging.INFO,
          "warning": logging.WARNING, "error": logging.ERROR, "fatal": logging.CRITICAL}

# Étiquettes InfluxDB des anciens add-ons, pour ne pas casser Grafana.
TAGS_LINKY = {"host": "raspberry", "region": "linky"}
TAGS_SHELLY = {"host": "raspberry", "region": "shellyem"}
TAGS_ARKTEOS = {"host": "elitedesk", "region": "pac"}

# Champs Linky écrits en texte par l'ancien add-on teleinfo ; tous les autres en entier (0 si illisible).
# InfluxDB refuse d'écrire un champ avec un autre type que celui déjà enregistré.
INFLUX_LINKY_TEXT = {"DATE", "NGTF", "LTARF", "MSG1", "NJOURF", "NJOURF+1", "PJOURF", "PJOURF+1",
                     "EASD02", "STGE", "RELAIS"}


class Outage:
    """Journal d'une source lue à intervalle régulier, sans avertir à chaque échec isolé.

    Avertit au premier échec si la source n'a encore jamais répondu (erreur de configuration),
    puis seulement après `after` secondes sans aucune lecture réussie, et de nouveau toutes
    les `every` secondes tant que ça dure. Signale le retour de la source.
    """

    def __init__(self, name: str, after: float = 900, every: float = 3600, clock=time.monotonic):
        self.name, self.after, self.every, self.clock = name, after, every, clock
        self.last_ok = None
        self.since = clock()
        self.warned_at = None

    def success(self):
        if self.warned_at is not None:
            log.info("%s : de nouveau joignable.", self.name)
        self.last_ok = self.clock()
        self.warned_at = None

    def failure(self, detail) -> bool:
        """Note un échec ; renvoie True si un avertissement a été écrit."""
        now = self.clock()
        silent_for = now - (self.since if self.last_ok is None else self.last_ok)
        if self.last_ok is None and self.warned_at is None:
            log.warning("%s : %s (nouvel essai à chaque intervalle)", self.name, detail)
        elif silent_for >= self.after and (self.warned_at is None or now - self.warned_at >= self.every):
            log.warning("%s : aucune lecture réussie depuis %d min (%s)", self.name, silent_for // 60, detail)
        else:
            log.debug("%s : %s", self.name, detail)
            return False
        self.warned_at = now
        return True


def influx_linky_value(name: str, value):
    """Type d'un champ Linky dans InfluxDB, identique à l'ancien add-on teleinfo."""
    if name == "COSPHI":
        return float(value)
    if name in INFLUX_LINKY_TEXT:
        return str(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

STATUS = {
    "addon_pending": MetricInfo("File d'attente vers le site", None, "measurement", {"icon": "mdi:tray-full"}),
    "addon_last_send": MetricInfo("Dernier envoi au site", "timestamp", None),
    "addon_error": MetricInfo("Dernière erreur d'envoi", None, None, {"icon": "mdi:alert-circle-outline"}),
    "linky_frames": MetricInfo("Trames Linky reçues", None, "total_increasing", {"icon": "mdi:counter"}),
}


def shelly_influx_name(topic: str, metric: str) -> str:
    """shellies/shellyem1/emeter/0/power -> SHELLYEM1_0, comme l'ancien getMqtt."""
    parts = topic.split("/")
    return (parts[1] + "_" + parts[3]).upper() if len(parts) >= 5 and parts[2] == "emeter" else metric


class App:
    def __init__(self, opts: dict):
        self.opts = opts
        self.stop = threading.Event()
        self.flush_now = threading.Event()
        self.agg = Aggregator()
        self.spool = Spool(os.path.join(DATA_DIR, "consov2.sqlite"))
        self.sender_wake = threading.Event()
        self.sender = None
        self.influx = None
        self.mqtt = None
        self.linky = None
        api = opts.get("api") or {}
        self.interval = max(60, int(api.get("interval_minutes", 5)) * 60)

    # ---------- démarrage ----------
    def start(self):
        o = self.opts
        api = o.get("api") or {}
        if api.get("url") and api.get("token"):
            self.sender = Sender(api["url"], api["token"], self.spool, self.stop, self.sender_wake)
            self.sender.start()
            if self.spool.pending():
                log.info("%d lot(s) restés en file : envoi au site.", self.spool.pending())
        else:
            log.warning("api.url ou api.token vide : les mesures sont gardées en file jusqu'à leur configuration.")

        ifx = o.get("influxdb") or {}
        if ifx.get("enabled"):
            from .influx import InfluxWriter
            self.influx = InfluxWriter(ifx.get("url", ""), ifx.get("token", ""), ifx.get("org", ""), self.stop)
            self.influx.start()

        self._start_mqtt()

        ecs = o.get("ecs") or {}
        if ecs.get("metric"):
            self.agg.watch(ecs["metric"], float(ecs.get("threshold_w", 500)), self._on_ecs)

        lk = o.get("linky") or {}
        if lk.get("enabled") and lk.get("port"):
            from .tic import LinkyReader
            self.linky = LinkyReader(lk["port"], self._on_linky, self.stop)
            self.linky.start()

        ark = o.get("arkteos") or {}
        if ark.get("enabled") and ark.get("host"):
            threading.Thread(target=self._arkteos_loop, name="arkteos", daemon=True).start()

        ha = o.get("homeassistant") or {}
        if ha.get("enabled") and ha.get("entities"):
            hass.EntityPoller(ha["entities"], max(15, int(ha.get("interval_seconds", 60))), self.agg.add, self.stop,
                              os.environ.get("CONSOV2_HA_API", hass.SUPERVISOR + "/core/api")).start()

        threading.Thread(target=self._live_loop, name="live", daemon=True).start()

    def _start_mqtt(self):
        o = self.opts
        m = o.get("mqtt") or {}
        sh = o.get("shelly") or {}
        ark = o.get("arkteos") or {}
        need = m.get("discovery", True) or sh.get("enabled") or ark.get("legacy_mqtt_topics")
        if not need:
            return
        host, port, user, pwd = m.get("host"), int(m.get("port") or 1883), m.get("username", ""), m.get("password", "")
        if not host:
            svc = hass.mqtt_service()
            if svc:
                host, port, user, pwd = svc.get("host"), int(svc.get("port", 1883)), svc.get("username", ""), svc.get("password", "")
        if not host:
            log.warning("Aucun broker MQTT (ni mqtt.host, ni Mosquitto) : Shelly et capteurs HA désactivés.")
            return
        from .mqtt import Mqtt
        self.mqtt = Mqtt(host, port, user, pwd, bool(m.get("discovery", True)))
        if sh.get("enabled"):
            for ch in sh.get("channels") or []:
                if ch.get("topic") and ch.get("metric"):
                    self.mqtt.subscribe(ch["topic"], self._shelly_handler(ch["topic"], ch["metric"]))
        self.mqtt.start()

    # ---------- collecteurs ----------
    def _on_linky(self, fields: dict, ts: int):
        lk = self.opts.get("linky") or {}
        index_field = lk.get("index_field") or "EASF01"
        if isinstance(fields.get(index_field), int):
            self.agg.add(Measurement("elec_index", fields[index_field], "Wh", ts, "linky", "counter"))
        if isinstance(fields.get("SINSTS"), int):
            self.agg.add(Measurement("elec_power", fields["SINSTS"], "VA", ts, "linky"))
        if isinstance(fields.get("URMS1"), int):
            self.agg.add(Measurement("elec_voltage", fields["URMS1"], "V", ts, "linky"))
        if self.influx:
            bucket = (self.opts.get("influxdb") or {}).get("bucket_linky") or "teleinfo2"
            irms, urms, sinsts = fields.get("IRMS1"), fields.get("URMS1"), fields.get("SINSTS")
            if all(isinstance(v, int) for v in (irms, urms, sinsts)) and irms > 0 and urms > 0:
                fields = dict(fields, COSPHI=sinsts / (irms * urms))
            for name, value in fields.items():
                self.influx.write(bucket, name, TAGS_LINKY, influx_linky_value(name, value), ts)

    def _shelly_handler(self, topic: str, metric: str):
        influx_name = shelly_influx_name(topic, metric)

        def handle(_topic: str, payload: bytes):
            value = abs(float(payload.decode("ascii", "replace").strip()))
            ts = int(time.time())
            self.agg.add(Measurement(metric, value, "W", ts, "shelly"))
            if self.influx:
                bucket = (self.opts.get("influxdb") or {}).get("bucket_shelly") or "teleinfo2"
                self.influx.write(bucket, influx_name, TAGS_SHELLY, value, ts)
        return handle

    def _arkteos_loop(self):
        ark = self.opts["arkteos"]
        host, port = ark["host"], int(ark.get("port") or 9641)
        every = max(30, int(ark.get("interval_seconds") or 300))
        # Délai d'une lecture (connexion comprise), toujours plus court que l'intervalle.
        budget = max(10, min(int(ark.get("timeout_seconds") or 120), every - 15))
        outage = Outage("PAC Arkteos (%s:%s)" % (host, port))
        while not self.stop.is_set():
            try:
                values = arkteos.read_once(host, port, timeout=budget, stop=self.stop)
            except OSError as exc:
                values = None
                outage.failure(exc)
            if values:
                outage.success()
                ts = int(time.time())
                for name, value in values.items():
                    self.agg.add(Measurement("pac_" + name, value, arkteos.UNITS[name], ts, "arkteos"))
                    if self.influx:
                        bucket = (self.opts.get("influxdb") or {}).get("bucket_arkteos") or "arkteos"
                        self.influx.write(bucket, name, TAGS_ARKTEOS, float(value), ts)
                    if self.mqtt and ark.get("legacy_mqtt_topics"):
                        self.mqtt.publish("arkteos/reg3/" + name, str(value))
            # Lecture suivante calée sur l'horloge, 10 s après le début d'une période : avec 300 s,
            # une lecture par période d'envoi de 5 min, même si la connexion a pris du temps.
            now = time.time()
            self.stop.wait((now // every + 1) * every + 10 - now)

    def _on_ecs(self, above: bool):
        log.info("Appoint ECS %s : envoi immédiat.", "en marche" if above else "arrêté")
        self.flush_now.set()

    # ---------- sorties ----------
    def _live_loop(self):
        """Publie les dernières valeurs vers Home Assistant toutes les 30 s."""
        while not self.stop.wait(30):
            if not self.mqtt:
                continue
            for metric, m in self.agg.snapshot().items():
                self.mqtt.publish_metric(metric, m.value, m.unit)
            self._publish_status()

    def _publish_status(self):
        if not self.mqtt:
            return
        values = {"addon_pending": self.spool.pending()}
        if self.sender:
            if self.sender.last_ok:
                values["addon_last_send"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.sender.last_ok))
            values["addon_error"] = self.sender.last_error or "aucune"
        if self.linky:
            values["linky_frames"] = self.linky.frames
        from .mqtt import BASE
        for key, value in values.items():
            self.mqtt.announce(key, STATUS[key], None, "%s/state/%s" % (BASE, key))
            self.mqtt.publish("%s/state/%s" % (BASE, key), str(value), retain=True)

    def flush(self, ts: int, regular: bool = True):
        batch: List[Measurement] = self.agg.flush(ts)
        if not batch:
            log.debug("Rien à envoyer pour cette période.")
            return
        self.spool.push(batch)
        self.sender_wake.set()
        log.debug("%d mesure(s) mises en file (%s).", len(batch), time.strftime("%H:%M:%S", time.localtime(ts)))
        api = self.opts.get("api") or {}
        # L'ancien site attend une ligne par période : pas d'envoi pour un envoi anticipé (ECS) ou à l'arrêt.
        if api.get("legacy_receiver_url") and regular:
            circuits = [ch.get("metric") for ch in (self.opts.get("shelly") or {}).get("channels") or []]
            threading.Thread(target=legacy.send, args=(api["legacy_receiver_url"], batch, "elec_index", circuits),
                             daemon=True).start()

    def run(self):
        self.start()
        while not self.stop.is_set():
            now = time.time()
            boundary = (int(now) // self.interval + 1) * self.interval
            triggered = self.flush_now.wait(timeout=max(0.0, boundary - now))
            if self.stop.is_set():
                break
            if triggered:
                self.flush_now.clear()
                self.flush(int(time.time()), regular=False)
            else:
                self.flush(boundary)
        self.flush(int(time.time()), regular=False)  # période en cours, pour ne rien perdre à l'arrêt
        if self.mqtt:
            self.mqtt.stop()
        pending = self.spool.pending()
        if pending:
            log.info("Arrêt terminé, %d lot(s) en file : envoyés au prochain démarrage.", pending)
        else:
            log.info("Arrêt terminé.")


def load_options(path: str = OPTIONS) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    opts = load_options()
    logging.basicConfig(level=LEVELS.get(str(opts.get("log_level", "info")).lower(), logging.INFO),
                        format="%(asctime)s %(levelname)s [%(name)s] %(message)s", stream=sys.stdout)
    log.info("ConsoV2 add-on %s", __version__)
    app = App(opts)

    def on_signal(signum, _frame):
        log.info("Signal %s reçu, arrêt.", signum)
        app.stop.set()
        app.flush_now.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    app.run()


if __name__ == "__main__":
    main()

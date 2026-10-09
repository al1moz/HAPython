"""MQTT : réception des Shelly EM et publication vers Home Assistant (découverte automatique).

Compatible paho-mqtt 1.x et 2.x (Debian fournit l'une ou l'autre selon la version).
"""
import json
import logging
import threading
from typing import Callable, Dict, Optional

import paho.mqtt.client as paho

from . import __version__
from .model import KNOWN, MetricInfo

log = logging.getLogger("mqtt")

BASE = "consov2"
STATUS_TOPIC = BASE + "/status"
DEVICE = {"identifiers": ["consov2"], "name": "ConsoV2", "manufacturer": "ConsoV2",
          "model": "Add-on Home Assistant", "sw_version": __version__}


def _new_client(client_id: str):
    try:  # paho 2.x
        return paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho 1.x
        return paho.Client(client_id=client_id)


class Mqtt:
    def __init__(self, host: str, port: int, username: str, password: str, discovery: bool,
                 discovery_prefix: str = "homeassistant"):
        self.discovery, self.prefix = discovery, discovery_prefix
        self.connected = threading.Event()
        self._subs: Dict[str, Callable[[str, bytes], None]] = {}
        self._announced = set()
        self.client = _new_client("consov2-addon")
        if username:
            self.client.username_pw_set(username, password or None)
        self.client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=5, max_delay=120)
        self.host, self.port = host, port

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def stop(self):
        try:
            self.client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish(3)
        except Exception:
            pass
        self.client.loop_stop()
        self.client.disconnect()

    # Les signatures des rappels changent entre paho 1 et 2 : on lit le code de retour en position 3.
    def _on_connect(self, client, userdata, flags, rc, *args):
        code = getattr(rc, "value", rc)
        if code != 0:
            log.error("Connexion MQTT refusée (%s)", rc)
            return
        log.info("Connecté au broker MQTT %s:%s", self.host, self.port)
        self._announced.clear()
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        for topic in self._subs:
            client.subscribe(topic, qos=0)
        self.connected.set()

    def _on_disconnect(self, client, userdata, *args):
        self.connected.clear()
        log.warning("Déconnecté du broker MQTT, reconnexion automatique.")

    def _on_message(self, client, userdata, msg):
        handler = self._subs.get(msg.topic)
        if handler is None:
            for pattern, h in self._subs.items():
                if paho.topic_matches_sub(pattern, msg.topic):
                    handler = h
                    break
        if handler is not None:
            try:
                handler(msg.topic, msg.payload)
            except Exception:
                log.exception("Message MQTT illisible sur %s", msg.topic)

    def subscribe(self, topic: str, handler: Callable[[str, bytes], None]):
        self._subs[topic] = handler
        if self.connected.is_set():
            self.client.subscribe(topic, qos=0)

    def publish(self, topic: str, payload, retain: bool = False):
        if not isinstance(payload, (str, bytes)):
            payload = json.dumps(payload, ensure_ascii=False)
        self.client.publish(topic, payload, qos=0, retain=retain)

    # ---------- Découverte Home Assistant ----------
    def announce(self, key: str, info: MetricInfo, unit: Optional[str], state_topic: str):
        if not self.discovery or key in self._announced or not self.connected.is_set():
            return
        config = {
            "name": info.label,
            "unique_id": "consov2_" + key,
            "object_id": "consov2_" + key,
            "state_topic": state_topic,
            "availability_topic": STATUS_TOPIC,
            "device": DEVICE,
        }
        if unit:
            config["unit_of_measurement"] = unit
        if info.device_class:
            config["device_class"] = info.device_class
        if info.state_class:
            config["state_class"] = info.state_class
        config.update({k: v for k, v in info.extra.items() if k != "component"})
        component = info.extra.get("component", "sensor")
        self.publish("%s/%s/consov2/%s/config" % (self.prefix, component, key), config, retain=True)
        self._announced.add(key)

    def publish_metric(self, metric: str, value, unit: Optional[str]):
        info = KNOWN.get(metric) or MetricInfo(metric.replace("_", " ").capitalize())
        topic = "%s/state/%s" % (BASE, metric)
        self.announce(metric, info, unit, topic)
        self.publish(topic, str(value), retain=True)

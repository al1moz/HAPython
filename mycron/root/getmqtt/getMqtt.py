#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Version 0.2 - migration vers InfluxDB 2.x

import os
import sys
import time
import logging
import random
from datetime import datetime, timezone

from paho.mqtt import client as mqtt_client
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


# ============================================================
# CONFIGURATION
# ============================================================

broker = '192.168.252.4'
port = 1883

# generate client ID with pub prefix randomly
client_id = f'python-mqtt-{random.randint(0, 100)}'
username = 'mqtt'
password = os.environ.get('PASSWORDMQTT')
LOGLEVEL = os.environ.get('LOGLEVEL')

# InfluxDB 2.x - mêmes variables d'environnement que les autres scripts
INFLUX_ORG = os.environ.get("INFLUX_ORG")
INFLUX_URL = os.environ.get("URLDB")
DB_TOKEN = os.environ.get("TOKENDB")

# Le "bucket" remplace la "database" InfluxDB 1.x.
# Valeur par défaut identique à l'ancienne DB_DATABASE = 'teleinfo2'.
BUCKET = os.environ.get("INFLUX_BUCKET", "teleinfo2")


# ============================================================
# LOGGING
# ============================================================

if LOGLEVEL == 'info':
    logging.basicConfig(level=logging.INFO)
elif LOGLEVEL == 'debug':
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.WARNING)

if password is None:
    logging.error('No password MQTT defined')
    sys.exit(1)

if not DB_TOKEN:
    logging.error("La variable TOKENDB n'est pas définie.")
    sys.exit(1)

if not INFLUX_URL:
    logging.error("La variable URLDB n'est pas définie.")
    sys.exit(1)

if not INFLUX_ORG:
    logging.error("La variable INFLUX_ORG n'est pas définie.")
    sys.exit(1)


# ============================================================
# CLIENT INFLUXDB 2.x
# ============================================================

CLIENT = InfluxDBClient(
    url=INFLUX_URL,
    token=DB_TOKEN,
    org=INFLUX_ORG
)

WRITE_API = CLIENT.write_api(write_options=SYNCHRONOUS)


def test_influx_connection():
    """Teste la connexion à InfluxDB et vérifie l'existence du bucket."""
    try:
        health = CLIENT.health()

        if health.status != "pass":
            logging.error("InfluxDB indisponible : %s", health.message)
            return False

        logging.info("InfluxDB connecté : version %s", health.version)

        buckets = CLIENT.buckets_api().find_buckets().buckets
        bucket_names = [bucket.name for bucket in buckets]

        if BUCKET not in bucket_names:
            logging.error("Le bucket '%s' n'existe pas.", BUCKET)
            logging.error(
                "Crée le bucket dans InfluxDB avant de lancer le script."
            )
            return False

        logging.info("Bucket '%s' trouvé.", BUCKET)
        return True

    except Exception:
        logging.exception("Impossible de contacter InfluxDB.")
        return False


# Attente active de la connexion InfluxDB.
CONNECTED = False
while not CONNECTED:
    if test_influx_connection():
        CONNECTED = True
    else:
        logging.warning(
            'InfluxDB is not reachable. Waiting 5 seconds to retry.'
        )
        time.sleep(5)


# ============================================================
# MQTT
# ============================================================

def connect_mqtt() -> mqtt_client:
    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logging.info("Connected to MQTT Broker!")
        else:
            logging.warning("Failed to connect, return code %s\n", reason_code)

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2,
        client_id
    )
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.connect(broker, port)
    return client


def subscribe(client: mqtt_client):
    def on_message(client, userdata, msg):
        trame = dict()
        topicArr = msg.topic.split('/')
        keyTopic = topicArr[1] + '_' + topicArr[3]
        trame[keyTopic.upper()] = float(msg.payload.decode())
        trame["timestamp"] = int(time.time())
        add_measures(trame)

    client.subscribe('shellies/shellyem1/emeter/0/power')
    client.subscribe('shellies/shellyem1/emeter/1/power')
    client.subscribe('shellies/shellyem2/emeter/0/power')
    client.subscribe('shellies/shellyem2/emeter/1/power')
    client.subscribe('shellies/shellyem3/emeter/0/power')
    client.subscribe('shellies/shellyem3/emeter/1/power')
    client.subscribe('shellies/shellyem4/emeter/0/power')
    client.subscribe('shellies/shellyem4/emeter/1/power')
    client.on_message = on_message


def run():
    client = connect_mqtt()
    subscribe(client)
    client.loop_forever()


# ============================================================
# ENVOI VERS INFLUXDB 2.x
# ============================================================

def add_measures(measures):
    """Envoie les mesures dans InfluxDB (format Point InfluxDB 2.x)."""

    points = []

    for measure, value in measures.items():

        if measure == "timestamp":
            continue

        point = (
            Point(str(measure))
            .tag("host", "raspberry")
            .tag("region", "shellyem")
            .field("value", abs(float(value)))
            .time(datetime.now(timezone.utc), WritePrecision.S)
        )

        points.append(point)

        logging.debug(
            "InfluxDB : %s = %s",
            measure,
            value
        )

    if not points:
        logging.warning("Aucun point à envoyer.")
        return

    try:
        WRITE_API.write(
            bucket=BUCKET,
            org=INFLUX_ORG,
            record=points
        )

        logging.debug("%d mesures envoyées à InfluxDB.", len(points))

    except Exception:
        logging.exception("Erreur lors de l'écriture dans InfluxDB.")


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

if __name__ == '__main__':

    try:
        run()

    except KeyboardInterrupt:
        logging.info("Arrêt demandé.")

    except Exception:
        logging.exception("Erreur fatale.")

    finally:
        try:
            WRITE_API.close()
            CLIENT.close()
        except Exception:
            pass
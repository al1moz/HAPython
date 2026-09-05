#!/usr/bin/python
# -*- coding: utf-8 -*-
# Version 0.2 - migration vers InfluxDB 2.x
# https://github.com/cyrilpawelko/arkteos_reg3

import socket
import time
import os
import random
import logging
import sys
from datetime import datetime, timezone

from paho.mqtt import client as mqtt_client
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


# ============================================================
# CONFIGURATION
# ============================================================

HOST = os.environ.get('ARKHOST')
PORT = 9641

MQTT_BASE_TOPIC = "arkteos/reg3/"   # ne pas oublier le slash final
MQTT_HOST = '192.168.252.4'
MQTT_PORT = 1883
USERNAME = 'mqtt'
PASSWORD = os.environ.get('PASSWORDMQTT')
LOGLEVEL = os.environ.get('LOGLEVEL')

client_id = f'python-mqtt-{random.randint(0, 100)}'

# InfluxDB 2.x - mêmes variables d'environnement que teleinfo.py
INFLUX_ORG = os.environ.get("INFLUX_ORG")
INFLUX_URL = os.environ.get("URLDB")
DB_TOKEN = os.environ.get("TOKENDB")

# Le "bucket" remplace la "database" InfluxDB 1.x.
# Valeur par défaut identique à l'ancienne DB_DATABASE = 'arkteos'.
BUCKET = os.environ.get("INFLUX_BUCKET", "arkteos")


# ============================================================
# LOGGING
# ============================================================

if LOGLEVEL == 'info':
    logging.basicConfig(level=logging.INFO)
elif LOGLEVEL == 'debug':
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.WARNING)

if PASSWORD is None:
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
# MQTT
# ============================================================

def connect_mqtt() -> mqtt_client:
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logging.info("Connected to MQTT Broker!")
        else:
            logging.warning("Failed to connect, return code %d\n", rc)

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION1,
        client_id
    )
    client.username_pw_set(USERNAME, PASSWORD)
    client.on_connect = on_connect
    client.connect(MQTT_HOST, MQTT_PORT)
    return client


mqttclient = connect_mqtt()
logging.info("Arkteos MQTT connection")


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
# Remplace l'ancienne boucle create_database()/switch_database()
# de l'API InfluxDB 1.x, qui n'existe plus en v2 (les buckets se
# créent depuis l'UI, la CLI ou l'API buckets_api()).
CONNECTEDDB = False
while not CONNECTEDDB:
    if test_influx_connection():
        CONNECTEDDB = True
    else:
        logging.warning(
            'InfluxDB is not reachable. Waiting 5 seconds to retry.'
        )
        time.sleep(5)


# ============================================================
# DECODEUR ARKTEOS (inchangé)
# ============================================================

decoder = [
    {'stream': 227, 'name': 'primaire_pression', 'descr': 'Pression eau primaire', 'byte1': 62, 'weight1': 1, 'byte2': 0, 'weight2': 0, 'divider': 10},
    {'stream': 227, 'name': 'externe_pression', 'descr': 'Pression eau extérieure', 'byte1': 46, 'weight1': 1, 'byte2': 0, 'weight2': 0, 'divider': 10},
    {'stream': 227, 'name': 'primaire_temp_eau_aller', 'descr': 'Température eau primaire aller', 'byte1': 54, 'weight1': 1, 'byte2': 55, 'weight2': 256, 'divider': 10},
    {'stream': 227, 'name': 'primaire_temp_eau_retour', 'descr': 'Température eau primaire retour', 'byte1': 56, 'weight1': 1, 'byte2': 57, 'weight2': 256, 'divider': 10},
    {'stream': 163, 'name': 'exterieur_temp', 'descr': 'Température extérieure', 'byte1': 24, 'weight1': 1, 'byte2': 25, 'weight2': 256, 'divider': 10},
    {'stream': 227, 'name': 'zone1_temp_interieur', 'descr': 'Température intérieur zone 1', 'byte1': 68, 'weight1': 1, 'byte2': 69, 'weight2': 256, 'divider': 10},
    {'stream': 227, 'name': 'zone2_temp_interieur', 'descr': 'Température intérieur zone 2', 'byte1': 88, 'weight1': 1, 'byte2': 89, 'weight2': 256, 'divider': 10},
    {'stream': 227, 'name': 'zone1_consigne', 'descr': 'Consigne intérieure zone 1', 'byte1': 70, 'weight1': 1, 'byte2': 71, 'weight2': 256, 'divider': 10},
    {'stream': 227, 'name': 'zone2_consigne', 'descr': 'Consigne intérieure zone 2', 'byte1': 90, 'weight1': 1, 'byte2': 91, 'weight2': 256, 'divider': 10},
    {'stream': 227, 'name': 'ecs_temp_eau_milieu', 'descr': 'Température ballon ECS milieu', 'byte1': 108, 'weight1': 1, 'byte2': 109, 'weight2': 256, 'divider': 10},
    {'stream': 227, 'name': 'ecs_temp_eau_bas', 'descr': 'Température ballon ECS bas', 'byte1': 110, 'weight1': 1, 'byte2': 111, 'weight2': 256, 'divider': 10},
]


# ============================================================
# ENVOI VERS INFLUXDB 2.x
# ============================================================

def add_measures(measures):
    """Envoie les mesures dans InfluxDB (format Point InfluxDB 2.x)."""

    points = []

    for measure, value in measures.items():

        point = (
            Point(str(measure))
            .tag("host", "elitedesk")
            .tag("region", "pac")
            .field("value", float(value))
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
# LECTURE SOCKET ARKTEOS
# ============================================================

def main():
    stream_received = {
        163: False,
        227: False
    }

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    CONNECTED = False
    while not CONNECTED:  # Attente de la connexion, parfois 1-2 minutes
        try:
            client.connect((HOST, PORT))
            CONNECTED = True
        except socket.error as e:
            logging.warning("Connection failed (%s), waiting" % e)
            time.sleep(5)
    logging.info(
        'Arkteos Connection to ' + HOST + ':' + str(PORT) + ' successfull.'
    )

    # Boucle sur la réponse jusqu'à recevoir les deux flux
    while not (stream_received[163] and stream_received[227]):
        data_lenght = 0
        try:
            data = client.recv(1024)
            data_lenght = len(data)
        except KeyboardInterrupt:
            pass

        data_lenght = len(data)
        stream_received[data_lenght] = True

        # Collecte des données
        trame = dict()
        for item in (x for x in decoder if x["stream"] == data_lenght):
            if item['byte2'] == 0:
                item_value = (data[item['byte1']] * item['weight1']) / item['divider']
            else:
                item_value = (
                    data[item['byte1']] * item['weight1']
                    + data[item['byte2']] * item['weight2']
                ) / item['divider']

            logging.debug(
                datetime.utcnow().strftime("%H:%M:%S") + ':'
                + MQTT_BASE_TOPIC + item['name'] + ':%.1f',
                item_value
            )

            mqttclient.publish(MQTT_BASE_TOPIC + item['name'], item_value)
            trame[item['name']] = item_value

        trame["timestamp"] = int(time.time())
        add_measures(trame)

    client.shutdown(socket.SHUT_RDWR)
    client.close()
    logging.info('Arkteos Connection: end')


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

if __name__ == '__main__':

    try:
        while True:
            main()
            time.sleep(300)

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
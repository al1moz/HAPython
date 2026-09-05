#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Version 0.2 - migration vers InfluxDB 2.x (requêtes Flux)

import os
import sys
import time
import logging
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

from influxdb_client import InfluxDBClient

print("Put2Web starting..")


# ============================================================
# CONFIGURATION
# ============================================================

LOGLEVEL = os.environ.get('LOGLEVEL')

# InfluxDB 2.x - mêmes variables d'environnement que les autres scripts
INFLUX_ORG = os.environ.get("INFLUX_ORG")
INFLUX_URL = os.environ.get("URLDB")
DB_TOKEN = os.environ.get("TOKENDB")

# Le "bucket" remplace la "database" InfluxDB 1.x.
# Valeur par défaut identique à l'ancienne DB_DATABASE = 'teleinfo2'.
BUCKET = os.environ.get("INFLUX_BUCKET", "teleinfo2")

URL_RECEIVER = 'https://conso.ctrl.ovh/bin/receiver.php'


# ============================================================
# LOGGING
# ============================================================

if LOGLEVEL == 'info':
    logging.basicConfig(level=logging.INFO)
elif LOGLEVEL == 'debug':
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.WARNING)

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

QUERY_API = CLIENT.query_api()


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
# REQUETES FLUX (remplacent les requêtes InfluxQL)
# ============================================================

def get_last_value(measurement, range_start="-30d"):
    """Équivalent Flux de :
    SELECT "value" FROM "<measurement>" ORDER BY time DESC LIMIT 1
    """

    query = f'''
    from(bucket: "{BUCKET}")
      |> range(start: {range_start})
      |> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "value")
      |> last()
    '''

    try:
        tables = QUERY_API.query(query, org=INFLUX_ORG)

        for table in tables:
            for record in table.records:
                return record.get_value()

    except Exception:
        logging.exception(
            "Erreur lors de la requête Flux sur '%s'",
            measurement
        )

    return None


def get_mean_value(measurement):
    """Équivalent Flux de :
    SELECT mean(value) FROM "<measurement>"
    WHERE time >= now()-6m AND time <= now()-1m
    """

    query = f'''
    from(bucket: "{BUCKET}")
      |> range(start: -6m, stop: -1m)
      |> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "value")
      |> mean()
    '''

    try:
        tables = QUERY_API.query(query, org=INFLUX_ORG)

        for table in tables:
            for record in table.records:
                return record.get_value()

    except Exception:
        logging.exception(
            "Erreur lors de la requête Flux sur '%s'",
            measurement
        )

    return None


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():

    # --------------------------------------------------------
    # Conso totale (EASF01 / 1000)
    # --------------------------------------------------------

    cindex_raw = get_last_value("EASF01")
    cindex = str(cindex_raw / 1000) if cindex_raw is not None else '0'

    # --------------------------------------------------------
    # Moyennes des 8 canaux Shelly EM
    # --------------------------------------------------------

    shelly_measurements = [
        "SHELLYEM1_0",
        "SHELLYEM1_1",
        "SHELLYEM2_0",
        "SHELLYEM2_1",
        "SHELLYEM3_0",
        "SHELLYEM3_1",
        "SHELLYEM4_0",
        "SHELLYEM4_1",
    ]

    valeurs = []

    for measurement in shelly_measurements:
        mean_value = get_mean_value(measurement)
        valeurs.append(
            str(round(mean_value)) if mean_value is not None else '0'
        )

    q1, q2, q3, q4, q5, q6, q7, q8 = valeurs

    # --------------------------------------------------------
    # Envoi vers le site distant
    # --------------------------------------------------------

    try:
        params = (
            f"cindex={cindex}&q1={q1}&q2={q2}&q3={q3}&q4={q4}"
            f"&q5={q5}&q6={q6}&q7={q7}&q8={q8}"
        )

        print(params)

        req = urlopen(f"{URL_RECEIVER}?{params}", data=None)

        print(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ' : ',
            req.read()
        )

    except HTTPError as e:
        print('Error code: ', e.code)

    except URLError as e:
        print('Reason: ', e.reason)


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
            CLIENT.close()
        except Exception:
            pass
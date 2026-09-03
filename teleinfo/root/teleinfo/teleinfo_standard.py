#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send teleinfo standard to InfluxDB 2.x."""

import logging
import os
import pathlib
import sys
import time
from configparser import ConfigParser
from datetime import datetime, timezone

import serial
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


# ============================================================
# Configuration
# ============================================================

MODE = "DEBUG"

TELEINFO_INI = "/teleinfo/teleinfo.ini"
KEYS_FILE = "/teleinfo/liste_champs_mode_standard.txt"
DICO_FILE = "/teleinfo/liste_fabricants_linky.txt"

# Définir dans les variables d'environnement.
ORG = "hataden"
INFLUX_URL = os.environ.get("URLDB")
DB_TOKEN = os.environ.get("TOKENDB")

if not DB_TOKEN:
    print("Erreur : la variable d'environnement TOKENDB est absente.")
    sys.exit(1)


# ============================================================
# Vérification configuration
# ============================================================

if not pathlib.Path(TELEINFO_INI).exists():
    print(f"Ini {TELEINFO_INI} not found!")
    sys.exit(1)


CONFIG = ConfigParser()
CONFIG.read(TELEINFO_INI)

if "teleinfo" not in CONFIG:
    print("Erreur : section [teleinfo] absente du fichier ini.")
    sys.exit(1)

TELEINFO_DATA = CONFIG["teleinfo"]

SERIALPORT = os.environ.get(
    "USBPORT",
    TELEINFO_DATA.get("serial_port", "")
)

# Avec InfluxDB 2.x, DB_DATABASE correspond en pratique
# au nom du bucket.
BUCKET = TELEINFO_DATA.get("influxdb_database", "")

if not SERIALPORT:
    print("Erreur : port série non configuré.")
    sys.exit(1)

if not BUCKET:
    print("Erreur : influxdb_database non configuré.")
    sys.exit(1)


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=getattr(logging, MODE, logging.DEBUG),
    format="%(asctime)s %(levelname)s %(message)s"
)

logging.info("Teleinfo starting...")
logging.info("Port série : %s", SERIALPORT)
logging.info("InfluxDB : %s", INFLUX_URL)
logging.info("Organisation : %s", ORG)
logging.info("Bucket : %s", BUCKET)


# ============================================================
# Client InfluxDB 2.x
# ============================================================

CLIENT = InfluxDBClient(
    url=INFLUX_URL,
    token=DB_TOKEN,
    org=ORG,
)

WRITE_API = CLIENT.write_api(write_options=SYNCHRONOUS)


def test_influx_connection():
    """Teste la connexion à InfluxDB."""
    try:
        health = CLIENT.health()

        if health.status != "pass":
            logging.error(
                "InfluxDB indisponible : %s",
                health.message
            )
            return False

        logging.info(
            "InfluxDB connecté : version %s",
            health.version
        )

        # Vérification que le bucket existe
        buckets = CLIENT.buckets_api().find_buckets().buckets

        bucket_names = [bucket.name for bucket in buckets]

        if BUCKET not in bucket_names:
            logging.error(
                "Le bucket '%s' n'existe pas.",
                BUCKET
            )
            logging.error(
                "Crée le bucket dans InfluxDB avant de lancer le script."
            )
            return False

        logging.info("Bucket '%s' trouvé.", BUCKET)

        return True

    except Exception:
        logging.exception("Impossible de contacter InfluxDB.")
        return False


# ============================================================
# Téléinfo
# ============================================================

CHAR_MEASURE_KEYS = [
    "DATE",
    "NGTF",
    "LTARF",
    "MSG1",
    "NJOURF",
    "NJOURF+1",
    "PJOURF",
    "PJOURF+1",
    "EASD02",
    "STGE",
    "RELAIS",
]


def add_measures(measures):
    """Envoie une trame complète dans InfluxDB."""

    points = []

    for measure, value in measures.items():

        # InfluxDB ne permet pas certains noms de mesure/champs
        # problématiques. On garde ici le nom Teleinfo.
        point = (
            Point(str(measure))
            .tag("host", "raspberry")
            .tag("region", "linky")
            .field("value", value)
            .time(datetime.now(timezone.utc), WritePrecision.S)
        )

        points.append(point)

        logging.debug(
            "Mesure : %s = %s",
            measure,
            value
        )

    if not points:
        return

    try:
        WRITE_API.write(
            bucket=BUCKET,
            org=ORG,
            record=points
        )

        logging.debug(
            "%d mesures envoyées à InfluxDB.",
            len(points)
        )

    except Exception:
        logging.exception(
            "Erreur lors de l'écriture dans InfluxDB."
        )


def verif_checksum(line_str, checksum):
    """Vérifie le checksum d'une ligne Teleinfo."""

    data = line_str[0:-2]

    data_unicode = sum(ord(caractere) for caractere in data)

    sum_unicode = (data_unicode & 63) + 32
    sum_chain = chr(sum_unicode)

    return checksum == sum_chain


def keys_from_file(filename):
    """Charge les clés Teleinfo depuis un fichier."""

    labels = []

    try:
        with open(filename, encoding="utf-8") as keys_file:
            for line in keys_file:
                line = line.strip()

                if not line:
                    continue

                information = line.split("\t")

                if len(information) >= 2:
                    labels.append(information[1])

    except OSError:
        logging.exception(
            "Impossible de lire le fichier %s",
            filename
        )
        sys.exit(1)

    return labels


def dico_from_file(filename):
    """Charge le dictionnaire des fabricants Linky."""

    information = {}

    try:
        with open(filename, encoding="utf-8") as dico_file:
            for line in dico_file:
                line = line.strip()

                if not line:
                    continue

                decoupage = line.split("\t")

                if len(decoupage) < 2:
                    continue

                try:
                    code_fabricant = int(decoupage[0])
                except ValueError:
                    continue

                nom_fabricant = decoupage[1]

                information[code_fabricant] = nom_fabricant

    except OSError:
        logging.exception(
            "Impossible de lire le fichier %s",
            filename
        )
        sys.exit(1)

    return information


# ============================================================
# Traitement d'une trame
# ============================================================

def process_trame(trame, liste_fabricants):
    """Complète et envoie une trame Teleinfo."""

    if not trame:
        return

    # --------------------------------------------------------
    # Fabricant
    # --------------------------------------------------------

    numero_compteur = str(trame.get("ADSC", ""))

    if len(numero_compteur) >= 4:
        try:
            id_fabricant = int(numero_compteur[2:4])

            if id_fabricant in liste_fabricants:
                trame["OEM"] = liste_fabricants[id_fabricant]
            else:
                trame["OEM"] = "UNKNOWN"

        except ValueError:
            trame["OEM"] = "UNKNOWN"
    else:
        trame["OEM"] = "UNKNOWN"


    # --------------------------------------------------------
    # Calcul CosPhi
    # --------------------------------------------------------

    irms1 = trame.get("IRMS1")
    urms1 = trame.get("URMS1")
    sinsts = trame.get("SINSTS")

    if (
        isinstance(irms1, (int, float))
        and isinstance(urms1, (int, float))
        and isinstance(sinsts, (int, float))
        and irms1 > 0
        and urms1 > 0
    ):
        trame["COSPHI"] = sinsts / (irms1 * urms1)

        logging.debug(
            "COSPHI = %.4f",
            trame["COSPHI"]
        )


    # --------------------------------------------------------
    # Timestamp Unix
    # --------------------------------------------------------

    trame["timestamp"] = int(time.time())


    # --------------------------------------------------------
    # Envoi InfluxDB
    # --------------------------------------------------------

    add_measures(trame)


# ============================================================
# Lecture port série
# ============================================================

def main():
    """Lit les trames Teleinfo."""

    labels_linky = keys_from_file(KEYS_FILE)
    liste_fabricants = dico_from_file(DICO_FILE)

    logging.info(
        "%d clés Teleinfo chargées.",
        len(labels_linky)
    )

    logging.info(
        "%d fabricants chargés.",
        len(liste_fabricants)
    )

    try:
        ser = serial.Serial(
            port=SERIALPORT,
            baudrate=9600,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.SEVENBITS,
            timeout=1
        )

    except serial.SerialException:
        logging.exception(
            "Impossible d'ouvrir le port série %s",
            SERIALPORT
        )
        sys.exit(1)


    logging.info(
        "Teleinfo reading on %s",
        SERIALPORT
    )

    logging.info("Mode standard")


    with ser:

        trame = {}

        # ----------------------------------------------------
        # Recherche du début de trame
        # ----------------------------------------------------

        logging.info("Recherche du début de trame...")

        while True:

            line = ser.readline()

            if not line:
                continue

            if b"\x02" in line:
                logging.debug("Début de trame trouvé.")
                break


        # ----------------------------------------------------
        # Lecture permanente
        # ----------------------------------------------------

        while True:

            line = ser.readline()

            if not line:
                continue

            logging.debug(
                "Ligne brute : %r",
                line
            )

            # ------------------------------------------------
            # Décodage
            # ------------------------------------------------

            try:
                line_str = line.decode(
                    "utf-8",
                    errors="replace"
                ).strip("\r\n")

            except UnicodeDecodeError:
                logging.warning(
                    "Erreur de décodage : %r",
                    line
                )
                continue


            # ------------------------------------------------
            # Début de trame
            # ------------------------------------------------

            if "\x02" in line_str:
                trame = {}
                continue


            # ------------------------------------------------
            # Fin de trame
            # ------------------------------------------------

            if "\x03" in line_str:

                logging.debug(
                    "Fin de trame : %s",
                    trame
                )

                process_trame(
                    trame,
                    liste_fabricants
                )

                trame = {}

                time.sleep(5)

                continue


            # ------------------------------------------------
            # Ligne Teleinfo
            # ------------------------------------------------

            ar_split = line_str.split("\t")

            if len(ar_split) < 2:
                continue

            key = ar_split[0].strip()

            if key not in labels_linky:
                logging.debug(
                    "Étiquette inconnue : %s",
                    key
                )
                continue


            # ------------------------------------------------
            # Valeur
            # ------------------------------------------------

            if len(ar_split) >= 2:
                value_str = ar_split[-2].strip()
            else:
                continue


            if key in CHAR_MEASURE_KEYS:

                value = value_str

            else:

                try:
                    value = int(value_str)

                except ValueError:

                    logging.debug(
                        "Valeur non numérique pour %s : %s",
                        key,
                        value_str
                    )

                    value = 0


            trame[key] = value


# ============================================================
# Programme principal
# ============================================================

if __name__ == "__main__":

    try:

        if not test_influx_connection():
            sys.exit(1)

        main()

    except KeyboardInterrupt:

        logging.info("Arrêt demandé.")

    except Exception:

        logging.exception(
            "Erreur fatale."
        )

    finally:

        try:
            WRITE_API.close()
            CLIENT.close()
        except Exception:
            pass
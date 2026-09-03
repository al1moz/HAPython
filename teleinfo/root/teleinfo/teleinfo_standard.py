#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Lecture Teleinfo Linky et envoi vers InfluxDB 2.x."""

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
# CONFIGURATION
# ============================================================

MODE = os.environ.get("debug_mode")

TELEINFO_INI = "/teleinfo/teleinfo.ini"
KEYS_FILE = "/teleinfo/liste_champs_mode_standard.txt"
DICO_FILE = "/teleinfo/liste_fabriquants_linky.txt"

# Définir dans les variables d'environnement.
INFLUX_ORG = os.environ.get("INFLUX_ORG")
INFLUX_URL = os.environ.get("URLDB")
DB_TOKEN = os.environ.get("TOKENDB")


if not DB_TOKEN:
    print("ERREUR : la variable TOKENDB n'est pas définie.")
    sys.exit(1)


# ============================================================
# VERIFICATION FICHIER DE CONFIGURATION
# ============================================================

if not pathlib.Path(TELEINFO_INI).exists():
    print(f"ERREUR : {TELEINFO_INI} introuvable.")
    sys.exit(1)


CONFIG = ConfigParser()
CONFIG.read(TELEINFO_INI)

if "teleinfo" not in CONFIG:
    print("ERREUR : section [teleinfo] absente du fichier ini.")
    sys.exit(1)


TELEINFO_DATA = CONFIG["teleinfo"]


# Port série
SERIALPORT = os.environ.get(
    "USBPORT",
    TELEINFO_DATA.get("serial_port", "")
)

# Dans InfluxDB 2.x, l'ancien "database" devient un "bucket".
BUCKET = TELEINFO_DATA.get(
    "influxdb_database",
    ""
)


if not SERIALPORT:
    print("ERREUR : aucun port série configuré.")
    sys.exit(1)


if not BUCKET:
    print("ERREUR : aucun bucket InfluxDB configuré.")
    sys.exit(1)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=getattr(logging, MODE, logging.DEBUG),
    format="%(asctime)s %(levelname)s %(message)s"
)

logging.info("========================================")
logging.info("Teleinfo starting")
logging.info("========================================")
logging.info("Port série : %s", SERIALPORT)
logging.info("InfluxDB   : %s", INFLUX_URL)
logging.info("Organisation : %s", INFLUX_ORG)
logging.info("Bucket     : %s", BUCKET)


# ============================================================
# CLIENT INFLUXDB
# ============================================================

CLIENT = InfluxDBClient(
    url=INFLUX_URL,
    token=DB_TOKEN,
    org=INFLUX_ORG
)

WRITE_API = CLIENT.write_api(
    write_options=SYNCHRONOUS
)


# ============================================================
# CHAMPS TELEINFO TEXTE
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
    "RELAIS"
]


# ============================================================
# TEST INFLUXDB
# ============================================================

def test_influx_connection():
    """Teste la connexion à InfluxDB et vérifie le bucket."""

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


        # Recherche du bucket
        buckets = CLIENT.buckets_api().find_buckets().buckets

        bucket_names = [
            bucket.name
            for bucket in buckets
        ]


        if BUCKET not in bucket_names:

            logging.error(
                "Le bucket '%s' n'existe pas.",
                BUCKET
            )

            return False


        logging.info(
            "Bucket '%s' trouvé.",
            BUCKET
        )

        return True


    except Exception:

        logging.exception(
            "Impossible de se connecter à InfluxDB."
        )

        return False


# ============================================================
# CHARGEMENT DES CLES TELEINFO
# ============================================================

def keys_from_file(filename):
    """Charge les noms des champs Teleinfo."""

    labels = []

    try:

        with open(
            filename,
            encoding="utf-8"
        ) as keys_file:

            for line in keys_file:

                line = line.strip()

                if not line:
                    continue

                information = line.split("\t")

                if len(information) >= 2:

                    labels.append(
                        information[1].strip()
                    )


    except OSError:

        logging.exception(
            "Impossible de lire %s",
            filename
        )

        sys.exit(1)


    return labels


# ============================================================
# CHARGEMENT DES FABRICANTS
# ============================================================

def dico_from_file(filename):
    """Charge le dictionnaire des fabricants Linky."""

    information = {}

    try:

        with open(
            filename,
            encoding="utf-8"
        ) as dico_file:

            for line in dico_file:

                line = line.strip()

                if not line:
                    continue

                decoupage = line.split("\t")

                if len(decoupage) < 2:
                    continue

                try:

                    code_fabricant = int(
                        decoupage[0]
                    )

                except ValueError:

                    continue

                nom_fabricant = decoupage[1].strip()

                information[
                    code_fabricant
                ] = nom_fabricant


    except OSError:

        logging.exception(
            "Impossible de lire %s",
            filename
        )

        sys.exit(1)


    return information


# ============================================================
# TRAITEMENT D'UNE LIGNE TELEINFO
# ============================================================

def process_teleinfo_line(
    data,
    trame,
    labels_linky
):
    """Traite une ligne Teleinfo."""

    if not data:
        return


    # Suppression CR / LF
    data = data.strip(b"\r\n")


    if not data:
        return


    try:

        line_str = data.decode(
            "utf-8",
            errors="replace"
        )

    except Exception:

        logging.exception(
            "Erreur de décodage : %r",
            data
        )

        return


    if MODE != "PRODUCTION":
        logging.debug(
            "Ligne Teleinfo : %s",
            line_str
        )


    # --------------------------------------------------------
    # Séparation des champs
    # --------------------------------------------------------

    ar_split = line_str.split("\t")


    if len(ar_split) < 2:
        return


    key = ar_split[0].strip()


    # --------------------------------------------------------
    # Champ inconnu
    # --------------------------------------------------------

    if key not in labels_linky:
        if MODE != "PRODUCTION":
            logging.debug(
                "Étiquette inconnue : %s",
                key
            )

        return


    # --------------------------------------------------------
    # Récupération de la valeur
    #
    # Format normal :
    #
    # KEY    VALUE    CHECKSUM
    #
    # Certains champs :
    #
    # KEY    DATE    VALUE    CHECKSUM
    #
    # Dans les deux cas la valeur est l'avant-dernier champ.
    # --------------------------------------------------------

    if len(ar_split) >= 3:

        value_str = ar_split[-2].strip()

    else:

        value_str = ar_split[1].strip()


    # --------------------------------------------------------
    # Champs texte
    # --------------------------------------------------------

    if key in CHAR_MEASURE_KEYS:

        value = value_str


    # --------------------------------------------------------
    # Champs numériques
    # --------------------------------------------------------

    else:

        try:

            value = int(value_str)

        except ValueError:

            if MODE != "PRODUCTION":
                logging.debug(
                    "Valeur non numérique : %s = %r",
                    key,
                    value_str
                )

            value = 0


    trame[key] = value


    if MODE != "PRODUCTION":
        logging.debug(
            "Champ : %s = %r",
            key,
            value
        )


# ============================================================
# TRAITEMENT D'UNE TRAME COMPLETE
# ============================================================

def process_trame(
    trame,
    liste_fabricants
):
    """Complète et envoie une trame complète."""

    if not trame:

        logging.warning(
            "Trame vide"
        )

        return


    if MODE != "PRODUCTION":
        logging.info(
            "Traitement d'une trame avec %d champs",
            len(trame)
        )


    # --------------------------------------------------------
    # Fabricant
    # --------------------------------------------------------

    numero_compteur = str(
        trame.get(
            "ADSC",
            ""
        )
    )


    if len(numero_compteur) >= 4:

        try:

            id_fabricant = int(
                numero_compteur[2:4]
            )

            trame["OEM"] = liste_fabricants.get(
                id_fabricant,
                "UNKNOWN"
            )

        except ValueError:

            trame["OEM"] = "UNKNOWN"

    else:

        trame["OEM"] = "UNKNOWN"


    # --------------------------------------------------------
    # CosPhi
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

        trame["COSPHI"] = (
            sinsts / (
                irms1 * urms1
            )
        )

        if MODE != "PRODUCTION":
            logging.debug(
                "COSPHI = %.4f",
                trame["COSPHI"]
            )


    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    trame["timestamp"] = int(
        time.time()
    )


    # --------------------------------------------------------
    # Envoi InfluxDB
    # --------------------------------------------------------

    if MODE != "PRODUCTION":
        logging.info(
            "Envoi de %d mesures vers InfluxDB...",
            len(trame)
        )


    add_measures(trame)


# ============================================================
# ENVOI VERS INFLUXDB
# ============================================================

def add_measures(measures):
    """Envoie les mesures dans InfluxDB."""

    points = []


    for measure, value in measures.items():

        if MODE != "PRODUCTION":
            logging.debug(
                "InfluxDB : %s = %r",
                measure,
                value
            )


        # ----------------------------------------------------
        # InfluxDB accepte les chaînes comme champs.
        # On force les valeurs non numériques en string.
        # ----------------------------------------------------

        if isinstance(value, bool):

            field_value = int(value)

        elif isinstance(value, (int, float)):

            field_value = value

        else:

            field_value = str(value)


        point = (
            Point(str(measure))
            .tag(
                "host",
                "raspberry"
            )
            .tag(
                "region",
                "linky"
            )
            .field(
                "value",
                field_value
            )
            .time(
                datetime.now(timezone.utc),
                WritePrecision.S
            )
        )


        points.append(point)


    if not points:

        logging.warning(
            "Aucun point à envoyer."
        )

        return


    try:

        WRITE_API.write(
            bucket=BUCKET,
            org=INFLUX_ORG,
            record=points
        )


        if MODE != "PRODUCTION":
            logging.info(
                "SUCCÈS : %d points écrits dans InfluxDB",
                len(points)
            )


    except Exception:

        logging.exception(
            "ERREUR pendant l'écriture InfluxDB"
        )


# ============================================================
# LECTURE DU PORT SERIE
# ============================================================

def main():
    """Lecture permanente du flux Teleinfo."""

    # --------------------------------------------------------
    # Chargement des fichiers
    # --------------------------------------------------------

    labels_linky = keys_from_file(
        KEYS_FILE
    )

    liste_fabricants = dico_from_file(
        DICO_FILE
    )


    logging.info(
        "%d clés Teleinfo chargées.",
        len(labels_linky)
    )

    logging.info(
        "%d fabricants chargés.",
        len(liste_fabricants)
    )


    # --------------------------------------------------------
    # Ouverture port série
    # --------------------------------------------------------

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

    logging.info(
        "Mode standard"
    )


    # --------------------------------------------------------
    # Variables de lecture
    # --------------------------------------------------------

    trame = {}

    dans_trame = False


    # --------------------------------------------------------
    # Lecture permanente
    # --------------------------------------------------------

    with ser:

        while True:

            line = ser.readline()


            if not line:
                continue


            if MODE != "PRODUCTION":
                logging.debug(
                    "Ligne brute : %r",
                    line
                )


            # ------------------------------------------------
            # Recherche des caractères STX / ETX
            #
            # STX = 0x02 : début de trame
            # ETX = 0x03 : fin de trame
            #
            # Une ligne peut contenir :
            #
            #   données + ETX + STX
            #
            # donc on ne peut pas simplement faire
            # "continue" dès qu'on trouve STX.
            # ------------------------------------------------

            position = 0


            while position < len(line):


                # ==================================================
                # PAS DANS UNE TRAME
                # ==================================================

                if not dans_trame:

                    start = line.find(
                        b"\x02",
                        position
                    )


                    if start == -1:

                        # Rien d'intéressant dans cette ligne.
                        break


                    # Début de trame trouvé
                    dans_trame = True

                    trame = {}

                    if MODE != "PRODUCTION":
                        logging.debug(
                            "Début de trame"
                        )


                    position = start + 1

                    continue


                # ==================================================
                # DANS UNE TRAME
                # ==================================================

                end = line.find(
                    b"\x03",
                    position
                )


                # --------------------------------------------------
                # Pas encore de fin de trame
                # --------------------------------------------------

                if end == -1:

                    data = line[position:]


                    process_teleinfo_line(
                        data,
                        trame,
                        labels_linky
                    )


                    # On a consommé toute la ligne.
                    break


                # --------------------------------------------------
                # Fin de trame trouvée
                # --------------------------------------------------

                data = line[
                    position:end
                ]


                process_teleinfo_line(
                    data,
                    trame,
                    labels_linky
                )


                # --------------------------------------------------
                # Trame complète
                # --------------------------------------------------

                if MODE != "PRODUCTION":
                    logging.info(
                        "Fin de trame : %d champs",
                        len(trame)
                    )


                process_trame(
                    trame,
                    liste_fabricants
                )


                # --------------------------------------------------
                # Réinitialisation
                # --------------------------------------------------

                trame = {}

                dans_trame = False


                # --------------------------------------------------
                # On continue après ETX.
                #
                # Si STX arrive immédiatement après, comme dans :
                #
                #   \x03\x02
                #
                # il sera détecté au prochain passage.
                # --------------------------------------------------

                position = end + 1


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

if __name__ == "__main__":

    try:

        if not test_influx_connection():

            logging.error(
                "Connexion InfluxDB impossible."
            )

            sys.exit(1)


        main()


    except KeyboardInterrupt:

        logging.info(
            "Arrêt demandé."
        )


    except Exception:

        logging.exception(
            "ERREUR FATALE"
        )


    finally:

        try:
            WRITE_API.close()
        except Exception:
            pass

        try:
            CLIENT.close()
        except Exception:
            pass


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

        if MODE != "PRODUCTION":
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

        if MODE != "PRODUCTION":
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

        if MODE != "PRODUCTION":
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

    logging.info("Teleinfo reading on %s", SERIALPORT)
    logging.info("Mode standard")

    trame = {}
    dans_trame = False

    with ser:

        while True:

            line = ser.readline()

            if not line:
                continue

            if MODE != "PRODUCTION":
                logging.debug("Ligne brute : %r", line)

            # ------------------------------------------------
            # Décodage
            # ------------------------------------------------

            try:
                line_str = line.decode(
                    "utf-8",
                    errors="replace"
                )

            except UnicodeDecodeError:
                logging.warning(
                    "Erreur de décodage : %r",
                    line
                )
                continue

            # ------------------------------------------------
            # Une ligne peut contenir :
            #
            #   \x03 = fin de trame
            #   \x02 = début de trame
            #
            # et les deux peuvent être présents dans la même
            # ligne :
            #
            #   PJOURF+1 ... \x03\x02
            #
            # ------------------------------------------------

            morceaux = line_str.split("\x02")

            for index, morceau in enumerate(morceaux):

                # Si on trouve \x02, on démarre une nouvelle trame.
                if index > 0:
                    dans_trame = True
                    trame = {}

                    if MODE != "PRODUCTION":
                        logging.debug("Début de nouvelle trame")

                # Rien à traiter si on n'est pas encore dans une
                # trame.
                if not dans_trame:
                    continue

                # ------------------------------------------------
                # Vérification fin de trame
                # ------------------------------------------------

                fin_trame = "\x03" in morceau

                if fin_trame:
                    morceau = morceau.split("\x03", 1)[0]

                # ------------------------------------------------
                # Traitement de la ligne
                # ------------------------------------------------

                morceau = morceau.strip("\r\n")

                if morceau:

                    ar_split = morceau.split("\t")

                    if len(ar_split) >= 2:

                        key = ar_split[0].strip()

                        if key in labels_linky:

                            # Dans une trame standard :
                            #
                            # KEY <TAB> VALUE <TAB> CHECKSUM
                            #
                            # Pour certains champs, il existe
                            # plusieurs colonnes :
                            #
                            # SMAXSN <TAB> DATE <TAB> VALUE <TAB> CHECKSUM
                            #
                            if len(ar_split) >= 3:
                                value_str = ar_split[-2].strip()
                            else:
                                value_str = ar_split[1].strip()

                            # Champs texte
                            if key in CHAR_MEASURE_KEYS:
                                value = value_str

                            else:
                                try:
                                    value = int(value_str)

                                except ValueError:
                                    logging.debug(
                                        "Valeur non numérique : "
                                        "%s = %r",
                                        key,
                                        value_str
                                    )
                                    value = 0

                            trame[key] = value

                            if MODE != "PRODUCTION":
                                logging.debug(
                                    "Champ : %s = %r",
                                    key,
                                    value
                                )

                        else:
                            if MODE != "PRODUCTION":
                                logging.debug(
                                    "Étiquette inconnue : %s",
                                    key
                                )

                # ------------------------------------------------
                # Fin de trame
                # ------------------------------------------------

                if fin_trame:


                    if MODE != "PRODUCTION":
                        logging.info(
                            "Fin de trame : %d champs",
                            len(trame)
                        )

                    if MODE != "PRODUCTION":
                        logging.debug(
                            "Trame complète : %s",
                            trame
                        )

                    process_trame(
                        trame,
                        liste_fabricants
                    )

                    trame = {}
                    dans_trame = False

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
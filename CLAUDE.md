# CLAUDE.md : HAPython

Add-ons Home Assistant d'Alain. Le site qui reçoit les données et la mémoire complète du projet sont dans `al1moz/hav2` (lire son `CLAUDE.md`).

## Contenu

- `consov2/` : **l'add-on unifié**, à utiliser. Il remplace les trois autres : Linky, PAC Arkteos, Shelly EM et entités Home Assistant (Netatmo) vers l'API du site ConsoV2, InfluxDB et MQTT.
- `teleinfo/`, `arkteos/`, `mycron/`, `tester/` : anciens add-ons, gardés jusqu'à ce qu'Alain fasse le ménage. Ne plus les modifier. Ils ne doivent pas tourner en même temps que ConsoV2 (le port série du Linky ne s'ouvre qu'une fois).

## Règles

- Répondre en français. Pas de PR : quand Alain le dit, commit et push directement sur `main`. Il n'a pas de copie locale de ce dépôt connectée à Claude : il teste l'add-on en le mettant à jour dans Home Assistant. Ne jamais pousser sans son « go ».
- Augmenter `version` dans `consov2/config.yaml` (et `__version__` dans `rootfs/app/consov2/__init__.py`) à chaque changement, sinon Home Assistant ne propose pas la mise à jour.
- Dépôt public : aucun secret, aucune adresse IP, aucun nom de commune ni coordonnée GPS dans le code ou les valeurs par défaut. L'IP de la PAC, les jetons et les entités se saisissent dans la configuration de l'add-on.
- Seulement des paquets Debian (`python3-serial`, `python3-paho-mqtt`), pas de pip. Rester compatible paho 1.x et 2.x.
- InfluxDB : garder les mêmes buckets, noms de mesures, étiquettes et types de champs que les anciens add-ons, sinon InfluxDB refuse l'écriture et Grafana casse. Linky dans `teleinfo2` (`host=raspberry`, `region=linky`), champs texte = liste `INFLUX_LINKY_TEXT` de `main.py`, le reste en entier ; Shelly `SHELLYEMn_c` en décimal (`region=shellyem`) ; PAC dans `arkteos` (`host=elitedesk`, `region=pac`) en décimal.

## Tester

```sh
python3 -m unittest discover -s consov2/tests
```

Pour un essai complet sans matériel : faux Linky sur un pty, fausse PAC en TCP, Mosquitto, fausse API HA (`CONSOV2_HA_API`), avec `CONSOV2_OPTIONS` et `CONSOV2_DATA` pointant vers un dossier de test, puis `python3 -m consov2.main` depuis `consov2/rootfs/app`.

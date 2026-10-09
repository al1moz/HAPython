# ConsoV2

Un seul add-on à la place de **teleinfo**, **arkteos** et **mycron** (getMqtt + put2web).

Il lit :

- le **Linky** sur le port série (mode standard, checksum vérifié) ;
- la **PAC Arkteos** (régulation REG3, port TCP 9641) ;
- les **Shelly EM** par MQTT ;
- des **entités Home Assistant** (Netatmo : températures, humidité, CO₂…).

Toutes les 5 minutes (calées sur l'horloge), il calcule une valeur par mesure (moyenne des lectures, ou dernier index pour le Linky) et l'envoie au site ConsoV2. Les lots attendent dans une file sur disque (`/data`) tant que le site ne répond pas : une coupure d'Internet ou un redémarrage ne perd rien, et un lot renvoyé n'est jamais compté deux fois.

## Configuration

### Site (`api`)

| Option | Rôle |
|---|---|
| `url` | adresse du site, par ex. `https://conso.exemple.fr` |
| `token` | jeton créé sur le serveur avec `php bin/token.php create addon ingest` |
| `interval_minutes` | période d'envoi, 5 par défaut |
| `legacy_receiver_url` | pendant la transition seulement : adresse de l'ancien `receiver.php`. L'add-on y envoie `cindex` et `q1`…`q8` comme put2web. Laisser vide ensuite. |

Sans `url` ni `token`, les mesures sont gardées en file jusqu'à ce qu'ils soient renseignés.

### MQTT

Laisser `host` vide : l'add-on prend automatiquement le broker Mosquitto de Home Assistant. Avec `discovery`, les mesures apparaissent dans Home Assistant (appareil « ConsoV2 »), avec quatre capteurs d'état : file d'attente, dernier envoi, dernière erreur, trames Linky reçues.

### Linky

`port` : de préférence le chemin stable `/dev/serial/by-id/…`. `index_field` : `EASF01` (index fournisseur, comme l'historique) ou `EAST`.

### PAC Arkteos

`host` : adresse IP de la régulation. Les valeurs arrivent sur le site sous les codes `pac_…` (eau départ et retour, ballon ECS, pressions, consignes). `legacy_mqtt_topics` publie aussi les anciens sujets `arkteos/reg3/…` pour les automatisations existantes.

`interval_seconds` : une lecture toutes les 300 s par défaut, calée sur les périodes d'envoi de 5 min, comme l'ancien add-on. La régulation est capricieuse : lire plus souvent ne donne pas plus de valeurs et peut la gêner. `timeout_seconds` : temps accordé à une lecture, connexion comprise (120 s par défaut). La régulation met parfois une à deux minutes à accepter la connexion ; l'add-on réessaie toutes les 5 s dans cette limite. Le journal ne signale la PAC qu'après 15 min sans aucune lecture réussie.

### Shelly EM

Les 8 canaux par défaut reprennent les sujets de getMqtt (`shellies/shellyemN/emeter/C/power`) dans l'ordre CPT1 à CPT8 de l'ancien site. Les valeurs négatives sont prises en valeur absolue, comme avant.

### Entités Home Assistant

Exemple pour Netatmo :

```yaml
homeassistant:
  enabled: true
  interval_seconds: 60
  entities:
    - entity_id: sensor.salon_temperature
      metric: temp_living
      source: netatmo
    - entity_id: sensor.salon_humidite
      metric: humidity_living
      source: netatmo
    - entity_id: sensor.exterieur_temperature
      metric: temp_outdoor
      source: netatmo
```

Codes connus du site : `temp_living`, `temp_outdoor`, `temp_upstairs`, `humidity_living`, `humidity_upstairs`, `humidity_outdoor`, `co2_living`, `pressure_outdoor`. Un autre code est créé automatiquement sur le site.

### InfluxDB

Facultatif. Les noms de mesures et les étiquettes sont ceux des anciens add-ons (`teleinfo2` avec `region=linky` et `region=shellyem`, `arkteos` avec `region=pac`) : les tableaux Grafana existants continuent de fonctionner.

### Alerte appoint ECS

Quand `circuit_appoint_ecs` franchit `threshold_w` (500 W), l'add-on envoie tout de suite au lieu d'attendre la fin des 5 minutes.

## Passer des anciens add-ons à celui-ci

1. Installer ConsoV2, le configurer, **sans le démarrer**.
2. Arrêter teleinfo, arkteos et mycron (le port série ne peut être lu que par un seul add-on).
3. Démarrer ConsoV2 et vérifier le journal, puis les capteurs « ConsoV2 » dans Home Assistant.
4. Une fois le nouveau site en service, vider `legacy_receiver_url` et désinstaller les anciens add-ons.

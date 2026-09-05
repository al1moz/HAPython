Déroulement :

Connexion MQTT : il se connecte à un broker MQTT local (192.168.252.4) pour publier les mesures en temps réel sous le topic arkteos/reg3/....
Connexion InfluxDB 2.x : il vérifie que la base de données (bucket arkteos) est joignable, pour y stocker l'historique des mesures.
Connexion au boîtier Arkteos : il ouvre une connexion socket TCP vers l'adresse ARKHOST:9641 (le module reg3 de la PAC), qui répond en envoyant des trames de données brutes (des paquets d'octets).
Décodage : selon la taille de la trame reçue (163 ou 227 octets), le script sait quelles valeurs extraire à quels octets précis (table decoder) — pression eau primaire, températures (extérieure, primaire aller/retour, intérieure zones 1/2, ballon ECS...), avec un facteur diviseur pour convertir en unité réelle (ex: dixièmes de degré).
Publication : chaque valeur décodée est :
publiée sur MQTT (topic dédié par mesure),
envoyée vers InfluxDB (avec tags host/region et timestamp).
Boucle infinie : une fois les deux trames (163 + 227 octets) reçues et traitées, la connexion se ferme, et le script recommence tout le cycle toutes les 5 minutes (time.sleep(300)).

En clair : il interroge périodiquement le module Arkteos de la pompe à chaleur, décode les données binaires en valeurs physiques (températures, pressions), et les diffuse à la fois en temps réel (MQTT) et en historique (InfluxDB).
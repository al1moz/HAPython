"""PAC Arkteos (régulation REG3) : lecture des trames sur le port TCP 9641.

À la connexion, la régulation envoie deux trames de 163 et 227 octets.
Décodage repris de l'ancien add-on (cyrilpawelko/arkteos_reg3), avec :
- un délai maximal (plus de boucle infinie si la PAC ne répond pas) ;
- des valeurs signées sur 16 bits (températures négatives dehors).
"""
import logging
import socket
import time
from typing import Dict, Optional

log = logging.getLogger("arkteos")

# (trame, nom, unité, octet bas, octet haut ou None, diviseur)
DECODER = [
    (227, "primaire_pression", "bar", 62, None, 10),
    (227, "externe_pression", "bar", 46, None, 10),
    (227, "primaire_temp_eau_aller", "°C", 54, 55, 10),
    (227, "primaire_temp_eau_retour", "°C", 56, 57, 10),
    (163, "exterieur_temp", "°C", 24, 25, 10),
    (227, "zone1_temp_interieur", "°C", 68, 69, 10),
    (227, "zone2_temp_interieur", "°C", 88, 89, 10),
    (227, "zone1_consigne", "°C", 70, 71, 10),
    (227, "zone2_consigne", "°C", 90, 91, 10),
    (227, "ecs_temp_eau_milieu", "°C", 108, 109, 10),
    (227, "ecs_temp_eau_bas", "°C", 110, 111, 10),
]
LABELS = {
    "primaire_pression": "PAC pression eau primaire",
    "externe_pression": "PAC pression eau extérieure",
    "primaire_temp_eau_aller": "PAC eau départ",
    "primaire_temp_eau_retour": "PAC eau retour",
    "exterieur_temp": "PAC température extérieure",
    "zone1_temp_interieur": "PAC intérieur zone 1",
    "zone2_temp_interieur": "PAC intérieur zone 2",
    "zone1_consigne": "PAC consigne zone 1",
    "zone2_consigne": "PAC consigne zone 2",
    "ecs_temp_eau_milieu": "Ballon ECS milieu",
    "ecs_temp_eau_bas": "Ballon ECS bas",
}
UNITS = {name: unit for _, name, unit, *_ in DECODER}


def decode(frame: bytes) -> Dict[str, float]:
    """Décode une trame de 163 ou 227 octets. Renvoie {nom: valeur}."""
    out = {}
    for size, name, _unit, lo, hi, div in DECODER:
        if len(frame) != size:
            continue
        raw = frame[lo] if hi is None else frame[lo] | (frame[hi] << 8)
        if hi is not None and raw >= 0x8000:
            raw -= 0x10000
        out[name] = round(raw / div, 2)
    return out


def read_once(host: str, port: int = 9641, timeout: float = 30.0) -> Optional[Dict[str, float]]:
    """Se connecte, lit les deux trames, renvoie les valeurs ou None après le délai."""
    deadline = time.monotonic() + timeout
    values: Dict[str, float] = {}
    seen = set()
    with socket.create_connection((host, port), timeout=min(10.0, timeout)) as sock:
        buf = b""
        while seen != {163, 227} and time.monotonic() < deadline:
            sock.settimeout(max(0.5, deadline - time.monotonic()))
            try:
                chunk = sock.recv(1024)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            # La régulation envoie chaque trame d'un bloc ; on accepte aussi des tailles concaténées.
            for size in (227, 163):
                if len(buf) == size or (len(buf) > size and len(buf) - size in (163, 227)):
                    frame, buf = buf[:size], buf[size:]
                    values.update(decode(frame))
                    seen.add(size)
            if len(buf) > 1024:
                log.debug("Trame Arkteos de taille inattendue (%d octets), ignorée", len(buf))
                buf = b""
    if not seen:
        return None
    if seen != {163, 227}:
        log.info("Arkteos : une seule trame reçue (%s)", sorted(seen))
    return values

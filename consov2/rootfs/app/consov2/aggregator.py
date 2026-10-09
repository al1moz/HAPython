"""Regroupe les lectures brutes en une valeur par mesure et par période.

- grandeur (« gauge ») : moyenne des lectures de la période ;
- index (« counter ») : dernière lecture de la période.
Toutes les valeurs d'une période portent l'horodatage de sa fin.
"""
import threading
from typing import Callable, Dict, List, Optional, Tuple

from .model import Measurement


class Aggregator:
    def __init__(self):
        self._lock = threading.Lock()
        self._gauges: Dict[str, list] = {}       # metric -> [somme, n, unité, source]
        self._counters: Dict[str, Measurement] = {}
        self.latest: Dict[str, Measurement] = {}  # dernière lecture brute (affichage MQTT)
        self._watchers: List[Tuple[str, float, Callable[[bool], None]]] = []

    def watch(self, metric: str, threshold: float, callback: Callable[[bool], None]):
        """Appelle callback(au_dessus) quand la mesure franchit le seuil, dans un sens ou dans l'autre."""
        self._watchers.append((metric, threshold, callback))

    def add(self, m: Measurement):
        fired = []
        with self._lock:
            previous: Optional[Measurement] = self.latest.get(m.metric)
            self.latest[m.metric] = m
            if m.kind == "counter":
                current = self._counters.get(m.metric)
                if current is None or m.ts >= current.ts:
                    self._counters[m.metric] = m
            else:
                slot = self._gauges.setdefault(m.metric, [0.0, 0, m.unit, m.source])
                slot[0] += m.value
                slot[1] += 1
            for metric, threshold, callback in self._watchers:
                if metric != m.metric:
                    continue
                was_above = previous is not None and previous.value >= threshold
                is_above = m.value >= threshold
                if previous is None and not is_above:
                    continue
                if was_above != is_above:
                    fired.append((callback, is_above))
        for callback, above in fired:
            callback(above)

    def flush(self, ts: int) -> List[Measurement]:
        with self._lock:
            out = [Measurement(metric, round(s / n, 3), unit, ts, source)
                   for metric, (s, n, unit, source) in self._gauges.items() if n]
            out += [Measurement(c.metric, c.value, c.unit, ts, c.source, "counter")
                    for c in self._counters.values()]
            self._gauges.clear()
            self._counters.clear()
        out.sort(key=lambda m: m.metric)
        return out

    def snapshot(self) -> Dict[str, Measurement]:
        with self._lock:
            return dict(self.latest)

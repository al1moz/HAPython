"""Une mesure commune à tous les collecteurs et à toutes les sorties."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Measurement:
    metric: str            # code de la mesure côté site, ex. "elec_index"
    value: float
    unit: str              # "W", "Wh", "°C", "%"…
    ts: int                # secondes Unix (UTC)
    source: str            # "linky", "shelly", "arkteos", "netatmo"…
    kind: str = "gauge"    # "gauge" (valeur/moyenne) ou "counter" (index qui ne fait que monter)

    def to_api(self) -> dict:
        from datetime import datetime, timezone
        return {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "kind": self.kind,
            "ts": datetime.fromtimestamp(self.ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


@dataclass
class MetricInfo:
    """Description d'une mesure pour la découverte MQTT de Home Assistant."""
    label: str
    device_class: Optional[str] = None
    state_class: Optional[str] = "measurement"
    extra: dict = field(default_factory=dict)


# Libellés et classes HA des mesures connues (les autres utilisent leur code comme nom).
KNOWN = {
    "elec_index": MetricInfo("Index Linky", "energy", "total_increasing"),
    "elec_power": MetricInfo("Puissance apparente Linky", "apparent_power"),
    "elec_voltage": MetricInfo("Tension Linky", "voltage"),
    "circuit_seche_serviettes": MetricInfo("Sèche-serviettes", "power"),
    "circuit_geothermie": MetricInfo("Géothermie", "power"),
    "circuit_prises_rdc": MetricInfo("Prises RDC", "power"),
    "circuit_appoint_ecs": MetricInfo("Appoint ECS", "power"),
    "circuit_double_flux": MetricInfo("Double flux", "power"),
    "circuit_cuisson": MetricInfo("Cuisson", "power"),
    "circuit_garage": MetricInfo("Garage", "power"),
    "circuit_lavage": MetricInfo("Lavage", "power"),
    "temp_living": MetricInfo("Température salon", "temperature"),
    "temp_outdoor": MetricInfo("Température extérieure", "temperature"),
    "temp_upstairs": MetricInfo("Température étage", "temperature"),
    "humidity_living": MetricInfo("Humidité salon", "humidity"),
    "humidity_upstairs": MetricInfo("Humidité étage", "humidity"),
    "humidity_outdoor": MetricInfo("Humidité extérieure", "humidity"),
    "co2_living": MetricInfo("CO₂ salon", "carbon_dioxide"),
    "pressure_outdoor": MetricInfo("Pression atmosphérique", "atmospheric_pressure"),
}


def _arkteos_metrics():
    from .arkteos import LABELS, UNITS
    for name, label in LABELS.items():
        KNOWN["pac_" + name] = MetricInfo(label, "temperature" if UNITS[name] == "°C" else "pressure")


_arkteos_metrics()

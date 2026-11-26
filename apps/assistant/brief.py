"""The 08:00 and 20:00 briefs: template facts, no LLM, no menu (PLAN §8.1)."""

from datetime import timedelta

from django.template.loader import render_to_string
from django.utils import timezone

from apps.agenda import day as simulation

MORNING, EVENING = "morning", "evening"
KINDS = (MORNING, EVENING)


def render(kind=MORNING, day=None):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    today = day or timezone.localdate()
    target = today + timedelta(days=1) if kind == EVENING else today

    result = simulation.simulate(target)
    stops = [
        _stop(index, stop, result["base"]) for index, stop in enumerate(result["stops"])
    ]
    return (
        render_to_string(
            f"brief/{kind}.txt",
            {
                "date": result["date"],
                "count": len(stops),
                "stops": stops,
                "conflicts": result["conflicts"],
                "degraded": result["degraded"],
            },
        ).strip()
        + "\n"
    )


def _stop(index, stop, base):
    if stop["missing_address"]:
        line = "Sin dirección"
    elif stop["degraded"]:
        line = "sin cálculo de traslado"
    elif index == 0:
        line = "Sal de {} a las {} ({} min de traslado + {} de margen)".format(
            base or "la oficina", stop["depart_at"], stop["travel_min"], stop["buffer_min"]
        )
    else:
        line = f"Traslado desde la anterior: {stop['travel_min']} min"
    return {**stop, "depart_line": line}

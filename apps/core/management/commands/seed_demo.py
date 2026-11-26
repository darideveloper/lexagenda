"""`manage.py seed_demo`: five clients, three cases and a deliberately impossible week."""

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.core.models import BaseLocation, Case, Client

CLIENTS = [
    ("García López, Marta", "+527711110001", "marta@example.com"),
    ("Peralta Ruiz, Hugo", "+527711110002", "hugo@example.com"),
    ("Ramírez Soto, Ana", "+527711110003", "ana@example.com"),
    ("Domínguez Vega, Luis", "+527711110004", "luis@example.com"),
    ("Vega Campos, Sofía", "+527711110005", "sofia@example.com"),
]

CASES = [
    ("EXP-2026-001", "Despido injustificado", "García López, Marta", "Junta 4 de lo Laboral"),
    ("EXP-2026-002", "Cobro de pagaré", "Peralta Ruiz, Hugo", "Juzgado de lo Civil"),
    ("EXP-2026-003", "Divorcio incausado", "Ramírez Soto, Ana", ""),
]

BASE = ("Oficina", "Calle Allende 12, Centro, Pachuca, Hidalgo")

# Times relative to Monday of the current week; Tue and Thu overlap on purpose.
WEEK = {
    0: [
        ("Visita García", Appointment.VISITA, 9, 30, 60, "Despacho demandado"),
    ],
    1: [
        ("Audiencia inicial Peralta", Appointment.AUDIENCIA, 9, 0, 90, "Juzgado de lo Civil"),
        ("Visita Ramírez", Appointment.VISITA, 10, 0, 60, "Colonia Centro"),
        ("Trámite Vega", Appointment.TRAMITE, 11, 0, 30, "Registro Público"),
    ],
    3: [
        ("Audiencia Domínguez", Appointment.AUDIENCIA, 9, 0, 120, "Juzgado 4° de lo Laboral"),
        ("Visita García", Appointment.VISITA, 10, 0, 60, "Despacho demandado"),
    ],
    4: [
        ("Reunión Vega", Appointment.REUNION, 12, 30, 45, ""),
    ],
}


class Command(BaseCommand):
    help = "Seed five clients, three cases and an impossible week for the demo."

    def add_arguments(self, parser):
        parser.add_argument("--monday", default=None, help="YYYY-MM-DD; this week by default")

    def handle(self, *args, **options):
        monday = (
            datetime.date.fromisoformat(options["monday"])
            if options["monday"]
            else _monday()
        )
        base = self._base()
        clients = self._clients()
        self._cases(clients)
        self._appointments(monday, clients)
        self.stdout.write(
            f"seed_demo: 5 clientes, 3 expedientes, semana del {monday.isoformat()} "
            f"desde {base.label}"
        )

    def _base(self):
        base, _ = BaseLocation.objects.get_or_create(
            label=BASE[0], defaults={"address": BASE[1], "is_default": True}
        )
        if not base.is_default:
            BaseLocation.objects.filter(is_default=True).update(is_default=False)
            base.is_default = True
            base.save(update_fields=["is_default"])
        return base

    def _clients(self):
        created = {}
        for name, phone, email in CLIENTS:
            client, _ = Client.objects.get_or_create(
                phone=phone,
                defaults={"name": name, "jid": f"{phone}@s.whatsapp.net", "email": email},
            )
            created[name] = client
        return created

    def _cases(self, clients):
        for reference, title, client_name, court in CASES:
            Case.objects.get_or_create(
                reference=reference,
                defaults={
                    "title": title,
                    "client": clients[client_name],
                    "court": court,
                    "opened_on": timezone.localdate() - datetime.timedelta(days=90),
                },
            )

    def _appointments(self, monday, clients):
        for offset, rows in WEEK.items():
            day = monday + datetime.timedelta(days=offset)
            for title, kind, hour, minute, duration, address in rows:
                starts_at = timezone.make_aware(
                    datetime.datetime.combine(day, datetime.time(hour, minute))
                )
                Appointment.objects.get_or_create(
                    title=title,
                    starts_at=starts_at,
                    defaults={
                        "kind": kind,
                        "duration_min": duration,
                        "address": address,
                        "location_name": address,
                        "address_source": Appointment.MANUAL if address else Appointment.NONE,
                        "client": _client_for(title, clients),
                    },
                )


def _client_for(title, clients):
    for name, client in clients.items():
        if name.split(",")[0].split()[0] in title:
            return client
    return None


def _monday():
    today = timezone.localdate()
    return today + datetime.timedelta(days=(0 - today.weekday()) % 7)

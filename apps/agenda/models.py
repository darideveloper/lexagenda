import uuid

from django.db import models

from apps.core.models import Case, Client, TimeStamped


class Appointment(TimeStamped):
    VISITA, AUDIENCIA, JUZGADO, REUNION, TRAMITE, PERSONAL = (
        "visita",
        "audiencia",
        "juzgado",
        "reunion",
        "tramite",
        "personal",
    )
    KINDS = [
        (VISITA, "visita"),
        (AUDIENCIA, "audiencia"),
        (JUZGADO, "juzgado"),
        (REUNION, "reunión"),
        (TRAMITE, "trámite"),
        (PERSONAL, "personal"),
    ]
    PLANNED, DONE, CANCELLED = "planned", "done", "cancelled"
    STATUS = [(PLANNED, "planeada"), (DONE, "hecha"), (CANCELLED, "cancelada")]
    PLACES, LINK, MANUAL, NONE = "places", "link", "manual", "none"
    ADDRESS_SOURCES = [
        (PLACES, "places"),
        (LINK, "link"),
        (MANUAL, "manual"),
        (NONE, "sin dirección"),
    ]

    case = models.ForeignKey(
        Case, on_delete=models.PROTECT, null=True, blank=True, related_name="appointments"
    )
    client = models.ForeignKey(
        Client, on_delete=models.PROTECT, null=True, blank=True, related_name="appointments"
    )
    kind = models.CharField(max_length=12, choices=KINDS, default=VISITA)
    title = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    duration_min = models.PositiveIntegerField(default=60)
    location_name = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    address_source = models.CharField(max_length=8, choices=ADDRESS_SOURCES, default=NONE)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    travel_min = models.PositiveIntegerField(null=True, blank=True)
    buffer_min = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS, default=PLANNED)
    ics_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    ics_sequence = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["starts_at"]
        indexes = [models.Index(fields=["starts_at"])]

    def __str__(self):
        return f"{self.starts_at:%Y-%m-%d %H:%M} {self.title}"

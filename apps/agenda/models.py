import uuid

from django.conf import settings
from django.db import models

from apps.agenda import business_days, calendars
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


def default_reminder_days():
    return [7, 3, 1]


class Deadline(TimeStamped):
    """A plazo: computed from its term when it has one, hand-typed when it does not."""

    PROCESAL, ADMINISTRATIVO, INTERNO = "procesal", "administrativo", "interno"
    KINDS = [
        (PROCESAL, "procesal"),
        (ADMINISTRATIVO, "administrativo"),
        (INTERNO, "interno"),
    ]
    OPEN, DONE, MISSED = "open", "done", "missed"
    STATUS = [(OPEN, "abierto"), (DONE, "cumplido"), (MISSED, "vencido")]
    DIAS_HABILES, DIAS_NATURALES, MESES = business_days.UNITS
    UNITS = [
        (DIAS_HABILES, "días hábiles"),
        (DIAS_NATURALES, "días naturales"),
        (MESES, "meses"),
    ]

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="deadlines")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=KINDS, default=PROCESAL)
    notified_on = models.DateField(null=True, blank=True)
    term_value = models.PositiveIntegerField(null=True, blank=True)
    term_unit = models.CharField(max_length=16, choices=UNITS, default=DIAS_HABILES)
    due_date = models.DateField()
    computed = models.BooleanField(default=False)
    calendar_overrides = models.JSONField(default=list, blank=True)
    basis = models.TextField(blank=True)
    reminder_days = models.JSONField(default=default_reminder_days)
    status = models.CharField(max_length=8, choices=STATUS, default=OPEN)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_deadlines",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_with_calendar = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["due_date"]
        indexes = [models.Index(fields=["due_date"])]

    def __str__(self):
        return f"{self.due_date} {self.title}"

    @property
    def calendar_names(self):
        return tuple(self.calendar_overrides or calendars.DEFAULT)

    def compute_due_date(self):
        return business_days.due_date(
            self.notified_on, self.term_value, self.term_unit, self.calendar_names
        )

    def save(self, *args, **kwargs):
        computed = self.compute_due_date()
        if computed is not None:
            self.due_date = computed
            self.computed = True
        super().save(*args, **kwargs)

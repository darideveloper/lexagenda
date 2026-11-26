from django.db import models


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BaseLocation(TimeStamped):
    """The office: the origin of every simulated day (PLAN.md D17)."""

    label = models.CharField(max_length=80)
    address = models.TextField()
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="one_default_base_location",
            )
        ]

    def __str__(self):
        return self.label


JID_SUFFIX = "@s.whatsapp.net"
LOCAL_COUNTRY = "52"


def jid_for_phone(phone):
    """The WhatsApp JID of a typed number: digits, plus the country code when it is local.

    Ten digits is a Mexican number as the lawyer types it; anything else must already
    carry its country code. Anything that is not 10–15 digits is not a WhatsApp number.
    """
    number = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(number) == 10:
        number = LOCAL_COUNTRY + number
    if not 10 <= len(number) <= 15:
        raise ValueError(f"not a phone number: {phone!r}")
    return number + JID_SUFFIX


class Client(TimeStamped):
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=24, unique=True)
    jid = models.CharField(max_length=64)
    # The name WhatsApp shows for the number, read from a forwarded contact card.
    wa_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Case(TimeStamped):
    OPEN, PAUSED, CLOSED = "open", "paused", "closed"
    STATUS = [(OPEN, "abierto"), (PAUSED, "en pausa"), (CLOSED, "cerrado")]

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="cases")
    reference = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=200)
    court = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default=OPEN)
    opened_on = models.DateField()
    closed_on = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.reference} — {self.title}"


class Note(TimeStamped):
    """A case note: the voice note's transcript and a typed note share this one shape (§5.2)."""

    VOICE, TEXT, WHATSAPP = "voice", "text", "whatsapp"
    SOURCES = [(VOICE, "voz"), (TEXT, "texto"), (WHATSAPP, "whatsapp")]

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="notes")
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="case_notes"
    )
    body = models.TextField()
    source = models.CharField(max_length=10, choices=SOURCES, default=TEXT)
    media = models.ForeignKey(
        "docs.InboundMedia",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )
    transcript_model = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.body[:40]

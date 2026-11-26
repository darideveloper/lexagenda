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


class Client(TimeStamped):
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=24, unique=True)
    jid = models.CharField(max_length=64)
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

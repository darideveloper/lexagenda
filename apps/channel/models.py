from django.db import models


class SendLog(models.Model):
    """One row per delivery, with the exact text, so a complaint can be answered (§6.3).

    The same rows are the ledger the caps count: `sent` counts, `draft` does not.
    """

    SENT, DRAFT = "sent", "draft"
    MODES = [(SENT, "enviado"), (DRAFT, "borrador")]

    client = models.ForeignKey(
        "core.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="sends"
    )
    jid = models.CharField(max_length=64)
    text = models.TextField()
    mode = models.CharField(max_length=8, choices=MODES, default=SENT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["mode", "created_at"])]

    def __str__(self):
        return f"{self.mode} {self.jid}"

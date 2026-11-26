from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages as flash
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django_otp import login as otp_login
from django_otp import match_token
from django_otp.decorators import otp_required
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.agenda import calendars
from apps.agenda.models import Appointment, Deadline
from apps.assistant.models import AuditLog, Job, Message, Proposal
from apps.core.models import Case, Client

ERROR = "Usuario, contraseña o código incorrectos."
staff_only = user_passes_test(lambda user: user.is_staff)


class ClientForm(forms.ModelForm):
    """Section 11: phone, email and notes are the only client fields the dashboard writes."""

    class Meta:
        model = Client
        fields = ["phone", "email", "notes"]


class CaseStatusForm(forms.ModelForm):
    class Meta:
        model = Case
        fields = ["status"]

    def save(self, commit=True):
        case = super().save(commit=False)
        if case.status == Case.CLOSED:
            case.closed_on = case.closed_on or timezone.localdate()
        else:
            case.closed_on = None
        if commit:
            case.save()
        return case


@require_http_methods(["GET", "POST"])
def login_view(request):
    error = None
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", ""),
            password=request.POST.get("password", ""),
        )
        device = match_token(user, request.POST.get("code", "").strip()) if user else None
        if user is not None and device is not None:
            auth_login(request, user)
            otp_login(request, device)
            next_url = request.POST.get("next") or ""
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = ""
            return redirect(next_url or "agenda")
        error = ERROR
    return render(request, "login.html", {"error": error, "next": request.GET.get("next", "")})


@otp_required
def agenda_today(request):
    today = timezone.localtime()
    day_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    appointments = Appointment.objects.filter(
        starts_at__gte=day_start, starts_at__lt=day_start + timedelta(days=1)
    ).select_related("client", "case")
    return render(
        request,
        "agenda/today.html",
        {"appointments": appointments, "day": today, "instance_name": settings.CONFIG["name"]},
    )


@otp_required
def plazos(request):
    """Every open plazo, with the provenance badge and a stale-calendar flag (PLAN.md §9.2)."""
    rows = []
    for deadline in Deadline.objects.select_related("case__client").exclude(
        status=Deadline.DONE
    ):
        version = calendars.version(deadline.calendar_names)
        rows.append(
            {
                "deadline": deadline,
                "stale": bool(deadline.verified_with_calendar)
                and deadline.verified_with_calendar != version,
            }
        )
    return render(
        request,
        "plazos.html",
        {"rows": rows, "instance_name": settings.CONFIG["name"]},
    )


@otp_required
def clients(request):
    rows = (
        Client.objects.annotate(
            open_cases=Count("cases", filter=Q(cases__status=Case.OPEN), distinct=True)
        )
        .order_by("name")
    )
    return render(
        request,
        "dashboard/clients.html",
        {"clients": rows, "instance_name": settings.CONFIG["name"]},
    )


@otp_required
@require_POST
def plazos_verify(request, pk):
    """The one click that keeps a computed date's provenance instead of erasing it."""
    deadline = get_object_or_404(Deadline, pk=pk)
    deadline.verified_by = request.user
    deadline.verified_at = timezone.now()
    deadline.verified_with_calendar = calendars.version(deadline.calendar_names)
    deadline.save()
    return redirect("plazos")


@otp_required
@require_http_methods(["GET", "POST"])
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    form = ClientForm(request.POST or None, instance=client)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("client", pk=client.pk)
    return render(
        request,
        "dashboard/client.html",
        {
            "client": client,
            "form": form,
            "cases": client.cases.order_by("-opened_on"),
            "instance_name": settings.CONFIG["name"],
        },
    )


@otp_required
@require_http_methods(["GET", "POST"])
def case_detail(request, pk):
    case = get_object_or_404(Case.objects.select_related("client"), pk=pk)
    form = CaseStatusForm(request.POST or None, instance=case)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("case", pk=case.pk)
    return render(
        request,
        "dashboard/case.html",
        {
            "case": case,
            "form": form,
            "appointments": case.appointments.order_by("starts_at"),
            "instance_name": settings.CONFIG["name"],
        },
    )


def lawyer():
    return User.objects.filter(username=settings.LAWYER_USERNAME).first()


@otp_required
@staff_only
def ops_console(request):
    return render(
        request,
        "ops/console.html",
        {
            "lawyer": lawyer(),
            "failed_count": Job.objects.filter(status=Job.FAILED).count(),
            "recent_messages": Message.objects.select_related("thread").order_by("-created_at")[:50],
            "audits": AuditLog.objects.select_related("thread")[:50],
            "jobs": Job.objects.order_by("-id")[:50],
            "proposals": Proposal.objects.select_related("thread")[:50],
            "instance_name": settings.CONFIG["name"],
        },
    )


@otp_required
@staff_only
@require_POST
def job_retry(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if job.status == Job.FAILED:
        job.status = Job.QUEUED
        job.attempts = 0
        job.error = ""
        job.locked_at = None
        job.run_after = timezone.now()
        job.save(update_fields=["status", "attempts", "error", "locked_at", "run_after"])
        flash.success(request, f"Trabajo {job.pk} de nuevo en cola.")
    else:
        flash.info(request, f"Trabajo {job.pk} está {job.status}; no se reintenta.")
    return redirect("ops")


@otp_required
@staff_only
@require_POST
def reset_2fa(request):
    """Reset the lawyer's 2FA: audited, and the lawyer is told by email (PLAN §11)."""
    user = lawyer()
    if user is None:
        flash.error(request, "No hay abogado configurado (LAWYER_USERNAME).")
        return redirect("ops")

    devices = TOTPDevice.objects.filter(user=user).count() + StaticDevice.objects.filter(
        user=user
    ).count()
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()

    emailed = False
    if user.email:
        try:
            emailed = bool(
                send_mail(
                    "Tu verificación en dos pasos de lexagenda se restableció",
                    "Se restableció el 2FA de tu cuenta. Genera un dispositivo nuevo con "
                    "`manage.py setup_lawyer` y guarda los códigos de recuperación.",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
            )
        except Exception as exc:  # a dead mail server must not undo the reset
            flash.warning(request, f"2FA restablecido, pero el correo falló: {exc}")

    AuditLog.objects.create(
        tool="2fa_reset",
        args={"operator": request.user.username},
        result={"devices_removed": devices, "emailed": emailed},
    )
    flash.success(
        request,
        f"2FA de {user.username} restablecido ({devices} dispositivo(s))."
        + ("" if emailed else " Sin correo: revisa el email del abogado."),
    )
    return redirect("ops")

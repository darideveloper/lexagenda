from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login
from django_otp import match_token
from django_otp.decorators import otp_required

from apps.agenda.models import Appointment

ERROR = "Usuario, contraseña o código incorrectos."


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

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("plazos/", views.plazos, name="plazos"),
    path("plazos/<int:pk>/verificar/", views.plazos_verify, name="plazos_verify"),
    path("", views.agenda_today, name="agenda"),
    path("clients/", views.clients, name="clients"),
    path("clients/<int:pk>/", views.client_detail, name="client"),
    path("cases/<int:pk>/", views.case_detail, name="case"),
    path("ops/", views.ops_console, name="ops"),
    path("ops/jobs/<int:pk>/retry/", views.job_retry, name="ops_job_retry"),
    path("ops/2fa/reset/", views.reset_2fa, name="ops_reset_2fa"),
]

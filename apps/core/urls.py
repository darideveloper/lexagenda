from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("plazos/", views.plazos, name="plazos"),
    path("plazos/<int:pk>/verificar/", views.plazos_verify, name="plazos_verify"),
    path("", views.agenda_today, name="agenda"),
]

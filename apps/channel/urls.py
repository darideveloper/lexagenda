from django.urls import path

from . import views

urlpatterns = [
    path("webhooks/gowa", views.gowa_webhook, name="gowa_webhook"),
]

from django.contrib import admin
from django.urls import include, path, re_path
from django_otp.admin import OTPAdminSite

from apps.integrations import ics

# Every admin page needs password + OTP: OTPAdminSite.has_permission() adds is_verified().
admin.site.__class__ = OTPAdminSite

urlpatterns = [
    path("admin/", admin.site.urls),
    re_path(r"^calendar/(?P<token>[^/]+)\.ics$", ics.feed, name="calendar_feed"),
    path("", include("apps.channel.urls")),
    path("", include("apps.core.urls")),
]

from django.contrib import admin
from django.urls import include, path
from django_otp.admin import OTPAdminSite

# Every admin page needs password + OTP: OTPAdminSite.has_permission() adds is_verified().
admin.site.__class__ = OTPAdminSite

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.channel.urls")),
    path("", include("apps.core.urls")),
]

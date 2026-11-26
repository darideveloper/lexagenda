from django.contrib import admin

from apps.core.models import BaseLocation


@admin.register(BaseLocation)
class BaseLocationAdmin(admin.ModelAdmin):
    list_display = ["label", "address", "is_default"]
    search_fields = ["label", "address"]

from django.contrib import admin
from .models import HijackLog

@admin.register(HijackLog)
class HijackLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action", "hijacker", "hijacked")
    list_filter = ("action", "hijacker", "hijacked")
    readonly_fields = ("timestamp", "hijacker", "hijacked", "action")

    def has_add_permission(self, request):
        return False

from django.contrib import admin
from django.contrib import messages
from django.utils import timezone  # Importação correta
from .models import BIReport

@admin.register(BIReport)
class BIReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'report_id', 'last_updated', 'next_update')
    search_fields = ('title', 'report_id')
    list_filter = ('last_updated', 'next_update')
    readonly_fields = ('last_updated', 'next_update')

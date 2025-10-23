# bi/admin.py
from django.contrib import admin
from django.utils import timezone
from .models import BIReport, BISavedView

@admin.register(BIReport)
class BIReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'report_id', 'last_updated', 'next_update')
    search_fields = ('title', 'report_id')
    list_filter = ('last_updated', 'next_update')
    readonly_fields = ('last_updated', 'next_update')


@admin.register(BISavedView)
class BISavedViewAdmin(admin.ModelAdmin):
    list_display = ('name', 'bi_report', 'owner', 'is_public', 'is_default', 'updated_at')
    list_filter = ('is_public', 'is_default', 'bi_report')
    search_fields = ('name', 'owner__username', 'bi_report__title')
    filter_horizontal = ('shared_users', 'shared_groups')
    readonly_fields = ('share_token',)

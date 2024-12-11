from django.contrib import admin
from .models import Usuario
from django.contrib.auth.models import Group
from django.contrib.auth.admin import GroupAdmin

@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'is_active', 'is_ad_user', 'ativo']
    search_fields = ['username', 'email']

admin.site.unregister(Group)  # Desregistre se já estiver registrado
admin.site.register(Group, GroupAdmin)
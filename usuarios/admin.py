from django.contrib import admin
from .models import Usuario, Grupo

@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'is_active', 'is_ad_user', 'ativo']
    search_fields = ['username', 'email']

@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
    list_display = ['nome']
    search_fields = ['nome']

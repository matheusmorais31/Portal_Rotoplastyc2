# formularios/admin.py
from django.contrib import admin
from .models import *

class OpçãoInline(admin.TabularInline):
    model = OpcaoCampo
    extra = 1

@admin.register(Campo)
class CampoAdmin(admin.ModelAdmin):
    list_display = ('rotulo', 'formulario', 'tipo', 'ordem')
    inlines = [OpçãoInline]

admin.site.register(Formulario)
admin.site.register(Resposta)

from django.contrib import admin
from .models import Usuario, Grupo

<<<<<<< HEAD
@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'is_active', 'is_ad_user', 'ativo']
    search_fields = ['username', 'email']

@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
    list_display = ['nome']
    search_fields = ['nome']
=======
admin.site.register(Usuario)
admin.site.register(Grupo)
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22

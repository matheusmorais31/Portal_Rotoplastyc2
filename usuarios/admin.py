from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.admin import GroupAdmin
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.timezone import localtime



from usuarios.models import Usuario

@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'is_active', 'is_ad_user', 'ativo']
    search_fields = ['username', 'email']

# Unregistra o Group padrão e registra novamente com o GroupAdmin
admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)

# Cria um filtro customizado para distinguir sessões ativas/expiradas
class ActiveSessionListFilter(admin.SimpleListFilter):
    title = 'Sessões Ativas'
    parameter_name = 'ativas'

    def lookups(self, request, model_admin):
        return [
            ('ativas', 'Ativas'),
            ('expiradas', 'Expiradas'),
        ]

    def queryset(self, request, queryset):
        agora = timezone.now()
        if self.value() == 'ativas':
            return queryset.filter(expire_date__gt=agora)
        elif self.value() == 'expiradas':
            return queryset.filter(expire_date__lte=agora)
        return queryset

@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ['session_key', 'user', 'expire_date_local']
    list_filter = [ActiveSessionListFilter]
    search_fields = ['session_key']

    # Defina a ação customizada "derrubar_sessoes"
    @admin.action(description='Derrubar sessões selecionadas')
    def derrubar_sessoes(self, request, queryset):
        # Atualiza a data de expiração para agora, invalidando as sessões selecionadas
        count = queryset.update(expire_date=timezone.now())
        self.message_user(request, f"{count} sessão(ões) derrubada(s) com sucesso.")

    # Registre a ação na classe
    actions = [derrubar_sessoes]

    def user(self, obj):
        data = obj.get_decoded()
        user_id = data.get('_auth_user_id')
        if user_id:
            try:
                usuario = Usuario.objects.get(pk=user_id)
                return f"{usuario.username} (ID: {user_id})"
            except Usuario.DoesNotExist:
                return "Usuário não encontrado"
        return "Sem usuário (sessão anônima)"

    def expire_date_local(self, obj):
        return localtime(obj.expire_date).strftime("%Y-%m-%d %H:%M:%S")
    
    expire_date_local.short_description = "Expira em"
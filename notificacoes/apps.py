from django.apps import AppConfig

class NotificacoesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notificacoes'

    def ready(self):
        import notificacoes.signals  # Conectar os sinais

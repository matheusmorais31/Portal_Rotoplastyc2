from django.db import models
from django.contrib.auth import get_user_model
from documentos.models import Documento

User = get_user_model()

class Notificacao(models.Model):
    destinatario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes_recebidas')
    solicitante = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notificacoes_enviadas', null=True, blank=True)
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, null=True, blank=True)
    mensagem = models.TextField()
    lida = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notificação para {self.destinatario.username}"
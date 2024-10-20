from django.db.models.signals import post_save
from django.dispatch import receiver
from documentos.models import Documento
from .models import Notificacao

@receiver(post_save, sender=Documento)
def criar_notificacao_para_aprovadores(sender, instance, created, **kwargs):
    if created:
        # Notificar aprovador 1
        if instance.aprovador1:
            Notificacao.objects.create(
                destinatario=instance.aprovador1,
                documento=instance,
                mensagem=f"{instance.elaborador.get_full_name()} adicionou um novo documento {instance.nome} e está solicitando sua aprovação."
            )
        # Notificar aprovador 2
        if instance.aprovador2:
            Notificacao.objects.create(
                destinatario=instance.aprovador2,
                documento=instance,
                mensagem=f"{instance.elaborador.get_full_name()} adicionou um novo documento {instance.nome} e está solicitando sua aprovação."
            )

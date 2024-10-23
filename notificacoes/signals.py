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
                solicitante=instance.elaborador,  # Associar o elaborador como solicitante
                documento=instance,
                mensagem=f"{instance.elaborador.get_full_name()} adicionou um novo documento \"{instance.nome}\" e está solicitando sua aprovação."
            )
        # Notificar aprovador 2
        if instance.aprovador2:
            Notificacao.objects.create(
                destinatario=instance.aprovador2,
                solicitante=instance.elaborador,  # Associar o elaborador como solicitante
                documento=instance,
                mensagem=f"{instance.elaborador.get_full_name()} adicionou um novo documento \"{instance.nome}\" e está solicitando sua aprovação."
            )

@receiver(post_save, sender=Documento)
def criar_notificacao_para_aprovadores(sender, instance, created, **kwargs):
    if created:
        # Notificar aprovador 1
        if instance.aprovador1:
            Notificacao.objects.create(
                destinatario=instance.aprovador1,
                solicitante=instance.elaborador,  # Associar o elaborador como solicitante
                documento=instance,
                mensagem=f"{instance.elaborador.get_full_name()} adicionou um novo documento \"{instance.nome}\" e está solicitando sua aprovação."
            )
        # Notificar aprovador 2
        if instance.aprovador2:
            Notificacao.objects.create(
                destinatario=instance.aprovador2,
                solicitante=instance.elaborador,  # Associar o elaborador como solicitante
                documento=instance,
                mensagem=f"{instance.elaborador.get_full_name()} adicionou um novo documento \"{instance.nome}\" e está solicitando sua aprovação."
            )

    # Notificação para reprovação do documento
    if instance.reprovado:
        reprovador = None
        if not instance.aprovado_por_aprovador1 and instance.aprovador1:
            reprovador = instance.aprovador1
        elif not instance.aprovado_por_aprovador2 and instance.aprovador2:
            reprovador = instance.aprovador2

        if reprovador:
            Notificacao.objects.create(
                destinatario=instance.elaborador,  # Notificar o elaborador
                solicitante=reprovador,  # Quem reprovou o documento
                documento=instance,
                mensagem=f"{reprovador.get_full_name()} reprovou o documento \"{instance.nome}\"."
            )
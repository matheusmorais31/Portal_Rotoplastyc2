from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.urls import reverse
from documentos.models import Documento
from notificacoes.models import Notificacao

@receiver(post_save, sender=Documento)
def notificar_aprovadores(sender, instance, created, **kwargs):
    # Notificação para o Aprovador 1 na criação do documento
    if created and instance.aprovador1:
        Notificacao.objects.create(
            destinatario=instance.aprovador1,
            solicitante=instance.elaborador,
            documento=instance,
            mensagem=f"{instance.elaborador.get_full_name()} adicionou um novo documento \"{instance.nome}\" e está solicitando sua aprovação.",
            link=reverse('documentos:listar_aprovacoes_pendentes')  # Link para aprovações pendentes
        )

    # Verifica se o documento foi reprovado
    elif instance.reprovado:
        reprovador = instance.aprovador1 if not instance.aprovado_por_aprovador1 else instance.aprovador2
        Notificacao.objects.create(
            destinatario=instance.elaborador,
            solicitante=reprovador,
            documento=instance,
            mensagem=f"{reprovador.get_full_name()} reprovou o documento \"{instance.nome}\".",
            link=reverse('documentos:listar_documentos_reprovados')  # Link para documentos reprovados
        )

    # Notificação para o Aprovador 2 após aprovação do Aprovador 1, se não reprovado
    elif instance.aprovado_por_aprovador1 and not instance.aprovado_por_aprovador2 and not instance.reprovado:
        Notificacao.objects.create(
            destinatario=instance.aprovador2,
            solicitante=instance.aprovador1,
            documento=instance,
            mensagem=f"{instance.aprovador1.get_full_name()} aprovou o documento \"{instance.nome}\". Por favor, revise e aprove.",
            link=reverse('documentos:listar_aprovacoes_pendentes')  # Link para aprovações pendentes
        )

    # Notificação para o Elaborador após aprovação completa, se não reprovado
    elif instance.aprovado_por_aprovador1 and instance.aprovado_por_aprovador2 and not instance.reprovado:
        Notificacao.objects.create(
            destinatario=instance.elaborador,
            solicitante=instance.aprovador2,
            documento=instance,
            mensagem=f"O documento \"{instance.nome}\" foi aprovado e publicado.",
            link=reverse('documentos:listar_documentos_aprovados')  # Link para documentos aprovados
        )

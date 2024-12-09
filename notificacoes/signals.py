# notificacoes/signals.py

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.auth import get_user_model
from documentos.models import Documento
from notificacoes.models import Notificacao
from django.contrib.auth.models import Permission
from django.db.models import Q
import logging

from .tasks import enviar_notificacao_email_task  # Importe a tarefa do Celery

logger = logging.getLogger(__name__)

User = get_user_model()

@receiver(pre_save, sender=Documento)
def armazenar_status_anterior(sender, instance, **kwargs):
    """
    Armazena o status anterior do documento para uso no pós-salvamento.
    """
    if instance.pk:
        try:
            documento_antigo = Documento.objects.get(pk=instance.pk)
            instance._old_status = documento_antigo.status
        except Documento.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None

@receiver(post_save, sender=Documento)
def notificar_eventos_documento(sender, instance, created, **kwargs):
    """
    Envia notificações com base nas mudanças de status do documento.
    Inclui o elaborador e a revisão do documento nas mensagens.
    """
    try:
        old_status = getattr(instance, '_old_status', None)
        new_status = instance.status

        # 1. Quando um documento é criado e está aguardando análise
        if created and new_status == 'aguardando_analise':
            try:
                # Obter a permissão 'can_analyze'
                permission = Permission.objects.get(codename='can_analyze')
            except Permission.DoesNotExist:
                logger.error("Permissão 'can_analyze' não encontrada.")
                return  # Não pode notificar sem permissão definida

            # Obter todos os usuários que têm essa permissão diretamente ou via grupo
            analistas = User.objects.filter(
                Q(user_permissions=permission) | Q(groups__permissions=permission),
                is_active=True
            ).distinct()

            logger.debug(f"Encontrados {analistas.count()} analistas para notificação.")

            for analista in analistas:
                notificacao = Notificacao.objects.create(
                    destinatario=analista,
                    solicitante=instance.elaborador,
                    documento=instance,
                    mensagem=(
                        f"{instance.elaborador.get_full_name()} criou o documento \"{instance.nome}\" "
                        f"(Revisão {instance.revisao:02d}) que está aguardando sua análise."
                    ),
                    link=reverse('documentos:listar_documentos_para_analise')
                )
                # Enfileira a tarefa assíncrona para enviar o e-mail
                enviar_notificacao_email_task.delay(notificacao.id)

        # 2. Após a análise ser concluída, notificar o elaborador que está aguardando aprovação
        elif old_status != 'aguardando_elaborador' and new_status == 'aguardando_elaborador' and instance.elaborador:
            notificacao, created = Notificacao.objects.get_or_create(
                destinatario=instance.elaborador,
                documento=instance,
                mensagem=(
                    f"O documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi analisado "
                    f"e está aguardando sua aprovação."
                ),
                defaults={
                    'solicitante': instance.analista,
                    'link': reverse('documentos:listar_aprovacoes_pendentes')
                }
            )
            if created:
                enviar_notificacao_email_task.delay(notificacao.id)

        # 3. Após aprovação do elaborador, notificar o aprovador
        elif old_status != 'aguardando_aprovador1' and new_status == 'aguardando_aprovador1' and instance.aprovador1:
            notificacao, created = Notificacao.objects.get_or_create(
                destinatario=instance.aprovador1,
                documento=instance,
                mensagem=(
                    f"O documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) está pendente de sua aprovação.\n"
                    f"Criado por {instance.elaborador.get_full_name()}."
                ),
                defaults={
                    'solicitante': instance.elaborador,
                    'link': reverse('documentos:listar_aprovacoes_pendentes')
                }
            )
            if created:
                enviar_notificacao_email_task.delay(notificacao.id)

        # 4. Após aprovação do aprovador, notificar todos os usuários sobre o novo documento aprovado
        elif old_status != 'aprovado' and new_status == 'aprovado' and not instance.reprovado:
            # Notificar todos os usuários, exceto o elaborador e o aprovador
            usuarios = User.objects.exclude(id__in=[instance.elaborador.id, instance.aprovador1.id]).distinct()
            logger.debug(f"Notificando {usuarios.count()} usuários sobre a aprovação do documento.")

            for usuario in usuarios:
                notificacao, created = Notificacao.objects.get_or_create(
                    destinatario=usuario,
                    documento=instance,
                    mensagem=(
                        f"Informamos que o novo documento \"{instance.nome}\" Revisão {instance.revisao:02d} criado por {instance.elaborador.get_full_name()} foi publicado."
                    ),
                    defaults={
                        'link': reverse('documentos:listar_documentos_aprovados')
                    }
                )
                if created:
                    enviar_notificacao_email_task.delay(notificacao.id)

            # Notificar também o elaborador e o aprovador
            notificacoes_para_criar = [
                {
                    'destinatario': instance.elaborador,
                    'mensagem': f"Seu documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi aprovado e publicado.",
                    'link': reverse('documentos:listar_documentos_aprovados')
                },
                {
                    'destinatario': instance.aprovador1,
                    'mensagem': f"Você aprovou o documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) que agora foi publicado.",
                    'link': reverse('documentos:listar_documentos_aprovados')
                }
            ]

            for notificacao_data in notificacoes_para_criar:
                notificacao, created = Notificacao.objects.get_or_create(
                    destinatario=notificacao_data['destinatario'],
                    documento=instance,
                    mensagem=notificacao_data['mensagem'],
                    defaults={
                        'link': notificacao_data['link']
                    }
                )
                if created:
                    enviar_notificacao_email_task.delay(notificacao.id)

        # 5. Se o documento for reprovado, notificar o elaborador
        elif old_status != 'reprovado' and new_status == 'reprovado' and instance.elaborador:
            notificacao, created = Notificacao.objects.get_or_create(
                destinatario=instance.elaborador,
                documento=instance,
                mensagem=(
                    f"Seu documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi reprovado."
                ),
                defaults={
                    'solicitante': instance.aprovador1 or instance.analista,
                    'link': reverse('documentos:listar_documentos_reprovados')
                }
            )
            if created:
                enviar_notificacao_email_task.delay(notificacao.id)

    except Exception as e:
        logger.error(f"Erro ao notificar eventos para documento {instance.id}: {e}", exc_info=True)

# Remova o sinal antigo que enviava e-mails diretamente e ajuste para apenas criar a notificação
# O envio do e-mail agora é tratado no sinal abaixo

@receiver(post_save, sender=Notificacao)
def enviar_notificacao_email(sender, instance, created, **kwargs):
    """
    Enfileira a tarefa para enviar o e-mail da notificação.
    """
    if created:
        enviar_notificacao_email_task.delay(instance.id)

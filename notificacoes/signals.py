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
                Notificacao.objects.create(
                    destinatario=analista,
                    solicitante=instance.elaborador,
                    documento=instance,
                    mensagem=(
                        f"{instance.elaborador.get_full_name()} criou o documento \"{instance.nome}\" "
                        f"(Revisão {instance.revisao:02d}) que está aguardando sua análise."
                    ),
                    link=reverse('documentos:listar_documentos_para_analise')
                )

        # 2. Após a análise ser concluída, notificar o elaborador que está aguardando aprovação
        elif old_status != 'aguardando_elaborador' and new_status == 'aguardando_elaborador' and instance.elaborador:
            if not Notificacao.objects.filter(
                destinatario=instance.elaborador,
                documento=instance,
                mensagem=(
                    f"O documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi analisado "
                    f"e está aguardando sua aprovação."
                )
            ).exists():
                Notificacao.objects.create(
                    destinatario=instance.elaborador,
                    solicitante=instance.analista,
                    documento=instance,
                    mensagem=(
                        f"O documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi analisado "
                        f"e está aguardando sua aprovação."
                    ),
                    link=reverse('documentos:listar_aprovacoes_pendentes')
                )

        # 3. Após aprovação do elaborador, notificar o aprovador
        elif old_status != 'aguardando_aprovador1' and new_status == 'aguardando_aprovador1' and instance.aprovador1:
            if not Notificacao.objects.filter(
                destinatario=instance.aprovador1,
                documento=instance,
                mensagem=(
                    f"O documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) está pendente de sua aprovação.\n"
                    f"Criado por {instance.elaborador.get_full_name()}."
                )
            ).exists():
                Notificacao.objects.create(
                    destinatario=instance.aprovador1,
                    solicitante=instance.elaborador,
                    documento=instance,
                    mensagem=(
                        f"O documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) está pendente de sua aprovação.\n"
                        f"Criado por {instance.elaborador.get_full_name()}."
                    ),
                    link=reverse('documentos:listar_aprovacoes_pendentes')
                )

        # 4. Após aprovação do aprovador, notificar todos os usuários sobre o novo documento aprovado
        elif old_status != 'aprovado' and new_status == 'aprovado' and not instance.reprovado:
            # Notificar todos os usuários, exceto o elaborador e o aprovador
            usuarios = User.objects.exclude(id__in=[instance.elaborador.id, instance.aprovador1.id]).distinct()
            logger.debug(f"Notificando {usuarios.count()} usuários sobre a aprovação do documento.")

            for usuario in usuarios:
                if not Notificacao.objects.filter(
                    destinatario=usuario,
                    documento=instance,
                    mensagem=(
                        f"Informamos que o novo documento \"{instance.nome}\" Revisão {instance.revisao:02d} criado por {instance.elaborador.get_full_name()} foi publicado."
                    )
                ).exists():
                    Notificacao.objects.create(
                        destinatario=usuario,
                        documento=instance,
                        mensagem=(
                            f"Informamos que o novo documento \"{instance.nome}\" Revisão {instance.revisao:02d} criado por {instance.elaborador.get_full_name()} foi publicado."
                        ),
                        link=reverse('documentos:listar_documentos_aprovados')
                    )

            # Notificar também o elaborador e o aprovador, verificando duplicação
            if not Notificacao.objects.filter(
                destinatario=instance.elaborador,
                documento=instance,
                mensagem=(
                    f"Seu documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi aprovado e publicado."
                )
            ).exists():
                Notificacao.objects.create(
                    destinatario=instance.elaborador,
                    documento=instance,
                    mensagem=(
                        f"Seu documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi aprovado e publicado."
                    ),
                    link=reverse('documentos:listar_documentos_aprovados')
                )
            if not Notificacao.objects.filter(
                destinatario=instance.aprovador1,
                documento=instance,
                mensagem=(
                    f"Você aprovou o documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) que agora foi publicado."
                )
            ).exists():
                Notificacao.objects.create(
                    destinatario=instance.aprovador1,
                    documento=instance,
                    mensagem=(
                        f"Você aprovou o documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) que agora foi publicado."
                    ),
                    link=reverse('documentos:listar_documentos_aprovados')
                )

        # 5. Se o documento for reprovado, notificar o elaborador
        elif old_status != 'reprovado' and new_status == 'reprovado' and instance.elaborador:
            if not Notificacao.objects.filter(
                destinatario=instance.elaborador,
                documento=instance,
                mensagem=(
                    f"Seu documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi reprovado."
                )
            ).exists():
                Notificacao.objects.create(
                    destinatario=instance.elaborador,
                    solicitante=instance.aprovador1 or instance.analista,
                    documento=instance,
                    mensagem=(
                        f"Seu documento \"{instance.nome}\" (Revisão {instance.revisao:02d}) foi reprovado."
                    ),
                    link=reverse('documentos:listar_documentos_reprovados')
                )

    except Exception as e:
        logger.error(f"Erro ao notificar eventos para documento {instance.id}: {e}", exc_info=True)
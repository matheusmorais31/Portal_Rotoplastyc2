# notificacoes/tasks.py

from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

@shared_task
def enviar_notificacao_email_task(notificacao_id):
    from .models import Notificacao  # Importar aqui para evitar problemas de importação circular
    try:
        notificacao = Notificacao.objects.get(id=notificacao_id)
        # Verifica se o destinatário tem um e-mail válido
        if notificacao.destinatario.email:
            assunto = 'Nova Notificação: {}'.format(notificacao.mensagem[:50])
            destinatario_email = [notificacao.destinatario.email]

            # Contexto para o template de e-mail
            contexto = {
                'notificacao': notificacao,
                'destinatario': notificacao.destinatario,
                'site_url': settings.SITE_URL,
            }

            # Renderiza o conteúdo do e-mail usando um template
            html_conteudo = render_to_string('notificacoes/email_notificacao.html', contexto)
            texto_conteudo = strip_tags(html_conteudo)

            send_mail(
                assunto,
                texto_conteudo,
                settings.DEFAULT_FROM_EMAIL,
                destinatario_email,
                html_message=html_conteudo,
                fail_silently=False,
            )
            logger.info(f"E-mail de notificação enviado para {notificacao.destinatario.email}")
        else:
            logger.warning(f"Usuário {notificacao.destinatario.username} não possui e-mail cadastrado.")
    except Notificacao.DoesNotExist:
        logger.error(f"Notificação com ID {notificacao_id} não encontrada.")
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail de notificação: {e}", exc_info=True)

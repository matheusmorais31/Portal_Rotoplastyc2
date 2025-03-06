import logging
from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings

# Obter o logger específico para email
logger = logging.getLogger('email')

@shared_task
def enviar_notificacao_email_task(notificacao_id):
    from .models import Notificacao  # Import local para evitar import circular
    try:
        notificacao = Notificacao.objects.get(id=notificacao_id)
        if notificacao.destinatario.email:
            assunto = 'Nova Notificação: {}'.format(notificacao.mensagem[:50])
            destinatario_email = [notificacao.destinatario.email]

            contexto = {
                'notificacao': notificacao,
                'destinatario': notificacao.destinatario,
                'site_url': settings.SITE_URL,
            }

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

@shared_task
def enviar_email_interno_task(assunto, mensagem):
    logger.info("Iniciando envio de e-mail interno.")
    try:
        send_mail(
            assunto,
            mensagem,
            settings.DEFAULT_FROM_EMAIL,
            ["interno@rotoplastyc.com.br"],
            fail_silently=False,
        )
        logger.info(f"E-mail interno enviado com sucesso para interno@rotoplastyc.com.br. Assunto: {assunto}")
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail interno: {e}", exc_info=True)

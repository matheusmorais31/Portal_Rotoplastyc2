# bi/tasks.py

from celery import shared_task
from django.conf import settings
from .utils import get_powerbi_reports, acquire_access_token
import logging

logger = logging.getLogger(__name__)

@shared_task
def sincronizar_bi_reports():
    """
    Tarefa Celery para sincronizar os relatórios BI com o banco de dados.
    """
    logger.info("Iniciando tarefa de sincronização de relatórios BI.")

    # Adquirir o token de acesso
    access_token = acquire_access_token()
    if not access_token:
        logger.error("Não foi possível adquirir o token de acesso. Tarefa abortada.")
        return

    # Obter e sincronizar relatórios
    reports = get_powerbi_reports(settings.POWERBI_GROUP_ID, access_token)

    if reports is not None:
        logger.info("Sincronização de relatórios concluída.")
    else:
        logger.error("Falha na sincronização de relatórios BI.")

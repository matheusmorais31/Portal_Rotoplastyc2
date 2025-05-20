# bi/tasks.py
import logging
from celery import shared_task
from django.conf import settings
from .utils import get_powerbi_access_token
import requests

logger = logging.getLogger(__name__)

def _listar_relatorios(group_id: str, access_token: str) -> list[dict] | None:
    """
    Chama a API Power BI e devolve a lista de relatórios do workspace.
    """
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("value", [])
    except requests.RequestException as exc:
        logger.error("Tarefa BI: erro ao listar relatórios – %s", exc)
        return None

@shared_task
def sincronizar_bi_reports():
    """
    Tarefa Celery: sincroniza a tabela BIReport com o conteúdo do workspace.
    """
    logger.info("Tarefa BI: começando sincronização.")

    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("Tarefa BI: sem access_token – abortando.")
        return

    group_id = settings.POWERBI_GROUP_ID_DEFAULT
    relatorios = _listar_relatorios(group_id, access_token)
    if relatorios is None:
        logger.error("Tarefa BI: falha na API – nada sincronizado.")
        return

    from .models import BIReport  # import tardio p/ evitar import circular

    for rep in relatorios:
        obj, created = BIReport.objects.update_or_create(
            report_id=rep["id"],
            defaults={
                "title": rep["name"],
                "embed_code": "",  # preencha se tiver embedCode salvo
                "group_id": group_id,
                "dataset_id": rep.get("datasetId"),
            },
        )
        logger.debug("Tarefa BI: %s %s", "Criado" if created else "Atualizado", obj.title)

    logger.info("Tarefa BI: %d relatórios sincronizados.", len(relatorios))

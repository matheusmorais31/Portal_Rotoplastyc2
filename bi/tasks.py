# bi/tasks.py
import logging
import datetime
import time
from typing import Optional, List, Dict

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


logger = logging.getLogger(__name__)  # ex.: "bi.tasks"


# -------------------------------------------------------------------
# Logging helpers
# -------------------------------------------------------------------
def _wire_level() -> int:
    """Wire logs sobem para INFO somente se POWERBI_LOG_VERBOSE_TASKS=True."""
    return logging.INFO if getattr(settings, "POWERBI_LOG_VERBOSE_TASKS", False) else logging.DEBUG


def _short(s: Optional[str], n: int = 500) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[:n] + "…"


def _fmt_names(names: List[str], max_chars: int = 900) -> str:
    """Concatena nomes com limite de tamanho; adiciona '… (+N)' se truncar."""
    if not names:
        return "—"
    out = ""
    for i, nm in enumerate(names):
        token = ("" if i == 0 else "; ") + str(nm)
        if len(out) + len(token) > max_chars:
            out += f"… (+{len(names) - i})"
            break
        out += token
    return out


# -------------------------------------------------------------------
# API helpers (mínimo de log)
# -------------------------------------------------------------------
def _get_dataset_last_refresh_time(
    dataset_id: str,
    dataset_group_id: str,
    access_token: str,
) -> Optional[timezone.datetime]:
    """Lê o último refresh de um dataset e retorna datetime (UTC aware se USE_TZ=True; senão naive local)."""
    if not dataset_id or not dataset_group_id:
        logger.warning("last_refresh_time: parâmetros ausentes (dataset/group).")
        return None

    url = f"https://api.powerbi.com/v1.0/myorg/groups/{dataset_group_id}/datasets/{dataset_id}/refreshes?$top=1"
    headers = {"Authorization": f"Bearer {access_token}"}
    logger.log(_wire_level(), "GET %s", url)

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        logger.log(_wire_level(), "HTTP %s (last_refresh_time)", resp.status_code)

        if resp.status_code != 200:
            logger.error("last_refresh_time: http_%s body=%s", resp.status_code, _short(resp.text))
            resp.raise_for_status()

        rows = (resp.json() or {}).get("value", []) or []
        last = rows[0] if rows else {}
        status = (last.get("status") or "").strip()
        end_s = last.get("endTime")
        start_s = last.get("startTime")

        ts = end_s if status == "Completed" and end_s else (end_s or start_s)
        if not ts:
            return None

        dt_parsed = parse_datetime(ts)
        if not dt_parsed:
            logger.warning("last_refresh_time: não foi possível parsear datetime: %s", ts)
            return None

        if timezone.is_naive(dt_parsed):
            aware = dt_parsed.replace(tzinfo=datetime.timezone.utc)
        else:
            aware = dt_parsed.astimezone(datetime.timezone.utc)

        if settings.USE_TZ:
            return aware
        # converter para naive local se USE_TZ=False
        try:
            local_tz = timezone.get_current_timezone()
            return timezone.localtime(aware, local_tz).replace(tzinfo=None)
        except Exception:
            return None

    except requests.RequestException as exc:
        logger.error("last_refresh_time: request_exception — %s", exc)
    except Exception:
        logger.exception("last_refresh_time: erro inesperado")

    return None


def _listar_relatorios(group_id: str, access_token: str) -> Optional[List[Dict]]:
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports"
    headers = {"Authorization": f"Bearer {access_token}"}
    logger.log(_wire_level(), "GET %s", url)
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        logger.log(_wire_level(), "HTTP %s (listar_relatorios)", resp.status_code)
        if resp.status_code != 200:
            logger.error("listar_relatorios: http_%s body=%s", resp.status_code, _short(resp.text))
            resp.raise_for_status()
        return (resp.json() or {}).get("value", []) or []
    except requests.RequestException as exc:
        logger.error("listar_relatorios: request_exception — %s", exc)
        return None
    except Exception:
        logger.exception("listar_relatorios: erro inesperado")
        return None


# -------------------------------------------------------------------
# Tasks
# -------------------------------------------------------------------
@shared_task
def sincronizar_bi_reports():
    """
    Sincroniza metadados básicos + last_updated de relatórios do workspace padrão.
    Logs enxutos: início/fim e contagens; erros relevantes. Ao final, lista nomes.
    """
    from .models import BIReport
    from .utils import get_powerbi_access_token

    logger.info("SINCRONIA: iniciando…")
    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("SINCRONIA: sem access_token — abortando.")
        return

    group_id = getattr(settings, "POWERBI_GROUP_ID_DEFAULT", "")
    api_reports = _listar_relatorios(group_id, access_token)

    if api_reports is None:
        logger.error("SINCRONIA: falha ao listar relatórios — abortando.")
        return
    if not api_reports:
        logger.info("SINCRONIA: nenhum relatório no workspace configurado.")
        return

    processed = 0
    created = 0
    lu_updated = 0
    errors = 0

    created_names: List[str] = []
    updated_names: List[str] = []
    error_names: List[str] = []

    for rpt in api_reports:
        processed += 1
        try:
            report_id = rpt.get("id")
            title = rpt.get("name") or f"Relatório {report_id}"
            dataset_id = rpt.get("datasetId")
            report_ws = rpt.get("groupId", group_id)
            dataset_ws = rpt.get("datasetWorkspaceId") or report_ws

            # último refresh (silencioso)
            last_dt = _get_dataset_last_refresh_time(dataset_id, dataset_ws, access_token) if (dataset_id and dataset_ws) else None

            defaults = {
                "title": title,
                "embed_code": rpt.get("embedUrl", ""),
                "group_id": report_ws,
                "dataset_id": dataset_id,
            }
            obj, was_created = BIReport.objects.update_or_create(
                report_id=report_id, defaults=defaults
            )
            if was_created:
                created += 1
                created_names.append(title)

            if last_dt is not None and obj.last_updated != last_dt:
                obj.last_updated = last_dt
                obj.save(update_fields=["last_updated"])
                lu_updated += 1
                updated_names.append(title)

        except Exception:
            errors += 1
            error_names.append(rpt.get("name") or rpt.get("id") or "desconhecido")
            logger.exception("SINCRONIA: erro ao processar um relatório")

    logger.info(
        "SINCRONIA: concluída — processados=%d, criados=%d, last_updated_atualizados=%d, erros=%d",
        processed, created, lu_updated, errors
    )
    if created:
        logger.info("SINCRONIA: criados (%d): %s", created, _fmt_names(created_names))
    if lu_updated:
        logger.info("SINCRONIA: last_updated atualizados (%d): %s", lu_updated, _fmt_names(updated_names))
    if errors:
        logger.info("SINCRONIA: com erro (%d): %s", errors, _fmt_names(error_names))


@shared_task
def cascade_refresh_dataset_with_dataflows(
    report_id: str,
    report_group_id: str,
    wait_timeout_seconds: int = 1800,   # mantidos para compat, não usados
    poll_every_seconds: int = 15,       # mantidos para compat, não usados
):
    """
    Dispara refresh dos dataflows (se configurados via UI) e, em seguida, do dataset.
    Implementação "fire-and-forget" usando utils.cascade_refresh (sem polling).
    Retorna o resumo do acionamento.
    """
    from .utils import cascade_refresh

    logger.info("CASCADE: acionando refresh para report=%s group=%s", report_id, report_group_id)
    try:
        result = cascade_refresh(report_id, report_group_id, refresh_type="Full")
        df_count = len(result.get("dataflows") or [])
        d_ok = (result.get("dataset") or {}).get("ok")
        logger.info("CASCADE: disparo concluído — dataflows=%d, dataset_ok=%s", df_count, d_ok)
        return result
    except Exception:
        logger.exception("CASCADE: erro inesperado")
        return {"ok": False, "stage": "internal_error"}
